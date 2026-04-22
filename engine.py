from collections import deque
from datatypes import (
    ColorSensor,
    Container,
    Droplet,
    Electrode,
    Heater,
    MicroShaker,
    TemperatureSensor,
    normalize_reagent_type,
    soil_color_from_npk,
)
from models import (
    bubble_merge,
    droplet_vibration,
    droplet_make_bubble,
    droplet_merge,
    droplet_split,
    droplet_temperature,
    heater_temperature_change,
    micro_shaker_frequency_change,
    move_bubble,
    move_bubble_from_droplet,
    recalculate_groups,
    update_micro_shaker_subscriptions,
    update_sensor_readings,
)
from loader import load_platform

DROPLET_MODEL_DISPATCH = {
    "split": droplet_split,
    "merge": droplet_merge,
    "temperature": droplet_temperature,
    "make_bubble": droplet_make_bubble,
    "vibration": droplet_vibration,
}

ACTUATOR_MODEL_DISPATCH = {
    "heater": heater_temperature_change,
    "micro_shaker": micro_shaker_frequency_change,
    "microShaker": micro_shaker_frequency_change,
}


def register_droplet_model(name: str, model_fn):
    """Register or replace a droplet model name with a callable."""
    DROPLET_MODEL_DISPATCH[name] = model_fn


def register_actuator_model(type_name: str, model_fn):
    """Register or replace per-step actuator model for a component type."""
    ACTUATOR_MODEL_DISPATCH[type_name] = model_fn

class NeighbourFinder:
    """Calculate neighbour relations if they are not already present in JSON input."""

    def __init__(self, container: Container):
        self.container = container

    def run(self):
        for electrode in self.container.electrodes:
            electrode.neighbours = []

        for i, e1 in enumerate(self.container.electrodes):
            for j in range(i + 1, len(self.container.electrodes)):
                e2 = self.container.electrodes[j]
                if self._are_neighbours(e1, e2):
                    e1.neighbours.append(e2.id)
                    e2.neighbours.append(e1.id)

    def _are_neighbours(self, e1: Electrode, e2: Electrode) -> bool:
        if e1.shape == 0 and e2.shape == 0:
            return self._rectangles_touch_on_side(e1, e2)
        return self._shapes_touch_or_overlap(e1, e2)

    def _rectangles_touch_on_side(self, e1: Electrode, e2: Electrode) -> bool:
        if (e1.x + e1.size_x == e2.x or e2.x + e2.size_x == e1.x):
            return not (e1.y + e1.size_y <= e2.y or e2.y + e2.size_y <= e1.y)
        if (e1.y + e1.size_y == e2.y or e2.y + e2.size_y == e1.y):
            return not (e1.x + e1.size_x <= e2.x or e2.x + e2.size_x <= e1.x)
        return False

    def _shapes_touch_or_overlap(self, e1: Electrode, e2: Electrode) -> bool:
        a_left, a_top, a_right, a_bottom = self._bounds(e1)
        b_left, b_top, b_right, b_bottom = self._bounds(e2)
        touch_or_overlap = (
            a_left <= b_right
            and b_left <= a_right
            and a_top <= b_bottom
            and b_top <= a_bottom
        )
        return touch_or_overlap

    def _bounds(self, electrode: Electrode):
        if electrode.shape == 1 and electrode.corners:
            xs = [c[0] for c in electrode.corners]
            ys = [c[1] for c in electrode.corners]
            return min(xs), min(ys), max(xs), max(ys)
        return (
            electrode.x,
            electrode.y,
            electrode.x + electrode.size_x,
            electrode.y + electrode.size_y,
        )


def find_neighbours(container: Container):
    """Public compatibility wrapper for neighbour-finder initialization."""
    NeighbourFinder(container).run()


def initialize_board(container: Container):
    """Initialize board-level metadata, currently neighbour mapping."""
    has_precomputed_neighbours = any(e.neighbours for e in container.electrodes)
    if not has_precomputed_neighbours:
        find_neighbours(container)

def initialize_subscriptions(container: Container):
    """Subscribe each droplet to every overlapping electrode region."""
    for electrode in container.electrodes:
        electrode.subscriptions = []

    for droplet in container.droplets:
        initialize_droplet_subscriptions(container, droplet)


def _remove_droplet_from_subscriptions(container: Container, droplet_id: int):
    for electrode in container.electrodes:
        electrode.subscriptions = [sid for sid in electrode.subscriptions if sid != droplet_id]


def initialize_droplet_subscriptions(container: Container, droplet: Droplet):
    """Refresh subscriptions for one droplet by recursive overlap walk."""
    _remove_droplet_from_subscriptions(container, droplet.id)

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

    candidates = [e for e in container.electrodes if _contains(e, droplet)]
    if not candidates:
        candidates = [e for e in container.electrodes if _droplet_overlaps_electrode(droplet, e)]

    if not candidates:
        droplet.electrode_id = -1
        return

    owner = min(candidates, key=lambda e: _center_distance_sq(e, droplet))
    droplet.electrode_id = owner.id

    visited = set()
    queue = deque([owner.id])
    while queue:
        electrode_id = queue.popleft()
        if electrode_id in visited:
            continue
        visited.add(electrode_id)

        electrode = _electrode_by_id(container, electrode_id)
        if electrode is None:
            continue
        if not _droplet_overlaps_electrode(droplet, electrode):
            continue

        if droplet.id not in electrode.subscriptions:
            electrode.subscriptions.append(droplet.id)

        for neighbour_id in electrode.neighbours:
            if neighbour_id not in visited:
                queue.append(neighbour_id)


def _electrode_by_id(container: Container, electrode_id: int):
    return next((e for e in container.electrodes if e.id == electrode_id), None)


def _droplet_overlaps_electrode(droplet: Droplet, electrode: Electrode) -> bool:
    left1 = droplet.x - droplet.size_x / 2
    right1 = droplet.x + droplet.size_x / 2
    top1 = droplet.y - droplet.size_y / 2
    bottom1 = droplet.y + droplet.size_y / 2

    left2 = electrode.x
    right2 = electrode.x + electrode.size_x
    top2 = electrode.y
    bottom2 = electrode.y + electrode.size_y

    return left1 < right2 and left2 < right1 and top1 < bottom2 and top2 < bottom1


def initialize_droplets(container: Container):
    """Initialize per-droplet state and starting group IDs by load order."""
    for idx, droplet in enumerate(container.droplets):
        droplet.group_id = idx
        droplet.next_model = 0
        droplet.reagent_type = normalize_reagent_type(getattr(droplet, "reagent_type", "none"))
        if droplet.is_soil_sample:
            droplet.color = soil_color_from_npk(droplet.nitrogen, droplet.phosphorus, droplet.potassium)
        if not droplet.model_order:
            droplet.model_order = ["split", "merge", "temperature", "make_bubble"]
        droplet.begin_of_time_sensitive_models = max(
            0,
            min(int(getattr(droplet, "begin_of_time_sensitive_models", 0)), len(droplet.model_order)),
        )
        has_shaker = any(getattr(a, "type", "") in ("micro_shaker", "microShaker") for a in container.actuators)
        if has_shaker and "vibration" not in droplet.model_order:
            droplet.model_order.append("vibration")


def initialize_actuators(container: Container):
    for actuator in container.actuators:
        if isinstance(actuator, Heater):
            if actuator.actual_temp is None:
                actuator.actual_temp = 20.0
            if actuator.desired_temp is None:
                actuator.desired_temp = 90.0
            if actuator.power_status is None:
                actuator.power_status = 0
        elif isinstance(actuator, MicroShaker):
            if actuator.vibration_frequency is None:
                actuator.vibration_frequency = 0.0
            if actuator.desired_frequency is None:
                actuator.desired_frequency = 0.0
            if actuator.power_status is None:
                actuator.power_status = 0

    update_micro_shaker_subscriptions(container)


def initialize_sensors(container: Container):
    for sensor in container.sensors:
        if isinstance(sensor, TemperatureSensor):
            if sensor.temperature is None:
                sensor.temperature = 20.0
        elif isinstance(sensor, ColorSensor):
            if sensor.value_r is None:
                sensor.value_r = 0
            if sensor.value_g is None:
                sensor.value_g = 0
            if sensor.value_b is None:
                sensor.value_b = 0


def _execute_model(container: Container, droplet: Droplet, model_name: str):
    model_fn = DROPLET_MODEL_DISPATCH.get(model_name)
    if model_fn is None:
        return [droplet.id]
    return model_fn(container, droplet)


def _allowed_model_indices(droplet: Droplet, trigger: str):
    model_count = len(droplet.model_order)
    if model_count == 0:
        return []

    boundary = getattr(droplet, "begin_of_time_sensitive_models", 0)
    boundary = max(0, min(int(boundary), model_count))

    if trigger == "time":
        return list(range(boundary, model_count))
    if trigger == "action":
        if 0 < boundary < model_count:
            return list(range(0, boundary))
        return list(range(model_count))
    return list(range(model_count))


def _next_allowed_model_index(droplet: Droplet, allowed_indices):
    if not allowed_indices:
        return None

    model_count = len(droplet.model_order)
    allowed_set = set(allowed_indices)
    start_idx = droplet.next_model % model_count

    for offset in range(model_count):
        idx = (start_idx + offset) % model_count
        if idx in allowed_set:
            return idx
    return None


def _handle_subscriber(container: Container, droplet_id: int, trigger: str):
    droplet = next((d for d in container.droplets if d.id == droplet_id), None)
    if droplet is None or not droplet.model_order:
        return [], False

    allowed_indices = _allowed_model_indices(droplet, trigger)
    model_idx = _next_allowed_model_index(droplet, allowed_indices)
    if model_idx is None:
        return [], False

    model_count = len(droplet.model_order)
    model_name = droplet.model_order[model_idx]
    subscribers = _execute_model(container, droplet, model_name) or [droplet.id]

    droplet_still_exists = any(d.id == droplet_id for d in container.droplets)
    if droplet_still_exists:
        # Breadth-first: each pass executes one model and requeues if more remain.
        droplet.next_model = (model_idx + 1) % model_count
        initialize_droplet_subscriptions(container, droplet)
        needs_requeue = _next_allowed_model_index(droplet, allowed_indices) is not None
    else:
        _remove_droplet_from_subscriptions(container, droplet_id)
        needs_requeue = False

    for sid in subscribers:
        sd = next((d for d in container.droplets if d.id == sid), None)
        if sd is not None:
            initialize_droplet_subscriptions(container, sd)
        else:
            _remove_droplet_from_subscriptions(container, sid)

    return subscribers, needs_requeue


def run_subscriber_cycle(container: Container, initial_subscribers, trigger: str = "all"):
    queue = deque()
    in_queue = set()
    executed_counts = {}

    def _model_count(subscriber_id):
        droplet = next((d for d in container.droplets if d.id == subscriber_id), None)
        if droplet is None or not droplet.model_order:
            return 0
        return len(_allowed_model_indices(droplet, trigger))

    def _enqueue(subscriber_id):
        if subscriber_id in in_queue:
            return
        model_count = _model_count(subscriber_id)
        if model_count == 0:
            return
        if executed_counts.get(subscriber_id, 0) >= model_count:
            return
        in_queue.add(subscriber_id)
        queue.append(subscriber_id)

    for subscriber_id in initial_subscribers:
        _enqueue(subscriber_id)

    while queue:
        droplet_id = queue.popleft()
        in_queue.discard(droplet_id)
        subscribers, needs_requeue = _handle_subscriber(container, droplet_id, trigger)
        executed_counts[droplet_id] = executed_counts.get(droplet_id, 0) + 1

        for sid in subscribers:
            if sid == droplet_id:
                continue
            _enqueue(sid)
        if needs_requeue:
            _enqueue(droplet_id)

def execute_action(container: Container, action: dict):
    """Process a single SETEL/CLREL action."""
    command_electrode_id = action.get("electrode_id", action.get("id", -1))
    driver_id = action.get("driver", None)
    value = action.get("change", 0)
    affected_subscribers = []

    for electrode in container.electrodes:
        if driver_id is not None and electrode.driver_id != driver_id:
            continue
        if electrode.electrode_id != command_electrode_id:
            continue

        electrode.status = value
        affected_subscribers.extend(electrode.subscriptions)

    run_subscriber_cycle(container, affected_subscribers)

def step(container: Container):
    """Advance simulation by one time step."""
    container.current_time += container.time_step

    for actuator in container.actuators:
        model = ACTUATOR_MODEL_DISPATCH.get(getattr(actuator, "type", ""))
        if model is not None:
            model(container, actuator)

    update_micro_shaker_subscriptions(container)

    # Run one breadth-first model cycle for time subscribers every simulation step.
    run_subscriber_cycle(container, [d.id for d in container.droplets], trigger="time")

    update_micro_shaker_subscriptions(container)

    # Bubble dynamics are caller-based and run every simulation step.
    for bubble in list(container.bubbles):
        if bubble in container.bubbles:
            move_bubble(container, bubble)
    for bubble in list(container.bubbles):
        if bubble in container.bubbles:
            bubble_merge(container, bubble)

    for bubble in container.bubbles:
        bubble.age += container.time_step
        if bubble.age >= bubble.lifetime:
            bubble.to_remove = True

    # Remove bubbles marked for removal.
    container.bubbles = [b for b in container.bubbles if not b.to_remove]
    update_sensor_readings(container)

def initialize(filepath: str) -> Container:
    container = load_platform(filepath)
    initialize_board(container)
    initialize_droplets(container)
    initialize_actuators(container)
    initialize_sensors(container)
    initialize_subscriptions(container)
    recalculate_groups(container)
    return container