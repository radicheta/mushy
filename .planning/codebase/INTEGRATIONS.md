# External Integrations

**Analysis Date:** 2026-03-28

## APIs & External Services

**Mission Control:**
- OpenMCT (NASA) - Web-based mission control interface
  - GitHub source: https://github.com/nasa/openmct
  - Cloned and built from source in Docker (see `src/mission-control/frontend/Dockerfile`)
  - Provides UI for telemetry visualization and system control
  - Runs on port 8080

## Data Storage

**Databases:**
- PostgreSQL (TimescaleDB variant)
  - Service: `timescale/timescaledb:latest-pg14`
  - Connection: Configured via docker-compose (port 5432, internal network)
  - Credentials: Default postgres user with password `mysecretpassword` (set in `docker-compose.yml` line 85)
  - Purpose: Time-series storage of telemetry data (temperature, humidity readings)
  - Volume: `timescale-data` for data persistence

**File Storage:**
- Local filesystem only
  - Docker volume mount for TimescaleDB persistence: `timescale-data:/var/lib/postgresql/data`
  - ROS2 workspace files mounted in containers as needed

**Caching:**
- None detected

## Authentication & Identity

**Auth Provider:**
- Custom/None - No explicit authentication layer detected
- ROS2 network isolation via ROS_DOMAIN_ID environment variable (value: 69)
- WebSocket bridge at `ws://localhost:8081` for telemetry (no auth required in current implementation)

## Monitoring & Observability

**Error Tracking:**
- None detected - errors logged to stdout in Docker containers

**Logs:**
- ROS2 logging framework (rclpy logging)
- Docker container logs via `docker logs` command
- All nodes configured with `output='screen'` in launch files for visibility

## CI/CD & Deployment

**Hosting:**
- Docker and Docker Compose - Multi-container orchestration
- Services defined in `docker-compose.yml` (main) and `src/docker-compose.yml` (modular)
- Compatible with Kubernetes via Docker images (not currently deployed to K8s)

**CI Pipeline:**
- None detected in codebase

## Environment Configuration

**Required env vars:**
- `ROS_DOMAIN_ID=69` - Network isolation identifier (prevents ROS message interference)
- `ROS_LOCALHOST_ONLY=0` - Allows external ROS connections across containers

**Optional env vars:**
- `DISPLAY` - X11 display for Gazebo simulation GUI
- `QT_X11_NO_MITSHM=1` - Qt X11 configuration for GUI rendering
- `XDG_RUNTIME_DIR=/run/user/1000` - Runtime directory for user processes
- `NVIDIA_VISIBLE_DEVICES=all` - GPU visibility (simulation container only)
- `NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute,video` - GPU capabilities
- `ROS_CONFIG_FILE` - Path to fc_config.yaml (defaults to package share directory)

**Secrets location:**
- `.env` file present but not read (contains environment configuration)
- PostgreSQL password hardcoded in `docker-compose.yml` (should be externalized to `.env`)
- No other detected secrets management (consider using docker secrets for production)

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## ROS2 Topic Architecture

**Published Topics:**
- `fc/temperature` - Temperature readings (sensor_msgs/msg/Temperature)
  - Published by: `fc_sensors` node
  - Subscribed by: `fc_controller`, `fc_telemetry`, bridge service

- `fc/humidity` - Humidity readings (sensor_msgs/msg/RelativeHumidity)
  - Published by: `fc_sensors` node
  - Subscribed by: `fc_controller`, `fc_telemetry`, bridge service

**WebSocket Endpoints:**
- `ws://localhost:8081` - Mission control bridge WebSocket server
  - Receives: Temperature and humidity telemetry from ROS topics
  - Broadcasts: JSON telemetry packets to connected OpenMCT clients
  - Message format: `{timestamp: ISO8601, temperature: number, humidity: number}`

## Hardware Integration

**Sensor Hardware:**
- DHT22 sensor (temperature and humidity)
  - Python library: `adafruit-circuitpython-dht`
  - GPIO pin: Configurable via `fc_config.yaml` (default: GPIO4)
  - Read interval: Configurable via `sensor_read_interval` parameter (default: 2.0 seconds)

**Actuator Hardware:**
- Fan control via PWM
  - Driver: `rpi_hardware_pwm`
  - PWM channel: Configurable (default: channel 0)
  - Frequency: Configurable (default: 25000 Hz)
  - Speed scaling: Via control loop in `fc_controller`

- Light control via GPIO
  - Library: `RPi.GPIO`
  - GPIO pin: Configurable via `fc_config.yaml` (default: GPIO18)

- Humidifier control via GPIO
  - Library: `RPi.GPIO`
  - GPIO pin: Configurable in hardware setup

**Simulation Mode:**
- All hardware replaced with software simulation when `simulation_mode: true` in config
- Simulated sensor values drift within bounds (±0.1°C, ±0.01 humidity per read)
- No actual GPIO access required in simulation mode

## Configuration Files

**Primary:**
- `src/chambers/fc-core/config/fc_config.yaml` - All fruiting chamber parameters
  - Target temperature, humidity, light hours, tolerances
  - GPIO pin assignments
  - Control parameters (fan speed scaling, PWM frequency)
  - Timing intervals for sensor reads and control updates

## Data Flow Summary

1. **Sensor Node** (`fc_sensors`): Reads DHT22 sensor → publishes `fc/temperature`, `fc/humidity` to ROS
2. **Controller Node** (`fc_controller`): Subscribes to sensor topics → publishes control commands to GPIO/PWM
3. **Telemetry Node** (`fc_telemetry`): Subscribes to sensor topics → streams via WebSocket to mission control
4. **Bridge Node** (Node.js): Translates ROS messages to WebSocket → broadcasts to OpenMCT frontend
5. **OpenMCT Frontend**: Displays real-time telemetry data from WebSocket connection
6. **TimescaleDB**: Receives telemetry data for long-term archival (connection configured but integration not explicitly shown in code)

---

*Integration audit: 2026-03-28*
