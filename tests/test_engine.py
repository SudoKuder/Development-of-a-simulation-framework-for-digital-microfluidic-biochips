import pytest
from engine import initialize, find_neighbours, initialize_subscriptions
from loader import load_platform
from models import blend_colors, recalculate_groups

def test_neighbour_finder():
    container = load_platform("data/platform640.json")
    find_neighbours(container)
    e0 = container.electrodes[0]
    assert len(e0.neighbours) > 0

def test_subscription_initialization():
    container = load_platform("data/platform640.json")
    find_neighbours(container)
    initialize_subscriptions(container)
    # Every droplet should be subscribed to at least one electrode
    for droplet in container.droplets:
        assert droplet.electrode_id != -1

def test_droplet_group_initialization():
    container = load_platform("data/platform640.json")
    find_neighbours(container)
    initialize_subscriptions(container)
    recalculate_groups(container)
    # All droplets should have a valid group id
    for d in container.droplets:
        assert d.group_id >= 0

def test_color_blend():
    result = blend_colors("#FF0000", "#0000FF")
    assert result == "#7f007f"