from datatypes import Container, Droplet, Electrode
from models import droplet_split, droplet_merge, droplet_temperature, droplet_make_bubble
from loader import load_platform

MODEL_DISPATCH = {
    "split":       droplet_split,
    "merge":       droplet_merge,
    "temperature": droplet_temperature,
    "makeBubble":  droplet_make_bubble,
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
    for droplet in container.droplets:
        for electrode in container.electrodes:
            if (electrode.x <= droplet.x <= electrode.x + electrode.size_x and
                electrode.y <= droplet.y <= electrode.y + electrode.size_y):
                electrode.subscriptions.append(droplet.id)
                droplet.electrode_id = electrode.id

def execute_action(container: Container, action: dict):
    """Process a single SETEL/CLREL action."""
    name = action.get("action", "")
    electrode_id = action.get("id", -1)
    value = action.get("change", 0)
    for electrode in container.electrodes:
        if electrode.id == electrode_id:
            electrode.status = value
            # Notify subscribed droplets
            for droplet_id in electrode.subscriptions:
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
    # Remove bubbles marked for removal
    container.bubbles = [b for b in container.bubbles if not b.to_remove]

def initialize(filepath: str) -> Container:
    container = load_platform(filepath)
    find_neighbours(container)
    initialize_subscriptions(container)
    return container