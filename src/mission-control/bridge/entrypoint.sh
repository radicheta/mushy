#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
source /opt/bridge/install/setup.bash
python3 -m mission_control_bridge.fake_sensors &
exec ros2 launch /opt/bridge/launch/bridge.launch.py 