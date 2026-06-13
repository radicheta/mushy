#!/bin/bash
# Force-condensation capture regime helper (SEED-005 Stage A).
#
# Self-contained for use from `at`/cron/systemd (does NOT rely on ~/.bashrc):
# sources the ROS env + DDS vars explicitly, same as the fc-core service.
#
# Subcommands:
#   fire [N]                     -> start a force-condensation experiment for N min (default 60)
#   capture <run-id> [D]         -> launch the dense capture harness for D min (default 180)
#   session <run-id> [D] [N]     -> capture (D min), wait 30s for baseline, then fire (N min)
#
# All actions are appended to regime.log with a UTC timestamp (paper trail).
set -u

CAP_DIR=/home/ubuntu/condensation-capture
DATA_DIR=/home/ubuntu/condensation-dataset
LOG="$CAP_DIR/regime.log"

source /opt/ros/jazzy/setup.bash
source /home/ubuntu/mushroom_farm_ws/install/setup.bash
export ROS_DOMAIN_ID=69 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
       RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///etc/cyclonedds.xml

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

case "${1:-}" in
  fire)
    N="${2:-60}"
    echo "[$(ts)] fire force-condensation ${N}min" >> "$LOG"
    ros2 service call /start_experiment fc_msgs/srv/StartExperiment \
      "{experiment_name: force-condensation, duration_minutes: $N}" >> "$LOG" 2>&1
    echo "[$(ts)] fire done (rc=$?)" >> "$LOG"
    ;;
  capture)
    RUNID="${2:?run-id required}"
    DUR="${3:-180}"
    echo "[$(ts)] start capture run=$RUNID dur=${DUR}min" >> "$LOG"
    nohup python3 "$CAP_DIR/capture_condensation_dataset.py" \
      --out-dir "$DATA_DIR" --run-id "$RUNID" \
      --duration-min "$DUR" --interval-sec 15 >> "$LOG" 2>&1 &
    echo "[$(ts)] capture launched pid $!" >> "$LOG"
    ;;
  session)
    RUNID="${2:?run-id required}"
    DUR="${3:-180}"
    N="${4:-60}"
    echo "[$(ts)] session start run=$RUNID dur=${DUR} fire=${N}" >> "$LOG"
    "$0" capture "$RUNID" "$DUR"
    sleep 30   # let the harness subscribe + record a pre-force baseline
    "$0" fire "$N"
    ;;
  *)
    echo "usage: $0 {fire [N] | capture <run-id> [dur-min]}" >&2
    exit 2
    ;;
esac
