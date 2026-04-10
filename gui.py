import pygame
from datatypes import Container, Droplet, Electrode
from engine import step

SCALE = 2          # Pixels per simulation unit
FPS = 30
BG_COLOR    = (30, 30, 30)
ELEC_OFF    = (200, 200, 200)
ELEC_ON     = (220, 60,  60)
ELEC_BORDER = (80, 80, 80)
ACTUATOR_COLOR = (220, 80, 80, 80)
SENSOR_COLOR   = (80, 120, 220, 80)

def hex_to_rgb(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

class SimulationGUI:
    def __init__(self, container: Container, simplevm=None):
        pygame.init()
        self.container = container
        self.simplevm = simplevm
        w = container.board_width * SCALE + 300  # extra for info panel
        h = container.board_height * SCALE + 80
        self.screen = pygame.display.set_mode((w, h))
        pygame.display.set_caption(f"DMFb Simulator — {container.platform_name}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("monospace", 11)
        self.big_font = pygame.font.SysFont("monospace", 14, bold=True)
        self.running = False
        self.speed = 1       # steps per frame
        self.selected = None
        self.electrode_surface = None  # cached static layer
        self._build_electrode_layer()

    def _build_electrode_layer(self):
        """Pre-render static electrode shapes once."""
        surf = pygame.Surface((
            self.container.board_width * SCALE,
            self.container.board_height * SCALE
        ))
        surf.fill(BG_COLOR)
        for e in self.container.electrodes:
            rect = (e.x*SCALE, e.y*SCALE, e.size_x*SCALE, e.size_y*SCALE)
            pygame.draw.rect(surf, ELEC_OFF, rect)
            pygame.draw.rect(surf, ELEC_BORDER, rect, 1)
        self.electrode_surface = surf

    def draw(self):
        self.screen.fill(BG_COLOR)
        # Blit static electrode layer
        if self.electrode_surface:
            self.screen.blit(self.electrode_surface, (0, 0))

        # Draw active electrodes on top
        for e in self.container.electrodes:
            if e.status == 1:
                rect = (e.x*SCALE, e.y*SCALE, e.size_x*SCALE, e.size_y*SCALE)
                pygame.draw.rect(self.screen, ELEC_ON, rect)
                pygame.draw.rect(self.screen, ELEC_BORDER, rect, 1)

        # Draw actuators (red overlay)
        for act in self.container.actuators:
            s = pygame.Surface((act.size_x*SCALE, act.size_y*SCALE), pygame.SRCALPHA)
            s.fill((220, 60, 60, 80))
            self.screen.blit(s, (act.x*SCALE, act.y*SCALE))
            pygame.draw.rect(self.screen, (220,60,60),
                (act.x*SCALE, act.y*SCALE, act.size_x*SCALE, act.size_y*SCALE), 2)

        # Draw sensors (blue overlay)
        for sen in self.container.sensors:
            s = pygame.Surface((sen.size_x*SCALE, sen.size_y*SCALE), pygame.SRCALPHA)
            s.fill((80, 120, 220, 80))
            self.screen.blit(s, (sen.x*SCALE, sen.y*SCALE))
            pygame.draw.rect(self.screen, (80,120,220),
                (sen.x*SCALE, sen.y*SCALE, sen.size_x*SCALE, sen.size_y*SCALE), 2)

        # Draw droplets as circles
        for d in self.container.droplets:
            cx = int(d.x * SCALE)
            cy = int(d.y * SCALE)
            radius = int(d.size_x * SCALE / 2)
            color = hex_to_rgb(d.color)
            pygame.draw.circle(self.screen, color, (cx, cy), radius)
            pygame.draw.circle(self.screen, (0,0,0), (cx, cy), radius, 2)

        # Draw bubbles
        for b in self.container.bubbles:
            cx = int(b.x * SCALE)
            cy = int(b.y * SCALE)
            pygame.draw.circle(self.screen, (180,180,255), (cx,cy), 4, 1)

        # Info panel (right side)
        self._draw_info_panel()
        pygame.display.flip()

    def _draw_info_panel(self):
        px = self.container.board_width * SCALE + 10
        texts = [
            f"Time: {self.container.current_time:.2f}s",
            f"Droplets: {len(self.container.droplets)}",
            f"Bubbles: {len(self.container.bubbles)}",
            f"Speed: {self.speed}x",
            f"Running: {'YES' if self.running else 'NO'}",
            "",
            "SPACE = play/pause",
            "UP/DOWN = speed",
            "Click = inspect",
        ]
        for i, t in enumerate(texts):
            surf = self.font.render(t, True, (200,200,200))
            self.screen.blit(surf, (px, 20 + i*18))

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    self.running = not self.running
                if event.key == pygame.K_UP:
                    self.speed = min(10, self.speed + 1)
                if event.key == pygame.K_DOWN:
                    self.speed = max(1, self.speed - 1)
        return True

    def run(self):
        while True:
            if not self.handle_events():
                break
            if self.running:
                for _ in range(self.speed):
                    if self.simplevm and self.simplevm.has_actions():
                        self.simplevm.execute_next()
                    step(self.container)
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()