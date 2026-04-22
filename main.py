import argparse

from engine import initialize
from simplevm import SimpleVM
from gui import SimulationGUI


def _parse_args():
    parser = argparse.ArgumentParser(description="Run DMFb simulation GUI")
    parser.add_argument(
        "--platform",
        default="data/showcase/platform_soil_npk_reaction.json",
        help="Path to platform JSON",
    )
    parser.add_argument(
        "--program",
        default="data/showcase/program_soil_npk_reaction.txt",
        help="Path to BioAssembly program TXT",
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = _parse_args()

    # 1. Load the platform from JSON
    container = initialize(args.platform)

    # 2. Load a BioAssembly program
    vm = SimpleVM(container)
    vm.load_program(args.program)

    # 3. Launch the GUI
    gui = SimulationGUI(container, simplevm=vm)
    gui.run()