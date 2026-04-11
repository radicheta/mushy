# Coding Conventions

**Analysis Date:** 2026-03-28

## Naming Patterns

**Files:**
- Lowercase with underscores: `fc_controller.py`, `fc_sensors.py`, `fc_display.py`, `fc_telemetry.py`
- Module files match their primary class/function name
- Test files follow convention: `test_<module_name>.py`

**Functions:**
- snake_case for all functions: `temperature_callback()`, `should_light_be_on()`, `set_fan_speed()`, `read_sensors()`
- Callback functions follow pattern: `<event>_callback()` (e.g., `temperature_callback()`, `humidity_callback()`)
- Private functions use leading underscore: not commonly used in current codebase
- Entry points named `main()` as per ROS2 conventions

**Variables:**
- snake_case for local variables: `current_temp`, `temp_diff`, `fan_speed`, `humidifier_state`
- Instance variables prefixed with `self.`: `self.current_temp`, `self.timer`, `self.GPIO`
- Constants not found in current codebase - parameters stored in YAML config instead

**Types:**
- Class names use PascalCase: `FruitingChamberController`, `FruitingChamberSensors`, `FruitingChamberDisplay`, `FruitingChamberTelemetry`
- ROS2 message types from imported modules: `Temperature`, `RelativeHumidity`

**JavaScript/Node.js:**
- camelCase for variables and functions: `readyState`, `websocket`, `broadcast()`
- PascalCase for classes/constructors: `WebSocket`, `Set`, `Node`
- Shorter variable names common: `ws`, `msg`, `data`

## Code Style

**Formatting:**
- Python: No explicit formatter configured (ament_flake8 present but no config file)
- Shebang line present: `#!/usr/bin/env python3` on all executable Python files
- Consistent indentation: 4 spaces for Python
- Line length: Generally reasonable length, no strict limit enforced

**Linting:**
- Python: ament_flake8 and ament_pep257 configured as test dependencies in `package.xml` at `src/chambers/fc-core/package.xml`
- JavaScript: No linter configured (bridge uses plain Node.js)
- ROS2 packages use ament_lint_auto for standard linting

**Imports in Python:**
- Standard library imports first: `import os`, `import json`, `import time`
- Third-party imports next: `import rclpy`, `from sensor_msgs.msg import ...`
- Conditional imports inside methods for hardware: `import RPi.GPIO as GPIO`, `import adafruit_dht`
- Each import on separate line or grouped logically

## Import Organization

**Order (Python):**
1. Shebang and encoding declarations
2. Standard library imports: `import os`, `import time`, `import json`, `from datetime import datetime`
3. Third-party imports: `import rclpy`, `from sensor_msgs.msg import ...`
4. Conditional imports (inside methods): Hardware-specific imports guarded by simulation_mode check
5. No local/relative imports observed (ROS2 package structure)

**Order (JavaScript):**
1. Variable/require statements: `const WebSocket = require('ws')`
2. Initialization logic follows

**Path Aliases:**
- No path aliases used in current codebase
- Direct imports and relative paths used

## Error Handling

**Patterns:**
- Try-finally blocks used for cleanup: See `fc_controller.py` lines 179-188, `fc_sensors.py` lines 79-88
- Specific exception catching: `except RuntimeError as e:` in `fc_sensors.py` line 75
- KeyboardInterrupt handling for graceful shutdown in `main()` functions
- Errors logged via `self.get_logger().error()` with descriptive messages
- Sleep after error for retry delay: `time.sleep(2.0)` after sensor read failure in `fc_sensors.py` line 77

**Error Handling in Hardware:**
- Conditional logic for simulation vs. real hardware prevents exceptions from missing GPIO on development machines
- No explicit exception handling for hardware operations (assumes GPIO/PWM libraries raise appropriately)

**WebSocket Error Handling:**
- Browser/JavaScript uses try-catch implicitly through promise chain in `plugin.js` lines 20-27
- Bridge JavaScript doesn't show explicit error handlers for WebSocket connections

## Logging

**Framework:** ROS2 built-in logger via `self.get_logger()`

**Patterns:**
- INFO level for node startup: `self.get_logger().info('Fruiting Chamber Sensors Node Started')` at `fc_sensors.py` line 43
- DEBUG level for telemetry data: `self.get_logger().debug(f'Temperature: {temperature}°C, Humidity: {humidity*100:.1f}%')` at `fc_sensors.py` line 73
- ERROR level with exception context: `self.get_logger().error(f'Failed to read sensor: {e}')` at `fc_sensors.py` line 76
- F-strings used for formatted logging throughout

**Console Output:**
- JavaScript uses `console.log()` for bridge status: `console.log('New client connected')` at `bridge/src/index.js` line 43
- Node startup messages: `console.log('Bridge service started on port 8081')` at `bridge/src/index.js` line 64

## Comments

**When to Comment:**
- Config files have inline comments explaining parameter purpose: `fc_config.yaml` lines 3-28
- Launch file comments describe node purpose: `fc.launch.py` lines 16-48
- Light hour logic includes comment explaining midnight crossing case: `fc_controller.py` line 107
- Comments used for section grouping in __init__ methods: `# Initialize hardware or simulation`, `# Create publishers`

**JSDoc/TSDoc:**
- Not used in current codebase
- No formal documentation generation configured

## Function Design

**Size:**
- Generally compact, single-responsibility functions
- Callbacks typically 1-3 lines: `temperature_callback()` at `fc_controller.py` line 90-91
- Control logic methods under 20 lines
- Largest function: `control_loop()` at `fc_controller.py` lines 143-174 (32 lines including logging)

**Parameters:**
- Minimal parameter passing; state stored in instance variables
- Callbacks receive single message parameter
- No default parameters observed (ROS2 uses parameter server)

**Return Values:**
- Callbacks return None
- Predicates return boolean: `should_light_be_on()` returns bool
- Setter methods return None
- Getter methods return value: `get_fan_speed()`, `get_humidifier_state()`, `get_light_state()`

## Module Design

**Exports:**
- Entry points defined in `setup.py`: `'fc_controller = fc_core.fc_controller:main'` style
- Each module has a `main()` function as entry point
- Node classes exported for import if needed

**Barrel Files:**
- Not used; `__init__.py` is empty in `fc_core/`
- Each module stands alone

**ROS2 Patterns:**
- Each executable is a separate module with its own Node class
- Configuration loaded from YAML files in `config/` directory
- Parameters declared in node `__init__`: `self.declare_parameters()` pattern
- Subscriptions and timers created in `__init__`

## Simulation Mode Pattern

**Throughout codebase:**
- All hardware-dependent operations check `self.get_parameter('simulation_mode').value`
- When True: internal state variables updated (`self.fan_speed`, `self.humidifier_state`, `self.light_state`)
- When False: actual hardware calls (`GPIO.output()`, `self.fan_pwm.change_duty_cycle()`)
- See `fc_controller.py` lines 34-64 (initialization), lines 110-141 (state access methods)

---

*Convention analysis: 2026-03-28*
