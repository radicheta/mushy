#!/usr/bin/env bash
set -euo pipefail

# Configuration
PI_HOST="${PI_HOST:-172.16.10.5}"  # wg0 IP per memory feedback_ssh_tailscale; override via env if a future host alias is added to ~/.ssh/config
PI_USER="${PI_USER:-ubuntu}"
PI_WS="/home/${PI_USER}/mushroom_farm_ws"
PI_REPO="${PI_WS}/mushy-repo"
BRANCH="${BRANCH:-fc1/prod}"

echo "=== Deploying fc_core to ${PI_HOST} (branch: ${BRANCH}) ==="

# Step 0: Report drift between the repo's unit files and the live ones.
# deploy.sh deploys CODE, not units: it syncs the checkout, builds, and restarts.
# Nothing here installs a .service file, so editing scripts/pi-deploy/*.service
# and running a deploy reports success while changing nothing on the Pi. That
# silence is the bug -- MUSHY-117's fix needed a manual scp nobody would guess.
#
# This only WARNS. It deliberately does not install: fc-system-sync.service
# installs netplan and /etc/cyclonedds.xml, so auto-syncing units would rewrite
# the chamber's network and DDS transport as a side effect of a code deploy.
# Installing a unit stays a deliberate, separately-reviewed act.
echo "[0/3] Checking systemd unit drift (informational)..."
for unit in fc-core.service fc-update.service fc-system-sync.service; do
  live=$(ssh "${PI_USER}@${PI_HOST}" "cat /etc/systemd/system/${unit} 2>/dev/null" || true)
  if [ -z "${live}" ]; then
    echo "  ${unit}: not installed on the Pi"
  elif [ "${live}" = "$(cat "$(dirname "$0")/${unit}")" ]; then
    echo "  ${unit}: in sync"
  else
    echo "  ${unit}: *** DRIFTED *** repo and Pi differ -- this deploy will NOT reconcile it."
    echo "      diff:    ssh ${PI_USER}@${PI_HOST} cat /etc/systemd/system/${unit} | diff - scripts/pi-deploy/${unit}"
    echo "      install: scp scripts/pi-deploy/${unit} ... && sudo install -m 644 ... && sudo systemctl daemon-reload"
  fi
done
echo

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
