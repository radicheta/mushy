# 2026-05-09 fc1 Lab Visit — Copy-Paste Runbook

**Pair with:** `2026-05-09-fc1-lab-visit-plan.md` (the structured plan).
**Purpose:** every command, in order, ready to paste. No prose between commands you need to type.
**Conventions:** prompts indicate where the command runs.
- `(local)` = your laptop / wherever you're driving from
- `(elder-plops)` = `ssh elder-plops` (or local if you're already on it)
- `(fc1)` = `ssh 172.16.10.5` over wg0 (memory `feedback_ssh_tailscale`)
- `(timescale)` = `docker compose exec -T timescale psql -U postgres -d telemetry` from elder-plops repo root

> **Safety preflight (memory `feedback_fc1_remote_action_preflight_protocol`):** before ANY reboot / network-config / transport-down action on fc1, confirm: (a) physical access available, (b) tailscaled running on fc1, (c) wg0 IP 172.16.10.5 reachable, (d) you have a recovery path (ethernet at lab). The 2026-05-07 incident (`project_2026_05_07_fc1_reboot_unrecoverable`) is the reason this list exists.

---

## 0. Pre-arrival (do from home/elder-plops before driving out)

```bash
# (local) — am I able to reach fc1 right now?
ssh -o ConnectTimeout=5 santi@172.16.10.5 'echo ok && uptime && hostname'

# (elder-plops) — bridge healthy?
cd /mnt/slime-kingdom/opt/mushy
docker compose ps
curl -sf http://localhost:3001/health && echo "bridge ok" || echo "BRIDGE NOT OK"

# (elder-plops) — Timescale baseline (capture this number)
docker compose exec -T timescale psql -U postgres -d telemetry -c \
  "select count(*) as rows_last_hour from telemetry where time > now() - interval '1 hour';"

# (local) — make sure your local main is up to date and has Phase 30+31 code
cd /mnt/slime-kingdom/opt/mushy
git fetch origin
git log --oneline -10
git status
```

If `ssh 172.16.10.5` fails: do NOT continue from home. Drive to the lab with ethernet cable + recovery USB. Memory `project_2026_05_07_fc1_reboot_unrecoverable` recipe applies.

---

## 1. On arrival — camera back online (do first)

```bash
# (fc1) — physical inspection done, now check service
ssh santi@172.16.10.5
sudo systemctl status fc-core --no-pager | head -30
journalctl -u fc-core -n 200 --no-pager | grep -iE 'camera|frame|libcamera' | tail -40

# (fc1) — is the camera topic publishing?
source /opt/ros/jazzy/setup.bash
source ~/mushroom_farm_ws/install/setup.bash
ros2 topic list | grep -i camera
timeout 10 ros2 topic hz /fc1/camera/frame    # expect ~1 Hz; ^C after a few samples

# (fc1) — if no frames, check libcamera at OS level
libcamera-hello --list-cameras
# if "no cameras available": physical issue, ribbon-cable; flag as 999.x; do not block on this

# (elder-plops) — bridge sees the camera frame?
curl -sf http://localhost:3001/snapshot -o /tmp/snap.jpg && \
  ls -la /tmp/snap.jpg && file /tmp/snap.jpg

# Open Mission Control in browser; visually confirm live feed:
echo "http://10.68.155.50:8080"
```

---

## 2. Deploy Phase 30 + Phase 31 together

```bash
# (local) — push to fc1's deploy remote
cd /mnt/slime-kingdom/opt/mushy
git status                            # MUST be clean
git log --oneline origin/main..HEAD   # show what's about to deploy
git push fc1/prod main                # triggers nothing yet — fc1-side deploy is manual

# (fc1) — deploy ROS side (builds fc_msgs new srvs + fc_core)
ssh santi@172.16.10.5
cd ~/mushroom_farm_ws
git -C src/chambers/fc-core fetch origin && \
  git -C src/chambers/fc-core log --oneline HEAD..origin/main   # preview
bash scripts/pi-deploy/deploy.sh
# WATCH FOR: "fc_msgs" build success (new srv files: StartExperiment, CancelExperiment)
# WATCH FOR: "fc_core" build success
# WATCH FOR: "fc-core.service" restart success (active running)

# (fc1) — sanity check post-deploy
sudo systemctl status fc-core --no-pager | head -20
ros2 service list | grep -E 'experiment|StartExperiment|CancelExperiment'
ros2 param list /fc_controller | grep -E 'schedule_windows|experiment'

# (elder-plops) — deploy bridge with new control_experiment.js, control_param.js, DB migrations
cd /mnt/slime-kingdom/opt/mushy
git pull origin main
docker compose up -d --build bridge
docker compose logs --tail 50 bridge | grep -iE 'migration|experiment|listening'
docker compose ps

# (elder-plops) — alerter rebuild for Signal command parser (Phase 31-04)
docker compose up -d --build alerter
docker compose logs --tail 30 alerter | grep -iE 'signal|command|listening'

# (elder-plops) — verify migrations landed
docker compose exec -T timescale psql -U postgres -d telemetry -c "\dt"
docker compose exec -T timescale psql -U postgres -d telemetry -c "\d fc_experiments"
```

---

## 3. Phase 30 smoke (Layer 1 + Layer 2)

```bash
# (elder-plops) — pick a near-term boundary; e.g. 5 minutes from now in fc1's local time
# Using UTC offsets to avoid DST/timezone confusion: confirm fc1's TZ first
ssh santi@172.16.10.5 'date && timedatectl | grep -i zone'

# Compose a 2-window schedule for Layer 1 (replace HH:MM values with near-future times)
SCHED='[{"start":"00:00","end":"23:59","mode":"fruiting"}]'    # placeholder — edit before sending
echo "$SCHED" | jq .

# (elder-plops) — Layer 1 hot-apply via /control/param
curl -sS -X POST http://localhost:3001/control/param \
  -H 'Content-Type: application/json' \
  -d "{\"param\":\"schedule_windows\",\"value\":\"$SCHED\"}" | jq

# (fc1) — confirm parameter took
ssh santi@172.16.10.5
ros2 param get /fc_controller schedule_windows
ros2 topic echo /fc1/current_mode --once       # check source='scheduler' on next 30s tick
sleep 35
ros2 topic echo /fc1/current_mode --once

# (elder-plops) — Layer 2 persist
curl -sS -X POST http://localhost:3001/control/persist \
  -H 'Content-Type: application/json' \
  -d "{\"param\":\"schedule_windows\",\"value\":\"$SCHED\"}" | jq

# (fc1) — verify runtime_overrides.yaml has the schedule
ssh santi@172.16.10.5
sudo cat /etc/fc-core/runtime_overrides.yaml | grep -A 5 schedule_windows

# (fc1) — restart fc-core; schedule must reload
sudo systemctl restart fc-core
sleep 10
ros2 param get /fc_controller schedule_windows

# (elder-plops) — backward-compat: empty schedule
curl -sS -X POST http://localhost:3001/control/persist \
  -H 'Content-Type: application/json' \
  -d '{"param":"schedule_windows","value":"[]"}' | jq

# (fc1) — confirm fallback to single-mode
ros2 topic echo /fc1/current_mode --once       # source should NOT be 'scheduler' anymore
```

> Capture timestamps + log evidence into `30-03-SMOKE.md`.

---

## 4. Phase 31 UAT — six scenarios (DO NOT SKIP UAT-5)

### UAT-1 — Happy path (force-condensation 5 min)

```bash
# (elder-plops) — Timescale snapshot before
docker compose exec -T timescale psql -U postgres -d telemetry -c \
  "select count(*) from fc_experiments;"

# Send Signal message: /force-condensation 5
# (or via REST if direct trigger preferred)
curl -sS -X POST http://localhost:3001/control/experiment \
  -H 'Content-Type: application/json' \
  -d '{"kind":"force-condensation","duration_min":5}' | jq

# (fc1) — observe duty pinned at ~100%
ros2 topic echo /fc1/actuators/humidifier --once
ros2 topic echo /fc1/current_mode --once       # source='experiment'

# (elder-plops) — wait 5 min, verify auto-revert
sleep 320
docker compose exec -T timescale psql -U postgres -d telemetry -c \
  "select id, kind, started_at, ended_at, end_reason, delta_rh from fc_experiments order by started_at desc limit 3;"
```

### UAT-2 — Hard cap rejection

```bash
# Should return 4xx with cap = 120 message
curl -sS -X POST http://localhost:3001/control/experiment \
  -H 'Content-Type: application/json' \
  -d '{"kind":"force-condensation","duration_min":200}' | jq
```

### UAT-3 — Single-experiment lockout

```bash
# Start a 30 min one
curl -sS -X POST http://localhost:3001/control/experiment \
  -H 'Content-Type: application/json' \
  -d '{"kind":"force-condensation","duration_min":30}' | jq

# Immediately try a second; expect experiment_in_progress
curl -sS -X POST http://localhost:3001/control/experiment \
  -H 'Content-Type: application/json' \
  -d '{"kind":"force-evaporation","duration_min":10}' | jq
```

### UAT-4 — Cancel

```bash
# (with the 30 min experiment from UAT-3 still running)
curl -sS -X POST http://localhost:3001/control/experiment/cancel | jq

# Verify revert + DB row populated
docker compose exec -T timescale psql -U postgres -d telemetry -c \
  "select id, kind, ended_at, end_reason from fc_experiments order by started_at desc limit 1;"
# end_reason MUST be 'cancelled'
```

### UAT-5 — Boot-recovery (LOAD-BEARING SAFETY SCENARIO)

> **Preflight check:** physical access ✓, ethernet cable nearby ✓, fc1 console accessible ✓, you accept the 2026-05-07 risk profile ✓.

```bash
# Start a 30 min experiment
curl -sS -X POST http://localhost:3001/control/experiment \
  -H 'Content-Type: application/json' \
  -d '{"kind":"force-condensation","duration_min":30}' | jq

# Wait ~3 min so the experiment is well underway
sleep 180

# (fc1) — physical reboot (NOT a soft restart of fc-core)
ssh santi@172.16.10.5 'sudo reboot'
# Connection drops. Wait.

# (local) — wait for fc1 to come back; expected ~40s per memory
until ssh -o ConnectTimeout=3 santi@172.16.10.5 'echo ok' 2>/dev/null; do
  printf '.'; sleep 5;
done
echo " fc1 back"

# (fc1) — controller MUST be in safe baseline, NOT force-condensation
ssh santi@172.16.10.5
ros2 topic echo /fc1/current_mode --once       # MUST be source='active_mode' or 'scheduler', NOT 'experiment'
ros2 topic echo /fc1/actuators/humidifier --once   # MUST NOT be 1.0/100%

# (elder-plops) — DB row marked truncated_by_restart
docker compose exec -T timescale psql -U postgres -d telemetry -c \
  "select id, kind, ended_at, end_reason from fc_experiments order by started_at desc limit 1;"
# end_reason MUST be 'truncated_by_restart'
```

### UAT-6 — Phase 30 + Phase 31 interaction (D-08)

```bash
# Set a schedule with a boundary 3 min from now (compose values manually based on `date`)
SCHED='[ ... two windows with boundary T+3min ... ]'
curl -sS -X POST http://localhost:3001/control/param \
  -H 'Content-Type: application/json' \
  -d "{\"param\":\"schedule_windows\",\"value\":\"$SCHED\"}" | jq

# Start a force-experiment that spans the boundary (e.g. 6 min)
curl -sS -X POST http://localhost:3001/control/experiment \
  -H 'Content-Type: application/json' \
  -d '{"kind":"force-condensation","duration_min":6}' | jq

# Wait past the boundary (~4 min), confirm scheduler is suppressed
sleep 250
ssh santi@172.16.10.5 'ros2 topic echo /fc1/current_mode --once'  # source='experiment'

# Wait for experiment to end, confirm scheduler re-aligns within 30s
sleep 130
ssh santi@172.16.10.5 'ros2 topic echo /fc1/current_mode --once'  # source='scheduler'
```

---

## 5. Failure-scenario sweep (opportunistic — only if UAT clean)

```bash
# (fc1) — kill mid-control; systemd should recover
sudo systemctl kill fc-core
sleep 5
sudo systemctl status fc-core --no-pager | head -10
# expect "active (running)" within ~10s; memory project_blackout_2026_05_02_fc_core_stuck regression check

# (fc1) — tailscale flap; wg0 must stay up
ip -4 addr show wg0
sudo systemctl restart tailscaled
sleep 5
ip -4 addr show wg0     # 172.16.10.5/x should still be there
# memory feedback_stopping_tailscaled_kills_pid: do NOT stop tailscaled, only restart

# (elder-plops) — bridge restart mid-experiment; TRANSIENT_LOCAL replay engages
# (start a fresh 5-min experiment, then:)
docker compose restart bridge
sleep 10
docker compose logs --tail 40 bridge | grep -iE 'experiment|subscribe|replay'

# (elder-plops) — bad schedule JSON; bridge AND controller should reject
curl -sS -X POST http://localhost:3001/control/param \
  -H 'Content-Type: application/json' \
  -d '{"param":"schedule_windows","value":"not-json"}' | jq
# expect 400 from bridge

# Schedule edit while in-mode-transition: harder to construct deterministically; skip if time-pressed
```

---

## 6. BUF-04 natural-event evidence (from visit plan item #5)

```bash
# Closes BUF-04 evidence sweep if we induce a real outage from elder-plops side
# (memory project_buf04_natural_event_evidence_sweep)

# (elder-plops) — pause bridge for 20 min to force fc_buffer to accumulate + replay on resume
docker compose stop bridge
date  # note START
sleep 1200      # 20 min
docker compose start bridge
date  # note END

# Evidence check: fc_buffer should have queued, then drained
ssh santi@172.16.10.5 'curl -sf http://localhost:8765/health && curl -sf http://localhost:8765/stats'

# (timescale) — telemetry rows for the gap window should land in a ~1-2 min burst on resume
docker compose exec -T timescale psql -U postgres -d telemetry -c \
  "select date_trunc('minute', time) m, count(*) from telemetry
   where time > now() - interval '40 minutes'
   group by 1 order by 1 desc limit 30;"
```

> If the buffer-replay cursor bug from memory `project_bridge_buffer_replay_cursor_bug` bites again here, capture the row counts and bridge logs — that's the canonical evidence to file the structural fix.

---

## 7. Farmer attestation

```bash
# Farmer reviews live system in browser:
echo "http://10.68.155.50:8080"

# Capture attestation in commit message or summary doc.
# Three accepted forms (memory project_phase26_sht30_happy_path_unverified pattern):
#   "approved"
#   "approved with notes: <text>"
#   "issues: <text>"

# (local) — write summary doc
cd /mnt/slime-kingdom/opt/mushy
$EDITOR .planning/30-03-SUMMARY.md   # or 31-04-SUMMARY.md
```

---

## 8. Lifecycle (only if both phases attested clean)

```bash
# In a Claude session at repo root:
#   /gsd-audit-milestone
#   /gsd-complete-milestone v1.5
#   /gsd-cleanup
```

---

## 9. Discussion items reminder (from visit plan §"Discussion items for the farmer")

Have the VPD note and the forced-condensation operational note open during the conversation:

- `2026-05-09-vpd-and-water-mass-observer-research.md` — for item #2 (VPD + closed-loop). **Recommendation to bring: Option B** (expose VPD as derived telemetry; defer closed-loop control).
- `2026-05-09-forced-condensation-operational-practice.md` — for items #1 (operational fit) and the F8 / fruiting-flush BLOCK question.

Other items: camera coverage gap (#3), first real-world schedule profile (#4), BUF-04 outage induction (#5 — see §6 above).

---

## 10. Recovery escape hatches

```bash
# fc1 unreachable post-reboot
# → drive to lab, ethernet to fc1's switch, follow project_2026_05_07_fc1_reboot_unrecoverable
#    (mossrock-west missing from netplan; ethernet path; hand-edit)

# fc_msgs build fails on fc1 deploy
ssh santi@172.16.10.5
cd ~/mushroom_farm_ws
ls log/latest_build/fc_msgs/    # check stderr.log
# Most likely: CMakeLists.txt missing srv entries; check 31-01 commit on fc1's branch
git -C src/chambers/fc-core log --oneline -5 -- fc_msgs/

# Bridge migration fails (table create)
docker compose logs bridge | grep -iE 'migration|create table'
# fc_experiments is IF NOT EXISTS-idempotent; if hard fail, rollback:
docker compose down bridge
docker tag mushy-bridge:previous mushy-bridge:latest
docker compose up -d bridge

# Camera totally dead, hardware-fault
# → file 999.x, do NOT block visit; visual signal isn't load-bearing for UAT
```
