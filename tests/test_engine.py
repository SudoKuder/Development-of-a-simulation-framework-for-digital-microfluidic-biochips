import json
import pytest
from engine import initialize, find_neighbours, initialize_subscriptions, execute_action, step
from datatypes import ColorSensor, Container, Droplet, Electrode, TemperatureSensor
from loader import load_platform
from models import blend_colors, droplet_make_bubble, droplet_merge, recalculate_groups, update_sensor_readings

def test_neighbour_finder():
    container = load_platform("data/platform640Center_path.json")
    find_neighbours(container)
    e0 = container.electrodes[0]
    assert len(e0.neighbours) > 0

def test_subscription_initialization():
    container = load_platform("data/platform640Center_path.json")
    find_neighbours(container)
    initialize_subscriptions(container)
    # Every droplet should be subscribed to at least one electrode
    for droplet in container.droplets:
        assert droplet.electrode_id != -1

def test_droplet_group_initialization():
    container = load_platform("data/platform640Center_path.json")
    find_neighbours(container)
    initialize_subscriptions(container)
    recalculate_groups(container)
    # All droplets should have a valid group id
    for d in container.droplets:
        assert d.group_id >= 0

def test_color_blend():
    result = blend_colors("#FF0000", "#0000FF")
    assert result == "#7f007f"


def test_action_routes_by_driver_and_command_electrode_id():
    container = load_platform("data/platform640Center_path.json")
    target = next((e for e in container.electrodes if e.electrode_id == 263 and e.driver_id == 1), None)
    other = next((e for e in container.electrodes if e.electrode_id == 263 and e.driver_id == 0), None)
    assert target is not None
    assert other is not None

    execute_action(container, {
        "action": "setel",
        "driver": 1,
        "electrode_id": 263,
        "change": 1,
    })

    assert target.status == 1
    assert other.status == 0


def test_split_conserves_volume():
    container = load_platform("data/platform640Center_path.json")
    find_neighbours(container)
    initialize_subscriptions(container)

    caller = container.droplets[0]
    parent_electrode = next(e for e in container.electrodes if e.id == caller.electrode_id)
    neigh = next(e for e in container.electrodes if e.id == parent_electrode.neighbours[0])
    neigh.status = 1

    before_total = sum(d.volume for d in container.droplets)
    execute_action(container, {
        "action": "setel",
        "driver": neigh.driver_id,
        "electrode_id": neigh.electrode_id,
        "change": 1,
    })
    after_total = sum(d.volume for d in container.droplets)
    assert after_total == pytest.approx(before_total, rel=1e-6)


def test_bubbles_decay_over_time():
    container = load_platform("data/platform640Center_path.json")
    caller = container.droplets[0]
    caller.temperature = 100.0
    caller.bubble_cooldown = 0.0

    step(container)
    assert len(container.bubbles) >= 1

    # Prevent fresh bubble generation so this test verifies lifecycle cleanup.
    caller.temperature = 20.0

    max_lifetime = max(b.lifetime for b in container.bubbles)
    steps = int(max_lifetime / container.time_step) + 2
    for _ in range(steps):
        step(container)

    assert len(container.bubbles) == 0


def _merge_test_container(smaller_status: int) -> Container:
    e1 = Electrode(id=1, electrode_id=1, driver_id=0, x=0, y=0, size_x=20, size_y=20, status=0)
    e2 = Electrode(id=2, electrode_id=2, driver_id=0, x=20, y=0, size_x=20, size_y=20, status=smaller_status)
    return Container(electrodes=[e1, e2], droplets=[])


def test_merge_off_electrode_allows_partial_overlap_absorption():
    container = _merge_test_container(smaller_status=0)
    larger = Droplet(
        id=1,
        name="large",
        x=15,
        y=10,
        size_x=16,
        size_y=16,
        color="#ff0000",
        volume=20.0,
        electrode_id=1,
    )
    smaller = Droplet(
        id=2,
        name="small",
        x=24,
        y=10,
        size_x=10,
        size_y=10,
        color="#0000ff",
        volume=5.0,
        electrode_id=2,
    )
    container.droplets = [larger, smaller]

    droplet_merge(container, larger)

    assert len(container.droplets) == 1
    assert container.droplets[0].id == 1


def test_merge_on_electrode_requires_complete_overlap():
    container = _merge_test_container(smaller_status=1)
    larger = Droplet(
        id=1,
        name="large",
        x=15,
        y=10,
        size_x=16,
        size_y=16,
        color="#ff0000",
        volume=20.0,
        electrode_id=1,
    )
    smaller = Droplet(
        id=2,
        name="small",
        x=24,
        y=10,
        size_x=10,
        size_y=10,
        color="#0000ff",
        volume=5.0,
        electrode_id=2,
    )
    container.droplets = [larger, smaller]

    droplet_merge(container, larger)

    assert len(container.droplets) == 2


def test_temperature_sensor_strict_read_requires_center_and_clear_periphery():
    center = Electrode(id=1, electrode_id=10, driver_id=0, x=0, y=0, size_x=20, size_y=20, status=0)
    container = Container(electrodes=[center], droplets=[])
    sensor = TemperatureSensor(id=1, sensor_id=1, x=0, y=0, size_x=20, size_y=20)
    container.sensors = [sensor]

    centered = Droplet(
        id=1,
        name="centered",
        x=10,
        y=10,
        size_x=8,
        size_y=8,
        color="#11aa22",
        temperature=42.0,
        volume=12.0,
        electrode_id=1,
    )
    container.droplets = [centered]

    update_sensor_readings(container)
    assert sensor.temperature == pytest.approx(42.0)

    peripheral_overlap = Droplet(
        id=2,
        name="peripheral",
        x=18,
        y=10,
        size_x=8,
        size_y=8,
        color="#333333",
        temperature=30.0,
        volume=6.0,
        electrode_id=1,
    )
    container.droplets.append(peripheral_overlap)

    update_sensor_readings(container)
    assert sensor.temperature == -1.0


def test_color_sensor_returns_invalid_when_not_strictly_readable():
    center = Electrode(id=1, electrode_id=10, driver_id=0, x=0, y=0, size_x=20, size_y=20, status=0)
    container = Container(electrodes=[center], droplets=[])
    sensor = ColorSensor(id=1, sensor_id=1, x=0, y=0, size_x=20, size_y=20)
    container.sensors = [sensor]

    centered = Droplet(
        id=1,
        name="centered",
        x=10,
        y=10,
        size_x=8,
        size_y=8,
        color="#0a141e",
        temperature=20.0,
        volume=10.0,
        electrode_id=1,
    )
    blocker = Droplet(
        id=2,
        name="blocker",
        x=18,
        y=10,
        size_x=8,
        size_y=8,
        color="#ffffff",
        temperature=20.0,
        volume=8.0,
        electrode_id=1,
    )
    container.droplets = [centered, blocker]

    update_sensor_readings(container)
    assert [sensor.value_r, sensor.value_g, sensor.value_b] == [-1, -1, -1]


def test_bubble_requires_accumulated_hot_time_before_trigger():
    droplet = Droplet(
        id=1,
        name="hot",
        x=5,
        y=5,
        size_x=10,
        size_y=10,
        color="#ff3300",
        temperature=95.0,
        volume=100.0,
        electrode_id=1,
    )
    container = Container(droplets=[droplet], time_step=0.1, current_time=0.0)

    for _ in range(4):
        container.current_time += container.time_step
        droplet_make_bubble(container, droplet)

    assert len(container.bubbles) == 0

    container.current_time += container.time_step
    droplet_make_bubble(container, droplet)
    assert len(container.bubbles) == 1


def test_loader_parses_micro_shaker_from_json(tmp_path):
    platform = {
        "information": {"name": "ms", "sizeX": 100, "sizeY": 100},
        "electrodes": [],
        "droplets": [],
        "actuators": [
            {
                "id": 11,
                "actuatorID": 5,
                "name": "microShaker",
                "type": "micro_shaker",
                "positionX": 10,
                "positionY": 10,
                "sizeX": 20,
                "sizeY": 20,
                "valueVibrationFrequency": 5.0,
                "valueDesiredFrequency": 30.0,
                "valuePowerStatus": 1,
            }
        ],
        "sensors": [],
    }
    path = tmp_path / "platform_micro_shaker.json"
    path.write_text(json.dumps(platform), encoding="utf-8")

    container = load_platform(str(path))

    assert len(container.actuators) == 1
    shaker = container.actuators[0]
    assert getattr(shaker, "type", "") == "micro_shaker"
    assert getattr(shaker, "name", "") == "microShaker"
    assert getattr(shaker, "desired_frequency", 0.0) == pytest.approx(30.0)


def test_micro_shaker_updates_and_vibrates_droplet(tmp_path):
    platform = {
        "information": {"name": "ms", "sizeX": 100, "sizeY": 100},
        "electrodes": [
            {"ID": 1, "electrodeID": 1, "driverID": 0, "shape": 0, "positionX": 0, "positionY": 0, "sizeX": 40, "sizeY": 40, "status": 0, "corners": []}
        ],
        "droplets": [
            {"id": 1, "name": "d", "positionX": 20, "positionY": 20, "sizeX": 10, "sizeY": 10, "color": "#ff0000", "temperature": 20.0, "electrodeID": 1}
        ],
        "actuators": [
            {
                "id": 11,
                "actuatorID": 5,
                "name": "microShaker",
                "type": "micro_shaker",
                "positionX": 5,
                "positionY": 5,
                "sizeX": 30,
                "sizeY": 30,
                "valueVibrationFrequency": 0.0,
                "valueDesiredFrequency": 60.0,
                "valuePowerStatus": 1,
            }
        ],
        "sensors": [],
    }
    path = tmp_path / "platform_micro_shaker_runtime.json"
    path.write_text(json.dumps(platform), encoding="utf-8")

    container = initialize(str(path))
    droplet = container.droplets[0]
    initial_temp = droplet.temperature

    step(container)

    shaker = container.actuators[0]
    assert getattr(shaker, "vibration_frequency", 0.0) > 0.0
    assert droplet.temperature > initial_temp
    assert droplet.id in getattr(shaker, "subscriptions", [])