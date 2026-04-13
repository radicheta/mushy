#!/usr/bin/env bash
set -euo pipefail

# Configuration
PI_HOST="${PI_HOST:-fc1-ts}"
PI_USER="${PI_USER:-ubuntu}"
PI_WS="/home/${PI_USER}/mushroom_farm_ws"
PI_REPO="${PI_WS}/mushy-repo"
BRANCH="${BRANCH:-fc1/prod}"

echo "=== Deploying fc_core to ${PI_HOST} (branch: ${BRANCH}) ==="

# Step 1: Pull latest from git
echo "[1/3] Pulling latest code..."
ssh "${PI_USER}@${PI_HOST}" "cd ${PI_REPO} && git fetch origin && git checkout ${BRANCH} && git pull origin ${BRANCH}"

# Step 2: Build on Pi
echo "[2/3] Building on Pi..."
ssh "${PI_USER}@${PI_HOST}" "cd ${PI_WS} && source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_core"

# Step 3: Restart service
echo "[3/3] Restarting fc-core service..."
ssh "${PI_USER}@${PI_HOST}" "sudo systemctl restart fc-core"

echo "=== Deploy complete. Check status: ssh ${PI_HOST} 'sudo systemctl status fc-core' ==="
