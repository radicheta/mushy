#!/usr/bin/env bash
# MUSHY-150: 24 h open-loop duty probe. The excitation five months of
# closed-loop operation cannot provide.
#
# WHY: in closed loop duty is not an independent input -- the controller raises
# duty BECAUSE RH fell, so cause and effect are not separable. Every structure
# comparison on MUSHY-150 was fitted through that confound. And fitting on the
# forced cycles alone failed: 3 cycles are only 7.7 h and every one of them
# visits just TWO duty levels, 0 and 1. Nothing in five months identifies what
# the chamber does at duty 0.35.
#
# DESIGN (Santi 2026-09-01):
#   * 1 h holds at random duty, 5 min ramps between them -- identifies LEVELS.
#     1 h is ~25 dead times, so every level fully settles.
#   * interleaved blocks of HARD steps -- identifies DEAD TIME and the fast
#     dynamics. A 5 min ramp is longer than the ~140 s dead time, so during a
#     ramp the input is still moving throughout the delay and the dead time is
#     smeared out. Ramps alone would repeat the corpus's own failure.
#   * INTERLEAVED, not one block of each: otherwise "hard steps" would be
#     confounded with whatever time of day they happened to run in, and the
#     whole point of 24 h is to span the diurnal temperature cycle.
#
# SAFETY. Three independent layers, because this runs unattended on a live grow:
#   1. RH floor/ceiling with hysteresis, checked every 20 s. Overrides the
#      schedule; the schedule does not resume until RH is back inside.
#   2. The Phase 31 experiment TTL. If this script dies or ssh drops, the
#      controller reverts to the prior mode on its own. The TTL is the deadman.
#   3. EXIT trap restores modes.force-condensation.force_duty. Without it the
#      mode stays redefined at whatever duty was last commanded, and the NEXT
#      person to run a genuine force-condensation gets that value instead of 1.0.
#
# DUTY RANGE. The 1 h holds sample [0, DUTY_MAX], not [0, 1]. Corpus mean duty
# is 0.137, i.e. the chamber holds steady at ~14%, so an hour at duty 0.6 is
# ~4x the water it needs and RH pins against the ceiling. The guard would then
# spend the hour overriding -- and the guard is CLOSED LOOP, so those minutes
# would be exactly the confounded data this experiment exists to avoid. The
# extremes still get visited: the hard-step blocks use full 0 and full 1, where
# the dwell is short enough (10-20 min) that neither rail is reached.
#
#   ./duty-probe.sh <label> [hours] [rh_floor] [rh_ceiling] [seed] [duty_max]
set -u
LABEL="${1:?label required}" ; HOURS="${2:-24}"
RH_FLOOR="${3:-0.75}"       ; RH_CEIL="${4:-0.98}" ; SEED="${5:-1}"
DUTY_MAX="${6:-0.35}"       # see DUTY RANGE above; ~2.5x the 0.137 equilibrium
FLOOR_CLEAR=$(awk "BEGIN{print $RH_FLOOR + 0.02}")   # hysteresis, avoid chatter
CEIL_CLEAR=$(awk "BEGIN{print $RH_CEIL - 0.02}")
MODE=force-condensation      # reused as a generic forced-duty mode; see EXIT trap
CHUNK=110                    # service cap is 120 min; re-fire before it expires
LOG=/home/ubuntu/duty-probe.log
CSV=/home/ubuntu/duty-probe-$LABEL.csv

set +u
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
setd(){ ros2 param set /fc_controller "modes.$MODE.force_duty" "$1" >/dev/null 2>&1
        echo "$(ts),$1,$2" >>"$CSV"; }
fire(){ ros2 service call /start_experiment fc_msgs/srv/StartExperiment \
          "{experiment_name: $MODE, duration_minutes: $CHUNK}" >>"$LOG" 2>&1; }
stop(){ ros2 service call /cancel_experiment fc_msgs/srv/CancelExperiment "{}" >>"$LOG" 2>&1; }
lt()  { awk "BEGIN{exit !($1 < $2)}"; }
gt()  { awk "BEGIN{exit !($1 > $2)}"; }

ORIG=$(ros2 param get /fc_controller "modes.$MODE.force_duty" 2>/dev/null | awk '{print $NF}')
[ -n "$ORIG" ] || { echo "FATAL: cannot read modes.$MODE.force_duty"; exit 1; }
echo "$ORIG" > /home/ubuntu/duty-probe-restore.txt   # recovery breadcrumb if we die hard

cleanup() {
  say "CLEANUP restoring modes.$MODE.force_duty=$ORIG and cancelling"
  ros2 param set /fc_controller "modes.$MODE.force_duty" "$ORIG" >/dev/null 2>&1
  stop
  say "CLEANUP done"
}
trap cleanup EXIT INT TERM

EXP_AT=0
keepalive() {   # re-fire the forced experiment before its TTL runs out
  local now; now=$(date +%s)
  if [ $((now - EXP_AT)) -ge $((CHUNK * 60 - 300)) ]; then
    fire; EXP_AT=$now; say "experiment (re)fired for ${CHUNK}min"
  fi
}

# guard: returns 0 if the schedule may proceed, 1 if we are overriding
guard() {
  local r; r=$(rh); [ -n "$r" ] || return 0        # no reading: hold course, TTL still protects
  if lt "$r" "$RH_FLOOR"; then
    say "FLOOR BREACH rh=$r < $RH_FLOOR -- forcing duty 1.0"
    setd 1.0 floor-override
    while r=$(rh); [ -n "$r" ] && lt "$r" "$FLOOR_CLEAR"; do keepalive; sleep 20; done
    say "floor cleared rh=$r"; return 1
  fi
  if gt "$r" "$RH_CEIL"; then
    say "CEILING BREACH rh=$r > $RH_CEIL -- forcing duty 0.0"
    setd 0.0 ceiling-override
    while r=$(rh); [ -n "$r" ] && gt "$r" "$CEIL_CLEAR"; do keepalive; sleep 20; done
    say "ceiling cleared rh=$r"; return 1
  fi
  return 0
}

hold() {        # hold $1 for $2 minutes, re-asserting after any override
  local d=$1 mins=$2 end; end=$(( $(date +%s) + mins * 60 ))
  setd "$d" "hold"
  say "HOLD duty=$d for ${mins}min"
  while [ "$(date +%s)" -lt "$end" ]; do
    keepalive
    guard || setd "$d" "hold-resume"
    sleep 20
  done
}

ramp() {        # linear $1 -> $2 over $3 minutes
  local a=$1 b=$2 mins=$3 n i v
  n=$(( mins * 4 ))                                  # a step every 15 s
  say "RAMP $a -> $b over ${mins}min"
  for i in $(seq 1 "$n"); do
    v=$(awk "BEGIN{printf \"%.3f\", $a + ($b - $a) * $i / $n}")
    setd "$v" "ramp"
    keepalive; guard || true
    sleep 15
  done
}

steps() {       # hard-transition block: no ramps. $1 = block minutes
  local left=$1 d dwell
  say "HARD-STEP BLOCK ${left}min"
  while [ "$left" -gt 0 ]; do
    d=$(( RANDOM % 2 ))                              # full off / full on: biggest edge
    dwell=$(( 10 + (RANDOM % 3) * 5 ))               # 10/15/20 min
    [ "$dwell" -gt "$left" ] && dwell=$left
    hold "$d.0" "$dwell"
    left=$(( left - dwell ))
  done
}

RANDOM=$SEED
say "START ${HOURS}h floor=$RH_FLOOR ceil=$RH_CEIL duty_max=$DUTY_MAX seed=$SEED orig_force_duty=$ORIG"
echo "iso,duty,phase" > "$CSV"
fire; EXP_AT=$(date +%s)
END=$(( $(date +%s) + HOURS * 3600 ))
PREV=0.0
while [ "$(date +%s)" -lt "$END" ]; do
  # one 4 h super-block: 3 x (1 h level hold) then 1 h of hard steps.
  for _ in 1 2 3; do
    [ "$(date +%s)" -lt "$END" ] || break
    NEXT=$(awk "BEGIN{srand($RANDOM); printf \"%.2f\", rand() * $DUTY_MAX}")
    ramp "$PREV" "$NEXT" 5
    hold "$NEXT" 55
    PREV=$NEXT
  done
  [ "$(date +%s)" -lt "$END" ] || break
  steps 60
  PREV=$(tail -1 "$CSV" | cut -d, -f2)
done
say "FINISHED"
