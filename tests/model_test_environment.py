import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datatypes import Droplet
from engine import initialize
from models import droplet_merge, dropletTemperatureChange, makeBubble


def _base_container(platform_path: str):
    return initialize(platform_path)


def _print_header(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def run_color_temperature_merge(platform_path: str) -> None:
    container = _base_container(platform_path)

    caller = Droplet(
        id=1,
        name="caller",
        x=20,
        y=40,
        size_x=16,
        size_y=16,
        color="#ff0000",
        temperature=30.0,
        volume=10.0,
        electrode_id=1,
        group_id=10,
        specific_heat_capacity=4.0,
    )
    group_mate = Droplet(
        id=2,
        name="group_mate",
        x=40,
        y=40,
        size_x=16,
        size_y=16,
        color="#00ff00",
        temperature=50.0,
        volume=20.0,
        electrode_id=2,
        group_id=10,
        specific_heat_capacity=2.0,
    )
    incoming = Droplet(
        id=3,
        name="incoming",
        x=22,
        y=40,
        size_x=8,
        size_y=8,
        color="#0000ff",
        temperature=90.0,
        volume=5.0,
        electrode_id=1,
        group_id=11,
        specific_heat_capacity=1.0,
    )
    container.droplets = [caller, group_mate, incoming]

    _print_header("Scenario 1: Group Color and Temperature Merge")
    print(f"Before merge: {[ (d.id, d.color, round(d.temperature, 3), d.volume, d.group_id) for d in container.droplets ]}")

    droplet_merge(container, caller)

    print(f"After merge:  {[ (d.id, d.color, round(d.temperature, 3), round(d.volume, 3), d.group_id) for d in container.droplets ]}")

    if len(container.droplets) != 2:
        raise RuntimeError("Merge scenario failed: expected 2 droplets after merge.")

    if container.droplets[0].color != container.droplets[1].color:
        raise RuntimeError("Merge scenario failed: group color was not propagated.")

    if abs(container.droplets[0].temperature - container.droplets[1].temperature) > 1e-9:
        raise RuntimeError("Merge scenario failed: group temperature was not propagated.")

    print("Result: PASS")


def run_heating_cooling(platform_path: str) -> None:
    container = _base_container(platform_path)

    droplet = Droplet(
        id=10,
        name="thermal_probe",
        x=40,
        y=40,
        size_x=12,
        size_y=12,
        color="#ffaa00",
        temperature=20.0,
        volume=20.0,
        electrode_id=2,
    )
    container.droplets = [droplet]

    _print_header("Scenario 2: Heating then Cooling")
    print(f"Start temperature: {droplet.temperature:.3f} C")

    for _ in range(20):
        dropletTemperatureChange(container, droplet)
    heated_temp = droplet.temperature
    print(f"After heating steps: {heated_temp:.3f} C")

    # Move droplet off heater onto room-temperature board.
    droplet.x = 20
    droplet.y = 40
    droplet.electrode_id = 1

    for _ in range(60):
        dropletTemperatureChange(container, droplet)
    cooled_temp = droplet.temperature
    print(f"After cooling steps: {cooled_temp:.3f} C")

    if heated_temp <= 20.0:
        raise RuntimeError("Heating scenario failed: temperature did not increase.")

    if cooled_temp >= heated_temp:
        raise RuntimeError("Cooling scenario failed: temperature did not decrease.")

    if cooled_temp < 20.0:
        raise RuntimeError("Cooling scenario failed: temperature dropped below room temperature clamp.")

    print("Result: PASS")


def run_bubble_generation(platform_path: str) -> None:
    container = _base_container(platform_path)

    droplet = Droplet(
        id=20,
        name="hot_drop",
        x=40,
        y=40,
        size_x=12,
        size_y=12,
        color="#ff3300",
        temperature=95.0,
        volume=100.0,
        electrode_id=2,
    )
    container.droplets = [droplet]

    _print_header("Scenario 3: Bubble Generation")
    print(f"Start volume: {droplet.volume:.3f}")

    spawned_at = None
    for i in range(1, 20):
        container.current_time += container.time_step
        makeBubble(container, droplet)
        if container.bubbles and spawned_at is None:
            spawned_at = i * container.time_step

    print(f"Bubble count: {len(container.bubbles)}")
    print(f"Droplet volume after evaporation: {droplet.volume:.3f}")
    print(f"First bubble time: {spawned_at}")

    if len(container.bubbles) == 0:
        raise RuntimeError("Bubble scenario failed: no bubble was generated.")

    print("Result: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a model validation environment for color, temperature, and bubbles.")
    parser.add_argument(
        "--platform",
        default="data/testing/platform_model_environment.json",
        help="Path to platform JSON used by all scenarios.",
    )
    args = parser.parse_args()

    run_color_temperature_merge(args.platform)
    run_heating_cooling(args.platform)
    run_bubble_generation(args.platform)

    print("\nAll model scenarios completed successfully.")


if __name__ == "__main__":
    main()
