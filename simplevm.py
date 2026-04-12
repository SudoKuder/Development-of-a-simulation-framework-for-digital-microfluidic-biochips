from datatypes import Container
from engine import execute_action
from collections import deque


class SimpleVM:
    def __init__(self, container: Container):
        self.container = container
        self.action_queue = deque()

    def load_program(self, filepath: str):
        """Read a .txt BioAssembly file and queue all actions."""
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("setel"):
                    parts = line.split()
                    driver_id = int(parts[1])
                    for el_id in parts[2:]:
                        electrode_id = int(el_id)
                        self.action_queue.append({
                            "action": "setel",
                            "driver": driver_id,
                            "electrode_id": electrode_id,
                            "id": electrode_id,
                            "change": 1
                        })
                elif line.startswith("clrel"):
                    parts = line.split()
                    driver_id = int(parts[1])
                    for el_id in parts[2:]:
                        electrode_id = int(el_id)
                        self.action_queue.append({
                            "action": "clrel",
                            "driver": driver_id,
                            "electrode_id": electrode_id,
                            "id": electrode_id,
                            "change": 0
                        })

    def execute_next(self):
        """Execute the next action in the queue."""
        if self.action_queue:
            action = self.action_queue.popleft()
            execute_action(self.container, action)
            return True
        return False

    def has_actions(self):
        return len(self.action_queue) > 0

    def enqueue_action(self, action: dict):
        """Allow external software to inject actions at runtime."""
        self.action_queue.append(action)

    def read_sensor(self, sensor_id: int):
        """Read sensor values dynamically during execution."""
        sensor = next((s for s in self.container.sensors if getattr(s, "sensor_id", None) == sensor_id), None)
        if sensor is None:
            return None

        sensor_type = getattr(sensor, "type", "")
        if sensor_type == "temperature":
            return {"type": sensor_type, "value": getattr(sensor, "temperature", -1.0)}
        if sensor_type == "color":
            return {
                "type": sensor_type,
                "value": [
                    getattr(sensor, "value_r", -1),
                    getattr(sensor, "value_g", -1),
                    getattr(sensor, "value_b", -1),
                ],
            }
        return {"type": sensor_type, "value": None}

    def set_heater_target(self, actuator_id: int, desired_temp: float) -> bool:
        """Control actuator parameters during runtime."""
        heater = next((a for a in self.container.actuators if getattr(a, "actuator_id", None) == actuator_id), None)
        if heater is None:
            return False
        heater.desired_temp = desired_temp
        heater.has_target_setpoint = True
        return True