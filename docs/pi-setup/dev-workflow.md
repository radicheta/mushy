# FC-1 Development Workflow

## Prerequisites

- SSH access to Pi configured (see ssh-setup.md)
- ROS2 Jazzy installed on Pi (see ROS2 Installation section below)

## ROS2 Installation on Pi

Run on Pi:

```bash
sudo apt update
sudo apt install -y ros-jazzy-ros-base python3-colcon-common-extensions
echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc
```

Create workspace:

```bash
mkdir -p ~/mushroom_farm_ws/src
cd ~/mushroom_farm_ws
source /opt/ros/jazzy/setup.bash
colcon build
```

## Install systemd Service

From workstation (run once, or after updating the service file):

```bash
scp scripts/pi-deploy/fc-core.service fc1:/tmp/
ssh fc1 "sudo cp /tmp/fc-core.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable fc-core"
```

## Deploy Cycle

One command from workstation repo root:

```bash
./scripts/pi-deploy/deploy.sh
```

This will:

1. rsync source code to Pi (`~/mushroom_farm_ws/src/`)
2. Rebuild the `fc_core` package on Pi using colcon
3. Restart the `fc-core` systemd service

Override defaults with environment variables if needed:

```bash
PI_HOST=fc1 PI_USER=ubuntu ./scripts/pi-deploy/deploy.sh
```

## Observe Logs

Stream service logs from workstation:

```bash
ssh fc1 "journalctl -u fc-core -f"
```

View recent logs without streaming:

```bash
ssh fc1 "journalctl -u fc-core --no-pager -n 50"
```

## ROS2 Topics from Workstation

Requires matching ROS domain — set before running any `ros2` commands:

```bash
export ROS_DOMAIN_ID=69
export ROS_LOCALHOST_ONLY=0
ros2 topic list
ros2 topic echo fc/humidity
ros2 topic echo fc/temperature
```

## Manual Service Operations

```bash
# Start the service
ssh fc1 "sudo systemctl start fc-core"

# Stop the service
ssh fc1 "sudo systemctl stop fc-core"

# Check service status
ssh fc1 "sudo systemctl status fc-core"

# Restart the service
ssh fc1 "sudo systemctl restart fc-core"
```

## Manual Build on Pi

If you need to rebuild without a full deploy:

```bash
ssh fc1 "cd ~/mushroom_farm_ws && source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_core --symlink-install"
```

## Configuration

The primary config file is `src/chambers/fc-core/config/fc_config.yaml`. Key settings:

- `simulation_mode: false` — must be set to `false` for real hardware operation
- `dht_pin: 4` — GPIO pin for DHT22 sensor (GPIO4)
- `target_humidity: 0.85` — 85% humidity setpoint
- `ROS_DOMAIN_ID=69` — set in the systemd service; must match workstation

The deploy script syncs this config file to the Pi automatically.
