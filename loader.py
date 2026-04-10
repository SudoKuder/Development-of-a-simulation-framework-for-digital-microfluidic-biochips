import json
from datatypes import *


def _get(obj: dict, *keys, default=None):
    for key in keys:
        if key in obj:
            return obj[key]
    return default

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
        container.droplets.append(Droplet(
            id=_get(d, "id", "ID"),
            name=_get(d, "name", default="droplet"),
            x=_get(d, "positionX", default=0.0),
            y=_get(d, "positionY", default=0.0),
            size_x=_get(d, "sizeX", default=0.0),
            size_y=_get(d, "sizeY", default=0.0),
            color=_get(d, "color", default="#FFFFFF"),
            temperature=_get(d, "temperature", default=20.0),
            electrode_id=_get(d, "electrodeID", "electrode_id", default=-1),
        ))

    for a in data.get("actuators", []):
        if _get(a, "type", default="") == "heater":
            container.actuators.append(Heater(
                id=_get(a, "id", "ID"),
                actuator_id=_get(a, "actuatorID", default=0),
                x=_get(a, "positionX", default=0),
                y=_get(a, "positionY", default=0),
                size_x=_get(a, "sizeX", default=0),
                size_y=_get(a, "sizeY", default=0),
                actual_temp=_get(a, "valueActualTemperature", default=20.0),
                desired_temp=_get(a, "valueDesiredTemperature", default=90.0),
                power_status=_get(a, "valuePowerStatus", default=0),
            ))

    for s in data.get("sensors", []):
        sensor_type = _get(s, "type", default="")
        if sensor_type == "temperature":
            container.sensors.append(TemperatureSensor(
                id=_get(s, "id", "ID"),
                sensor_id=_get(s, "sensorID", default=0),
                x=_get(s, "positionX", default=0),
                y=_get(s, "positionY", default=0),
                size_x=_get(s, "sizeX", default=0),
                size_y=_get(s, "sizeY", default=0),
                temperature=_get(s, "valueTemperature", "temperature", default=20.0),
            ))
        elif sensor_type == "RGB_color":
            container.sensors.append(ColorSensor(
                id=_get(s, "id", "ID"),
                sensor_id=_get(s, "sensorID", default=0),
                x=_get(s, "positionX", default=0),
                y=_get(s, "positionY", default=0),
                size_x=_get(s, "sizeX", default=0),
                size_y=_get(s, "sizeY", default=0),
                value_r=_get(s, "valueRed", default=0),
                value_g=_get(s, "valueGreen", default=0),
                value_b=_get(s, "valueBlue", default=0),
            ))

    return container