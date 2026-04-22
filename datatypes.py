from dataclasses import dataclass, field
from typing import List, Optional


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_nitrogen(value: float) -> str:
    if value < 0.40:
        return "Low"
    if value <= 0.80:
        return "Medium"
    return "High"


def score_phosphorus(value: float) -> str:
    if value < 0.30:
        return "Low"
    if value <= 0.70:
        return "Medium"
    return "High"


def score_potassium(value: float) -> str:
    if value < 50.0:
        return "Low"
    if value <= 100.0:
        return "Medium"
    return "High"


def soil_color_from_npk(nitrogen: float, phosphorus: float, potassium: float) -> str:
    """Map NPK concentrations into a stable visible color for soil droplets."""
    n_norm = _clamp01(nitrogen / 1.0)
    p_norm = _clamp01(phosphorus / 1.0)
    k_norm = _clamp01(potassium / 150.0)

    # Base soil tone shifted by nutrient makeup.
    r = int(max(0, min(255, 90 + 120 * k_norm + 35 * p_norm)))
    g = int(max(0, min(255, 68 + 140 * n_norm + 20 * k_norm)))
    b = int(max(0, min(255, 45 + 120 * p_norm + 10 * n_norm)))
    return f"#{r:02x}{g:02x}{b:02x}"


REAGENT_NONE = "none"
REAGENT_NITROGEN = "nitrogen"
REAGENT_PHOSPHORUS = "phosphorus"
REAGENT_POTASSIUM = "potassium"


def normalize_reagent_type(value: Optional[str]) -> str:
    if value is None:
        return REAGENT_NONE
    normalized = str(value).strip().lower()
    if normalized in {REAGENT_NITROGEN, REAGENT_PHOSPHORUS, REAGENT_POTASSIUM}:
        return normalized
    return REAGENT_NONE


def is_reagent_type(value: Optional[str]) -> bool:
    return normalize_reagent_type(value) != REAGENT_NONE


def soil_reagent_reaction(reagent_type: str, nitrogen: float, phosphorus: float, potassium: float):
    """Return reaction text and optional visual color for soil-reagent assays."""
    reagent = normalize_reagent_type(reagent_type)
    if reagent == REAGENT_NITROGEN:
        if nitrogen < 0.40:
            return "No color change (Nitrogen Low)", None
        if nitrogen <= 0.80:
            return "Light color change (Nitrogen Medium)", "#f4e8aa"
        return "Strong color change (Nitrogen High)", "#f2d24c"

    if reagent == REAGENT_PHOSPHORUS:
        if phosphorus < 0.30:
            return "No color change (Phosphorus Low)", None
        if phosphorus <= 0.70:
            return "Light blue color (Phosphorus Medium)", "#7fb7ff"
        return "Deep blue color (Phosphorus High)", "#1f4da5"

    if reagent == REAGENT_POTASSIUM:
        if potassium < 50.0:
            return "No turbidity (Potassium Low)", None
        if potassium <= 100.0:
            return "Moderate turbidity (Potassium Medium)", "#c8d0d8"
        return "Strong turbidity (Potassium High)", "#9ca5ae"

    return "No reagent reaction", None

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
    is_soil_sample: bool = False
    nitrogen: float = 0.0
    phosphorus: float = 0.0
    potassium: float = 0.0
    reagent_type: str = REAGENT_NONE
    reaction_result: str = ""

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