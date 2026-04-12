from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Electrode:
    id: int
    electrode_id: int
    driver_id: int
    x: int
    y: int
    size_x: int
    size_y: int
    status: int = 0           # 0 = OFF, 1 = ON
    shape: int = 0            # 0 = square, 1 = polygon
    corners: list = field(default_factory=list)
    neighbours: list = field(default_factory=list)
    subscriptions: list = field(default_factory=list)  # droplet IDs

@dataclass
class Droplet:
    id: int
    name: str
    x: float
    y: float
    size_x: float
    size_y: float
    color: str          # e.g. "#FF0000"
    temperature: float = 20.0
    volume: float = 1.0
    density: float = 1.0
    specific_heat_capacity: float = 4.18
    thermal_conductivity: float = 0.12
    group_id: int = -1
    electrode_id: int = -1
    model_order: list = field(default_factory=lambda:
        ["split", "merge", "temperature", "make_bubble"])
    begin_of_time_sensitive_models: int = 2
    next_model: int = 0
    last_bubble_time: float = -1e9
    bubble_cooldown: float = 1.0
    accumulatingBubbleEscapeVolume: float = 0.0

@dataclass
class Bubble:
    id: int
    x: float
    y: float
    size_x: float
    size_y: float
    to_remove: bool = False
    age: float = 0.0
    lifetime: float = 3.0
    subscriptions: list = field(default_factory=list)

@dataclass
class Heater:
    id: int
    actuator_id: int
    x: int
    y: int
    size_x: int
    size_y: int
    actual_temp: float = 20.0
    desired_temp: float = 90.0
    # Set to True only after a controller (e.g. VM/UI) explicitly sets desired_temp.
    has_target_setpoint: bool = False
    # Signed power direction selected by the heater model: -1 cooling, 0 hold, 1 heating.
    power_status: int = 0
    type: str = "heater"


@dataclass
class MicroShaker:
    id: int
    actuator_id: int
    name: str
    x: int
    y: int
    size_x: int
    size_y: int
    vibration_frequency: float = 0.0
    desired_frequency: float = 0.0
    power_status: int = 0      # 0 = OFF, 1 = ON
    type: str = "micro_shaker"
    subscriptions: list = field(default_factory=list)  # droplet IDs

@dataclass
class TemperatureSensor:
    id: int
    sensor_id: int
    x: int
    y: int
    size_x: int
    size_y: int
    temperature: float = 20.0
    type: str = "temperature"

@dataclass
class ColorSensor:
    id: int
    sensor_id: int
    x: int
    y: int
    size_x: int
    size_y: int
    value_r: int = 0
    value_g: int = 0
    value_b: int = 0
    type: str = "color"

@dataclass
class Container:
    electrodes: List[Electrode] = field(default_factory=list)
    droplets: List[Droplet] = field(default_factory=list)
    bubbles: List[Bubble] = field(default_factory=list)
    actuators: list = field(default_factory=list)
    sensors: list = field(default_factory=list)
    current_time: float = 0.0
    time_step: float = 0.1
    platform_name: str = ""
    board_width: int = 0
    board_height: int = 0