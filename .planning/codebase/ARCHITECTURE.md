# Architecture

**Analysis Date:** 2026-03-28

## Pattern Overview

**Overall:** Event-driven distributed ROS2 system with pub/sub architecture

**Key Characteristics:**
- Decoupled ROS2 nodes communicating via topic subscription model
- Sensor data publishers feeding controller and display subscribers
- Hardware abstraction layer supporting simulation mode for development
- WebSocket-based telemetry for external frontend consumption
- Configuration-driven parameters with YAML config files

## Layers

**Sensor Layer:**
- Purpose: Acquire environmental data from hardware or simulation
- Location: `src/chambers/fc-core/fc_core/fc_sensors.py`
- Contains: DHT22 sensor reading, data publication to ROS topics
- Depends on: rclpy, sensor_msgs, hardware libraries (adafruit-dht, board)
- Used by: Controller, Display, Telemetry nodes

**Control Layer:**
- Purpose: Process sensor data and actuate hardware based on control logic
- Location: `src/chambers/fc-core/fc_core/fc_controller.py`
- Contains: Temperature/humidity control loops, actuator command logic, parameter-driven thresholds
- Depends on: Sensor topics, ROS parameters, GPIO/PWM libraries
- Used by: Hardware (GPIO pins, PWM channels)

**Display Layer:**
- Purpose: Display current environmental state and actuator status
- Location: `src/chambers/fc-core/fc_core/fc_display.py`
- Contains: Console logging of chamber status, periodic updates
- Depends on: Temperature and humidity topics
- Used by: Operators (console output)

**Telemetry Layer:**
- Purpose: Export real-time environmental data to external systems
- Location: `src/chambers/fc-core/fc_core/fc_telemetry.py`
- Contains: WebSocket server, JSON telemetry packets, subscription to ROS topics
- Depends on: websockets, asyncio, Temperature/Humidity topics
- Used by: OpenMCT frontend, mission control systems

**Frontend Layer:**
- Purpose: Web-based monitoring and control interface
- Location: `src/mission-control/frontend/plugins/fruiting-chamber/`
- Contains: OpenMCT plugin, telemetry provider, view components
- Depends on: WebSocket connection to telemetry layer
- Used by: Users/operators

**Bridge Layer:**
- Purpose: Connect OpenMCT frontend to ROS backend (planned/stub)
- Location: `src/mission-control/bridge/`
- Contains: WebSocket bridge, fake sensor utilities
- Depends on: ROS topics, WebSocket server
- Used by: Frontend telemetry subscriptions

## Data Flow

**Sensing to Control Loop:**

1. `fc_sensors` reads DHT22 (real) or simulated data every `sensor_read_interval` (2.0s default)
2. Temperature published to `fc/temperature` topic (sensor_msgs.Temperature)
3. Humidity published to `fc/humidity` topic (sensor_msgs.RelativeHumidity)
4. `fc_controller` subscribes to both topics, stores latest values
5. Control timer fires every `control_interval` (1.0s default)
6. Control loop reads current values and compares to parameters
7. Actuator commands (fan PWM, humidifier GPIO, light GPIO) sent to hardware/simulation
8. `fc_display` simultaneously reads topics and logs status

**Telemetry to Frontend:**

1. `fc_telemetry` subscribes to temperature and humidity topics
2. Async WebSocket server runs in daemon thread alongside ROS spinning
3. Frontend (OpenMCT) connects WebSocket to `localhost:8081`
4. Frontend sends topic subscription requests
5. Telemetry node sends JSON packets with timestamp and sensor values
6. Frontend updates display DOM with latest values

**State Management:**

- **Sensor State:** Latest temperature/humidity held in `fc_sensors` instance variables
- **Control State:** Current actuator states (fan_speed, humidifier_state, light_state) held in `fc_controller`
- **Simulation State:** Simulated values in instance variables when `simulation_mode: true`
- **No persistent state:** Values in memory only; restart resets to defaults

## Key Abstractions

**ROS2 Node:**
- Purpose: Base class for all agents; handles subscription/publication lifecycle
- Examples: `FruitingChamberSensors`, `FruitingChamberController`, `FruitingChamberDisplay`, `FruitingChamberTelemetry`
- Pattern: Each inherits from `rclpy.node.Node`, declares parameters, sets up timers/subscriptions

**Hardware Abstraction:**
- Purpose: Decouple control logic from hardware specifics
- Examples: `simulation_mode` parameter in config
- Pattern: If-else branches check `simulation_mode` to use real GPIO/PWM or in-memory state variables

**Topic-Based Communication:**
- Purpose: Loose coupling between nodes
- Topics: `fc/temperature`, `fc/humidity`
- Messages: ROS standard sensor_msgs (Temperature, RelativeHumidity)

**Parameter Server:**
- Purpose: Externalize configuration from code
- Location: `src/chambers/fc-core/config/fc_config.yaml`
- Pattern: Nodes declare parameters in `__init__`, read via `get_parameter()`

## Entry Points

**fc_sensors (Executable):**
- Location: `src/chambers/fc-core/fc_core/fc_sensors.py::main()`
- Triggers: ROS2 launch file, docker-compose, or direct `ros2 run`
- Responsibilities: Periodically read hardware sensors, publish Temperature and RelativeHumidity messages

**fc_controller (Executable):**
- Location: `src/chambers/fc-core/fc_core/fc_controller.py::main()`
- Triggers: ROS2 launch file, docker-compose, or direct `ros2 run`
- Responsibilities: Subscribe to sensor topics, compute control logic, write actuator commands

**fc_display (Executable):**
- Location: `src/chambers/fc-core/fc_core/fc_display.py::main()`
- Triggers: ROS2 launch file, docker-compose, or direct `ros2 run`
- Responsibilities: Display current chamber status to console

**fc_telemetry (Executable):**
- Location: `src/chambers/fc-core/fc_core/fc_telemetry.py::main()`
- Triggers: ROS2 launch file, docker-compose, or direct `ros2 run`
- Responsibilities: Expose ROS sensor data over WebSocket for external clients

**Launch Orchestrator:**
- Location: `src/chambers/fc-core/launch/fc.launch.py`
- Triggers: `ros2 launch fc_core fc.launch.py`
- Responsibilities: Start all four nodes with shared config file

## Error Handling

**Strategy:** Silent failures with logging; no exception propagation

**Patterns:**

- **Sensor Read Failures:** Catch `RuntimeError` in `fc_sensors.read_sensors()`, log error, sleep 2s, retry on next timer
- **Missing Sensor Data:** `fc_controller.control_loop()` checks if current_temp/humidity are None, returns early without actuation
- **Hardware Mode Errors:** Silently fail (no hardware available) in simulation mode; real hardware errors logged but not raised
- **WebSocket Connection Loss:** `fc_telemetry` runs async server; client disconnects handled implicitly by asyncio

## Cross-Cutting Concerns

**Logging:**
- Via `self.get_logger()` from ROS node base class
- Debug: Per-cycle actuator state and sensor values
- Info: Node startup messages
- Error: Hardware read failures only

**Validation:**
- Parameters bounded via `min()` and `max()` in control logic (fan speed 0-100)
- Simulated values constrained to realistic ranges (temp 15-30°C, humidity 50-100%)

**Authentication:**
- None; assumes trusted local network (ROS_LOCALHOST_ONLY=0 allows external connections but no credentials)

**Configuration:**
- YAML file with sensible defaults
- All parameters can be overridden via launch arguments or ROS parameter server
- No environment variables; config is self-contained in `fc_config.yaml`
