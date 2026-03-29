#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
source /opt/bridge/install/setup.bash

# Fake sensors: only run if FAKE_SENSORS=1 (e.g. when Pi is unavailable)
if [ "${FAKE_SENSORS:-0}" = "1" ]; then
    echo "[bridge] FAKE_SENSORS=1 — starting simulated sensor publisher"
    python3 -m mission_control_bridge.fake_sensors &
else
    echo "[bridge] Connecting to real ROS2 topics on domain ${ROS_DOMAIN_ID:-?}"
fi

exec ros2 launch /opt/bridge/launch/bridge.launch.py
