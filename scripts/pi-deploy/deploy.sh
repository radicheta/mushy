#!/usr/bin/env bash
set -euo pipefail

# Configuration
PI_HOST="${PI_HOST:-172.16.10.5}"  # wg0 IP per memory feedback_ssh_tailscale; override via env if a future host alias is added to ~/.ssh/config
PI_USER="${PI_USER:-ubuntu}"
PI_WS="/home/${PI_USER}/mushroom_farm_ws"
PI_REPO="${PI_WS}/mushy-repo"
BRANCH="${BRANCH:-fc1/prod}"

echo "=== Deploying fc_core to ${PI_HOST} (branch: ${BRANCH}) ==="

# Step 1: Make the checkout MATCH the branch.
# Not `git pull`: fc1/prod gets force-pushed (main->prod syncs rewrite it), and
# a pull is then a non-fast-forward merge that conflicts in fc_controller.py,
# aborts here at 1/3, and leaves the Pi on a conflicted tree still running the
# OLD build -- the chamber keeps being controlled, so nothing alarms. MUSHY-117.
echo "[1/3] Syncing checkout to ${BRANCH}..."
ssh "${PI_USER}@${PI_HOST}" "
  set -e
  cd ${PI_REPO}
  if [ -n \"\$(git status --porcelain)\" ]; then
    echo '  ABORT: working tree is dirty -- reset --hard would discard it.'
    git status --short
    exit 1
  fi
  echo \"  before: \$(git rev-parse --short HEAD)\"
  git fetch -q origin
  git checkout -q ${BRANCH}
  git reset -q --hard origin/${BRANCH}
  echo \"  after:  \$(git rev-parse --short HEAD) \$(git log -1 --format=%s)\"
"

# Step 2: Build on Pi
echo "[2/3] Building on Pi..."
ssh "${PI_USER}@${PI_HOST}" "cd ${PI_WS} && source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_msgs fc_core"

# Step 3: Restart service
echo "[3/3] Restarting fc-core service..."
ssh "${PI_USER}@${PI_HOST}" "sudo systemctl restart fc-core"

echo "=== Deploy complete. Check status: ssh ${PI_HOST} 'sudo systemctl status fc-core' ==="
