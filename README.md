# Digital Microfluidic Biochip Simulation Framework

Python simulation framework for digital microfluidic biochips (DMFb), with:

- Platform loading from JSON.
- Program execution through a simple VM.
- Interactive visualization using pygame.
- Automated tests with pytest.

This README is optimized for sharing the repository so anyone can run and verify the project quickly.

## 1) Quick Start

### Prerequisites

- Python 3.10+
- pip

### Clone and set up

```bash
git clone <your-repo-url>
cd Development-of-a-simulation-framework-for-digital-microfluidic-biochips

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### Run the simulator

```bash
python main.py
```

Run with custom input files:

```bash
python main.py --platform data/platform640Center_path.json --program data/center_path.txt
```

## 2) Verify Everything Works

Run the test suite:

```bash
pytest -q
```

Expected result: all tests pass.

If you are on a headless Linux server and pygame display initialization fails, run tests only (tests do not require launching the GUI).

## 3) Project Structure

Top-level files:

- `main.py`: CLI entry point for loading platform + program and launching the GUI.
- `engine.py`: Simulation initialization, execution loop, and action handling.
- `models.py`: Droplet/actuator physics and behavior models.
- `loader.py`: Platform JSON parsing and object construction.
- `gui.py`: pygame-based simulation rendering and interaction.
- `simplevm.py`: Program parser/executor for BioAssembly-like instructions.
- `datatypes.py`: Core dataclasses for droplets, electrodes, actuators, sensors, etc.

Data and tests:

- `data/showcase/`: Demo platforms and programs.
- `data/testing/`: Inputs used for scenario-focused testing.
- `tests/`: Unit tests and test fixtures.

## 4) Common Commands

```bash
# run app with defaults
python main.py

# run app with selected scenario
python main.py --platform data/showcase/platform_dual_driver.json --program data/showcase/program_dual_driver.txt

# run all tests
pytest -q

# run one test file
pytest -q tests/test_engine.py
```

## 5) Dependency Notes

- Runtime GUI dependency: `pygame`
- Test dependency: `pytest`

Dependencies are pinned in `requirements.txt` for reproducible setup.

## 6) Troubleshooting

- `ModuleNotFoundError`: ensure your virtual environment is activated and dependencies are installed from `requirements.txt`.
- `python: command not found`: use `python3` instead of `python`, then repeat setup.
- GUI does not open: verify you are running in a desktop session with display access.

## 7) Development and Extension Notes

Model extension workflow:

- Droplet models are dispatched through `DROPLET_MODEL_DISPATCH` in `engine.py`.
- Actuator models are dispatched through `ACTUATOR_MODEL_DISPATCH` in `engine.py`.
- Additional behavior can be registered using:
  - `register_droplet_model(name, fn)`
  - `register_actuator_model(type_name, fn)`

`MicroShaker` is included as an example extension spanning datatype definition, loader registration, initialization, model execution, and GUI rendering.