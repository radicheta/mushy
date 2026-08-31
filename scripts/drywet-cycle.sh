#!/usr/bin/env bash
# MUSHY-150: dry-down / wet-up cycle, to put the chamber in the two regimes
# five months of closed-loop operation never visited.
#
# WHY: the controller only switches the humidifier off when the chamber is
# already humid (drying gap 0.74 g/m3 OFF vs 2.76 ON), so "humidifier off while
# actually drying" is absent from the corpus -- 8 natural cases in 5 months.
# Every candidate model therefore fits the humidifier OUT. One hour of forced
# off in dry conditions, then full-on to saturation, buys the identification
# data that more months of production would not.
#
# SAFETY: both phases go through the Phase 31 forcing-experiment service, which
# carries its own monotonic-clock TTL and auto-reverts to the prior mode. If
# this script dies, is killed, or the ssh session drops, the controller still
# reverts on its own -- the TTL is the deadman, the cancel is only precision.
#
#   ./drywet-cycle.sh <label> [off_min] [on_max_min] [rh_stop_fraction]
set -u
LABEL="${1:?label required}" ; OFF_MIN="${2:-60}"
ON_MAX="${3:-30}"            ; RH_STOP="${4:-0.99}"
LOG=/home/ubuntu/drywet-cycle.log

set +u          # ROS setup.bash reads unset vars; set -u aborts on them
source /opt/ros/jazzy/setup.bash
source /home/ubuntu/mushroom_farm_ws/install/setup.bash
set -u
export ROS_DOMAIN_ID=69 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
       RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///etc/cyclonedds.xml

ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $LABEL $*" | tee -a "$LOG"; }
rh()  { ros2 topic echo /fc1/humidity --once --qos-reliability best_effort \
          --qos-durability volatile 2>/dev/null \
        | awk '/^relative_humidity:/{printf "%.4f", $2; exit}'; }
fire(){ ros2 service call /start_experiment fc_msgs/srv/StartExperiment \
          "{experiment_name: $1, duration_minutes: $2}" >>"$LOG" 2>&1; }

say "BEGIN off=${OFF_MIN}min on_max=${ON_MAX}min stop=${RH_STOP} rh=$(rh) mode=$(
     ros2 param get /fc_controller active_mode 2>/dev/null | awk '{print $NF}')"

say "DRYDOWN start rh=$(rh)"
fire force-evaporation "$OFF_MIN"
for ((i=0; i<OFF_MIN; i++)); do sleep 60; say "  drydown t+${i}min rh=$(rh)"; done
sleep 30                                   # let the TTL revert land
say "DRYDOWN end rh=$(rh) mode=$(ros2 param get /fc_controller active_mode 2>/dev/null | awk '{print $NF}')"

say "WETUP start rh=$(rh)"
fire force-condensation "$ON_MAX"
for ((i=0; i<ON_MAX*3; i++)); do
  sleep 20
  r=$(rh); [ -z "$r" ] && continue
  (( i % 3 == 0 )) && say "  wetup t+$((i/3))min rh=$r"
  if awk "BEGIN{exit !($r >= $RH_STOP)}"; then
    say "WETUP reached $RH_STOP at rh=$r -- cancelling early"
    ros2 service call /cancel_experiment fc_msgs/srv/CancelExperiment "{}" >>"$LOG" 2>&1
    break
  fi
done
sleep 30
say "DONE rh=$(rh) mode=$(ros2 param get /fc_controller active_mode 2>/dev/null | awk '{print $NF}')"
