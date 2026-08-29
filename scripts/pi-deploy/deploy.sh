#!/usr/bin/env bash
set -euo pipefail

# Configuration
PI_HOST="${PI_HOST:-172.16.10.5}"  # wg0 IP per memory feedback_ssh_tailscale; override via env if a future host alias is added to ~/.ssh/config
PI_USER="${PI_USER:-ubuntu}"
PI_WS="/home/${PI_USER}/mushroom_farm_ws"
PI_REPO="${PI_WS}/mushy-repo"
BRANCH="${BRANCH:-fc1/prod}"

echo "=== Deploying fc_core to ${PI_HOST} (branch: ${BRANCH}) ==="

# Step 0: Reconcile the repo's unit files onto the Pi.
# deploy.sh used to deploy CODE but not units: it synced the checkout, built,
# and restarted. Nothing installed a .service file, so editing
# scripts/pi-deploy/*.service and running a deploy reported success while
# changing nothing on the Pi, and you found out at the next boot. That silence
# was the bug -- MUSHY-117's fix needed a manual scp nobody would guess, and
# fc-system-sync.service was left 36 lines stale for months (MUSHY-119).
#
# Installing a unit FILE executes nothing: it is a write plus daemon-reload.
# fc-core.service takes effect at step 3's restart; the other two take effect at
# the next boot. fc-system-sync in particular only acts on a real difference --
# every file it stages is cmp-guarded -- so a unit landing here cannot rewrite
# netplan or /etc/cyclonedds.xml as a side effect of shipping Python. Nothing is
# restarted here, deliberately: restarting fc-system-sync is what would run
# netplan generate and wpa_cli reconfigure on the box whose only link is wifi.
#
# Units are read from origin/${BRANCH}, NOT from the local working tree: step 1
# deploys that branch, and a checkout sitting on main would otherwise install
# main's units next to fc1/prod's code -- the same "reports one thing, does
# another" failure this step exists to kill.
echo "[0/3] Reconciling systemd units (from origin/${BRANCH})..."
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
git -C "${REPO_ROOT}" fetch -q origin
UNITS_CHANGED=0
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT
for unit in fc-core.service fc-update.service fc-system-sync.service; do
  if ! git -C "${REPO_ROOT}" show "origin/${BRANCH}:scripts/pi-deploy/${unit}" > "${STAGE}/${unit}" 2>/dev/null; then
    echo "  ${unit}: not present on origin/${BRANCH} -- skipping"
    continue
  fi
  live=$(ssh "${PI_USER}@${PI_HOST}" "cat /etc/systemd/system/${unit} 2>/dev/null" || true)
  if [ "${live}" = "$(cat "${STAGE}/${unit}")" ]; then
    echo "  ${unit}: in sync"
    continue
  fi
  if [ -z "${live}" ]; then
    echo "  ${unit}: not installed on the Pi -- installing"
  else
    echo "  ${unit}: drifted -- installing origin/${BRANCH}'s copy (backup kept on the Pi)"
  fi
  scp -q "${STAGE}/${unit}" "${PI_USER}@${PI_HOST}:/tmp/${unit}"
  ssh "${PI_USER}@${PI_HOST}" "
    set -e
    if [ -f /etc/systemd/system/${unit} ]; then
      sudo cp -a /etc/systemd/system/${unit} /root/${unit}.bak-\$(date +%Y%m%d-%H%M%S)
    fi
    sudo install -m 644 -o root -g root /tmp/${unit} /etc/systemd/system/${unit}
    rm -f /tmp/${unit}
  "
  UNITS_CHANGED=1
done
if [ "${UNITS_CHANGED}" = "1" ]; then
  ssh "${PI_USER}@${PI_HOST}" "sudo systemctl daemon-reload"
  echo "  daemon-reload done. fc-core picks its unit up at step 3;"
  echo "  fc-update / fc-system-sync take effect at the next boot."
fi
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
