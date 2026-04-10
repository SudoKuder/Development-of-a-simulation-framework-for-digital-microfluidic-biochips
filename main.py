from engine import initialize
from simplevm import SimpleVM
from gui import SimulationGUI

if __name__ == "__main__":
    # 1. Load the platform from JSON
    container = initialize("data/testing/platform_small_cross.json")

    # 2. Load a BioAssembly program
    vm = SimpleVM(container)
    vm.load_program("data/testing/program_cross_route.txt")

    # 3. Launch the GUI
    gui = SimulationGUI(container, simplevm=vm)
    gui.run()