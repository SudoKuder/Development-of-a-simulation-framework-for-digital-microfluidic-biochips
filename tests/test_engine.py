import pytest
from engine import initialize, find_neighbours, initialize_subscriptions, execute_action, step
from loader import load_platform
from models import blend_colors, recalculate_groups

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