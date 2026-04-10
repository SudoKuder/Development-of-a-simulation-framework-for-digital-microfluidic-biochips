from datatypes import Container, Droplet
from typing import List
from datatypes import Bubble

def droplet_split(container: Container, caller: Droplet) -> List[int]:
    """Spawns a new droplet on an adjacent ON electrode if pull is strong enough."""
    subscribers = [caller.id]
    electrode = next((e for e in container.electrodes if e.id == caller.electrode_id), None)
    if not electrode:
        return subscribers

    for n_id in electrode.neighbours:
        neighbour = next((e for e in container.electrodes if e.id == n_id), None)
        if neighbour and neighbour.status == 1:
            # Check size ratio (electrode pull strength vs droplet size)
            pull_area = neighbour.size_x * neighbour.size_y
            droplet_area = caller.size_x * caller.size_y
            if pull_area >= droplet_area * 0.5:
                # Create new droplet on neighbour electrode
                new_droplet = Droplet(
                    id=max(d.id for d in container.droplets) + 1,
                    name=f"droplet_{len(container.droplets)}",
                    x=neighbour.x + neighbour.size_x / 2,
                    y=neighbour.y + neighbour.size_y / 2,
                    size_x=caller.size_x,
                    size_y=caller.size_y,
                    color=caller.color,
                    temperature=caller.temperature,
                    group_id=caller.group_id,
                    electrode_id=n_id
                )
                container.droplets.append(new_droplet)
                subscribers.append(new_droplet.id)
    return subscribers

def droplet_merge(container: Container, caller: Droplet) -> List[int]:
    """Merges caller droplet into any overlapping droplet on the same electrode."""
    subscribers = [caller.id]
    for other in container.droplets:
        if other.id == caller.id:
            continue
        if other.electrode_id == caller.electrode_id:
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
    if caller.temperature > 90.0:
        new_bubble = Bubble(
            id=len(container.bubbles),
            x=caller.x, y=caller.y,
            size_x=5, size_y=5
        )
        container.bubbles.append(new_bubble)
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