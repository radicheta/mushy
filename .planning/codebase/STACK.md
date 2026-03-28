# Technology Stack

**Analysis Date:** 2026-03-28

## Languages

**Primary:**
- Python 3 - ROS2 node implementations for fruiting chamber control and bridge services
- JavaScript (Node.js) - Mission control bridge service and OpenMCT frontend plugins

**Secondary:**
- Bash - Docker entrypoints and launch scripts

## Runtime

**Environment:**
- ROS2 Jazzy (Ubuntu 24.04 base)
- Node.js - for mission control bridge and OpenMCT

**Package Manager:**
- pip3 - Python package management
- npm - Node.js package management
- colcon - ROS2 workspace build tool
- ament_python - ROS2 Python build system

## Frameworks

**Core:**
- ROS2 Jazzy (`ros:jazzy-ros-core`) - Robotic Operating System for distributed sensor and actuator control
- rclpy - ROS2 Python client library for node creation and communication

**Web/Frontend:**
- OpenMCT (NASA) - Web-based mission control interface for telemetry visualization
- Express.js (implicit via npm install) - Web framework for serving OpenMCT

**Testing:**
- pytest - Python unit testing framework
- ament_flake8 - ROS2 Python linting
- ament_pep257 - ROS2 Python docstring style checker

**Build/Dev:**
- colcon - Workspace build orchestrator for ROS2 packages
- python3-colcon-common-extensions - Extended colcon functionality
- rosdep - ROS dependency manager

## Key Dependencies

**Critical:**
- `rclpy` - ROS2 Python client library for node communication and subscriptions/publications
- `sensor_msgs` - Standard ROS2 message types for temperature and humidity data
- `std_msgs` - Standard ROS2 message types
- `adafruit-circuitpython-dht` v3.7+ - DHT22 temperature/humidity sensor driver
- `RPi.GPIO` - Raspberry Pi GPIO control for hardware integration
- `rpi_hardware_pwm` - Raspberry Pi hardware PWM for fan speed control
- `websockets` v8.16.0+ - Python WebSocket support for real-time telemetry streaming
- `rclnodejs` v0.3.0+ - ROS2 Node.js client library for JavaScript bridge
- `ws` v8.16.0+ - Node.js WebSocket server implementation

**Infrastructure:**
- `python3-rosdep` - Dependency resolution for ROS packages
- `python3-vcstool` - Version control tool management for ROS
- `rosbridge_server` - RESTful and WebSocket interface to ROS topics (included in fc-core bridge Dockerfile)

**Database/Storage:**
- TimescaleDB (postgres:14) - Time-series database for telemetry storage (via Docker image `timescale/timescaledb:latest-pg14`)

## Configuration

**Environment:**
- ROS2 environment sourced from `/opt/ros/jazzy/setup.bash`
- Workspace environment sourced from `install/setup.bash`
- ROS_DOMAIN_ID environment variable for network isolation (set to 69 in docker-compose)
- ROS_LOCALHOST_ONLY environment variable for external ROS connectivity (set to 0 for docker environment)

**Build:**
- `fc_config.yaml` - Main configuration file for fruiting chamber parameters (target temperature, humidity, control parameters, GPIO pin assignments)
- Located at: `src/chambers/fc-core/config/fc_config.yaml`
- Launch configuration in: `src/chambers/fc-core/launch/fc.launch.py`

## Platform Requirements

**Development:**
- Linux with Docker and Docker Compose support
- GPU support optional (nvidia runtime configured for Gazebo simulation in docker-compose)
- Python 3.x (specific version in `.python-version`: "mushroom_farm")
- Node.js with npm

**Production/Deployment:**
- Raspberry Pi (for GPIO hardware control) or simulation mode for development
- Docker containerization for all services
- Multiple networked containers (ROS network, frontend network)

## Architecture Notes

**Service Topology:**
- `ros-core` - ROS2 daemon and core services (base container)
- `fc-core` - Fruiting chamber control nodes (sensors, controller, display)
- `simulation` - Gazebo simulation environment with GPU support
- `openmct` - NASA OpenMCT frontend (port 8080)
- `bridge` - Node.js WebSocket bridge connecting OpenMCT to ROS topics (port 8081)
- `timescale` - PostgreSQL-compatible time-series database for telemetry archival

**Network Configuration:**
- `ros-net` - Docker network for ROS2 node communication
- `frontend-net` - Docker network for OpenMCT, bridge, and database

---

*Stack analysis: 2026-03-28*
