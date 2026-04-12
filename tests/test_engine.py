import json
import pytest
from engine import (
    initialize,
    find_neighbours,
    initialize_subscriptions,
    execute_action,
    register_droplet_model,
    run_subscriber_cycle,
    step,
)
from datatypes import ColorSensor, Container, Droplet, Electrode, Heater, TemperatureSensor
from loader import load_platform
from models import (
    blend_colors,
    colorSensor,
    dropletColorChange,
    dropletTemperatureChange,
    droplet_make_bubble,
    droplet_merge,
    droplet_split,
    heater_temperature_change,
    makeBubble,
    recalculate_groups,
    temperatureSensor,
    updateGroupColor,
    updateGroupTemperature,
    update_sensor_readings,
)

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


def test_split_requires_overlap_to_be_attracted():
    center = Electrode(id=1, electrode_id=10, driver_id=0, x=20, y=20, size_x=20, size_y=20, status=1, neighbours=[2])
    right = Electrode(id=2, electrode_id=11, driver_id=0, x=40, y=20, size_x=20, size_y=20, status=1, neighbours=[1])
    droplet = Droplet(
        id=1,
        name="d",
        x=30,
        y=30,
        size_x=16,
        size_y=16,
        color="#33cc66",
        volume=20.0,
        electrode_id=1,
    )
    container = Container(electrodes=[center, right], droplets=[droplet])

    droplet_split(container, droplet)

    assert len(container.droplets) == 1
    assert container.droplets[0].volume == pytest.approx(20.0)
    assert container.droplets[0].electrode_id == 1


def test_split_with_two_on_neighbours_creates_equal_daughters():
    center = Electrode(id=1, electrode_id=10, driver_id=0, x=20, y=20, size_x=20, size_y=20, status=1, neighbours=[2, 3])
    left = Electrode(id=2, electrode_id=11, driver_id=0, x=0, y=20, size_x=20, size_y=20, status=1, neighbours=[1])
    right = Electrode(id=3, electrode_id=12, driver_id=0, x=40, y=20, size_x=20, size_y=20, status=1, neighbours=[1])
    droplet = Droplet(
        id=1,
        name="d",
        x=30,
        y=30,
        size_x=40,
        size_y=40,
        color="#33cc66",
        volume=20.0,
        electrode_id=1,
    )
    container = Container(electrodes=[center, left, right], droplets=[droplet])

    droplet_split(container, droplet)

    assert len(container.droplets) == 3
    assert sum(d.volume for d in container.droplets) == pytest.approx(20.0)
    assert len({d.group_id for d in container.droplets}) == 1
    for d in container.droplets:
        assert d.volume == pytest.approx(20.0 / 3.0)
    assert {d.electrode_id for d in container.droplets} == {1, 2, 3}


def test_large_droplet_can_small_split_to_non_neighbour():
    center = Electrode(id=1, electrode_id=10, driver_id=0, x=20, y=20, size_x=20, size_y=20, status=1, neighbours=[2])
    right = Electrode(id=2, electrode_id=11, driver_id=0, x=40, y=20, size_x=20, size_y=20, status=0, neighbours=[1])
    remote = Electrode(id=3, electrode_id=12, driver_id=0, x=60, y=20, size_x=20, size_y=20, status=1, neighbours=[])
    droplet = Droplet(
        id=1,
        name="d",
        x=30,
        y=30,
        size_x=70,
        size_y=70,
        color="#33cc66",
        volume=500.0,
        electrode_id=1,
    )
    container = Container(electrodes=[center, right, remote], droplets=[droplet])

    droplet_split(container, droplet)

    assert len(container.droplets) == 2
    parent, child = sorted(container.droplets, key=lambda d: d.id)
    assert child.electrode_id == 3
    assert child.group_id != parent.group_id
    assert child.volume == pytest.approx(0.9 * (20 * 20))


def test_classical_split_requires_origin_electrode_on():
    center = Electrode(id=1, electrode_id=10, driver_id=0, x=20, y=20, size_x=20, size_y=20, status=0, neighbours=[2])
    right = Electrode(id=2, electrode_id=11, driver_id=0, x=40, y=20, size_x=20, size_y=20, status=1, neighbours=[1])
    droplet = Droplet(
        id=1,
        name="d",
        x=30,
        y=30,
        size_x=40,
        size_y=40,
        color="#33cc66",
        volume=20.0,
        electrode_id=1,
    )
    container = Container(electrodes=[center, right], droplets=[droplet])

    droplet_split(container, droplet)

    # Origin electrode is OFF, so this is interpreted as motion-pull context, not classical split.
    assert len(container.droplets) == 1


def test_split_onto_bridge_joins_groups_without_absorption_regression():
    e1 = Electrode(id=1, electrode_id=101, driver_id=0, x=20, y=20, size_x=20, size_y=20, status=1, neighbours=[2])
    e2 = Electrode(id=2, electrode_id=102, driver_id=0, x=40, y=20, size_x=20, size_y=20, status=1, neighbours=[1, 3])
    e3 = Electrode(id=3, electrode_id=103, driver_id=0, x=60, y=20, size_x=20, size_y=20, status=1, neighbours=[2])

    # Large droplet on e1 overlaps e2 peripheral area and can split to it.
    left_big = Droplet(
        id=1,
        name="left_big",
        x=30,
        y=30,
        size_x=32,
        size_y=32,
        color="#1f77ff",
        volume=90.0,
        electrode_id=1,
    )
    # Small droplet on e3 provides the second group to be joined through bridge e2.
    right_small = Droplet(
        id=2,
        name="right_small",
        x=70,
        y=30,
        size_x=20,
        size_y=20,
        color="#00dd66",
        volume=40.0,
        electrode_id=3,
    )
    container = Container(electrodes=[e1, e2, e3], droplets=[left_big, right_small])

    droplet_split(container, left_big)

    assert len(container.droplets) == 3
    assert any(d.electrode_id == 2 for d in container.droplets)
    assert len({d.group_id for d in container.droplets}) == 1


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


def test_merge_updates_entire_group_color_and_temperature():
    e1 = Electrode(id=1, electrode_id=1, driver_id=0, x=0, y=0, size_x=20, size_y=20, status=0, neighbours=[2])
    e2 = Electrode(id=2, electrode_id=2, driver_id=0, x=20, y=0, size_x=20, size_y=20, status=0, neighbours=[1, 3])
    e3 = Electrode(id=3, electrode_id=3, driver_id=0, x=40, y=0, size_x=20, size_y=20, status=0, neighbours=[2])
    container = Container(electrodes=[e1, e2, e3], droplets=[])

    # Same group before merge.
    caller = Droplet(
        id=1,
        name="caller",
        x=10,
        y=10,
        size_x=16,
        size_y=16,
        color="#ff0000",
        temperature=30.0,
        volume=10.0,
        electrode_id=1,
        group_id=7,
        specific_heat_capacity=4.0,
    )
    group_mate = Droplet(
        id=2,
        name="group_mate",
        x=30,
        y=10,
        size_x=16,
        size_y=16,
        color="#00ff00",
        temperature=50.0,
        volume=20.0,
        electrode_id=2,
        group_id=7,
        specific_heat_capacity=2.0,
    )
    incoming = Droplet(
        id=3,
        name="incoming",
        x=16,
        y=10,
        size_x=10,
        size_y=10,
        color="#0000ff",
        temperature=90.0,
        volume=5.0,
        electrode_id=1,
        group_id=8,
        specific_heat_capacity=1.0,
    )
    container.droplets = [caller, group_mate, incoming]

    droplet_merge(container, caller)

    assert len(container.droplets) == 2
    updated_caller = next(d for d in container.droplets if d.id == 1)
    updated_group_mate = next(d for d in container.droplets if d.id == 2)

    # Color should be updated for whole caller-group and include incoming volume share.
    expected_group_color = blend_colors("#ff0000", "#00ff00", w1=10.0, w2=20.0)
    expected_final_color = blend_colors(expected_group_color, "#0000ff", w1=30.0, w2=5.0)
    assert updated_caller.color == expected_final_color
    assert updated_group_mate.color == expected_final_color

    # Temperature should be heat-capacity weighted across group + incoming.
    expected_temp = ((30.0 * 10.0 * 4.0) + (50.0 * 20.0 * 2.0) + (90.0 * 5.0 * 1.0)) / (
        (10.0 * 4.0) + (20.0 * 2.0) + (5.0 * 1.0)
    )
    assert updated_caller.temperature == pytest.approx(expected_temp)
    assert updated_group_mate.temperature == pytest.approx(expected_temp)


def test_merge_off_to_on_neighbouring_droplets_removes_caller_and_distributes_volume():
    center = Electrode(id=1, electrode_id=1, driver_id=0, x=20, y=20, size_x=20, size_y=20, status=0, neighbours=[2, 3], subscriptions=[1])
    left = Electrode(id=2, electrode_id=2, driver_id=0, x=0, y=20, size_x=20, size_y=20, status=1, neighbours=[1], subscriptions=[2])
    right = Electrode(id=3, electrode_id=3, driver_id=0, x=40, y=20, size_x=20, size_y=20, status=1, neighbours=[1], subscriptions=[3])

    caller = Droplet(
        id=1,
        name="caller",
        x=30,
        y=30,
        size_x=20,
        size_y=20,
        color="#33cc66",
        volume=12.0,
        electrode_id=1,
    )
    d2 = Droplet(
        id=2,
        name="n1",
        x=10,
        y=30,
        size_x=19,
        size_y=19,
        color="#33cc66",
        volume=20.0,
        electrode_id=2,
    )
    d3 = Droplet(
        id=3,
        name="n2",
        x=50,
        y=30,
        size_x=21,
        size_y=21,
        color="#33cc66",
        volume=30.0,
        electrode_id=3,
    )
    container = Container(electrodes=[center, left, right], droplets=[caller, d2, d3])

    touched = droplet_merge(container, caller)

    assert len(container.droplets) == 2
    assert all(d.id != 1 for d in container.droplets)
    updated2 = next(d for d in container.droplets if d.id == 2)
    updated3 = next(d for d in container.droplets if d.id == 3)
    assert updated2.volume == pytest.approx(26.0)
    assert updated3.volume == pytest.approx(36.0)
    assert 1 not in center.subscriptions
    assert touched == [2, 3]


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


def test_sensor_model_aliases_match_spec_names_and_type_guards():
    center = Electrode(id=1, electrode_id=10, driver_id=0, x=0, y=0, size_x=20, size_y=20, status=0)
    droplet = Droplet(
        id=1,
        name="centered",
        x=10,
        y=10,
        size_x=8,
        size_y=8,
        color="#112233",
        temperature=37.5,
        volume=10.0,
        electrode_id=1,
    )
    container = Container(electrodes=[center], droplets=[droplet])
    t_sensor = TemperatureSensor(id=1, sensor_id=1, x=0, y=0, size_x=20, size_y=20)
    c_sensor = ColorSensor(id=2, sensor_id=2, x=0, y=0, size_x=20, size_y=20)

    assert temperatureSensor(container, t_sensor) == pytest.approx(37.5)
    assert colorSensor(container, c_sensor) == [17, 34, 51]

    # Wrong sensor type must return sentinel values.
    assert temperatureSensor(container, c_sensor) == -1.0
    assert colorSensor(container, t_sensor) == [-1, -1, -1]


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


def test_camel_case_model_aliases_match_snake_case_logic():
    e1 = Electrode(id=1, electrode_id=1, driver_id=0, x=0, y=0, size_x=20, size_y=20, status=0)
    container = Container(electrodes=[e1], droplets=[], time_step=0.1)

    d_group = Droplet(
        id=1,
        name="g",
        x=10,
        y=10,
        size_x=12,
        size_y=12,
        color="#ff0000",
        temperature=30.0,
        volume=10.0,
        group_id=1,
        electrode_id=1,
    )
    d_peer = Droplet(
        id=2,
        name="p",
        x=14,
        y=10,
        size_x=12,
        size_y=12,
        color="#00ff00",
        temperature=40.0,
        volume=5.0,
        group_id=1,
        electrode_id=1,
    )
    d_in = Droplet(
        id=3,
        name="i",
        x=16,
        y=10,
        size_x=8,
        size_y=8,
        color="#0000ff",
        temperature=90.0,
        volume=2.0,
        group_id=2,
        electrode_id=1,
    )
    container.droplets = [d_group, d_peer, d_in]

    assert updateGroupColor(container, d_group, d_in) == dropletColorChange(container, d_group, d_in)
    assert updateGroupTemperature(container, d_group, d_in) == pytest.approx(
        updateGroupTemperature(container, d_group, d_in)
    )

    cool_d = Droplet(
        id=4,
        name="cool",
        x=10,
        y=10,
        size_x=10,
        size_y=10,
        color="#aaaaaa",
        temperature=20.0,
        volume=10.0,
        electrode_id=1,
    )
    hot_d = Droplet(
        id=5,
        name="hot",
        x=10,
        y=10,
        size_x=10,
        size_y=10,
        color="#ff3300",
        temperature=95.0,
        volume=100.0,
        electrode_id=1,
    )

    container.droplets = [cool_d]
    before = cool_d.temperature
    dropletTemperatureChange(container, cool_d)
    assert cool_d.temperature == pytest.approx(before)

    bubble_container_a = Container(droplets=[hot_d], time_step=0.1, current_time=0.0)
    bubble_container_b = Container(
        droplets=[
            Droplet(
                id=6,
                name="hot2",
                x=10,
                y=10,
                size_x=10,
                size_y=10,
                color="#ff3300",
                temperature=95.0,
                volume=100.0,
                electrode_id=1,
            )
        ],
        time_step=0.1,
        current_time=0.0,
    )
    for _ in range(5):
        bubble_container_a.current_time += bubble_container_a.time_step
        bubble_container_b.current_time += bubble_container_b.time_step
        droplet_make_bubble(bubble_container_a, bubble_container_a.droplets[0])
        makeBubble(bubble_container_b, bubble_container_b.droplets[0])

    assert len(bubble_container_a.bubbles) == len(bubble_container_b.bubbles)


def test_heater_requires_explicit_setpoint_before_temperature_change():
    heater = Heater(
        id=1,
        actuator_id=1,
        x=0,
        y=0,
        size_x=10,
        size_y=10,
        actual_temp=20.0,
        desired_temp=90.0,
        has_target_setpoint=False,
    )
    container = Container(actuators=[heater], time_step=1.0)

    heater_temperature_change(container, heater)

    assert heater.actual_temp == pytest.approx(20.0)
    assert heater.power_status == 0


def test_heater_smart_model_heats_toward_target_after_setpoint():
    heater = Heater(
        id=1,
        actuator_id=1,
        x=0,
        y=0,
        size_x=10,
        size_y=10,
        actual_temp=20.0,
        desired_temp=21.0,
        has_target_setpoint=True,
    )
    container = Container(actuators=[heater], time_step=1.0)

    heater_temperature_change(container, heater)

    assert heater.power_status == 1
    assert heater.actual_temp == pytest.approx(20.0 + (70.0 / 90.0))


def test_heater_smart_model_uses_negative_power_for_cooling():
    heater = Heater(
        id=1,
        actuator_id=1,
        x=0,
        y=0,
        size_x=10,
        size_y=10,
        actual_temp=30.0,
        desired_temp=20.0,
        has_target_setpoint=True,
    )
    container = Container(actuators=[heater], time_step=1.0)

    heater_temperature_change(container, heater)

    assert heater.power_status == -1
    assert heater.actual_temp == pytest.approx(30.0 - (70.0 / 90.0))


def test_subscriber_queue_runs_models_breadth_first_per_droplet_order():
    sequence = []

    def model_a(_container, droplet):
        sequence.append((droplet.id, "a"))
        return [droplet.id]

    def model_b(_container, droplet):
        sequence.append((droplet.id, "b"))
        return [droplet.id]

    register_droplet_model("unit_a", model_a)
    register_droplet_model("unit_b", model_b)

    d1 = Droplet(
        id=1,
        name="d1",
        x=0,
        y=0,
        size_x=10,
        size_y=10,
        color="#ffffff",
        model_order=["unit_a", "unit_b"],
    )
    d2 = Droplet(
        id=2,
        name="d2",
        x=0,
        y=0,
        size_x=10,
        size_y=10,
        color="#ffffff",
        model_order=["unit_a", "unit_b"],
    )
    container = Container(droplets=[d1, d2])

    run_subscriber_cycle(container, [1, 2], trigger="all")

    assert sequence == [(1, "a"), (2, "a"), (1, "b"), (2, "b")]


def test_time_and_action_subscribers_run_different_model_ranges():
    sequence = []

    def model_split(_container, droplet):
        sequence.append((droplet.id, "split"))
        return [droplet.id]

    def model_merge(_container, droplet):
        sequence.append((droplet.id, "merge"))
        return [droplet.id]

    def model_temp(_container, droplet):
        sequence.append((droplet.id, "temperature"))
        return [droplet.id]

    def model_bubble(_container, droplet):
        sequence.append((droplet.id, "make_bubble"))
        return [droplet.id]

    register_droplet_model("unit_split", model_split)
    register_droplet_model("unit_merge", model_merge)
    register_droplet_model("unit_temperature", model_temp)
    register_droplet_model("unit_make_bubble", model_bubble)

    droplet = Droplet(
        id=1,
        name="d",
        x=0,
        y=0,
        size_x=10,
        size_y=10,
        color="#ffffff",
        model_order=["unit_split", "unit_merge", "unit_temperature", "unit_make_bubble"],
        begin_of_time_sensitive_models=2,
    )
    container = Container(droplets=[droplet])

    run_subscriber_cycle(container, [1], trigger="action")
    assert sequence == [(1, "split"), (1, "merge")]

    sequence.clear()
    droplet.next_model = 0
    run_subscriber_cycle(container, [1], trigger="time")
    assert sequence == [(1, "temperature"), (1, "make_bubble")]