import json
from datatypes import *


ACTUATOR_LOADERS = {}
SENSOR_LOADERS = {}


def _get(obj: dict, *keys, default=None):
    for key in keys:
        if key in obj:
            return obj[key]
    return default


def register_actuator_loader(type_name: str, loader_fn):
    """Register a JSON -> actuator parser for a component type."""
    ACTUATOR_LOADERS[type_name] = loader_fn


def register_sensor_loader(type_name: str, loader_fn):
    """Register a JSON -> sensor parser for a component type."""
    SENSOR_LOADERS[type_name] = loader_fn


def _load_heater(data: dict) -> Heater:
    return Heater(
        id=_get(data, "id", "ID"),
        actuator_id=_get(data, "actuatorID", default=0),
        x=_get(data, "positionX", default=0),
        y=_get(data, "positionY", default=0),
        size_x=_get(data, "sizeX", default=0),
        size_y=_get(data, "sizeY", default=0),
        actual_temp=_get(data, "valueActualTemperature", default=20.0),
        desired_temp=_get(data, "valueDesiredTemperature", default=90.0),
        power_status=_get(data, "valuePowerStatus", default=0),
    )


def _load_micro_shaker(data: dict) -> MicroShaker:
    return MicroShaker(
        id=_get(data, "id", "ID"),
        actuator_id=_get(data, "actuatorID", default=0),
        name=_get(data, "name", default="micro_shaker"),
        x=_get(data, "positionX", default=0),
        y=_get(data, "positionY", default=0),
        size_x=_get(data, "sizeX", default=0),
        size_y=_get(data, "sizeY", default=0),
        vibration_frequency=_get(data, "valueVibrationFrequency", "vibrationFrequency", default=0.0),
        desired_frequency=_get(data, "valueDesiredFrequency", "desiredFrequency", default=0.0),
        power_status=_get(data, "valuePowerStatus", "powerStatus", default=0),
        subscriptions=_get(data, "subscriptions", default=[]),
    )


def _load_temperature_sensor(data: dict) -> TemperatureSensor:
    return TemperatureSensor(
        id=_get(data, "id", "ID"),
        sensor_id=_get(data, "sensorID", default=0),
        x=_get(data, "positionX", default=0),
        y=_get(data, "positionY", default=0),
        size_x=_get(data, "sizeX", default=0),
        size_y=_get(data, "sizeY", default=0),
        temperature=_get(data, "valueTemperature", "temperature", default=20.0),
    )


def _load_color_sensor(data: dict) -> ColorSensor:
    return ColorSensor(
        id=_get(data, "id", "ID"),
        sensor_id=_get(data, "sensorID", default=0),
        x=_get(data, "positionX", default=0),
        y=_get(data, "positionY", default=0),
        size_x=_get(data, "sizeX", default=0),
        size_y=_get(data, "sizeY", default=0),
        value_r=_get(data, "valueRed", default=0),
        value_g=_get(data, "valueGreen", default=0),
        value_b=_get(data, "valueBlue", default=0),
    )


register_actuator_loader("heater", _load_heater)
register_actuator_loader("micro_shaker", _load_micro_shaker)
register_actuator_loader("microShaker", _load_micro_shaker)

register_sensor_loader("temperature", _load_temperature_sensor)
register_sensor_loader("RGB_color", _load_color_sensor)
register_sensor_loader("color", _load_color_sensor)

def load_platform(filepath: str) -> Container:
    with open(filepath, "r") as f:
        data = json.load(f)

    container = Container()
    info = data.get("information", {})
    container.platform_name = _get(info, "name", "platform_name", default="")
    container.board_width = _get(info, "sizeX", default=0)
    container.board_height = _get(info, "sizeY", default=0)

    for e in data.get("electrodes", []):
        container.electrodes.append(Electrode(
            id=_get(e, "id", "ID"),
            electrode_id=_get(e, "electrodeID", "id", "ID", default=-1),
            driver_id=_get(e, "driverID", default=0),
            x=_get(e, "positionX", default=0),
            y=_get(e, "positionY", default=0),
            size_x=_get(e, "sizeX", default=0),
            size_y=_get(e, "sizeY", default=0),
            status=_get(e, "status", default=0),
            shape=_get(e, "shape", default=0),
            corners=_get(e, "corners", default=[]),
            neighbours=_get(e, "neighbours", default=[]),
            subscriptions=_get(e, "subscriptions", default=[]),
        ))

    for d in data.get("droplets", []):
        size_x = _get(d, "sizeX", default=0.0)
        size_y = _get(d, "sizeY", default=0.0)
        inferred_volume = max(1.0, (size_x * size_y) / 10.0)
        container.droplets.append(Droplet(
            id=_get(d, "id", "ID"),
            name=_get(d, "name", default="droplet"),
            x=_get(d, "positionX", default=0.0),
            y=_get(d, "positionY", default=0.0),
            size_x=size_x,
            size_y=size_y,
            color=_get(d, "color", default="#FFFFFF"),
            temperature=_get(d, "temperature", default=20.0),
            volume=_get(d, "volume", default=inferred_volume),
            density=_get(d, "density", default=1.0),
            specific_heat_capacity=_get(d, "specificHeatCapacity", "specific_heat_capacity", default=4.18),
            thermal_conductivity=_get(d, "thermalConductivity", "thermal_conductivity", default=0.12),
            electrode_id=_get(d, "electrodeID", "electrode_id", default=-1),
            model_order=_get(d, "modelOrder", "model_order", default=["split", "merge", "temperature", "make_bubble"]),
        ))

    for a in data.get("actuators", []):
        actuator_type = _get(a, "type", default="")
        loader = ACTUATOR_LOADERS.get(actuator_type)
        if loader is not None:
            container.actuators.append(loader(a))

    for s in data.get("sensors", []):
        sensor_type = _get(s, "type", default="")
        loader = SENSOR_LOADERS.get(sensor_type)
        if loader is not None:
            container.sensors.append(loader(s))

    return container