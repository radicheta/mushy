# Testing Patterns

**Analysis Date:** 2026-03-28

## Test Framework

**Runner:**
- pytest (Python)
- Config: No explicit pytest.ini or setup.cfg found; configured via `setup.py` `tests_require=['pytest']`
- Test dependencies declared in `package.xml`: `python3-pytest` at `src/chambers/fc-core/package.xml`

**Assertion Library:**
- pytest built-in assertions (implicit through test functions)
- pytest fixtures used for setup/teardown

**Run Commands:**
```bash
colcon test --packages-select fc_core                      # Run package tests via colcon
pytest src/chambers/fc-core/fc_core/test/               # Run tests directly with pytest
ament_flake8 src/chambers/fc-core/                       # Linting (test dependency)
ament_pep257 src/chambers/fc-core/                       # Docstring linting (test dependency)
```

## Test File Organization

**Location:**
- Co-located with source: `src/chambers/fc-core/fc_core/test/test_controller.py` alongside source in `fc_core/` directory
- Pattern: `fc_core/test/test_<module>.py` structure

**Naming:**
- Test files: `test_controller.py`
- Test functions: `test_<feature>()` pattern (e.g., `test_controller_initialization`, `test_temperature_control`, `test_humidity_control`, `test_light_control`)

**Structure:**
```
src/chambers/fc-core/
├── fc_core/
│   ├── fc_controller.py
│   ├── fc_sensors.py
│   ├── fc_display.py
│   ├── fc_telemetry.py
│   └── test/
│       └── test_controller.py
```

## Test Structure

**Suite Organization:**
```python
# From test_controller.py - fixture pattern
@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()

def test_controller_initialization(ros_context):
    node = FruitingChamberController()
    assert node is not None
    node.destroy_node()
```

**Patterns:**
- **Setup:** ROS context initialization via fixture `ros_context` - calls `rclpy.init()` before tests
- **Teardown:** Explicit node cleanup with `node.destroy_node()` after each test; ROS shutdown in fixture teardown
- **Assertion:** Direct assert statements: `assert node is not None`, `assert node.fan_pwm.get_duty_cycle() == ...`
- **Fixture scope:** Function-level (default), provides fresh ROS context per test

## Mocking

**Framework:** unittest.mock (Python standard library)

**Patterns:**
```python
# From test_controller.py lines 86-93
from unittest.mock import patch

with patch('datetime.datetime') as mock_datetime:
    mock_datetime.now.return_value.hour = 10
    assert node.should_light_be_on() == True
```

**What to Mock:**
- Time-dependent functions: Use `patch('datetime.datetime')` to control current hour for light cycle testing
- Hardware would be mocked via simulation_mode in actual hardware tests

**What NOT to Mock:**
- ROS2 node initialization - let actual ROS context run
- Message creation - use real `Temperature()` and `RelativeHumidity()` objects
- Internal node state access - tests call actual methods like `control_loop()`, `temperature_callback()`

## Fixtures and Factories

**Test Data:**
```python
# From test_controller.py - message creation
temp_msg = Temperature()
temp_msg.temperature = node.get_parameter('target_temp').value - 2.0
node.temperature_callback(temp_msg)

humidity_msg = RelativeHumidity()
humidity_msg.relative_humidity = node.get_parameter('target_humidity').value
node.humidity_callback(humidity_msg)
```

**Location:**
- Test fixtures defined at top of test file: `ros_context` fixture at lines 9-13
- Test data created inline in test functions (no factory pattern currently)
- ROS messages constructed directly where needed

## Coverage

**Requirements:** None enforced (no coverage configuration found)

**View Coverage:**
```bash
# No explicit coverage tool configured
# Would need to install pytest-cov and run:
pytest --cov=fc_core src/chambers/fc-core/fc_core/test/
```

## Test Types

**Unit Tests:**
- Scope: Individual node methods and control logic
- Approach: Isolate functionality, test state changes
- Examples: `test_temperature_control()` tests fan speed adjustment, `test_humidity_control()` tests humidifier state, `test_light_control()` tests light scheduling
- See `src/chambers/fc-core/fc_core/test/test_controller.py` lines 15-95

**Integration Tests:**
- Not currently implemented
- Would test multiple nodes communicating via ROS2 topics
- Could test sensor publisher → controller subscriber → actuator output flow

**E2E Tests:**
- Not implemented
- Framework: Could use docker-compose as per CLAUDE.md for full system test with simulation mode
- Orchestrated via `docker-compose up simulation` for Gazebo-based simulation

## Common Patterns

**Node Initialization Testing:**
```python
def test_controller_initialization(ros_context):
    node = FruitingChamberController()
    assert node is not None
    node.destroy_node()
```
- Creates node, asserts existence, cleans up
- ROS context handles init/shutdown around test

**Sensor Callback Testing:**
```python
temp_msg = Temperature()
temp_msg.temperature = node.get_parameter('target_temp').value - 2.0
node.temperature_callback(temp_msg)
node.control_loop()
```
- Manually create message
- Call callback directly to simulate sensor data
- Run control logic to verify response

**State Assertion:**
```python
assert node.fan_pwm.get_duty_cycle() == node.get_parameter('min_fan_speed').value
assert node.humidifier_pin == 1  # ON state
assert node.humidifier_pin == 0  # OFF state
```
- Verify internal state via getter methods
- Check pin values directly when in simulation mode

**Time-Based Testing:**
```python
with patch('datetime.datetime') as mock_datetime:
    mock_datetime.now.return_value.hour = 10
    assert node.should_light_be_on() == True
```
- Mock datetime to test hour-based light scheduling
- Verify logic at specific times without waiting

## Known Test Gaps

**Sensor Module (`fc_sensors.py`):**
- No tests exist (only `test_controller.py` present)
- `read_sensors()` not tested for DHT reading or simulation noise injection
- RuntimeError handling not exercised

**Display Module (`fc_display.py`):**
- No tests

**Telemetry Module (`fc_telemetry.py`):**
- No tests
- WebSocket server and async patterns not tested

**Bridge (`mission_control_bridge/`):**
- No tests found in codebase
- Node.js WebSocket communication not tested

**Integration Scenarios:**
- Topic-based communication between nodes not tested
- Data flow from sensors → controller → actuators not tested end-to-end

---

*Testing analysis: 2026-03-28*
