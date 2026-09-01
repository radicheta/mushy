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
# DESIGN (Santi 2026-09-01, dwell revised after measuring the drift):
#   * SEGMENTS of 7-15 min at a constant duty, back to back for 24 h.
#     LOWER BOUND ~3x the ~140 s dead time: below that consecutive responses
#     overlap inside the chamber and cannot be attributed to their own step.
#     UPPER BOUND is where thermal drift starts competing with the duty signal.
#     THERE IS NO STEADY STATE to wait for -- the chamber tracks outside
#     temperature and ambient AH, both always moving. Over 60 min T moves
#     1.0-1.3 C and AH_sat ~0.9 g/m3 = ~7 RH points, against a forced dry-down
#     excursion of ~8 points TOTAL, so an hour-long hold measures the weather as
#     much as the humidifier. At 10 min drift is ~1.2 points and duty dominates
#     ~6x. (This replaces the original 1 h holds and the claim that "1 h is ~25
#     dead times so every level fully settles" -- there is nothing to settle to.)
#   * MOSTLY HARD STEPS. A 5 min ramp is longer than the dead time, so during a
#     ramp the input is still moving throughout the delay and the edge that
#     pins the dead time is smeared out. A quarter of the transitions are
#     2 min ramps instead, kept only as a check that the fitted model handles a
#     moving input and not just steps.
#   * Duty and transition style are drawn INDEPENDENTLY PER SEGMENT rather than
#     in blocks, so neither is confounded with time of day -- spanning the
#     diurnal temperature cycle is the whole reason this runs for 24 h.
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
# DUTY RANGE. Two thirds of segments draw uniformly from [0, DUTY_MAX], not
# [0, 1]. Corpus mean duty is 0.137, i.e. the chamber holds steady at ~14%, so a
# long stretch at duty 0.6 is ~4x the water it needs and RH pins against the
# ceiling -- and the guard that then takes over is CLOSED LOOP, producing
# exactly the confounded data this experiment exists to avoid. The other third
# goes to a rail (0.0 or 1.0) for the biggest available edge; at a 7-15 min
# dwell neither rail has time to reach the guard (the 2026-08-31 forced cycle
# needed 45 min at full duty to climb from 85% to 99%).
#
#   ./duty-probe.sh <label> [hours] [rh_floor] [rh_ceiling] [seed] [duty_max]
#
# DRY RUN. `DRYRUN=1 ./duty-probe.sh dry` prints the whole 24 h schedule in a
# second against a virtual clock and touches neither ROS nor the chamber. Run
# it before every real run: this is 24 h of a live grow and the schedule is
# random, so "it looked right last time" is not a check.
set -u
DRYRUN="${DRYRUN:-0}"
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

VCLOCK=$(date +%s)
now() { if [ "$DRYRUN" = 1 ]; then echo "$VCLOCK"; else date +%s; fi; }
nap() { if [ "$DRYRUN" = 1 ]; then VCLOCK=$((VCLOCK + $1)); else sleep "$1"; fi; }
ts()  { if [ "$DRYRUN" = 1 ]; then date -u -d "@$VCLOCK" +%Y-%m-%dT%H:%M:%SZ
        else date -u +%Y-%m-%dT%H:%M:%SZ; fi; }
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

if [ "$DRYRUN" = 1 ]; then          # no ROS, no chamber, no waiting
  setd(){ echo "$(ts),$1,$2" >>"$CSV"; }
  fire(){ :; }; stop(){ :; }; rh(){ echo 0.90; }
  LOG=/dev/null; CSV=$(mktemp); ORIG=1.0
  say "DRY RUN -- virtual clock, nothing sent to fc1"
fi

[ "$DRYRUN" = 1 ] || ORIG=$(ros2 param get /fc_controller "modes.$MODE.force_duty" 2>/dev/null | awk '{print $NF}')
[ -n "$ORIG" ] || { echo "FATAL: cannot read modes.$MODE.force_duty"; exit 1; }
[ "$DRYRUN" = 1 ] || echo "$ORIG" > /home/ubuntu/duty-probe-restore.txt  # breadcrumb if we die hard

cleanup() {
  [ "$DRYRUN" = 1 ] && { echo "dry-run schedule: $CSV"; return; }
  say "CLEANUP restoring modes.$MODE.force_duty=$ORIG and cancelling"
  ros2 param set /fc_controller "modes.$MODE.force_duty" "$ORIG" >/dev/null 2>&1
  stop
  say "CLEANUP done"
}
trap cleanup EXIT INT TERM

EXP_AT=0
keepalive() {   # re-fire the forced experiment before its TTL runs out
  local t; t=$(now)
  if [ $((t - EXP_AT)) -ge $((CHUNK * 60 - 300)) ]; then
    fire; EXP_AT=$t; say "experiment (re)fired for ${CHUNK}min"
  fi
}

# guard: returns 0 if the schedule may proceed, 1 if we are overriding
guard() {
  local r; r=$(rh); [ -n "$r" ] || return 0        # no reading: hold course, TTL still protects
  if lt "$r" "$RH_FLOOR"; then
    say "FLOOR BREACH rh=$r < $RH_FLOOR -- forcing duty 1.0"
    setd 1.0 floor-override
    while r=$(rh); [ -n "$r" ] && lt "$r" "$FLOOR_CLEAR"; do keepalive; nap 20; done
    say "floor cleared rh=$r"; return 1
  fi
  if gt "$r" "$RH_CEIL"; then
    say "CEILING BREACH rh=$r > $RH_CEIL -- forcing duty 0.0"
    setd 0.0 ceiling-override
    while r=$(rh); [ -n "$r" ] && gt "$r" "$CEIL_CLEAR"; do keepalive; nap 20; done
    say "ceiling cleared rh=$r"; return 1
  fi
  return 0
}

hold() {        # hold $1 for $2 minutes, re-asserting after any override
  local d=$1 mins=$2 end; end=$(( $(now) + mins * 60 ))
  setd "$d" "hold"
  say "HOLD duty=$d for ${mins}min"
  while [ "$(now)" -lt "$end" ]; do
    keepalive
    guard || setd "$d" "hold-resume"
    nap 20
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
    nap 15
  done
}

segment() {     # one scheduled segment: pick a duty, get there, hold it
  local d style dwell
  if [ $(( RANDOM % 3 )) -eq 0 ]; then
    d=$(( RANDOM % 2 )).0                            # rail: the biggest edge
  else
    d=$(awk "BEGIN{srand($RANDOM); printf \"%.2f\", rand() * $DUTY_MAX}")
  fi
  dwell=$(( 7 + RANDOM % 9 ))                        # 7-15 min, see DESIGN
  if [ $(( RANDOM % 4 )) -eq 0 ]; then               # 1 in 4 arrives on a ramp
    style=ramp; ramp "$PREV" "$d" 2
  else
    style=step
  fi
  say "SEGMENT $style duty=$d dwell=${dwell}min"
  hold "$d" "$dwell"
  PREV=$d
}

RANDOM=$SEED
say "START ${HOURS}h floor=$RH_FLOOR ceil=$RH_CEIL duty_max=$DUTY_MAX seed=$SEED orig_force_duty=$ORIG"
echo "iso,duty,phase" > "$CSV"
fire; EXP_AT=$(now)
END=$(( $(now) + HOURS * 3600 ))
PREV=0.0
while [ "$(now)" -lt "$END" ]; do
  segment
done
say "FINISHED"
