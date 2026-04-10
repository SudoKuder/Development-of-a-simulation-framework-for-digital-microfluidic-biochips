from typing import List, Optional, Tuple
from datatypes import Bubble, ColorSensor, Container, Droplet, Electrode, Heater, MicroShaker, TemperatureSensor
import math

ROOM_TEMP_C = 20.0
BUBBLE_TRIGGER_TEMP_C = 90.0
BUBBLE_TRIGGER_SECONDS = 0.5
BUBBLE_DROP_VOLUME_THRESHOLD = 10.0
EVAPORATION_RATE_PER_SECOND = 0.10
MICRO_SHAKER_RAMP_HZ_PER_SECOND = 35.0


def droplet_split(container: Container, caller: Droplet) -> List[int]:
    """Split toward ON neighbour electrodes using pull strength and overlap constraints."""
    subscribers = [caller.id]
    electrode = _electrode_by_id(container, caller.electrode_id)
    if electrode is None or caller.volume <= 0.2:
        return subscribers

    on_neighbours = []
    for neighbour_id in electrode.neighbours:
        neighbour = _electrode_by_id(container, neighbour_id)
        if neighbour is None or neighbour.status != 1:
            continue
        on_neighbours.append(neighbour)

    if not on_neighbours:
        return subscribers

    # Primary transport behavior: when the source electrode is turned OFF,
    # translate the droplet to one adjacent ON electrode.
    if electrode.status == 0:
        target = max(on_neighbours, key=lambda e: e.size_x * e.size_y)
        caller.x = target.x + target.size_x / 2
        caller.y = target.y + target.size_y / 2
        caller.electrode_id = target.id
        return subscribers

    droplet_span_area = max(1e-9, caller.size_x * caller.size_y)
    pull_area = sum(n.size_x * n.size_y for n in on_neighbours)

    # Classical split: enough pull to move half the liquid while preserving group ID.
    if pull_area >= 0.5 * droplet_span_area:
        target = max(on_neighbours, key=lambda e: e.size_x * e.size_y)
        subscribers.append(_spawn_split_droplet(container, caller, target, keep_group=True))
        recalculate_groups(container)
        return subscribers

    # New-group split: weak pull can still pinch off a small offspring near the target electrode size.
    target = max(on_neighbours, key=lambda e: e.size_x * e.size_y)
    subscribers.append(_spawn_split_droplet(container, caller, target, keep_group=False))
    recalculate_groups(container)
    return subscribers


def _spawn_split_droplet(container: Container, caller: Droplet, target: Electrode, keep_group: bool) -> int:
    parent_area = max(1e-9, caller.size_x * caller.size_y)
    target_area = max(1e-9, target.size_x * target.size_y)

    desired_child_ratio = min(0.5, max(0.15, target_area / (2.0 * parent_area)))
    old_volume = max(caller.volume, 1e-9)
    child_volume = max(0.05, old_volume * desired_child_ratio)
    parent_volume = max(0.05, old_volume - child_volume)

    caller.volume = parent_volume
    _scale_droplet_by_volume(caller, old_volume, parent_volume)

    child_area_scale = math.sqrt(child_volume / old_volume)
    child = Droplet(
        id=(max((d.id for d in container.droplets), default=0) + 1),
        name=f"droplet_{len(container.droplets)}",
        x=target.x + target.size_x / 2,
        y=target.y + target.size_y / 2,
        size_x=max(1.0, caller.size_x / math.sqrt(max(1e-9, parent_volume / old_volume)) * child_area_scale),
        size_y=max(1.0, caller.size_y / math.sqrt(max(1e-9, parent_volume / old_volume)) * child_area_scale),
        color=caller.color,
        temperature=caller.temperature,
        volume=child_volume,
        density=caller.density,
        specific_heat_capacity=caller.specific_heat_capacity,
        thermal_conductivity=caller.thermal_conductivity,
        group_id=caller.group_id if keep_group else -1,
        electrode_id=target.id,
    )
    container.droplets.append(child)
    return child.id


def droplet_merge(container: Container, caller: Droplet) -> List[int]:
    """Merge smaller touching droplets into caller under ON/OFF electrode overlap rules."""
    subscribers = [caller.id]
    if caller not in container.droplets:
        return subscribers

    merged = False
    for other in list(container.droplets):
        if other.id == caller.id:
            continue

        larger, smaller = (caller, other) if _droplet_area(caller) >= _droplet_area(other) else (other, caller)
        if larger.id != caller.id:
            continue

        if not _droplets_overlap_or_touch(larger, smaller):
            continue

        smaller_on = _droplet_on_on_electrode(container, smaller)
        if smaller_on and not _is_complete_overlap(larger, smaller):
            continue

        old_large_volume = max(larger.volume, 1e-9)
        total_volume = max(1e-9, larger.volume + smaller.volume)

        larger.x = (larger.x * larger.volume + smaller.x * smaller.volume) / total_volume
        larger.y = (larger.y * larger.volume + smaller.y * smaller.volume) / total_volume
        larger.temperature = update_group_temperature(larger, smaller)
        larger.color = blend_colors(larger.color, smaller.color, w1=larger.volume, w2=smaller.volume)
        larger.volume = total_volume
        _scale_droplet_by_volume(larger, old_large_volume, total_volume)

        container.droplets = [d for d in container.droplets if d.id != smaller.id]
        merged = True

    if merged:
        recalculate_groups(container)
    return subscribers


def update_group_temperature(group_droplet: Droplet, incoming_droplet: Droplet) -> float:
    """Heat-capacity weighted group temperature update after a merge."""
    m1 = max(1e-9, group_droplet.volume * group_droplet.density)
    m2 = max(1e-9, incoming_droplet.volume * incoming_droplet.density)
    c1 = max(1e-9, group_droplet.specific_heat_capacity)
    c2 = max(1e-9, incoming_droplet.specific_heat_capacity)

    numerator = m1 * c1 * group_droplet.temperature + m2 * c2 * incoming_droplet.temperature
    denominator = m1 * c1 + m2 * c2
    return numerator / max(1e-9, denominator)


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


def bubble_merge(container: Container) -> None:
    """Merge touching bubbles by absorbing smaller into larger."""
    changed = True
    while changed:
        changed = False
        for i, b1 in enumerate(container.bubbles):
            for j, b2 in enumerate(container.bubbles):
                if j <= i:
                    continue
                if _distance(b1.x, b1.y, b2.x, b2.y) > _bubble_radius(b1) + _bubble_radius(b2):
                    continue

                large, small = (b1, b2) if _bubble_radius(b1) >= _bubble_radius(b2) else (b2, b1)
                a_large = math.pi * _bubble_radius(large) ** 2
                a_small = math.pi * _bubble_radius(small) ** 2
                a_total = max(1e-9, a_large + a_small)

                large.x = (large.x * a_large + small.x * a_small) / a_total
                large.y = (large.y * a_large + small.y * a_small) / a_total
                r_total = math.sqrt(a_total / math.pi)
                large.size_x = r_total * 2
                large.size_y = r_total * 2
                small.to_remove = True
                changed = True
                break
            if changed:
                break

        if changed:
            container.bubbles = [b for b in container.bubbles if not b.to_remove]


def move_bubble(container: Container, bubble: Bubble) -> None:
    """Push bubbles away from touching droplets."""
    push_x = 0.0
    push_y = 0.0
    for droplet in container.droplets:
        dr = max(1e-9, min(droplet.size_x, droplet.size_y) / 2.0)
        br = _bubble_radius(bubble)
        dx = bubble.x - droplet.x
        dy = bubble.y - droplet.y
        dist = max(1e-9, math.hypot(dx, dy))
        if dist > dr + br:
            continue
        strength = (dr + br - dist) / max(1e-9, dr + br)
        push_x += (dx / dist) * strength
        push_y += (dy / dist) * strength

    if push_x == 0.0 and push_y == 0.0:
        return

    norm = max(1e-9, math.hypot(push_x, push_y))
    speed = 5.0 * container.time_step
    bubble.x += (push_x / norm) * speed
    bubble.y += (push_y / norm) * speed


def move_bubble_from_droplet(container: Container, bubble: Bubble) -> None:
    """Immediately relocate a newly spawned bubble from droplet center toward droplet periphery."""
    for droplet in container.droplets:
        if not _droplet_overlaps_circle(droplet, bubble.x, bubble.y, _bubble_radius(bubble)):
            continue

        dx = bubble.x - droplet.x
        dy = bubble.y - droplet.y
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            dx, dy = 1.0, 0.0
        dist = max(1e-9, math.hypot(dx, dy))
        target_dist = (min(droplet.size_x, droplet.size_y) / 2.0) + _bubble_radius(bubble)
        bubble.x = droplet.x + (dx / dist) * target_dist
        bubble.y = droplet.y + (dy / dist) * target_dist
        return


def heater_temperature_change(container: Container, heater: Heater) -> None:
    """Smart-heater model with calibrated heating/cooling rates."""
    dt = max(1e-9, container.time_step)
    delta = heater.desired_temp - heater.actual_temp

    if abs(delta) < 0.01:
        heater.power_status = 0
    else:
        heater.power_status = 1 if delta > 0 else -1

    # Calibrated so 20C to 90C takes about 90s at full heating power.
    degrees_per_second = 70.0 / 90.0
    heater.actual_temp += heater.power_status * degrees_per_second * dt

    if heater.power_status > 0:
        heater.actual_temp = min(heater.actual_temp, heater.desired_temp)
    elif heater.power_status < 0:
        heater.actual_temp = max(heater.actual_temp, heater.desired_temp)


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
    droplet = _valid_sensor_droplet(container, sensor)
    return droplet.temperature if droplet is not None else -1.0


def color_sensor(container: Container, sensor: ColorSensor) -> List[int]:
    droplet = _valid_sensor_droplet(container, sensor)
    if droplet is None:
        return [-1, -1, -1]
    return list(_hex_to_rgb(droplet.color))


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
