import copy
import json
import math
from collections import defaultdict

import pygame

from datatypes import (
    ColorSensor,
    Container,
    Droplet,
    Electrode,
    MicroShaker,
    TemperatureSensor,
    is_reagent_type,
    soil_color_from_npk,
    soil_reagent_reaction,
)
from engine import step

SCALE = 2
FPS = 30
SKETCH_HEADER_H = 36

BG_COLOR = (24, 24, 24)
ELEC_OFF = (230, 230, 230)
ELEC_ON = (220, 60, 60)
ELEC_BORDER = (0, 0, 0)
BUBBLE_COLOR = (170, 190, 255)
PANEL_BG = (38, 38, 38)
PANEL_BORDER = (82, 82, 82)
TEXT_COLOR = (225, 225, 225)
MUTED_TEXT = (165, 165, 165)
SKETCH_HEADER_BG = (236, 236, 236)
SKETCH_HEADER_TEXT = (20, 20, 20)


def hex_to_rgb(hex_color: str):
    normalized = hex_color.lstrip("#")
    if len(normalized) != 6:
        return (255, 255, 255)
    return tuple(int(normalized[i:i + 2], 16) for i in (0, 2, 4))


def clamp(value, low, high):
    return max(low, min(high, value))


def point_in_rect(px, py, x, y, w, h):
    return x <= px <= x + w and y <= py <= y + h


class GUIBroker:
    """Intermediary data exchange layer between simulation state and GUI panels."""

    def __init__(self, container: Container):
        self.container = container
        self.board = {
            "electrodes": [],
            "droplets": [],
            "actuators": [],
            "sensors": [],
            "bubbles": [],
        }
        self.prev_droplet_groups = {}
        self.droplet_groups = {}
        self.data_for_download = []
        self.selections = [
            {"id": "active_electrodes", "text": "Show Active Electrodes", "checked": True},
            {"id": "actuators", "text": "Show Actuators", "checked": True},
            {"id": "sensors", "text": "Show Sensors", "checked": True},
            {"id": "droplet_groups", "text": "Show Droplet Groups", "checked": True},
            {"id": "bubbles", "text": "Show Bubbles", "checked": True},
        ]
        self.sync_from_container()

    def is_enabled(self, selection_id: str) -> bool:
        entry = next((s for s in self.selections if s["id"] == selection_id), None)
        return bool(entry and entry["checked"])

    def toggle(self, selection_id: str):
        for entry in self.selections:
            if entry["id"] == selection_id:
                entry["checked"] = not entry["checked"]
                break

    def sync_from_container(self):
        self.prev_droplet_groups = copy.deepcopy(self.droplet_groups)
        self.board["electrodes"] = self.container.electrodes
        self.board["droplets"] = self.container.droplets
        self.board["actuators"] = self.container.actuators
        self.board["sensors"] = self.container.sensors
        self.board["bubbles"] = self.container.bubbles
        self.droplet_groups = self._build_droplet_groups()

    def _build_droplet_groups(self):
        groups = {}
        by_gid = defaultdict(list)
        for droplet in self.container.droplets:
            by_gid[droplet.group_id].append(droplet)

        for gid, droplets in by_gid.items():
            components = self._split_connected(droplets)
            for idx, component in enumerate(components):
                key = f"{gid}:{idx}"
                contour = self._contour_for_component(component)
                groups[key] = {
                    "group_id": gid,
                    "key": key,
                    "droplets": component,
                    "droplet_ids": {d.id for d in component},
                    "contour": contour,
                    "color": self._average_color(component),
                }
        return groups

    def _split_connected(self, droplets):
        if not droplets:
            return []
        unvisited = {d.id: d for d in droplets}
        components = []

        while unvisited:
            _, seed = unvisited.popitem()
            queue = [seed]
            component = [seed]
            while queue:
                cur = queue.pop(0)
                for other_id, other in list(unvisited.items()):
                    if self._droplets_touch(cur, other):
                        component.append(other)
                        queue.append(other)
                        del unvisited[other_id]
            components.append(component)
        return components

    def _droplets_touch(self, d1: Droplet, d2: Droplet) -> bool:
        left1 = d1.x - d1.size_x / 2
        right1 = d1.x + d1.size_x / 2
        top1 = d1.y - d1.size_y / 2
        bottom1 = d1.y + d1.size_y / 2

        left2 = d2.x - d2.size_x / 2
        right2 = d2.x + d2.size_x / 2
        top2 = d2.y - d2.size_y / 2
        bottom2 = d2.y + d2.size_y / 2

        inter_x = min(right1, right2) - max(left1, left2)
        inter_y = min(bottom1, bottom2) - max(top1, top2)
        eps = 1e-6
        if inter_x > eps and inter_y > eps:
            return True
        touch_vertical = inter_x > eps and (abs(bottom1 - top2) <= eps or abs(bottom2 - top1) <= eps)
        touch_horizontal = inter_y > eps and (abs(right1 - left2) <= eps or abs(right2 - left1) <= eps)
        return touch_vertical or touch_horizontal

    def _contour_for_component(self, droplets):
        if len(droplets) == 1:
            d = droplets[0]
            return [
                (d.x - d.size_x / 2, d.y - d.size_y / 2),
                (d.x + d.size_x / 2, d.y - d.size_y / 2),
                (d.x + d.size_x / 2, d.y + d.size_y / 2),
                (d.x - d.size_x / 2, d.y + d.size_y / 2),
            ]

        # Clockwise boundary traversal through cell-edge counting.
        edges = defaultdict(int)
        for d in droplets:
            l = d.x - d.size_x / 2
            r = d.x + d.size_x / 2
            t = d.y - d.size_y / 2
            b = d.y + d.size_y / 2
            rect_edges = [((l, t), (r, t)), ((r, t), (r, b)), ((r, b), (l, b)), ((l, b), (l, t))]
            for p1, p2 in rect_edges:
                k = tuple(sorted((p1, p2)))
                edges[k] += 1

        boundary = [k for k, count in edges.items() if count == 1]
        if not boundary:
            return []

        adjacency = defaultdict(list)
        for p1, p2 in boundary:
            adjacency[p1].append(p2)
            adjacency[p2].append(p1)

        start = min(adjacency.keys(), key=lambda p: (p[1], p[0]))
        contour = [start]
        prev = None
        current = start
        guard = 0
        while guard < 5000:
            guard += 1
            neighbors = adjacency[current]
            if prev is None:
                nxt = neighbors[0]
            else:
                nxt = neighbors[0] if neighbors[1] == prev else neighbors[1]
            if nxt == start:
                break
            contour.append(nxt)
            prev, current = current, nxt

        return contour

    def _average_color(self, droplets):
        rgb = [hex_to_rgb(d.color) for d in droplets]
        if not rgb:
            return (255, 255, 255)
        return (
            sum(c[0] for c in rgb) // len(rgb),
            sum(c[1] for c in rgb) // len(rgb),
            sum(c[2] for c in rgb) // len(rgb),
        )

    def snapshot(self):
        return {
            "time": self.container.current_time,
            "droplets": [
                {
                    "id": d.id,
                    "group_id": d.group_id,
                    "x": d.x,
                    "y": d.y,
                    "size_x": d.size_x,
                    "size_y": d.size_y,
                    "temperature": d.temperature,
                    "volume": d.volume,
                    "color": d.color,
                    "electrode_id": d.electrode_id,
                    "is_soil_sample": d.is_soil_sample,
                    "nitrogen": d.nitrogen,
                    "phosphorus": d.phosphorus,
                    "potassium": d.potassium,
                    "reagent_type": getattr(d, "reagent_type", "none"),
                    "reaction_result": getattr(d, "reaction_result", ""),
                }
                for d in self.container.droplets
            ],
            "bubbles": [
                {
                    "id": b.id,
                    "x": b.x,
                    "y": b.y,
                    "size_x": b.size_x,
                    "size_y": b.size_y,
                    "age": b.age,
                }
                for b in self.container.bubbles
            ],
            "actuators": [
                {
                    "id": getattr(a, "id", -1),
                    "actuator_id": getattr(a, "actuator_id", -1),
                    "name": getattr(a, "name", ""),
                    "type": getattr(a, "type", ""),
                    "actual_temp": getattr(a, "actual_temp", None),
                    "desired_temp": getattr(a, "desired_temp", None),
                    "vibration_frequency": getattr(a, "vibration_frequency", None),
                    "desired_frequency": getattr(a, "desired_frequency", None),
                    "power_status": getattr(a, "power_status", None),
                    "subscriptions": list(getattr(a, "subscriptions", [])),
                }
                for a in self.container.actuators
            ],
            "sensors": [
                {
                    "id": getattr(s, "id", -1),
                    "sensor_id": getattr(s, "sensor_id", -1),
                    "type": getattr(s, "type", ""),
                    "temperature": getattr(s, "temperature", None),
                    "rgb": [getattr(s, "value_r", None), getattr(s, "value_g", None), getattr(s, "value_b", None)],
                }
                for s in self.container.sensors
            ],
        }

    def store_download_data(self):
        self.data_for_download.append(self.snapshot())

    def clear_download_data(self):
        self.data_for_download = []


class SimulationGUI:
    def __init__(self, container: Container, simplevm=None):
        pygame.init()
        self.container = container
        self.simplevm = simplevm
        self.broker = GUIBroker(container)

        self.board_w_px = container.board_width * SCALE
        self.board_h_px = container.board_height * SCALE
        self.side_w = 420
        self.screen = pygame.display.set_mode((self.board_w_px + self.side_w, max(self.board_h_px + SKETCH_HEADER_H, 720)))
        pygame.display.set_caption(f"DMFb Simulator - {container.platform_name}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("monospace", 12)
        self.big_font = pygame.font.SysFont("monospace", 14, bold=True)

        self.running = False
        self.speed = 1
        self.selected = None
        self.selected_type = None

        self.selection_rects = {}
        self.control_buttons = {}
        self.info_edit_rects = {}
        self.info_edit_fields = {}
        self.show_npk_overlay = False

        self.multi_select_menu = None
        self.edit_mode = False
        self.edit_target_key = None
        self.edit_buffer = ""

        self.download_modal_open = False
        self.download_dt = "0.5"
        self.download_end_time = "20.0"
        self.download_active_field = None
        self.download_feedback = ""

        self.group_animation_t = 1.0
        self.group_animation_pairs = {}

        self.electrode_surface = None
        self._build_electrode_layer()
        self._build_control_layout()
        self._refresh_group_animation_targets()

    def _build_electrode_layer(self):
        surf = pygame.Surface((self.board_w_px, self.board_h_px))
        surf.fill(BG_COLOR)
        for e in self.broker.board["electrodes"]:
            rect = (e.x * SCALE, e.y * SCALE, e.size_x * SCALE, e.size_y * SCALE)
            pygame.draw.rect(surf, ELEC_OFF, rect)
            pygame.draw.rect(surf, ELEC_BORDER, rect, 1)
        self.electrode_surface = surf

    def _build_control_layout(self):
        panel_x = self.board_w_px + 10
        self.control_buttons = {
            "step": pygame.Rect(panel_x, 220, 88, 26),
            "play": pygame.Rect(panel_x + 96, 220, 88, 26),
            "slow": pygame.Rect(panel_x, 252, 88, 26),
            "fast": pygame.Rect(panel_x + 96, 252, 88, 26),
            "save": pygame.Rect(panel_x, 284, 184, 26),
            "download": pygame.Rect(panel_x, 316, 184, 26),
            "edit": pygame.Rect(panel_x, 348, 184, 26),
        }

    def run(self):
        while True:
            if not self.handle_events():
                break
            if self.running and not self.download_modal_open:
                for _ in range(self.speed):
                    self._execute_frame_step()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()

    def _execute_frame_step(self):
        if self.simplevm and self.simplevm.has_actions():
            self.simplevm.execute_next()
        step(self.container)
        self.broker.sync_from_container()
        self._refresh_group_animation_targets()

    def _refresh_group_animation_targets(self):
        self.group_animation_t = 0.0
        self.group_animation_pairs = {}

        prev = self.broker.prev_droplet_groups
        cur = self.broker.droplet_groups

        for key, cur_group in cur.items():
            src_group = prev.get(key)
            if src_group is None:
                # Split-case correlation: choose previous group with max droplet-id overlap.
                best = None
                best_overlap = 0
                for prev_group in prev.values():
                    overlap = len(prev_group["droplet_ids"].intersection(cur_group["droplet_ids"]))
                    if overlap > best_overlap:
                        best = prev_group
                        best_overlap = overlap
                src_group = best

            from_contour = src_group["contour"] if src_group else cur_group["contour"]
            to_contour = cur_group["contour"]
            pairs = self._build_lerp_pairs(from_contour, to_contour)
            self.group_animation_pairs[key] = pairs

    def _build_lerp_pairs(self, from_points, to_points):
        if not from_points or not to_points:
            return []
        count = max(len(from_points), len(to_points))
        a = self._resample_points(from_points, count)
        b = self._resample_points(to_points, count)
        pairs = []
        for i, ap in enumerate(a):
            bp = min(b, key=lambda p: (p[0] - ap[0]) ** 2 + (p[1] - ap[1]) ** 2)
            pairs.append((ap, bp))
            # Prevent repeatedly matching to one point by rotating candidate list.
            b = b[1:] + b[:1]
            _ = i
        return pairs

    def _resample_points(self, points, target_count):
        if not points:
            return []
        if len(points) == target_count:
            return list(points)
        sampled = []
        for i in range(target_count):
            idx = int(i * len(points) / target_count) % len(points)
            sampled.append(points[idx])
        return sampled

    def lerp_group_vertices(self, group_key, amount):
        pairs = self.group_animation_pairs.get(group_key, [])
        if not pairs:
            group = self.broker.droplet_groups.get(group_key)
            return group["contour"] if group else []
        interpolated = []
        for p_from, p_to in pairs:
            x = p_from[0] + (p_to[0] - p_from[0]) * amount
            y = p_from[1] + (p_to[1] - p_from[1]) * amount
            interpolated.append((x, y))
        return interpolated

    def draw(self):
        self.screen.fill(BG_COLOR)
        self._draw_sketch_header()
        if self.electrode_surface:
            self.screen.blit(self.electrode_surface, (0, SKETCH_HEADER_H))

        self._draw_sketch_panel()
        self._draw_info_panel()
        self._draw_control_panel()
        self._draw_selection_panel()

        if self.multi_select_menu:
            self._draw_multi_select_menu()
        if self.download_modal_open:
            self._draw_download_modal()

        pygame.display.flip()
        self.group_animation_t = clamp(self.group_animation_t + 0.08, 0.0, 1.0)

    def _draw_sketch_header(self):
        header_rect = pygame.Rect(0, 0, self.board_w_px, SKETCH_HEADER_H)
        pygame.draw.rect(self.screen, SKETCH_HEADER_BG, header_rect)
        pygame.draw.rect(self.screen, ELEC_BORDER, header_rect, 1)

        board_label = self.big_font.render(self.container.platform_name, True, SKETCH_HEADER_TEXT)
        time_label = self.font.render(f"Simulation Time: {self.container.current_time:.2f}s", True, SKETCH_HEADER_TEXT)
        self.screen.blit(board_label, (8, 9))
        self.screen.blit(time_label, (self.board_w_px - time_label.get_width() - 8, 12))

    def _draw_sketch_panel(self):
        if self.broker.is_enabled("active_electrodes"):
            for e in self.broker.board["electrodes"]:
                if e.status == 1:
                    rect = (e.x * SCALE, SKETCH_HEADER_H + e.y * SCALE, e.size_x * SCALE, e.size_y * SCALE)
                    pygame.draw.rect(self.screen, ELEC_ON, rect)
                    pygame.draw.rect(self.screen, ELEC_BORDER, rect, 1)

        if self.broker.is_enabled("actuators"):
            for a in self.broker.board["actuators"]:
                sx = getattr(a, "size_x", 0) * SCALE
                sy = getattr(a, "size_y", 0) * SCALE
                overlay = pygame.Surface((sx, sy), pygame.SRCALPHA)
                if getattr(a, "type", "") in ("micro_shaker", "microShaker"):
                    overlay.fill((80, 190, 230, 90))
                else:
                    overlay.fill((220, 70, 70, 85))
                self.screen.blit(overlay, (getattr(a, "x", 0) * SCALE, SKETCH_HEADER_H + getattr(a, "y", 0) * SCALE))
                border_color = (80, 190, 230) if getattr(a, "type", "") in ("micro_shaker", "microShaker") else (220, 70, 70)
                rect = (getattr(a, "x", 0) * SCALE, SKETCH_HEADER_H + getattr(a, "y", 0) * SCALE, sx, sy)
                pygame.draw.rect(self.screen, border_color, rect, 2)

                if getattr(a, "type", "") in ("micro_shaker", "microShaker"):
                    self._draw_shaker_waves(a)

        if self.broker.is_enabled("sensors"):
            for s in self.broker.board["sensors"]:
                sx = getattr(s, "size_x", 0) * SCALE
                sy = getattr(s, "size_y", 0) * SCALE
                overlay = pygame.Surface((sx, sy), pygame.SRCALPHA)
                overlay.fill((80, 120, 220, 85))
                self.screen.blit(overlay, (getattr(s, "x", 0) * SCALE, SKETCH_HEADER_H + getattr(s, "y", 0) * SCALE))
                pygame.draw.rect(
                    self.screen,
                    (80, 120, 220),
                    (getattr(s, "x", 0) * SCALE, SKETCH_HEADER_H + getattr(s, "y", 0) * SCALE, sx, sy),
                    2,
                )

        if self.broker.is_enabled("droplet_groups"):
            for key, group in self.broker.droplet_groups.items():
                if len(group.get("droplets", [])) == 1:
                    self._draw_single_droplet(group["droplets"][0])
                    continue

                contour = self.lerp_group_vertices(key, self.group_animation_t)
                if len(contour) < 3:
                    self._draw_group_droplet_fallback(group)
                    continue
                rounded = self._round_contour(contour, radius=2.8)
                pts = [(int(x * SCALE), int(SKETCH_HEADER_H + y * SCALE)) for x, y in rounded]
                if len(pts) >= 3 and self._group_contour_is_valid(pts, group.get("droplets", [])):
                    pygame.draw.polygon(self.screen, group["color"], pts)
                    pygame.draw.polygon(self.screen, (0, 0, 0), pts, 2)
                else:
                    self._draw_group_droplet_fallback(group)
        else:
            for d in self.broker.board["droplets"]:
                self._draw_single_droplet(d)

        if self.broker.is_enabled("bubbles"):
            for b in self.broker.board["bubbles"]:
                cx = int(b.x * SCALE)
                cy = int(SKETCH_HEADER_H + b.y * SCALE)
                radius = max(2, int(min(b.size_x, b.size_y) * SCALE / 2))
                pygame.draw.circle(self.screen, BUBBLE_COLOR, (cx, cy), radius, 1)

        if self.show_npk_overlay:
            self._draw_npk_overlay()

    def _draw_info_panel(self):
        panel_x = self.board_w_px + 220
        panel_rect = pygame.Rect(panel_x, 10, 190, 680)
        pygame.draw.rect(self.screen, PANEL_BG, panel_rect)
        pygame.draw.rect(self.screen, PANEL_BORDER, panel_rect, 1)

        header = self.big_font.render("Information", True, TEXT_COLOR)
        self.screen.blit(header, (panel_x + 8, 12))

        lines = [
            f"Time: {self.container.current_time:.2f}s",
            f"Droplets: {len(self.broker.board['droplets'])}",
            f"Bubbles: {len(self.broker.board['bubbles'])}",
            f"Speed: {self.speed}x",
            f"Running: {'YES' if self.running else 'NO'}",
            f"Edit mode: {'ON' if self.edit_mode else 'OFF'}",
        ]
        y = 36
        for line in lines:
            self.screen.blit(self.font.render(line, True, TEXT_COLOR), (panel_x + 8, y))
            y += 18

        self.info_edit_rects = {}
        self.info_edit_fields = {}
        if self.selected is None:
            self.screen.blit(self.font.render("No selection", True, MUTED_TEXT), (panel_x + 8, y + 8))
            return

        details = self.information_filter(self.selected_type, self.selected)
        y += 10
        self.screen.blit(self.font.render("Selection", True, TEXT_COLOR), (panel_x + 8, y))
        y += 18

        for key, value, editable in details:
            label = f"{key}:"
            self.screen.blit(self.font.render(label, True, TEXT_COLOR), (panel_x + 8, y))

            if editable and self.edit_mode:
                value_rect = pygame.Rect(panel_x + 74, y - 2, 104, 16)
                pygame.draw.rect(self.screen, (58, 58, 58), value_rect)
                pygame.draw.rect(self.screen, PANEL_BORDER, value_rect, 1)
                shown = str(value)
                if self.edit_target_key == key:
                    shown = self.edit_buffer + "|"
                self.screen.blit(self.font.render(shown, True, TEXT_COLOR), (value_rect.x + 3, value_rect.y + 1))
                self.info_edit_rects[key] = value_rect
                self.info_edit_fields[key] = value
            else:
                self.screen.blit(
                    self.font.render(str(value), True, TEXT_COLOR if editable else MUTED_TEXT),
                    (panel_x + 74, y),
                )
            y += 18

    def information_filter(self, kind, obj):
        if kind == "electrode":
            editable = {"status"}
            pairs = [
                ("id", obj.id),
                ("electrode_id", obj.electrode_id),
                ("driver_id", obj.driver_id),
                ("status", obj.status),
                ("position", f"({obj.x}, {obj.y})"),
                ("size", f"({obj.size_x}, {obj.size_y})"),
                ("subscriptions", len(obj.subscriptions)),
            ]
            return [(k, v, k in editable) for k, v in pairs]

        if kind == "droplet":
            editable = {"temperature", "volume", "color"}
            pairs = [
                ("id", obj.id),
                ("name", obj.name),
                ("group_id", obj.group_id),
                ("electrode_id", obj.electrode_id),
                ("temperature", round(obj.temperature, 3)),
                ("volume", round(obj.volume, 4)),
                ("position", f"({obj.x:.1f}, {obj.y:.1f})"),
                ("size", f"({obj.size_x:.1f}, {obj.size_y:.1f})"),
                ("color", obj.color),
            ]
            if getattr(obj, "is_soil_sample", False):
                editable.update({"nitrogen", "phosphorus", "potassium"})
                pairs.extend([
                    ("nitrogen", round(getattr(obj, "nitrogen", 0.0), 4)),
                    ("phosphorus", round(getattr(obj, "phosphorus", 0.0), 4)),
                    ("potassium", round(getattr(obj, "potassium", 0.0), 4)),
                ])
            pairs.extend([
                ("reagent_type", getattr(obj, "reagent_type", "none")),
                ("reaction_result", getattr(obj, "reaction_result", "")),
            ])
            return [(k, v, k in editable) for k, v in pairs]

        if kind == "actuator":
            if isinstance(obj, MicroShaker):
                editable = {"desired_frequency", "power_status"}
                pairs = [
                    ("id", getattr(obj, "id", -1)),
                    ("actuator_id", getattr(obj, "actuator_id", -1)),
                    ("type", getattr(obj, "type", "")),
                    ("name", getattr(obj, "name", "")),
                    ("vibration_frequency", round(getattr(obj, "vibration_frequency", 0.0), 3)),
                    ("desired_frequency", round(getattr(obj, "desired_frequency", 0.0), 3)),
                    ("power_status", getattr(obj, "power_status", 0)),
                    ("subscriptions", len(getattr(obj, "subscriptions", []))),
                    ("position", f"({getattr(obj, 'x', 0)}, {getattr(obj, 'y', 0)})"),
                ]
                return [(k, v, k in editable) for k, v in pairs]

            editable = {"desired_temp", "power_status"}
            pairs = [
                ("id", getattr(obj, "id", -1)),
                ("actuator_id", getattr(obj, "actuator_id", -1)),
                ("type", getattr(obj, "type", "")),
                ("actual_temp", round(getattr(obj, "actual_temp", 0.0), 3)),
                ("desired_temp", round(getattr(obj, "desired_temp", 0.0), 3)),
                ("power_status", getattr(obj, "power_status", 0)),
                ("position", f"({getattr(obj, 'x', 0)}, {getattr(obj, 'y', 0)})"),
            ]
            return [(k, v, k in editable) for k, v in pairs]

        if kind == "sensor":
            if isinstance(obj, TemperatureSensor):
                pairs = [
                    ("id", obj.id),
                    ("sensor_id", obj.sensor_id),
                    ("type", obj.type),
                    ("temperature", round(obj.temperature, 3)),
                    ("position", f"({obj.x}, {obj.y})"),
                ]
            elif isinstance(obj, ColorSensor):
                pairs = [
                    ("id", obj.id),
                    ("sensor_id", obj.sensor_id),
                    ("type", obj.type),
                    ("rgb", f"({obj.value_r}, {obj.value_g}, {obj.value_b})"),
                    ("position", f"({obj.x}, {obj.y})"),
                ]
            else:
                pairs = []
            return [(k, v, False) for k, v in pairs]

        if kind == "bubble":
            pairs = [
                ("id", obj.id),
                ("position", f"({obj.x:.1f}, {obj.y:.1f})"),
                ("size", f"({obj.size_x:.1f}, {obj.size_y:.1f})"),
                ("age", round(obj.age, 3)),
            ]
            return [(k, v, False) for k, v in pairs]

        return []

    def _draw_control_panel(self):
        panel_x = self.board_w_px + 10
        panel_rect = pygame.Rect(panel_x, 10, 200, 390)
        pygame.draw.rect(self.screen, PANEL_BG, panel_rect)
        pygame.draw.rect(self.screen, PANEL_BORDER, panel_rect, 1)

        self.screen.blit(self.big_font.render("Control", True, TEXT_COLOR), (panel_x + 8, 12))
        self.screen.blit(self.font.render("SPACE: play/pause", True, MUTED_TEXT), (panel_x + 8, 38))
        self.screen.blit(self.font.render("RIGHT: single step", True, MUTED_TEXT), (panel_x + 8, 54))
        self.screen.blit(self.font.render("UP/DOWN: speed", True, MUTED_TEXT), (panel_x + 8, 70))
        self.screen.blit(self.font.render("E: toggle edit mode", True, MUTED_TEXT), (panel_x + 8, 86))

        labels = {
            "step": "STEP",
            "play": "PAUSE" if self.running else "PLAY",
            "slow": "SLOW",
            "fast": "FAST",
            "save": "SAVE SNAPSHOT",
            "download": "DOWNLOAD JSON",
            "edit": "EDIT MODE ON" if self.edit_mode else "EDIT MODE OFF",
        }

        for key, rect in self.control_buttons.items():
            pygame.draw.rect(self.screen, (58, 58, 58), rect)
            pygame.draw.rect(self.screen, PANEL_BORDER, rect, 1)
            label = self.font.render(labels[key], True, TEXT_COLOR)
            tx = rect.x + (rect.width - label.get_width()) // 2
            ty = rect.y + (rect.height - label.get_height()) // 2
            self.screen.blit(label, (tx, ty))

        if self.download_feedback:
            self.screen.blit(self.font.render(self.download_feedback, True, TEXT_COLOR), (panel_x + 8, 382))

    def _draw_selection_panel(self):
        panel_x = self.board_w_px + 10
        panel_rect = pygame.Rect(panel_x, 410, 200, 280)
        pygame.draw.rect(self.screen, PANEL_BG, panel_rect)
        pygame.draw.rect(self.screen, PANEL_BORDER, panel_rect, 1)
        self.screen.blit(self.big_font.render("Selection", True, TEXT_COLOR), (panel_x + 8, 412))

        self.selection_rects = {}
        y = 436
        for entry in self.broker.selections:
            box = pygame.Rect(panel_x + 8, y, 14, 14)
            pygame.draw.rect(self.screen, (60, 60, 60), box)
            pygame.draw.rect(self.screen, PANEL_BORDER, box, 1)
            if entry["checked"]:
                pygame.draw.line(self.screen, (20, 220, 120), (box.x + 2, box.y + 7), (box.x + 6, box.y + 11), 2)
                pygame.draw.line(self.screen, (20, 220, 120), (box.x + 6, box.y + 11), (box.x + 12, box.y + 2), 2)
            text = self.font.render(entry["text"], True, TEXT_COLOR)
            self.screen.blit(text, (panel_x + 28, y - 1))
            self.selection_rects[entry["id"]] = pygame.Rect(panel_x + 6, y - 2, 186, 18)
            y += 24

        box = pygame.Rect(panel_x + 8, y, 14, 14)
        pygame.draw.rect(self.screen, (60, 60, 60), box)
        pygame.draw.rect(self.screen, PANEL_BORDER, box, 1)
        if self.show_npk_overlay:
            pygame.draw.line(self.screen, (20, 220, 120), (box.x + 2, box.y + 7), (box.x + 6, box.y + 11), 2)
            pygame.draw.line(self.screen, (20, 220, 120), (box.x + 6, box.y + 11), (box.x + 12, box.y + 2), 2)
        text = self.font.render("Show NPK labels", True, TEXT_COLOR)
        self.screen.blit(text, (panel_x + 28, y - 1))
        self.selection_rects["npk_overlay"] = pygame.Rect(panel_x + 6, y - 2, 186, 18)

    def _draw_multi_select_menu(self):
        menu = self.multi_select_menu
        if menu is None:
            return
        x, y = menu["x"], menu["y"]
        options = menu["options"]
        width = 210
        height = 22 + len(options) * 18
        rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(self.screen, (45, 45, 45), rect)
        pygame.draw.rect(self.screen, PANEL_BORDER, rect, 1)
        self.screen.blit(self.font.render("Multiple selections", True, TEXT_COLOR), (x + 6, y + 4))

        row_rects = []
        cy = y + 22
        for idx, option in enumerate(options):
            row = pygame.Rect(x + 4, cy, width - 8, 16)
            pygame.draw.rect(self.screen, (64, 64, 64), row)
            pygame.draw.rect(self.screen, PANEL_BORDER, row, 1)
            label = f"{idx + 1}. {option['type']}#{getattr(option['obj'], 'id', '?')}"
            self.screen.blit(self.font.render(label, True, TEXT_COLOR), (row.x + 4, row.y + 1))
            row_rects.append((row, option))
            cy += 18
        menu["row_rects"] = row_rects

    def _draw_download_modal(self):
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        self.screen.blit(overlay, (0, 0))

        w, h = 360, 200
        x = (self.screen.get_width() - w) // 2
        y = (self.screen.get_height() - h) // 2
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.screen, PANEL_BG, rect)
        pygame.draw.rect(self.screen, PANEL_BORDER, rect, 1)

        self.screen.blit(self.big_font.render("Download Simulation Data", True, TEXT_COLOR), (x + 10, y + 10))
        self.screen.blit(self.font.render("Capture every dt seconds until end time.", True, MUTED_TEXT), (x + 10, y + 34))

        dt_rect = pygame.Rect(x + 160, y + 70, 130, 20)
        end_rect = pygame.Rect(x + 160, y + 102, 130, 20)

        self.screen.blit(self.font.render("dt:", True, TEXT_COLOR), (x + 20, y + 72))
        self.screen.blit(self.font.render("end_time:", True, TEXT_COLOR), (x + 20, y + 104))

        for key, box, value in [
            ("dt", dt_rect, self.download_dt),
            ("end", end_rect, self.download_end_time),
        ]:
            pygame.draw.rect(self.screen, (58, 58, 58), box)
            pygame.draw.rect(self.screen, PANEL_BORDER, box, 1)
            shown = value + ("|" if self.download_active_field == key else "")
            self.screen.blit(self.font.render(shown, True, TEXT_COLOR), (box.x + 4, box.y + 2))

        start_rect = pygame.Rect(x + 40, y + 146, 120, 26)
        cancel_rect = pygame.Rect(x + 200, y + 146, 120, 26)
        pygame.draw.rect(self.screen, (58, 58, 58), start_rect)
        pygame.draw.rect(self.screen, PANEL_BORDER, start_rect, 1)
        pygame.draw.rect(self.screen, (58, 58, 58), cancel_rect)
        pygame.draw.rect(self.screen, PANEL_BORDER, cancel_rect, 1)
        self.screen.blit(self.font.render("START", True, TEXT_COLOR), (start_rect.x + 36, start_rect.y + 6))
        self.screen.blit(self.font.render("CANCEL", True, TEXT_COLOR), (cancel_rect.x + 32, cancel_rect.y + 6))

        self.multi_select_menu = None
        self.download_modal_geometry = {
            "dt": dt_rect,
            "end": end_rect,
            "start": start_rect,
            "cancel": cancel_rect,
        }

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            if event.type == pygame.KEYDOWN:
                if self.download_modal_open:
                    self._handle_download_key(event)
                    continue

                if self.edit_target_key is not None:
                    self._handle_info_edit_key(event)
                    continue

                if event.key == pygame.K_SPACE:
                    self.running = not self.running
                elif event.key == pygame.K_RIGHT:
                    self._execute_frame_step()
                elif event.key == pygame.K_UP:
                    self.speed = min(12, self.speed + 1)
                elif event.key == pygame.K_DOWN:
                    self.speed = max(1, self.speed - 1)
                elif event.key == pygame.K_e:
                    self.edit_mode = not self.edit_mode
                    self.edit_target_key = None

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

        return True

    def _handle_click(self, pos):
        x, y = pos

        if self.download_modal_open:
            self._handle_download_click(pos)
            return

        if self.multi_select_menu:
            for row, option in self.multi_select_menu.get("row_rects", []):
                if row.collidepoint(pos):
                    self.selected_type = option["type"]
                    self.selected = option["obj"]
                    self.multi_select_menu = None
                    return
            self.multi_select_menu = None

        for key, rect in self.control_buttons.items():
            if rect.collidepoint(pos):
                self._handle_control_click(key)
                return

        for selection_id, rect in self.selection_rects.items():
            if rect.collidepoint(pos):
                if selection_id == "npk_overlay":
                    self.show_npk_overlay = not self.show_npk_overlay
                else:
                    self.broker.toggle(selection_id)
                return

        if self.edit_mode:
            for field_key, rect in self.info_edit_rects.items():
                if rect.collidepoint(pos):
                    self.edit_target_key = field_key
                    self.edit_buffer = str(self.info_edit_fields.get(field_key, ""))
                    return

        if x <= self.board_w_px and y <= SKETCH_HEADER_H + self.board_h_px:
            if y < SKETCH_HEADER_H:
                self.selected = None
                self.selected_type = None
                return
            candidates = self._hit_candidates(x / SCALE, (y - SKETCH_HEADER_H) / SCALE)
            if len(candidates) == 1:
                self.selected_type = candidates[0]["type"]
                self.selected = candidates[0]["obj"]
            elif len(candidates) > 1:
                self.multi_select_menu = {
                    "x": min(x + 6, self.screen.get_width() - 220),
                    "y": min(y + 6, self.screen.get_height() - 200),
                    "options": candidates,
                    "row_rects": [],
                }
            else:
                self.selected = None
                self.selected_type = None
            return

        self.selected = None
        self.selected_type = None

    def _handle_control_click(self, key):
        if key == "step":
            self._execute_frame_step()
        elif key == "play":
            self.running = not self.running
        elif key == "slow":
            self.speed = max(1, self.speed - 1)
        elif key == "fast":
            self.speed = min(12, self.speed + 1)
        elif key == "save":
            self._save_snapshot("data/gui_snapshot.json")
            self.download_feedback = "Snapshot saved"
        elif key == "download":
            self.download_modal_open = True
            self.download_active_field = None
            self.download_feedback = ""
        elif key == "edit":
            self.edit_mode = not self.edit_mode
            if not self.edit_mode:
                self.edit_target_key = None

    def _hit_candidates(self, x, y):
        candidates = []

        for droplet in reversed(self.broker.board["droplets"]):
            rx = max(1e-9, droplet.size_x / 2)
            ry = max(1e-9, droplet.size_y / 2)
            nx = (x - droplet.x) / rx
            ny = (y - droplet.y) / ry
            if nx * nx + ny * ny <= 1.0:
                candidates.append({"type": "droplet", "obj": droplet})

        for electrode in self.broker.board["electrodes"]:
            if point_in_rect(x, y, electrode.x, electrode.y, electrode.size_x, electrode.size_y):
                candidates.append({"type": "electrode", "obj": electrode})

        for actuator in self.broker.board["actuators"]:
            if point_in_rect(x, y, getattr(actuator, "x", 0), getattr(actuator, "y", 0), getattr(actuator, "size_x", 0), getattr(actuator, "size_y", 0)):
                candidates.append({"type": "actuator", "obj": actuator})

        for sensor in self.broker.board["sensors"]:
            if point_in_rect(x, y, getattr(sensor, "x", 0), getattr(sensor, "y", 0), getattr(sensor, "size_x", 0), getattr(sensor, "size_y", 0)):
                candidates.append({"type": "sensor", "obj": sensor})

        for bubble in self.broker.board["bubbles"]:
            r = max(1e-9, min(bubble.size_x, bubble.size_y) / 2)
            if math.hypot(x - bubble.x, y - bubble.y) <= r:
                candidates.append({"type": "bubble", "obj": bubble})

        return candidates

    def _handle_info_edit_key(self, event):
        if self.edit_target_key is None:
            return

        if event.key == pygame.K_RETURN:
            self._commit_edit()
            return
        if event.key == pygame.K_ESCAPE:
            self.edit_target_key = None
            self.edit_buffer = ""
            return
        if event.key == pygame.K_BACKSPACE:
            self.edit_buffer = self.edit_buffer[:-1]
            return

        if event.unicode:
            self.edit_buffer += event.unicode

    def _commit_edit(self):
        if self.selected is None or self.edit_target_key is None:
            return

        raw = self.edit_buffer.strip()
        key = self.edit_target_key
        target = self.selected

        try:
            if key == "status":
                target.status = int(raw)
            elif key == "temperature":
                target.temperature = float(raw)
            elif key == "volume":
                target.volume = max(0.0, float(raw))
            elif key == "color":
                if raw.startswith("#") and len(raw) == 7:
                    target.color = raw
            elif key == "nitrogen":
                target.nitrogen = max(0.0, float(raw))
            elif key == "phosphorus":
                target.phosphorus = max(0.0, float(raw))
            elif key == "potassium":
                target.potassium = max(0.0, float(raw))
            elif key == "desired_temp":
                target.desired_temp = float(raw)
                target.has_target_setpoint = True
            elif key == "power_status":
                target.power_status = int(raw)
            elif key == "desired_frequency":
                target.desired_frequency = max(0.0, float(raw))

            # Keep visual assay state consistent after manual NPK edits.
            if getattr(target, "is_soil_sample", False):
                if is_reagent_type(getattr(target, "reagent_type", "none")):
                    reaction_text, reaction_color = soil_reagent_reaction(
                        target.reagent_type,
                        target.nitrogen,
                        target.phosphorus,
                        target.potassium,
                    )
                    target.reaction_result = reaction_text
                    target.color = reaction_color if reaction_color is not None else soil_color_from_npk(
                        target.nitrogen,
                        target.phosphorus,
                        target.potassium,
                    )
                else:
                    target.reaction_result = ""
                    target.color = soil_color_from_npk(target.nitrogen, target.phosphorus, target.potassium)
        except ValueError:
            self.download_feedback = "Invalid edit value"

        self.edit_target_key = None
        self.edit_buffer = ""
        self.broker.sync_from_container()

    def _handle_download_click(self, pos):
        g = getattr(self, "download_modal_geometry", None)
        if g is None:
            return
        if g["dt"].collidepoint(pos):
            self.download_active_field = "dt"
            return
        if g["end"].collidepoint(pos):
            self.download_active_field = "end"
            return
        if g["cancel"].collidepoint(pos):
            self.download_modal_open = False
            self.download_active_field = None
            return
        if g["start"].collidepoint(pos):
            self._run_download_capture()
            self.download_modal_open = False
            self.download_active_field = None
            return

    def _handle_download_key(self, event):
        if event.key == pygame.K_ESCAPE:
            self.download_modal_open = False
            self.download_active_field = None
            return
        if self.download_active_field is None:
            return
        if event.key == pygame.K_BACKSPACE:
            if self.download_active_field == "dt":
                self.download_dt = self.download_dt[:-1]
            else:
                self.download_end_time = self.download_end_time[:-1]
            return
        if event.key == pygame.K_RETURN:
            return

        if event.unicode and event.unicode in "0123456789.-":
            if self.download_active_field == "dt":
                self.download_dt += event.unicode
            else:
                self.download_end_time += event.unicode

    def _run_download_capture(self):
        try:
            dt = max(0.01, float(self.download_dt))
            end_time = float(self.download_end_time)
        except ValueError:
            self.download_feedback = "Download input invalid"
            return

        if end_time <= self.container.current_time:
            self.download_feedback = "end_time must be in future"
            return

        self.broker.clear_download_data()
        last_capture = self.container.current_time
        self.broker.store_download_data()

        max_steps = 200000
        steps = 0
        while self.container.current_time < end_time and steps < max_steps:
            steps += 1
            if self.simplevm and self.simplevm.has_actions():
                self.simplevm.execute_next()
            step(self.container)
            self.broker.sync_from_container()
            if self.container.current_time - last_capture >= dt or self.container.current_time >= end_time:
                self.broker.store_download_data()
                last_capture = self.container.current_time

        output_path = "data/data.json"
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(self.broker.data_for_download, handle, indent=2)

        self.download_feedback = f"Downloaded to {output_path}"
        self._refresh_group_animation_targets()

    def _save_snapshot(self, filepath):
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(self.broker.snapshot(), handle, indent=2)

    def _draw_single_droplet(self, droplet: Droplet):
        cx = int(droplet.x * SCALE)
        cy = int(SKETCH_HEADER_H + droplet.y * SCALE)
        rx = max(1, int(droplet.size_x * SCALE / 2))
        ry = max(1, int(droplet.size_y * SCALE / 2))
        rect = pygame.Rect(cx - rx, cy - ry, 2 * rx, 2 * ry)
        pygame.draw.ellipse(self.screen, hex_to_rgb(droplet.color), rect)
        pygame.draw.ellipse(self.screen, (0, 0, 0), rect, 2)

    def _draw_npk_overlay(self):
        for droplet in self.broker.board["droplets"]:
            if getattr(droplet, "is_soil_sample", False):
                label = (
                    f"N:{getattr(droplet, 'nitrogen', 0.0):.2f} "
                    f"P:{getattr(droplet, 'phosphorus', 0.0):.2f} "
                    f"K:{getattr(droplet, 'potassium', 0.0):.1f}"
                )
                reaction = getattr(droplet, "reaction_result", "")
                if reaction:
                    label = f"{label} | {reaction}"
            else:
                reagent_type = str(getattr(droplet, "reagent_type", "none") or "none").strip().lower()
                if reagent_type in ("", "none"):
                    continue
                label = f"Reagent: {reagent_type}"

            text = self.font.render(label, True, (235, 235, 235))
            tx = int(droplet.x * SCALE - text.get_width() / 2)
            ty = int(SKETCH_HEADER_H + droplet.y * SCALE + droplet.size_y * SCALE / 2 + 4)
            bg = pygame.Rect(tx - 2, ty - 1, text.get_width() + 4, text.get_height() + 2)
            pygame.draw.rect(self.screen, (20, 20, 20), bg)
            pygame.draw.rect(self.screen, (70, 70, 70), bg, 1)
            self.screen.blit(text, (tx, ty))

    def _draw_group_droplet_fallback(self, group):
        fill = group.get("color", (255, 255, 255))
        droplets = group.get("droplets", [])
        if not droplets:
            return

        # Build a local alpha mask so touching droplets render as one merged silhouette.
        margin = 4
        rects = []
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")

        for droplet in droplets:
            cx = int(droplet.x * SCALE)
            cy = int(SKETCH_HEADER_H + droplet.y * SCALE)
            rx = max(1, int(droplet.size_x * SCALE / 2))
            ry = max(1, int(droplet.size_y * SCALE / 2))
            rect = pygame.Rect(cx - rx, cy - ry, 2 * rx, 2 * ry)
            rects.append(rect)
            min_x = min(min_x, rect.left)
            min_y = min(min_y, rect.top)
            max_x = max(max_x, rect.right)
            max_y = max(max_y, rect.bottom)

        local_w = max(1, int(max_x - min_x + 2 * margin))
        local_h = max(1, int(max_y - min_y + 2 * margin))
        local = pygame.Surface((local_w, local_h), pygame.SRCALPHA)

        for rect in rects:
            shifted = pygame.Rect(rect.x - int(min_x) + margin, rect.y - int(min_y) + margin, rect.width, rect.height)
            pygame.draw.ellipse(local, (*fill, 255), shifted)

        self.screen.blit(local, (int(min_x) - margin, int(min_y) - margin))

        mask = pygame.mask.from_surface(local)
        outline = mask.outline()
        if len(outline) >= 3:
            points = [(x + int(min_x) - margin, y + int(min_y) - margin) for x, y in outline]
            pygame.draw.polygon(self.screen, (0, 0, 0), points, 2)
            return

        for rect in rects:
            pygame.draw.ellipse(self.screen, (0, 0, 0), rect, 2)

    def _group_contour_is_valid(self, pts, droplets):
        if len(pts) < 3:
            return False

        if abs(self._polygon_area_pixels(pts)) < 2.0:
            return False

        return all(self._point_in_polygon(int(d.x * SCALE), int(SKETCH_HEADER_H + d.y * SCALE), pts) for d in droplets)

    def _polygon_area_pixels(self, points):
        area = 0.0
        for i in range(len(points)):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % len(points)]
            area += x1 * y2 - x2 * y1
        return area / 2.0

    def _point_in_polygon(self, px, py, polygon):
        inside = False
        n = len(polygon)
        for i in range(n):
            x1, y1 = polygon[i]
            x2, y2 = polygon[(i + 1) % n]
            if (y1 > py) != (y2 > py):
                denom = (y2 - y1) if (y2 - y1) != 0 else 1e-9
                x_at_y = x1 + (py - y1) * (x2 - x1) / denom
                if x_at_y >= px:
                    inside = not inside
        return inside

    def _draw_shaker_waves(self, shaker):
        if getattr(shaker, "power_status", 0) != 1:
            return
        cx = int((getattr(shaker, "x", 0) + getattr(shaker, "size_x", 0) / 2) * SCALE)
        cy = int(SKETCH_HEADER_H + (getattr(shaker, "y", 0) + getattr(shaker, "size_y", 0) / 2) * SCALE)
        amp = int(min(14, 2 + getattr(shaker, "vibration_frequency", 0.0) / 12.0))
        for ring in range(1, 4):
            pygame.draw.circle(self.screen, (80, 190, 230), (cx, cy), amp * ring, 1)

    def _round_contour(self, points, radius=3.5, segments=5):
        if len(points) < 3:
            return points

        clockwise = self._polygon_area(points) < 0
        rounded = []
        n = len(points)
        for i in range(n):
            prev_pt = points[(i - 1) % n]
            curr_pt = points[i]
            next_pt = points[(i + 1) % n]

            v1 = (prev_pt[0] - curr_pt[0], prev_pt[1] - curr_pt[1])
            v2 = (next_pt[0] - curr_pt[0], next_pt[1] - curr_pt[1])
            len1 = math.hypot(v1[0], v1[1])
            len2 = math.hypot(v2[0], v2[1])
            if len1 == 0 or len2 == 0:
                continue

            r = min(radius, len1 / 2.0, len2 / 2.0)
            u1 = (v1[0] / len1, v1[1] / len1)
            u2 = (v2[0] / len2, v2[1] / len2)
            p1 = (curr_pt[0] + u1[0] * r, curr_pt[1] + u1[1] * r)
            p2 = (curr_pt[0] + u2[0] * r, curr_pt[1] + u2[1] * r)

            cross = v1[0] * v2[1] - v1[1] * v2[0]
            is_convex = (cross > 0) if clockwise else (cross < 0)
            if not is_convex:
                rounded.append(curr_pt)
                continue

            a1 = math.atan2(p1[1] - curr_pt[1], p1[0] - curr_pt[0])
            a2 = math.atan2(p2[1] - curr_pt[1], p2[0] - curr_pt[0])
            arc = self._arc_points(curr_pt, r, a1, a2, clockwise, segments)
            if not rounded:
                rounded.extend(arc)
            else:
                rounded.extend(arc[1:])
        return rounded

    def _arc_points(self, center, radius, angle_start, angle_end, clockwise, segments):
        delta = angle_end - angle_start

        # Always sweep the shorter arc. The previous wrap logic could pick the
        # long path around the circle, producing visible spikes/artifacts.
        if delta > math.pi:
            delta -= 2 * math.pi
        elif delta < -math.pi:
            delta += 2 * math.pi

        # Keep winding stable with contour orientation while still avoiding
        # full-circle turns.
        if clockwise and delta > 0:
            delta -= 2 * math.pi
        elif not clockwise and delta < 0:
            delta += 2 * math.pi

        if delta > math.pi:
            delta -= 2 * math.pi
        elif delta < -math.pi:
            delta += 2 * math.pi

        points = []
        for i in range(segments + 1):
            t = i / segments
            angle = angle_start + delta * t
            points.append((center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius))
        return points

    def _polygon_area(self, points):
        area = 0.0
        for i in range(len(points)):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % len(points)]
            area += x1 * y2 - x2 * y1
        return area / 2.0
