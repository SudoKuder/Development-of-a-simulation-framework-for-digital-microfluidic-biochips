from typing import List, Optional, Tuple
from datatypes import (
    Bubble,
    ColorSensor,
    Container,
    Droplet,
    Electrode,
    Heater,
    MicroShaker,
    REAGENT_NONE,
    TemperatureSensor,
    is_reagent_type,
    normalize_reagent_type,
    soil_reagent_reaction,
    soil_color_from_npk,
)
import math

ROOM_TEMP_C = 20.0
BUBBLE_TRIGGER_TEMP_C = 90.0
BUBBLE_TRIGGER_SECONDS = 0.5
BUBBLE_DROP_VOLUME_THRESHOLD = 10.0
EVAPORATION_RATE_PER_SECOND = 0.10
MICRO_SHAKER_RAMP_HZ_PER_SECOND = 35.0


def _mix_weighted(a: float, b: float, wa: float, wb: float) -> float:
    total = max(1e-9, wa + wb)
    return ((a * wa) + (b * wb)) / total


def _mix_npk(first: Droplet, second: Droplet, first_volume: float, second_volume: float) -> Tuple[float, float, float]:
    return (
        _mix_weighted(first.nitrogen, second.nitrogen, first_volume, second_volume),
        _mix_weighted(first.phosphorus, second.phosphorus, first_volume, second_volume),
        _mix_weighted(first.potassium, second.potassium, first_volume, second_volume),
    )


def _apply_soil_color(droplet: Droplet) -> None:
    if droplet.is_soil_sample:
        droplet.color = soil_color_from_npk(droplet.nitrogen, droplet.phosphorus, droplet.potassium)


def _soil_npk_from_merge(first: Droplet, second: Droplet, first_volume: float, second_volume: float) -> Tuple[float, float, float]:
    first_soil = bool(first.is_soil_sample)
    second_soil = bool(second.is_soil_sample)

    if first_soil and second_soil:
        return _mix_npk(first, second, first_volume, second_volume)
    if first_soil:
        return (first.nitrogen, first.phosphorus, first.potassium)
    if second_soil:
        return (second.nitrogen, second.phosphorus, second.potassium)
    return _mix_npk(first, second, first_volume, second_volume)


def _reagent_reaction_for_soil(soil: Droplet, reagent: Droplet):
    if not soil.is_soil_sample:
        return "", None
    reagent_type = normalize_reagent_type(getattr(reagent, "reagent_type", REAGENT_NONE))
    if not is_reagent_type(reagent_type):
        return "", None
    return soil_reagent_reaction(reagent_type, soil.nitrogen, soil.phosphorus, soil.potassium)


def _apply_soil_or_reagent_outcome(target: Droplet, first: Droplet, second: Droplet, first_volume: float, second_volume: float) -> None:
    if not (first.is_soil_sample or second.is_soil_sample):
        return

    mix_n, mix_p, mix_k = _soil_npk_from_merge(first, second, first_volume, second_volume)
    target.is_soil_sample = True
    target.nitrogen = mix_n
    target.phosphorus = mix_p
    target.potassium = mix_k

    reaction_text = ""
    reaction_color = None
    reaction_reagent = REAGENT_NONE
    if first.is_soil_sample and is_reagent_type(getattr(second, "reagent_type", REAGENT_NONE)):
        reaction_text, reaction_color = _reagent_reaction_for_soil(target, second)
        reaction_reagent = normalize_reagent_type(getattr(second, "reagent_type", REAGENT_NONE))
    elif second.is_soil_sample and is_reagent_type(getattr(first, "reagent_type", REAGENT_NONE)):
        reaction_text, reaction_color = _reagent_reaction_for_soil(target, first)
        reaction_reagent = normalize_reagent_type(getattr(first, "reagent_type", REAGENT_NONE))

    target.reaction_result = reaction_text
    target.reagent_type = reaction_reagent
    if reaction_color is None:
        _apply_soil_color(target)
    else:
        target.color = reaction_color


def droplet_split(container: Container, caller: Droplet) -> List[int]:
    """Split/move model following thesis rules for pull strength and split type."""
    subscribers = [caller.id]
    electrode = _electrode_by_id(container, caller.electrode_id)
    if electrode is None or caller.volume <= 0.2:
        return subscribers

    pulling = _pulling_overlap_electrodes(container, caller)
    if not pulling:
        return subscribers

    droplet_span_area = max(1e-9, caller.size_x * caller.size_y)
    pull_area = sum(max(1e-9, e.size_x * e.size_y) for e in pulling)

    neighbour_targets = [e for e in pulling if e.id in electrode.neighbours and not _electrode_fully_engulfed_by_droplet(caller, e)]
    remote_targets = [e for e in pulling if e.id not in electrode.neighbours and not _electrode_fully_engulfed_by_droplet(caller, e)]
    neighbour_split_targets = [e for e in neighbour_targets if _electrode_is_empty(container, e.id, ignore_droplet_id=caller.id)]
    remote_split_targets = [e for e in remote_targets if _electrode_is_empty(container, e.id, ignore_droplet_id=caller.id)]

    # A droplet can be moved only when pull area can overcome droplet span.
    if electrode.status == 0 and pull_area >= droplet_span_area and neighbour_targets:
        target = max(neighbour_targets, key=lambda e: e.size_x * e.size_y)
        caller.x = target.x + target.size_x / 2
        caller.y = target.y + target.size_y / 2
        caller.electrode_id = target.id
        return subscribers

    touched_group_ids = {caller.group_id}

    # Classical split requires an anchored origin (ON electrode) and an empty neighbouring peripheral target.
    if electrode.status == 1 and neighbour_split_targets:
        for target in neighbour_split_targets:
            subscribers.append(_spawn_split_droplet(container, caller, target, keep_group=True, small_split=False))

    # Small split from large droplet: non-neighbour periphery electrode yields new group.
    if pull_area < droplet_span_area and remote_split_targets:
        target = max(remote_split_targets, key=lambda e: e.size_x * e.size_y)
        subscribers.append(_spawn_split_droplet(container, caller, target, keep_group=False, small_split=True))

    if len(subscribers) == 1:
        return subscribers

    recalculate_groups(container)
    for sid in subscribers:
        split_d = next((d for d in container.droplets if d.id == sid), None)
        if split_d is not None:
            touched_group_ids.add(split_d.group_id)
    for gid in touched_group_ids:
        _normalize_group_state(container, gid)
    return subscribers


def _spawn_split_droplet(
    container: Container,
    caller: Droplet,
    target: Electrode,
    keep_group: bool,
    small_split: bool,
) -> int:
    old_parent_volume = max(caller.volume, 1e-9)
    if small_split:
        target_volume = max(0.05, target.size_x * target.size_y)
        child_volume = max(0.05, 0.9 * target_volume)
    else:
        child_volume = max(0.05, old_parent_volume * 0.5)

    child_volume = min(child_volume, max(0.05, old_parent_volume - 0.05))
    new_parent_volume = max(0.05, old_parent_volume - child_volume)
    caller.volume = new_parent_volume
    _scale_droplet_by_volume(caller, old_parent_volume, new_parent_volume)

    child = Droplet(
        id=(max((d.id for d in container.droplets), default=0) + 1),
        name=f"droplet_{len(container.droplets)}",
        x=target.x + target.size_x / 2,
        y=target.y + target.size_y / 2,
        size_x=max(1.0, target.size_x * (0.95 if small_split else 1.0)),
        size_y=max(1.0, target.size_y * (0.95 if small_split else 1.0)),
        color=caller.color,
        temperature=caller.temperature,
        volume=child_volume,
        density=caller.density,
        specific_heat_capacity=caller.specific_heat_capacity,
        thermal_conductivity=caller.thermal_conductivity,
        group_id=caller.group_id if keep_group else -1,
        electrode_id=target.id,
        is_soil_sample=caller.is_soil_sample,
        nitrogen=caller.nitrogen,
        phosphorus=caller.phosphorus,
        potassium=caller.potassium,
        reagent_type=caller.reagent_type,
        reaction_result=caller.reaction_result,
    )
    if not child.reaction_result:
        _apply_soil_color(child)
    container.droplets.append(child)
    return child.id


def _pulling_overlap_electrodes(container: Container, droplet: Droplet) -> List[Electrode]:
    overlapped = _subscribed_or_overlapped_electrodes(container, droplet)
    return [e for e in overlapped if e.status == 1 and e.id != droplet.electrode_id]


def _subscribed_or_overlapped_electrodes(container: Container, droplet: Droplet) -> List[Electrode]:
    subscribed = [e for e in container.electrodes if droplet.id in e.subscriptions]
    if subscribed:
        return subscribed
    return [e for e in container.electrodes if _droplet_overlaps_electrode(droplet, e)]


def _electrode_is_empty(container: Container, electrode_id: int, ignore_droplet_id: Optional[int] = None) -> bool:
    electrode = _electrode_by_id(container, electrode_id)
    if electrode is None:
        return False
    return not any(
        d.id != ignore_droplet_id and _droplet_overlaps_electrode(d, electrode)
        for d in container.droplets
    )


def _electrode_fully_engulfed_by_droplet(droplet: Droplet, electrode: Electrode) -> bool:
    left = droplet.x - droplet.size_x / 2
    right = droplet.x + droplet.size_x / 2
    top = droplet.y - droplet.size_y / 2
    bottom = droplet.y + droplet.size_y / 2
    return (
        left <= electrode.x
        and electrode.x + electrode.size_x <= right
        and top <= electrode.y
        and electrode.y + electrode.size_y <= bottom
    )


def _normalize_group_state(container: Container, group_id: int) -> None:
    group = [d for d in container.droplets if d.group_id == group_id]
    if not group:
        return

    total_volume = sum(max(1e-9, d.volume) for d in group)
    total_heat_capacity = sum(max(1e-9, d.volume * d.density * d.specific_heat_capacity) for d in group)
    avg_temp = (
        sum(d.temperature * max(1e-9, d.volume * d.density * d.specific_heat_capacity) for d in group)
        / max(1e-9, total_heat_capacity)
    )

    group_has_soil = any(d.is_soil_sample for d in group)
    mixed = group[0].color
    mixed_w = max(1e-9, group[0].volume)
    soil_members = [d for d in group if d.is_soil_sample]
    soil_n = soil_members[0].nitrogen if soil_members else group[0].nitrogen
    soil_p = soil_members[0].phosphorus if soil_members else group[0].phosphorus
    soil_k = soil_members[0].potassium if soil_members else group[0].potassium
    if group_has_soil and soil_members:
        mixed_w = max(1e-9, soil_members[0].volume)
        for d in soil_members[1:]:
            w = max(1e-9, d.volume)
            soil_n = _mix_weighted(soil_n, d.nitrogen, mixed_w, w)
            soil_p = _mix_weighted(soil_p, d.phosphorus, mixed_w, w)
            soil_k = _mix_weighted(soil_k, d.potassium, mixed_w, w)
            mixed_w += w
    else:
        for d in group[1:]:
            w = max(1e-9, d.volume)
            mixed = blend_colors(mixed, d.color, w1=mixed_w, w2=w)
            mixed_w += w

    area_weights = []
    for d in group:
        e = _electrode_by_id(container, d.electrode_id)
        area_weights.append(max(1.0, (e.size_x * e.size_y) if e is not None else (d.size_x * d.size_y)))

    total_area_w = sum(area_weights)
    for d, area_w in zip(group, area_weights):
        old_v = max(1e-9, d.volume)
        new_v = max(0.05, total_volume * (area_w / max(1e-9, total_area_w)))
        d.volume = new_v
        _scale_droplet_by_volume(d, old_v, new_v)
        d.temperature = avg_temp
        if group_has_soil:
            d.is_soil_sample = True
            d.nitrogen = soil_n
            d.phosphorus = soil_p
            d.potassium = soil_k
            d_reagent = normalize_reagent_type(getattr(d, "reagent_type", REAGENT_NONE))
            if is_reagent_type(d_reagent):
                d.reaction_result, reaction_color = soil_reagent_reaction(d_reagent, d.nitrogen, d.phosphorus, d.potassium)
                d.color = reaction_color if reaction_color is not None else soil_color_from_npk(d.nitrogen, d.phosphorus, d.potassium)
            else:
                d.reaction_result = ""
                _apply_soil_color(d)
        else:
            d.color = mixed
            d.reaction_result = ""


def droplet_merge(container: Container, caller: Droplet) -> List[int]:
    """Two-stage merge model: OFF-to-ON neighbour merge-into, then absorb smaller overlapping droplets."""
    if caller not in container.droplets:
        return [caller.id]

    # Stage 1: if caller is on OFF electrode and neighbours have ON droplets, merge caller into those neighbours.
    merge_into_ids = _off_to_on_merge_targets(container, caller)
    if merge_into_ids:
        recipients = [d for d in container.droplets if d.id in merge_into_ids]
        if recipients:
            share = caller.volume / max(1, len(recipients))
            for recipient in recipients:
                old_v = max(1e-9, recipient.volume)
                recipient.volume = max(0.05, recipient.volume + share)
                _scale_droplet_by_volume(recipient, old_v, recipient.volume)
                _apply_soil_or_reagent_outcome(recipient, recipient, caller, old_v, share)

        _remove_droplet(container, caller.id)
        recalculate_groups(container)
        return [d.id for d in recipients]

    # Stage 2: caller can absorb smaller droplets that are overlapping subscribed electrodes.
    merged = False
    overlapped_ids = {e.id for e in _subscribed_or_overlapped_electrodes(container, caller)}
    for other in list(container.droplets):
        if other.id == caller.id:
            continue
        if _droplet_area(caller) < 1.05 * _droplet_area(other):
            continue
        if other.electrode_id not in overlapped_ids and not _droplets_overlap_or_touch(caller, other):
            continue
        if not _droplets_overlap_or_touch(caller, other):
            continue

        smaller_on = _droplet_on_on_electrode(container, other)
        if smaller_on and not _is_complete_overlap(caller, other):
            continue

        old_large_volume = max(caller.volume, 1e-9)
        total_volume = max(1e-9, caller.volume + other.volume)

        caller.x = (caller.x * caller.volume + other.x * other.volume) / total_volume
        caller.y = (caller.y * caller.volume + other.y * other.volume) / total_volume
        caller.temperature = update_group_temperature(container, caller, other)
        if caller.is_soil_sample or other.is_soil_sample:
            _apply_soil_or_reagent_outcome(caller, caller, other, caller.volume, other.volume)
        else:
            caller.color = update_group_color(container, caller, other)
        caller.volume = total_volume
        _scale_droplet_by_volume(caller, old_large_volume, total_volume)

        # Apply group-wide color and temperature update for all members that remain in caller group.
        for member in container.droplets:
            if member.id in (caller.id, other.id):
                continue
            if member.group_id != caller.group_id:
                continue
            member.temperature = caller.temperature
            if caller.is_soil_sample:
                member.is_soil_sample = True
                member.nitrogen = caller.nitrogen
                member.phosphorus = caller.phosphorus
                member.potassium = caller.potassium
                member_reagent = normalize_reagent_type(getattr(member, "reagent_type", REAGENT_NONE))
                if is_reagent_type(member_reagent):
                    member.reaction_result, reaction_color = soil_reagent_reaction(
                        member_reagent,
                        member.nitrogen,
                        member.phosphorus,
                        member.potassium,
                    )
                    member.color = reaction_color if reaction_color is not None else soil_color_from_npk(
                        member.nitrogen,
                        member.phosphorus,
                        member.potassium,
                    )
                else:
                    member.reaction_result = ""
                    _apply_soil_color(member)
            else:
                member.color = caller.color

        _remove_droplet(container, other.id)
        merged = True

    if merged:
        recalculate_groups(container)
    return [caller.id]


def _off_to_on_merge_targets(container: Container, caller: Droplet) -> List[int]:
    origin = _electrode_by_id(container, caller.electrode_id)
    if origin is None:
        return []

    # Merge-into neighbours applies only when caller sits on an OFF electrode.
    if origin.status != 0:
        return []

    on_neighbour_ids = {
        nid
        for nid in origin.neighbours
        if (e := _electrode_by_id(container, nid)) is not None and e.status == 1
    }
    if not on_neighbour_ids:
        return []

    targets = []
    for other in container.droplets:
        if other.id == caller.id:
            continue
        if other.electrode_id not in on_neighbour_ids:
            continue
        targets.append(other.id)
    return targets


def _remove_droplet(container: Container, droplet_id: int) -> None:
    container.droplets = [d for d in container.droplets if d.id != droplet_id]
    for electrode in container.electrodes:
        electrode.subscriptions = [sid for sid in electrode.subscriptions if sid != droplet_id]
    for actuator in container.actuators:
        if hasattr(actuator, "subscriptions"):
            actuator.subscriptions = [sid for sid in actuator.subscriptions if sid != droplet_id]


def update_group_temperature(container: Container, group_droplet: Droplet, incoming_droplet: Droplet) -> float:
    """Heat-capacity weighted group temperature update after a merge into a group."""
    group = [
        d
        for d in container.droplets
        if d.group_id == group_droplet.group_id and d.id != incoming_droplet.id
    ]

    if not group:
        group = [group_droplet]

    group_numerator = sum(
        max(1e-9, d.volume * d.density) * max(1e-9, d.specific_heat_capacity) * d.temperature
        for d in group
    )
    group_denominator = sum(
        max(1e-9, d.volume * d.density) * max(1e-9, d.specific_heat_capacity)
        for d in group
    )

    incoming_m = max(1e-9, incoming_droplet.volume * incoming_droplet.density)
    incoming_c = max(1e-9, incoming_droplet.specific_heat_capacity)
    numerator = group_numerator + (incoming_m * incoming_c * incoming_droplet.temperature)
    denominator = group_denominator + (incoming_m * incoming_c)
    return numerator / max(1e-9, denominator)


def update_group_color(container: Container, group_droplet: Droplet, incoming_droplet: Droplet) -> str:
    """Volume-weighted color update for a merge into an existing droplet group."""
    group = [
        d
        for d in container.droplets
        if d.group_id == group_droplet.group_id and d.id != incoming_droplet.id
    ]

    if not group:
        if incoming_droplet.is_soil_sample:
            return soil_color_from_npk(
                incoming_droplet.nitrogen,
                incoming_droplet.phosphorus,
                incoming_droplet.potassium,
            )
        return incoming_droplet.color

    if any(d.is_soil_sample for d in group) or incoming_droplet.is_soil_sample:
        soil_n = group[0].nitrogen
        soil_p = group[0].phosphorus
        soil_k = group[0].potassium
        group_volume = max(1e-9, group[0].volume)
        for d in group[1:]:
            d_volume = max(1e-9, d.volume)
            soil_n = _mix_weighted(soil_n, d.nitrogen, group_volume, d_volume)
            soil_p = _mix_weighted(soil_p, d.phosphorus, group_volume, d_volume)
            soil_k = _mix_weighted(soil_k, d.potassium, group_volume, d_volume)
            group_volume += d_volume

        incoming_volume = max(1e-9, incoming_droplet.volume)
        soil_n = _mix_weighted(soil_n, incoming_droplet.nitrogen, group_volume, incoming_volume)
        soil_p = _mix_weighted(soil_p, incoming_droplet.phosphorus, group_volume, incoming_volume)
        soil_k = _mix_weighted(soil_k, incoming_droplet.potassium, group_volume, incoming_volume)
        return soil_color_from_npk(soil_n, soil_p, soil_k)

    group_color = group[0].color
    group_volume = max(1e-9, group[0].volume)
    for d in group[1:]:
        d_volume = max(1e-9, d.volume)
        group_color = blend_colors(group_color, d.color, w1=group_volume, w2=d_volume)
        group_volume += d_volume

    incoming_volume = max(1e-9, incoming_droplet.volume)
    return blend_colors(group_color, incoming_droplet.color, w1=group_volume, w2=incoming_volume)


def updateGroupColor(container: Container, group_droplet: Droplet, incoming_droplet: Droplet) -> str:
    """Compatibility alias for update_group_color."""
    return update_group_color(container, group_droplet, incoming_droplet)


def updateGroupTemperature(container: Container, group_droplet: Droplet, incoming_droplet: Droplet) -> float:
    """Compatibility alias for update_group_temperature."""
    return update_group_temperature(container, group_droplet, incoming_droplet)


def dropletColorChange(container: Container, group_droplet: Droplet, incoming_droplet: Droplet) -> str:
    """Compatibility alias for group merge color update logic."""
    return update_group_color(container, group_droplet, incoming_droplet)


def droplet_temperature(container: Container, caller: Droplet) -> List[int]:
    """Apply heater-driven temperature change or passive cooling toward room temperature."""
    dt = max(1e-9, container.time_step)
    mass = max(1e-9, caller.volume * caller.density)
    cp = max(1e-9, caller.specific_heat_capacity)
    area = max(1e-9, math.pi * (min(caller.size_x, caller.size_y) / 2.0) ** 2)

    heaters = [a for a in container.actuators if isinstance(a, Heater)]
    touching_heaters = [h for h in heaters if _droplet_overlaps_rect(caller, h.x, h.y, h.size_x, h.size_y)]

    if touching_heaters:
        # Use the hottest overlapping heater as dominant source.
        heater = max(touching_heaters, key=lambda h: h.actual_temp)
        delta_t = heater.actual_temp - caller.temperature
        conductivity = max(1e-9, caller.thermal_conductivity)
        q_dot = conductivity * area * delta_t
        d_temp = (q_dot / (mass * cp)) * dt
        caller.temperature += d_temp
    else:
        # Simplified convection cooling toward room temperature.
        h_coeff = 0.05
        d_temp = (h_coeff * area * (ROOM_TEMP_C - caller.temperature) / (mass * cp)) * dt
        caller.temperature += d_temp

    if caller.temperature < ROOM_TEMP_C and not touching_heaters:
        caller.temperature = ROOM_TEMP_C
    return [caller.id]


def dropletTemperatureChange(container: Container, caller: Droplet) -> List[int]:
    """Compatibility alias for droplet_temperature."""
    return droplet_temperature(container, caller)


def droplet_make_bubble(container: Container, caller: Droplet) -> List[int]:
    """Evaporate hot droplets and generate bubbles from accumulated high-temperature exposure."""
    if caller not in container.droplets:
        return [caller.id]

    dt = max(1e-9, container.time_step)
    if caller.temperature <= BUBBLE_TRIGGER_TEMP_C:
        caller.accumulatingBubbleEscapeVolume = 0.0
        return [caller.id]

    old_volume = max(1e-9, caller.volume)
    evaporated = old_volume * EVAPORATION_RATE_PER_SECOND * dt
    caller.volume = max(0.0, old_volume - evaporated)
    _scale_droplet_by_volume(caller, old_volume, caller.volume)
    caller.accumulatingBubbleEscapeVolume += dt

    manual_cooldown_override = (
        caller.bubble_cooldown <= 0.0
        and (container.current_time - caller.last_bubble_time) >= 0.0
    )
    should_spawn = (
        manual_cooldown_override
        or
        caller.accumulatingBubbleEscapeVolume >= BUBBLE_TRIGGER_SECONDS
        or caller.volume <= BUBBLE_DROP_VOLUME_THRESHOLD
    )
    if not should_spawn:
        return [caller.id]

    bubble_volume = max(evaporated, 0.25)
    _spawn_bubble(container, caller.x, caller.y, bubble_volume)
    caller.accumulatingBubbleEscapeVolume = 0.0
    caller.last_bubble_time = container.current_time

    if caller.volume <= BUBBLE_DROP_VOLUME_THRESHOLD:
        # Entire droplet becomes vaporized/escaped; remove it from simulation.
        container.droplets = [d for d in container.droplets if d.id != caller.id]

    return [caller.id]


def makeBubble(container: Container, caller: Droplet) -> List[int]:
    """Compatibility alias for droplet_make_bubble."""
    return droplet_make_bubble(container, caller)


def _spawn_bubble(container: Container, x: float, y: float, source_volume: float) -> None:
    radius = max(2.0, math.sqrt(max(1e-9, source_volume) / math.pi))
    container.bubbles.append(
        Bubble(
            id=(max((b.id for b in container.bubbles), default=-1) + 1),
            x=x,
            y=y,
            size_x=radius * 2,
            size_y=radius * 2,
        )
    )


def bubble_merge(container: Container, caller: Optional[Bubble] = None) -> None:
    """Merge model where the caller bubble absorbs the first smaller touching bubble."""
    if caller is None:
        # Compatibility mode: run caller-based merge for all bubbles once this step.
        for bubble in list(container.bubbles):
            if bubble in container.bubbles:
                bubble_merge(container, bubble)
        return

    if caller not in container.bubbles:
        return

    caller_radius = _bubble_radius(caller)
    for other in container.bubbles:
        if other.id == caller.id:
            continue

        other_radius = _bubble_radius(other)
        if other_radius >= caller_radius:
            continue

        if _distance(caller.x, caller.y, other.x, other.y) > caller_radius + other_radius:
            continue

        # Keep area in 2D and move caller toward absorbed bubble by area-weighted centroid.
        a_caller = math.pi * caller_radius * caller_radius
        a_other = math.pi * other_radius * other_radius
        a_total = max(1e-9, a_caller + a_other)

        caller.x = (caller.x * a_caller + other.x * a_other) / a_total
        caller.y = (caller.y * a_caller + other.y * a_other) / a_total
        merged_radius = math.sqrt(a_total / math.pi)
        caller.size_x = merged_radius * 2.0
        caller.size_y = merged_radius * 2.0
        other.to_remove = True

        # Caller merges only with the first valid candidate; other overlaps are handled by peers.
        break

    container.bubbles = [b for b in container.bubbles if not b.to_remove]


def move_bubble(container: Container, bubble: Bubble) -> None:
    """Move a touching bubble using group-aware direction correction and droplet repulsion."""
    for droplet in container.droplets:
        if not _droplet_overlaps_circle(droplet, bubble.x, bubble.y, _bubble_radius(bubble)):
            continue
        move_bubble_according_to_group(container, bubble, droplet)
        move_bubble_from_droplet(container, bubble, droplet)


def move_bubble_according_to_group(container: Container, bubble: Bubble, droplet: Droplet) -> None:
    """Nudge bubble away from neighbouring droplets in the same group."""
    neighbours = _group_neighbours(container, droplet)
    if not neighbours:
        return

    nudge = 0.1
    for neighbour in neighbours:
        dx = bubble.x - neighbour.x
        dy = bubble.y - neighbour.y
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            # Keep movement deterministic even if centers coincide.
            dx = droplet.x - neighbour.x
            dy = droplet.y - neighbour.y
        dist = max(1e-9, math.hypot(dx, dy))
        bubble.x += (dx / dist) * nudge
        bubble.y += (dy / dist) * nudge


def move_bubble_from_droplet(container: Container, bubble: Bubble, droplet: Optional[Droplet] = None) -> None:
    """Place bubble on a droplet periphery using thesis distance rules."""
    candidates = [droplet] if droplet is not None else container.droplets
    for candidate in candidates:
        if candidate is None:
            continue
        if not _droplet_overlaps_circle(candidate, bubble.x, bubble.y, _bubble_radius(bubble)):
            continue

        br = _bubble_radius(bubble)
        dr = min(candidate.size_x, candidate.size_y) / 2.0
        dx = bubble.x - candidate.x
        dy = bubble.y - candidate.y
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            dx, dy = 1.0, 0.0

        dist = max(1e-9, math.hypot(dx, dy))
        electrode_size = _electrode_nominal_size(container, candidate)
        if dr + br < 0.5 * electrode_size:
            target_dist = 0.6 * electrode_size
        else:
            target_dist = dr + br

        bubble.x = candidate.x + (dx / dist) * target_dist
        bubble.y = candidate.y + (dy / dist) * target_dist
        return


def heater_temperature_change(container: Container, heater: Heater) -> None:
    """Smart-heater model with explicit setpoint gating and signed heating/cooling."""
    dt = max(1e-9, container.time_step)

    # Do not drive temperature until a controller explicitly sets a target.
    if not getattr(heater, "has_target_setpoint", False):
        heater.power_status = 0
        return

    delta = heater.desired_temp - heater.actual_temp

    if abs(delta) < 0.01:
        heater.power_status = 0
    else:
        heater.power_status = 1 if delta > 0 else -1

    # Calibrated from empirical observation: 20C -> 90C in ~90s at full power.
    degrees_per_second = 70.0 / 90.0
    heater.actual_temp += heater.power_status * degrees_per_second * dt

    if heater.power_status > 0:
        heater.actual_temp = min(heater.actual_temp, heater.desired_temp)
    elif heater.power_status < 0:
        heater.actual_temp = max(heater.actual_temp, heater.desired_temp)


def heaterTemperatureChange(container: Container, heater: Heater) -> None:
    """Compatibility alias for heater_temperature_change."""
    heater_temperature_change(container, heater)


def micro_shaker_frequency_change(container: Container, shaker: MicroShaker) -> None:
    """Drive vibration frequency toward desired setpoint while tracking power state."""
    dt = max(1e-9, container.time_step)
    target = shaker.desired_frequency if shaker.power_status == 1 else 0.0
    delta = target - shaker.vibration_frequency
    max_step = MICRO_SHAKER_RAMP_HZ_PER_SECOND * dt
    if abs(delta) <= max_step:
        shaker.vibration_frequency = target
    else:
        shaker.vibration_frequency += max_step if delta > 0 else -max_step


def droplet_vibration(container: Container, caller: Droplet) -> List[int]:
    """Dependent model: micro-shaker slightly agitates subscribed droplets and returns subscribers."""
    subscribers = [caller.id]
    for shaker in _active_micro_shakers(container):
        if caller.id not in shaker.subscriptions:
            continue
        freq_factor = min(1.0, shaker.vibration_frequency / 100.0)
        if freq_factor <= 0.0:
            continue
        # Small agitation raises effective temperature and lowers local viscosity surrogate.
        caller.temperature += 0.05 * freq_factor * container.time_step
        caller.thermal_conductivity = max(0.01, caller.thermal_conductivity * (1.0 + 0.01 * freq_factor))
    return subscribers


def update_sensor_readings(container: Container) -> None:
    for sensor in container.sensors:
        if isinstance(sensor, TemperatureSensor):
            sensor.temperature = temperature_sensor(container, sensor)
        elif isinstance(sensor, ColorSensor):
            rgb = color_sensor(container, sensor)
            sensor.value_r, sensor.value_g, sensor.value_b = rgb


def temperature_sensor(container: Container, sensor: TemperatureSensor) -> float:
    if not isinstance(sensor, TemperatureSensor):
        return -1.0
    droplet = _valid_sensor_droplet(container, sensor)
    return droplet.temperature if droplet is not None else -1.0


def color_sensor(container: Container, sensor: ColorSensor) -> List[int]:
    if not isinstance(sensor, ColorSensor):
        return [-1, -1, -1]
    droplet = _valid_sensor_droplet(container, sensor)
    if droplet is None:
        return [-1, -1, -1]
    return list(_hex_to_rgb(droplet.color))


def temperatureSensor(container: Container, sensor) -> float:
    """Compatibility alias for temperature_sensor."""
    return temperature_sensor(container, sensor)


def colorSensor(container: Container, sensor) -> List[int]:
    """Compatibility alias for color_sensor."""
    return color_sensor(container, sensor)


def _valid_sensor_droplet(container: Container, sensor) -> Optional[Droplet]:
    center_electrode = _sensor_center_electrode(container, sensor)
    if center_electrode is None:
        return None

    candidates = []
    for droplet in container.droplets:
        if _droplet_fully_within_electrode(droplet, center_electrode):
            candidates.append(droplet)

    if len(candidates) != 1:
        return None

    candidate = candidates[0]
    sensor_rect = (sensor.x, sensor.y, sensor.size_x, sensor.size_y)
    for other in container.droplets:
        if other.id == candidate.id:
            continue
        if not _droplet_overlaps_rect(other, *sensor_rect):
            continue
        if not _droplet_fully_within_electrode(other, center_electrode):
            return None

    return candidate


def update_micro_shaker_subscriptions(container: Container) -> None:
    """Keep shaker-to-droplet subscriptions aligned with current geometry."""
    shakers = [a for a in container.actuators if isinstance(a, MicroShaker)]
    if not shakers:
        return
    for shaker in shakers:
        shaker.subscriptions = []
        for droplet in container.droplets:
            if _droplet_overlaps_rect(droplet, shaker.x, shaker.y, shaker.size_x, shaker.size_y):
                shaker.subscriptions.append(droplet.id)


def _active_micro_shakers(container: Container) -> List[MicroShaker]:
    shakers = [a for a in container.actuators if isinstance(a, MicroShaker)]
    return [s for s in shakers if s.power_status == 1 and s.vibration_frequency > 0.0]


def _sensor_center_electrode(container: Container, sensor) -> Optional[Electrode]:
    cx = sensor.x + sensor.size_x / 2.0
    cy = sensor.y + sensor.size_y / 2.0
    for electrode in container.electrodes:
        if electrode.x <= cx < electrode.x + electrode.size_x and electrode.y <= cy < electrode.y + electrode.size_y:
            return electrode
    return None


def blend_colors(c1: str, c2: str, w1: float = 1.0, w2: float = 1.0) -> str:
    """Blend two hex colors with optional weights."""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    total = max(1e-9, w1 + w2)
    r = int((r1 * w1 + r2 * w2) / total)
    g = int((g1 * w1 + g2 * w2) / total)
    b = int((b1 * w1 + b2 * w2) / total)
    return f"#{r:02x}{g:02x}{b:02x}"


def recalculate_groups(container: Container):
    """BFS to reassign group IDs after a merge/split."""
    visited = {}
    group_id = 0
    for droplet in container.droplets:
        if droplet.id not in visited:
            queue = [droplet]
            while queue:
                d = queue.pop(0)
                visited[d.id] = group_id
                d.group_id = group_id
                for other in container.droplets:
                    if other.id not in visited and are_adjacent(d, other, container):
                        queue.append(other)
            group_id += 1


def are_adjacent(d1: Droplet, d2: Droplet, container: Container) -> bool:
    e1 = _electrode_by_id(container, d1.electrode_id)
    e2 = _electrode_by_id(container, d2.electrode_id)
    if e1 and e2:
        return e2.id in e1.neighbours
    return False


def droplets_overlap_or_touch(d1: Droplet, d2: Droplet) -> bool:
    return _droplets_overlap_or_touch(d1, d2)


def electrodes_touch_or_equal(container: Container, d1: Droplet, d2: Droplet) -> bool:
    if d1.electrode_id == -1 or d2.electrode_id == -1:
        return False
    if d1.electrode_id == d2.electrode_id:
        return True
    e1 = _electrode_by_id(container, d1.electrode_id)
    return e1 is not None and d2.electrode_id in e1.neighbours


def _droplet_area(d: Droplet) -> float:
    return max(1e-9, d.size_x * d.size_y)


def _bubble_radius(b: Bubble) -> float:
    return max(1e-9, min(b.size_x, b.size_y) / 2.0)


def _electrode_nominal_size(container: Container, droplet: Droplet) -> float:
    electrode = _electrode_by_id(container, droplet.electrode_id)
    if electrode is None:
        return max(1.0, max(droplet.size_x, droplet.size_y))
    return max(1.0, max(electrode.size_x, electrode.size_y))


def _group_neighbours(container: Container, droplet: Droplet) -> List[Droplet]:
    return [
        other
        for other in container.droplets
        if other.id != droplet.id
        and other.group_id == droplet.group_id
        and electrodes_touch_or_equal(container, droplet, other)
    ]


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x1 - x2, y1 - y2)


def _is_complete_overlap(larger: Droplet, smaller: Droplet) -> bool:
    r_large = min(larger.size_x, larger.size_y) / 2.0
    r_small = min(smaller.size_x, smaller.size_y) / 2.0
    d = _distance(larger.x, larger.y, smaller.x, smaller.y)
    return d + r_small <= r_large


def _droplet_on_on_electrode(container: Container, droplet: Droplet) -> bool:
    electrode = _electrode_by_id(container, droplet.electrode_id)
    return electrode is not None and electrode.status == 1


def _droplets_overlap_or_touch(d1: Droplet, d2: Droplet) -> bool:
    left1 = d1.x - d1.size_x / 2
    right1 = d1.x + d1.size_x / 2
    top1 = d1.y - d1.size_y / 2
    bottom1 = d1.y + d1.size_y / 2

    left2 = d2.x - d2.size_x / 2
    right2 = d2.x + d2.size_x / 2
    top2 = d2.y - d2.size_y / 2
    bottom2 = d2.y + d2.size_y / 2

    overlap_x = left1 <= right2 and left2 <= right1
    overlap_y = top1 <= bottom2 and top2 <= bottom1
    return overlap_x and overlap_y


def _droplet_overlaps_rect(droplet: Droplet, x: float, y: float, w: float, h: float) -> bool:
    left1 = droplet.x - droplet.size_x / 2
    right1 = droplet.x + droplet.size_x / 2
    top1 = droplet.y - droplet.size_y / 2
    bottom1 = droplet.y + droplet.size_y / 2

    left2 = x
    right2 = x + w
    top2 = y
    bottom2 = y + h

    return left1 < right2 and left2 < right1 and top1 < bottom2 and top2 < bottom1


def _droplet_overlaps_electrode(droplet: Droplet, electrode: Electrode) -> bool:
    return _droplet_overlaps_rect(droplet, electrode.x, electrode.y, electrode.size_x, electrode.size_y)


def _droplet_fully_within_electrode(droplet: Droplet, electrode: Electrode) -> bool:
    left = droplet.x - droplet.size_x / 2
    right = droplet.x + droplet.size_x / 2
    top = droplet.y - droplet.size_y / 2
    bottom = droplet.y + droplet.size_y / 2
    return (
        electrode.x <= left
        and right <= electrode.x + electrode.size_x
        and electrode.y <= top
        and bottom <= electrode.y + electrode.size_y
    )


def _droplet_overlaps_circle(droplet: Droplet, x: float, y: float, radius: float) -> bool:
    r_d = min(droplet.size_x, droplet.size_y) / 2.0
    return _distance(droplet.x, droplet.y, x, y) <= r_d + radius


def _electrode_by_id(container: Container, electrode_id: int) -> Optional[Electrode]:
    return next((e for e in container.electrodes if e.id == electrode_id), None)


def _scale_droplet_by_volume(droplet: Droplet, old_volume: float, new_volume: float) -> None:
    if old_volume <= 1e-9:
        return
    scale = math.sqrt(max(1e-9, new_volume) / old_volume)
    droplet.size_x = max(1.0, droplet.size_x * scale)
    droplet.size_y = max(1.0, droplet.size_y * scale)


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    normalized = hex_color.lstrip("#")
    if len(normalized) != 6:
        return (255, 255, 255)
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )
