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

The Pi owns a clone of the main repo at `~/mushroom_farm_ws/mushy-repo/`
that tracks the `fc1/prod` branch — deploys fast-forward this checkout
rather than rsync'ing source trees. The colcon workspace is
`~/mushroom_farm_ws/`, and `~/mushroom_farm_ws/src` is a symlink into
`mushy-repo/src`, so a single `colcon build` from the workspace root
picks up all packages from the live checkout.

Bootstrap a replacement Pi:

```bash
mkdir -p ~/mushroom_farm_ws
cd ~/mushroom_farm_ws
git clone <repo-url> mushy-repo
( cd mushy-repo && git checkout fc1/prod )
ln -s mushy-repo/src src
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

Deploy is git-based. Commit and push to `fc1/prod`, then run one command
from the workstation:

```bash
git checkout fc1/prod
git merge --ff-only milestone/fc1-humidity-mvp   # or cherry-pick
git push origin fc1/prod
./scripts/pi-deploy/deploy.sh
```

`deploy.sh` ssh'es into the Pi and:

1. `git fetch && git checkout fc1/prod && git pull origin fc1/prod` in `~/mushroom_farm_ws/mushy-repo/`
2. Rebuilds the `fc_core` package on the Pi with colcon
3. Restarts the `fc-core` systemd service

The Pi also runs an `fc-update.service` systemd oneshot (see
`scripts/pi-deploy/fc-update.service`) that pulls `fc1/prod` before
`fc-core.service` starts at boot — so a reboot is an alternative way to
pick up the latest committed-and-pushed code, no ssh required.

Override defaults with environment variables if needed:

```bash
PI_HOST=fc1-ts PI_USER=ubuntu BRANCH=fc1/prod ./scripts/pi-deploy/deploy.sh
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

- `sensor_simulation_mode: false` — must be `false` for real hardware (SHT30 over I2C)
- `actuator_simulation_mode: false` — must be `false` to drive GPIO for the humidifier SSR
- `sht30_i2c_address: 0x44` — SHT30 humidity/temperature sensor
- `humidifier_pin: 27` — GPIO27 for the humidifier SSR
- `target_humidity: 0.80` — 80% setpoint
- `humidity_tolerance: 0.05` — ±5% deadband (humidifier on <75%, off >85%)
- `min_dwell_time: 180.0` — seconds, minimum between humidifier toggles (3 min)
- `ROS_DOMAIN_ID=69` — set in the systemd service; must match workstation

Edit, commit to `fc1/prod`, push, and run `deploy.sh` — the config file
is part of the git checkout the Pi pulls, so it ships with the code.
