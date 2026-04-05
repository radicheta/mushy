# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build System

This is a ROS2 Jazzy workspace for a mushroom farm control system. The workspace uses colcon for building:

```bash
# Build all packages
colcon build

# Build specific package
colcon build --packages-select fc_core

# Build with symlink install (for Python development)
colcon build --symlink-install
```

## Environment Setup

Source the ROS2 environment and workspace:
```bash
source /opt/ros/jazzy/setup.bash
source ~/mushroom_farm_ws/install/setup.bash
# Or use the provided script:
source setup.sh
```

Key environment variables:
- `ROS_DOMAIN_ID=69` - Network isolation for multi-robot systems
- `ROS_LOCALHOST_ONLY=0` - Allows external ROS connections

## Development Commands

### Testing
```bash
# Run package tests
colcon test --packages-select fc_core
pytest src/chambers/fc-core/fc_core/test/
```

### Linting
```bash
# Python linting for ROS packages
ament_flake8 src/chambers/fc-core/
ament_pep257 src/chambers/fc-core/
```

### Running Services
```bash
# Launch fruiting chamber system
ros2 launch fc_core fc.launch.py

# Run individual nodes
ros2 run fc_core fc_controller
ros2 run fc_core fc_sensors
ros2 run fc_core fc_display

# Docker services
docker-compose up -d
docker-compose up simulation  # For simulation with GUI
```

## Architecture Overview

### Core Components

**ROS2 Packages:**
- `fc_core` - Fruiting chamber control (sensors, actuators, environmental control)
- `mission_control_bridge` - Bridge between OpenMCT frontend and ROS backend

**Docker Services:**
- `ros-core` - ROS2 daemon and core services
- `simulation` - Gazebo simulation environment with GPU support
- `openmct` - Web-based mission control interface (port 8080)
- `bridge` - WebSocket bridge connecting OpenMCT to ROS
- `timescale` - TimescaleDB for telemetry storage

### Hardware Integration

The system supports both simulation and real hardware modes controlled by the `simulation_mode` parameter in `fc_config.yaml`:

**Real Hardware:**
- DHT22 sensors on GPIO pins for temperature/humidity
- Hardware PWM for fan control
- GPIO pins for humidifier and light control
- Raspberry Pi GPIO library integration

**Simulation Mode:**
- Software simulation of all hardware interactions
- Compatible with development environments without GPIO access

### Configuration

Primary configuration in `src/chambers/fc-core/config/fc_config.yaml`:
- Environmental targets (temperature, humidity, lighting schedule)
- Hardware pin assignments
- Control parameters and tolerances
- Timing intervals

### Network Architecture

ROS2 topics for fruiting chamber:
- `fc1/temperature` - Temperature sensor data
- `fc1/humidity` - Humidity sensor data
- `fc1/co2` - CO2 sensor data
- `fc1/actuators/humidifier` - Humidifier state
- Internal control loop handles actuator commands

Docker networks:
- `ros-net` - Internal ROS communication
- `frontend-net` - Web interface and database access

## Development Workflow

1. **Local Development:** Use simulation mode for testing without hardware
2. **Package Testing:** Build and test individual ROS packages with colcon
3. **Integration Testing:** Use docker-compose for full system testing
4. **Hardware Deployment:** Switch simulation_mode to false in config