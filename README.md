# Development-of-a-simulation-framework-for-digital-microfluidic-biochips

## Chapter 7: Simulation Interchangeability

This project now follows a structured extension pipeline for adding or replacing component behavior safely.

### 7.1 Add or change an existing model

- Droplet models are resolved through `DROPLET_MODEL_DISPATCH` in `engine.py`.
- Actuator models are resolved through `ACTUATOR_MODEL_DISPATCH` in `engine.py`.
- You can replace behavior without changing the simulation loop by calling:
	- `register_droplet_model(name, fn)`
	- `register_actuator_model(type_name, fn)`

### 7.2 Initialization and datatype

New components must define their datatypes in `datatypes.py` and flow through loader + initialization.

Implemented example: `MicroShaker`

- Required fields include: `name`, `id`, `type`, `position`, `size`, `power_status`, `vibration_frequency`.
- Runtime subscription IDs are tracked in `subscriptions`.

#### 7.2.1 Add a component to JSON

Add a component to `actuators` with an explicit `type`:

```json
{
	"id": 11,
	"actuatorID": 5,
	"name": "microShaker",
	"type": "micro_shaker",
	"positionX": 10,
	"positionY": 10,
	"sizeX": 20,
	"sizeY": 20,
	"valueVibrationFrequency": 0.0,
	"valueDesiredFrequency": 60.0,
	"valuePowerStatus": 1
}
```

#### 7.2.2 Add a component to the container

- JSON parsing is handled by registries in `loader.py`:
	- `register_actuator_loader(type_name, loader_fn)`
	- `register_sensor_loader(type_name, loader_fn)`
- Built-in registrations include `heater` and `micro_shaker`.

#### 7.2.3 Initialize a component

- `initialize_actuators` in `engine.py` assigns defaults.
- `update_micro_shaker_subscriptions` in `models.py` synchronizes affected droplets before/after cycles.

### 7.3 Add new models

- Droplet execution is breadth-first through a subscriber queue: each queue turn executes one model for that droplet.
- Each droplet owns its own `model_order` and `next_model` pointer.
- Action-triggered cycles execute indices before `begin_of_time_sensitive_models`.
- Time-triggered cycles execute indices from `begin_of_time_sensitive_models` onward.
- `begin_of_time_sensitive_models` is configurable per droplet via JSON (`beginOfTimeSensitiveModels` / `begin_of_time_sensitive_models`).

#### 7.3.1 Component-specific models

- Add actuator dynamics in `models.py` (example: `micro_shaker_frequency_change`).
- Register in `ACTUATOR_MODEL_DISPATCH` or via `register_actuator_model`.
- Actuator models execute every simulation step.

#### 7.3.2 Component-dependent models

- Add dependent droplet logic in `models.py` (example: `droplet_vibration`).
- Dependent models must return a list of droplet subscriber IDs so breadth-first queue execution remains correct.
- If a micro-shaker is present, droplets automatically include `vibration` in `model_order` during initialization.

### 7.4 Visualizing a component

- GUI sketch rendering in `gui.py` now maps actuator visuals by type.
- `micro_shaker` actuators are drawn with cyan overlays and animated wave rings while powered.
- Information panel and JSON downloads expose both generic actuator fields and type-specific fields:
	- `vibration_frequency`
	- `desired_frequency`
	- `subscriptions`

## Quick extension checklist

1. Add/extend datatype in `datatypes.py`.
2. Register JSON loader in `loader.py`.
3. Initialize defaults/subscriptions in `engine.py` and `models.py`.
4. Register runtime model in `engine.py` dispatch or via registration function.
5. Add dependent model(s) that return subscriber droplet IDs.
6. Add GUI drawing + info panel handling in `gui.py`.
7. Add tests in `tests/test_engine.py`.

## Chapter 8: Evaluation and Testing

This chapter summarizes how the simulation framework was evaluated and which tests were executed to verify correctness and runtime behavior.

### 8.1 Runtime and Platform Coverage

- The simulator is implemented in Python and rendered with `pygame`, which supports desktop execution across major operating systems.
- The current workspace validation was executed on Linux.
- The architecture (platform JSON + VM instruction input + simulation step loop) is independent of a specific operating system and can be run on other supported Python/`pygame` environments.

### 8.2 Unit Testing

- Unit tests are implemented with `pytest` in `tests/test_engine.py`.
- Current status: **14 tests passed**.
- Covered core functionality includes:
	- Neighbour discovery (`find_neighbours`) to ensure electrode graph connectivity.
	- Subscription initialization (`initialize_subscriptions`) so droplets map to valid electrodes.
	- Droplet group initialization (`recalculate_groups`) so each droplet receives a valid group ID.
	- Action routing correctness for driver/electrode addressing (`execute_action`).
	- Split behavior with mass conservation (`test_split_conserves_volume`).
	- Merge behavior under both permissive and strict overlap conditions.
	- Bubble lifecycle behavior, including delayed generation and decay cleanup.
	- Sensor read strictness for color and temperature sensors (`update_sensor_readings`).
	- Color mixing logic (`blend_colors`).
	- Loader/runtime coverage for the `micro_shaker` component, including subscription and vibration effects.

### 8.3 Scenario and Platform Testing

Beyond isolated unit tests, the framework is also exercised through scenario execution using platform JSONs and VM programs in `data/testing/` and `data/showcase/`.

- Methodology:
	- Initialize simulation state from a platform file.
	- Execute instruction queues through `SimpleVM`.
	- Compare simulation behavior step-by-step against expected physical lab behavior.
- Example scenario classes used in this repository:
	- Single-droplet route execution (`platform_small_cross.json` + `program_cross_route.txt`).
	- Split/merge routing paths (`platform_split_merge.json` + `program_split_merge.txt`).
	- Demonstration scenarios with actuators and dynamic control (`platform_dual_driver.json`, `platform_heater_bubbles.json`).

Behaviorally, scenario runs validate:

- Heater interaction and droplet temperature evolution.
- Bubble spawning when high-temperature conditions are sustained.
- Droplet split/merge transitions under realistic actuation.
- Color blending when droplets combine.
- Movement constraints based on droplet size relative to electrode dimensions.

### 8.4 Performance

Several runtime-oriented improvements were integrated to reduce computation cost per step:

- Optimized traversal for neighbour discovery and related lookup-heavy paths.
- Reworked subscription initialization to improve startup behavior on larger platforms.
- Focused model dispatch through registration maps (instead of hard-coded branching) to keep update cycles maintainable and efficient.