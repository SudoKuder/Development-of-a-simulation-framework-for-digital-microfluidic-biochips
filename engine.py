from datatypes import Container, Droplet, Electrode
from models import droplet_split, droplet_merge, droplet_temperature, droplet_make_bubble
from loader import load_platform

MODEL_DISPATCH = {
    "split":       droplet_split,
    "merge":       droplet_merge,
}

def find_neighbours(container: Container):
    """For each electrode, find all electrodes sharing a full side."""
    for e1 in container.electrodes:
        e1.neighbours = []
        for e2 in container.electrodes:
            if e1.id == e2.id:
                continue
            # Share a vertical side
            if (e1.x + e1.size_x == e2.x or e2.x + e2.size_x == e1.x):
                if not (e1.y + e1.size_y <= e2.y or e2.y + e2.size_y <= e1.y):
                    e1.neighbours.append(e2.id)
            # Share a horizontal side
            elif (e1.y + e1.size_y == e2.y or e2.y + e2.size_y == e1.y):
                if not (e1.x + e1.size_x <= e2.x or e2.x + e2.size_x <= e1.x):
                    e1.neighbours.append(e2.id)

def initialize_subscriptions(container: Container):
    """Subscribe each droplet to the electrodes it overlaps."""
    for electrode in container.electrodes:
        electrode.subscriptions = []

    def _contains(electrode, droplet):
        # Half-open boundaries avoid ambiguous double ownership on shared edges.
        return (
            electrode.x <= droplet.x < electrode.x + electrode.size_x and
            electrode.y <= droplet.y < electrode.y + electrode.size_y
        )

    def _center_distance_sq(electrode, droplet):
        cx = electrode.x + electrode.size_x / 2
        cy = electrode.y + electrode.size_y / 2
        return (droplet.x - cx) ** 2 + (droplet.y - cy) ** 2

    for droplet in container.droplets:
        candidates = []
        for electrode in container.electrodes:
            if _contains(electrode, droplet):
                candidates.append(electrode)

        if not candidates:
            droplet.electrode_id = -1
            continue

        owner = min(candidates, key=lambda e: _center_distance_sq(e, droplet))
        owner.subscriptions.append(droplet.id)
        droplet.electrode_id = owner.id

def execute_action(container: Container, action: dict):
    """Process a single SETEL/CLREL action."""
    command_electrode_id = action.get("electrode_id", action.get("id", -1))
    driver_id = action.get("driver", None)
    value = action.get("change", 0)

    for electrode in container.electrodes:
        if driver_id is not None and electrode.driver_id != driver_id:
            continue
        if electrode.electrode_id != command_electrode_id:
            continue

        electrode.status = value
        # Notify subscribed droplets.
        for droplet_id in list(electrode.subscriptions):
            droplet = next((d for d in container.droplets if d.id == droplet_id), None)
            if droplet:
                run_droplet_models(container, droplet)

def run_droplet_models(container: Container, droplet: Droplet):
    """Run all models for a droplet in order."""
    for model_name in droplet.model_order:
        if model_name in MODEL_DISPATCH:
            MODEL_DISPATCH[model_name](container, droplet)
    # Update subscriptions after models run
    initialize_subscriptions(container)

def step(container: Container):
    """Advance simulation by one time step."""
    container.current_time += container.time_step
    # Run time-sensitive models (heater, bubbles) every step
    for droplet in list(container.droplets):
        droplet_temperature(container, droplet)
        droplet_make_bubble(container, droplet)
    for bubble in container.bubbles:
        bubble.age += container.time_step
        if bubble.age >= bubble.lifetime:
            bubble.to_remove = True
    # Remove bubbles marked for removal.
    container.bubbles = [b for b in container.bubbles if not b.to_remove]

def initialize(filepath: str) -> Container:
    container = load_platform(filepath)
    find_neighbours(container)
    initialize_subscriptions(container)
    return container