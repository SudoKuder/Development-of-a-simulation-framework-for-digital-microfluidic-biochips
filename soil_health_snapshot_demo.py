import argparse
from pathlib import Path

import pygame

from datatypes import (
    Droplet,
    score_nitrogen,
    score_phosphorus,
    score_potassium,
    soil_color_from_npk,
)
from engine import initialize, initialize_subscriptions
from models import droplet_merge

SCALE = 4
MARGIN = 20
BG = (246, 241, 232)
ELEC_OFF = (220, 214, 205)
ELEC_BORDER = (88, 78, 68)
TEXT = (42, 36, 31)


def _hex_to_rgb(hex_color: str):
    normalized = hex_color.lstrip("#")
    if len(normalized) != 6:
        return (255, 255, 255)
    return tuple(int(normalized[i:i + 2], 16) for i in (0, 2, 4))


def _render_snapshot(container, title: str, output_path: Path):
    width = container.board_width * SCALE + MARGIN * 2
    height = container.board_height * SCALE + MARGIN * 2 + 90

    pygame.init()
    pygame.font.init()

    surface = pygame.Surface((width, height))
    surface.fill(BG)

    for electrode in container.electrodes:
        rect = pygame.Rect(
            MARGIN + electrode.x * SCALE,
            MARGIN + electrode.y * SCALE,
            electrode.size_x * SCALE,
            electrode.size_y * SCALE,
        )
        pygame.draw.rect(surface, ELEC_OFF, rect)
        pygame.draw.rect(surface, ELEC_BORDER, rect, 1)

    for droplet in container.droplets:
        center = (int(MARGIN + droplet.x * SCALE), int(MARGIN + droplet.y * SCALE))
        radius = int(max(4, min(droplet.size_x, droplet.size_y) * SCALE / 2))
        pygame.draw.circle(surface, _hex_to_rgb(droplet.color), center, radius)
        pygame.draw.circle(surface, (30, 30, 30), center, radius, 1)

    title_font = pygame.font.SysFont("monospace", 22, bold=True)
    text_font = pygame.font.SysFont("monospace", 16)

    surface.blit(title_font.render(title, True, TEXT), (MARGIN, height - 80))

    line_y = height - 52
    for droplet in sorted(container.droplets, key=lambda d: d.id):
        n_level = score_nitrogen(droplet.nitrogen)
        p_level = score_phosphorus(droplet.phosphorus)
        k_level = score_potassium(droplet.potassium)
        summary = (
            f"{droplet.name}: N={droplet.nitrogen:.2f}({n_level}) "
            f"P={droplet.phosphorus:.2f}({p_level}) "
            f"K={droplet.potassium:.1f}({k_level}) color={droplet.color}"
        )
        surface.blit(text_font.render(summary, True, TEXT), (MARGIN, line_y))
        line_y += 18

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(output_path))
    pygame.quit()


def _demo_droplets():
    droplet_a = Droplet(
        id=1,
        name="soil_A",
        x=30,
        y=30,
        size_x=22,
        size_y=22,
        color=soil_color_from_npk(0.75, 0.40, 60.0),
        volume=22.0,
        electrode_id=1,
        is_soil_sample=True,
        nitrogen=0.75,
        phosphorus=0.40,
        potassium=60.0,
    )
    droplet_b = Droplet(
        id=2,
        name="soil_B",
        x=50,
        y=30,
        size_x=18,
        size_y=18,
        color=soil_color_from_npk(0.95, 0.70, 120.0),
        volume=12.0,
        electrode_id=2,
        is_soil_sample=True,
        nitrogen=0.95,
        phosphorus=0.70,
        potassium=120.0,
    )
    return droplet_a, droplet_b


def run(platform: str, output_dir: str):
    container = initialize(platform)

    droplet_a, droplet_b = _demo_droplets()
    container.droplets = [droplet_a, droplet_b]
    initialize_subscriptions(container)

    before_path = Path(output_dir) / "soil_merge_before.png"
    after_path = Path(output_dir) / "soil_merge_after.png"

    _render_snapshot(container, "Before merge: two soil droplets", before_path)

    # Caller is larger, so merge model absorbs droplet_b into droplet_a.
    droplet_merge(container, droplet_a)
    initialize_subscriptions(container)

    _render_snapshot(container, "After merge: nutrient-weighted color", after_path)

    print(f"Saved: {before_path}")
    print(f"Saved: {after_path}")
    for droplet in container.droplets:
        print(
            f"{droplet.name} -> N={droplet.nitrogen:.3f}, "
            f"P={droplet.phosphorus:.3f}, K={droplet.potassium:.3f}, color={droplet.color}"
        )


def _parse_args():
    parser = argparse.ArgumentParser(description="Generate NPK soil droplet merge snapshots.")
    parser.add_argument(
        "--platform",
        default="data/testing/platform_small_cross.json",
        help="Path to platform JSON used as board layout.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/showcase",
        help="Directory where before/after PNG files will be written.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(args.platform, args.output_dir)
