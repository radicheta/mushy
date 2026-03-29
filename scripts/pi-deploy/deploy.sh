#!/usr/bin/env bash
set -euo pipefail

# Configuration
PI_HOST="${PI_HOST:-fc1}"
PI_USER="${PI_USER:-ubuntu}"
PI_WS="/home/${PI_USER}/mushroom_farm_ws"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== Deploying fc_core to ${PI_HOST} ==="

# Step 1: rsync source to Pi workspace
echo "[1/4] Syncing source code..."
rsync -avz --delete \
  --exclude='.git' \
  --exclude='build/' \
  --exclude='install/' \
  --exclude='log/' \
  --exclude='__pycache__' \
  "${REPO_ROOT}/src/" \
  "${PI_USER}@${PI_HOST}:${PI_WS}/src/"

# Step 2: rsync config
echo "[2/4] Syncing config..."
rsync -avz \
  "${REPO_ROOT}/src/chambers/fc-core/config/" \
  "${PI_USER}@${PI_HOST}:${PI_WS}/src/chambers/fc-core/config/"

# Step 3: Build on Pi
echo "[3/4] Building on Pi..."
ssh "${PI_HOST}" "cd ${PI_WS} && source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_core"

# Step 4: Restart service
echo "[4/4] Restarting fc-core service..."
ssh "${PI_HOST}" "sudo systemctl restart fc-core"

echo "=== Deploy complete. Check status: ssh ${PI_HOST} 'sudo systemctl status fc-core' ==="
