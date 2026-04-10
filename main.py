from engine import initialize
from simplevm import SimpleVM
from gui import SimulationGUI

if __name__ == "__main__":
    # 1. Load the platform from JSON
    container = initialize("data/platform640Center_path.json")

    # 2. Load a BioAssembly program
    vm = SimpleVM(container)
    vm.load_program("data/center_path.txt")

    # 3. Launch the GUI
    gui = SimulationGUI(container, simplevm=vm)
    gui.run()