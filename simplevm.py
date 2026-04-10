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
                        self.action_queue.append({
                            "action": "setel",
                            "driver": driver_id,
                            "id": int(el_id),
                            "change": 1
                        })
                elif line.startswith("clrel"):
                    parts = line.split()
                    driver_id = int(parts[1])
                    for el_id in parts[2:]:
                        self.action_queue.append({
                            "action": "clrel",
                            "driver": driver_id,
                            "id": int(el_id),
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