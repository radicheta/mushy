#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
# Phase 31: fc_msgs overlay for StartExperiment/CancelExperiment srv types
source /opt/fc_msgs_ws/install/setup.bash

# RMW for CycloneDDS (peer discovery over WireGuard)
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

echo "[bridge] Starting Node.js bridge on port 8081"
exec node /opt/bridge/src/index.js
