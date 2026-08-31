#!/usr/bin/env bash
# MUSHY-150: dry-down / wet-up cycle, to put the chamber in the two regimes
# five months of closed-loop operation never visited.
#
# WHY: the controller only switches the humidifier off when the chamber is
# already humid (drying gap 0.74 g/m3 off vs 2.76 on), so "humidifier off while
# actually drying" has 8 natural cases in 5 months and every candidate model
# fits the humidifier OUT.
#
# The dry-down ends on a CONDITION, not a clock. A fixed hour is not enough
# when the chamber starts wall-loaded from a recent humidification push -- the
# first observed attempt went UP 0.7 points in 15 min with duty at zero, the
# walls still shedding. So: hold off until RH falls to the floor, or the cap.
#
# SAFETY: every phase goes through the Phase 31 forcing-experiment service,
# which carries its own monotonic-clock TTL and auto-reverts to the prior mode.
# If this script dies or the ssh session drops, the controller reverts on its
# own. The TTL is the deadman; the cancels here are only precision. Service cap
# is 120 min per experiment, so a longer hold is chained in chunks.
#
#   ./drywet-cycle.sh <label> [off_max_min] [rh_floor] [rh_stop] [wet_max_min]
set -u
LABEL="${1:?label required}" ; OFF_MAX="${2:-180}" ; RH_FLOOR="${3:-0.85}"
RH_STOP="${4:-0.99}"         ; WET_MAX="${5:-45}"  ; CHUNK=120
LOG=/home/ubuntu/drywet-cycle.log

set +u          # ROS setup.bash reads unset vars; set -u aborts on them
source /opt/ros/jazzy/setup.bash
source /home/ubuntu/mushroom_farm_ws/install/setup.bash
set -u
export ROS_DOMAIN_ID=69 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
       RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///etc/cyclonedds.xml

ts()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
say()  { echo "[$(ts)] $LABEL $*" >>"$LOG"; }
rh()   { ros2 topic echo /fc1/humidity --once --qos-reliability best_effort \
           --qos-durability volatile 2>/dev/null \
         | awk '/^relative_humidity:/{printf "%.4f", $2; exit}'; }
mode() { ros2 param get /fc_controller active_mode 2>/dev/null | awk '{print $NF}'; }
fire() { ros2 service call /start_experiment fc_msgs/srv/StartExperiment \
           "{experiment_name: $1, duration_minutes: $2}" >>"$LOG" 2>&1; }
stop() { ros2 service call /cancel_experiment fc_msgs/srv/CancelExperiment "{}" >>"$LOG" 2>&1; }
le()   { awk "BEGIN{exit !($1 <= $2)}"; }
ge()   { awk "BEGIN{exit !($1 >= $2)}"; }

T0=$(date +%s)
# Elapsed comes from the WALL CLOCK, not from counting 20 s sleeps: each pass
# also spends several seconds in `ros2 topic echo`, which drifted the counter
# ~33% slow on cycle 1 (a labelled "t+45min" was 60 real minutes).
el_min() { echo $(( ($(date +%s) - T0) / 60 )); }

say "BEGIN off_max=${OFF_MAX}min floor=${RH_FLOOR} stop=${RH_STOP} rh=$(rh) mode=$(mode)"
stop                                    # take control of anything in flight
sleep 2

hit=0
while [ "$(el_min)" -lt "$OFF_MAX" ]; do
  n=$(( OFF_MAX - $(el_min) )); [ "$n" -gt "$CHUNK" ] && n=$CHUNK
  say "DRYDOWN chunk ${n}min (elapsed $(el_min)min) rh=$(rh)"
  fire force-evaporation "$n"
  chunk_end=$(( $(date +%s) + n * 60 - 10 ))     # leave the TTL the last word
  while [ "$(date +%s)" -lt "$chunk_end" ] && [ "$(el_min)" -lt "$OFF_MAX" ]; do
    sleep 60; r=$(rh)
    say "  drydown t+$(el_min)min rh=$r T=$(ros2 topic echo /fc1/temperature --once \
         --qos-reliability best_effort --qos-durability volatile 2>/dev/null \
         | awk '/^temperature:/{printf "%.2f", $2; exit}')"
    if [ -n "$r" ] && le "$r" "$RH_FLOOR"; then hit=1; break; fi
  done
  stop; sleep 3
  [ "$hit" = 1 ] && { say "DRYDOWN floor $RH_FLOOR reached at t+$(el_min)min"; break; }
done
say "DRYDOWN end t+$(el_min)min rh=$(rh) mode=$(mode)"

say "WETUP start rh=$(rh)"
fire force-condensation "$WET_MAX"
for ((i=0; i<WET_MAX*3; i++)); do
  sleep 20; r=$(rh); [ -z "$r" ] && continue
  (( i % 3 == 0 )) && say "  wetup t+$((i/3))min rh=$r"
  if ge "$r" "$RH_STOP"; then say "WETUP reached $RH_STOP at rh=$r"; stop; break; fi
done
sleep 5
say "DONE rh=$(rh) mode=$(mode)"
