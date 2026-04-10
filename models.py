from datatypes import Container, Droplet
from typing import List
from datatypes import Bubble
import math

def droplet_split(container: Container, caller: Droplet) -> List[int]:
    """Split a droplet once into one adjacent ON electrode if pull is strong enough."""
    subscribers = [caller.id]
    electrode = next((e for e in container.electrodes if e.id == caller.electrode_id), None)
    if not electrode:
        return subscribers

    if caller.volume <= 0.2:
        return subscribers

    original_size_x = caller.size_x
    original_size_y = caller.size_y

    for n_id in electrode.neighbours:
        neighbour = next((e for e in container.electrodes if e.id == n_id), None)
        if neighbour and neighbour.status == 1:
            # Check size ratio (electrode pull strength vs droplet size)
            pull_area = neighbour.size_x * neighbour.size_y
            droplet_area = original_size_x * original_size_y
            if pull_area >= droplet_area * 0.5:
                split_ratio = 0.5
                parent_ratio = 1.0 - split_ratio
                parent_old_volume = max(caller.volume, 1e-9)
                caller.volume = parent_old_volume * parent_ratio
                caller_scale = math.sqrt(parent_ratio)
                caller.size_x = max(1.0, original_size_x * caller_scale)
                caller.size_y = max(1.0, original_size_y * caller_scale)

                # Create new droplet on neighbour electrode
                new_droplet = Droplet(
                    id=max(d.id for d in container.droplets) + 1,
                    name=f"droplet_{len(container.droplets)}",
                    x=neighbour.x + neighbour.size_x / 2,
                    y=neighbour.y + neighbour.size_y / 2,
                    size_x=max(1.0, original_size_x * math.sqrt(split_ratio)),
                    size_y=max(1.0, original_size_y * math.sqrt(split_ratio)),
                    color=caller.color,
                    temperature=caller.temperature,
                    volume=parent_old_volume * split_ratio,
                    group_id=caller.group_id,
                    electrode_id=n_id
                )
                container.droplets.append(new_droplet)
                subscribers.append(new_droplet.id)
                recalculate_groups(container)
                break
    return subscribers

def droplet_merge(container: Container, caller: Droplet) -> List[int]:
    """Merge caller with the first nearby droplet that physically overlaps/touches."""
    subscribers = [caller.id]
    for other in container.droplets:
        if other.id == caller.id:
            continue
        if droplets_overlap_or_touch(caller, other) and electrodes_touch_or_equal(container, caller, other):
            total_volume = max(other.volume + caller.volume, 1e-9)
            wx = (other.x * other.volume + caller.x * caller.volume) / total_volume
            wy = (other.y * other.volume + caller.y * caller.volume) / total_volume
            wt = (other.temperature * other.volume + caller.temperature * caller.volume) / total_volume

            old_volume = max(other.volume, 1e-9)
            scale = math.sqrt(total_volume / old_volume)

            other.x = wx
            other.y = wy
            other.temperature = wt
            other.volume = total_volume
            other.size_x = max(1.0, other.size_x * scale)
            other.size_y = max(1.0, other.size_y * scale)
            # Blend colors
            other.color = blend_colors(other.color, caller.color)
            # Remove caller
            container.droplets = [d for d in container.droplets if d.id != caller.id]
            recalculate_groups(container)
            break
    return subscribers

def droplet_temperature(container: Container, caller: Droplet) -> List[int]:
    """Heat up if on a heater, cool down toward room temp otherwise."""
    ROOM_TEMP = 20.0
    on_heater = False
    for act in container.actuators:
        if (hasattr(act, 'power_status') and act.power_status == 1 and
            act.x <= caller.x <= act.x + act.size_x and
            act.y <= caller.y <= act.y + act.size_y):
            caller.temperature += (act.desired_temp - caller.temperature) * 0.05
            on_heater = True
    if not on_heater:
        caller.temperature += (ROOM_TEMP - caller.temperature) * 0.02
    return [caller.id]

def droplet_make_bubble(container: Container, caller: Droplet) -> List[int]:
    """Spawn a bubble if droplet is above 90°C."""
    if (
        caller.temperature > 90.0 and
        container.current_time - caller.last_bubble_time >= caller.bubble_cooldown
    ):
        new_bubble = Bubble(
            id=len(container.bubbles),
            x=caller.x, y=caller.y,
            size_x=5, size_y=5
        )
        container.bubbles.append(new_bubble)
        caller.last_bubble_time = container.current_time
        caller.volume = max(0.1, caller.volume - 0.01)
    return [caller.id]

def blend_colors(c1: str, c2: str) -> str:
    """Average two hex colors."""
    r1, g1, b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2, g2, b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    return f"#{(r1+r2)//2:02x}{(g1+g2)//2:02x}{(b1+b2)//2:02x}"

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
    e1 = next((e for e in container.electrodes if e.id == d1.electrode_id), None)
    e2 = next((e for e in container.electrodes if e.id == d2.electrode_id), None)
    if e1 and e2:
        return e2.id in e1.neighbours
    return False


def droplets_overlap_or_touch(d1: Droplet, d2: Droplet) -> bool:
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


def electrodes_touch_or_equal(container: Container, d1: Droplet, d2: Droplet) -> bool:
    if d1.electrode_id == -1 or d2.electrode_id == -1:
        return False
    if d1.electrode_id == d2.electrode_id:
        return True
    e1 = next((e for e in container.electrodes if e.id == d1.electrode_id), None)
    return e1 is not None and d2.electrode_id in e1.neighbours