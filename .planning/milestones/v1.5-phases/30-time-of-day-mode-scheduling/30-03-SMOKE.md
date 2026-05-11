# Plan 30-03 — SMOKE evidence (Tasks 2-3)

**Status:** SMOKE PASSED 2026-05-09; Task 4 farmer attestation pending operator review of this file.

## Environment

- **fc1:** ubuntu@172.16.10.5 (wg0). fc-core systemd unit, branch `fc1/prod` at `338894c` (functionally current — only docs commits beyond, no fc-core code changes).
- **elder-plops:** bridge container `mushy-bridge-1` up; `/control/param` (Phase 28-05) + `/control/persist` (Phase 28-06) endpoints live; `schedule_windows` allowlisted in `control_param.js:165` per Phase 30-02.
- **Test driver:** Claude (autonomous, mid-session 2026-05-09 22:45-22:53 UTC), validating a real pinning window (perturbs chamber RH band briefly), with operator approval prior to perturbation.

## Task 2 — Deploy verify

- fc1 `~/mushroom_farm_ws/mushy-repo` at `338894c` (branch `fc1/prod`, clean tree). Diff against `main` (commit `91c9d5a`): 3 commits, all docs / alerter-only changes — **zero changes to `src/chambers/fc-core/`**.
- `journalctl -u fc-core` shows scheduler tick alive (`[scheduler] no window matches HH:MM; keeping current mode 'fruiting'` lines every ~30s when `schedule_windows="[]"`).
- `ros2 param get /fc_controller schedule_windows` confirmed working post-restart with proper CycloneDDS env (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `CYCLONEDDS_URI=file:///etc/cyclonedds.xml`, `ROS_DOMAIN_ID=69`).

## Task 3 — Live smoke

### Layer 1 hot apply (boundary transition)

Initial state: `active_mode=fruiting`, `schedule_windows="[]"`. Chamber RH 96.7%.

```
22:45:52 UTC  POST /control/param  schedule_windows=[{"start":"22:47","end":"22:50","mode":"pinning"}]
              → {"ok":true,"applied":[...]}
22:45:58 UTC  fc-core: [scheduler] no window matches 22:45; keeping current mode 'fruiting'
22:47:28 UTC  fc-core: [scheduler] transition: fruiting → pinning at 22:47 (window=22:47-22:50)   ← BOUNDARY HIT
22:50:28 UTC  fc-core: [scheduler] no window matches 22:50; keeping current mode 'pinning'        ← gap-keeps-mode (CONTEXT D-08)
22:51:12 UTC  POST /control/param  active_mode=fruiting (manual reset to clear pinning carry-over)
              → fc-core: current_mode → fruiting [band 0.945–0.975, defend=both, source=param_set]
```

**Confirms:** scheduler tick evaluates every ~30s; transitions fire at start-boundary; gap behaviour is by design (D-08 — keeps current mode in gaps; revert is operator's responsibility or another window's job).

### Layer 2 persist + restart survival

```
22:51:22 UTC  POST /control/persist  schedule_windows=[{"start":"09:00","end":"10:00","mode":"pinning"}]
              → {"ok":true,"persisted":[...],"path":"/var/lib/fc-core/runtime_overrides.yaml"}
22:51:22 UTC  /var/lib/fc-core/runtime_overrides.yaml updated with timestamp 2026-05-09T22:51:22.610Z;
              schedule_windows: '[{"start":"09:00","end":"10:00","mode":"pinning"}]'

22:51:30 UTC  ssh ubuntu@172.16.10.5 sudo systemctl restart fc-core
22:52:01 UTC  fc-core (new pid 7808): current_mode → fruiting [source=config_default]            ← restart survived
22:52:01 UTC  fc-core: [scheduler] no window matches 22:52; keeping current mode 'fruiting'      ← scheduler alive post-restart
22:52:30 UTC  ros2 param get /fc_controller schedule_windows
              → "[{\"start\":\"09:00\",\"end\":\"10:00\",\"mode\":\"pinning\"}]"                    ← param survived
```

**Confirms:** Layer 2 persist writes to `runtime_overrides.yaml` correctly; restart-survival proven; controller loads override on boot; scheduler reads it (no transition because 22:52 is in the gap before 09:00).

### Baseline restore

```
22:52:50 UTC  POST /control/param   schedule_windows="[]"  → ok
22:52:50 UTC  POST /control/persist schedule_windows="[]"  → ok
22:52:50 UTC  /var/lib/fc-core/runtime_overrides.yaml: schedule_windows: '[]'  ← restored
```

**Final state:** chamber back to fruiting (config_default), schedule disabled, runtime_overrides.yaml clean.

## Side-findings

- **Scheduler gap-behaviour (D-08) carries the previous mode into gaps.** This is intentional but means: if you set a one-shot pinning window that ends at 22:50, the chamber stays in pinning until something else resets it (next window, manual `active_mode` set, or restart loading config_default). For Phase 32 / future schedules, operator needs to either (a) define a covering "fruiting" window for the rest of the day, or (b) accept that the schedule's job is "switch in, manually switch out". Worth surfacing in farmer-facing docs / UI.
- **Restart-time mode resolves to `config_default` (fruiting) regardless of `schedule_windows`** — confirmed by the 22:52:01 log line showing `source=config_default`. The very next scheduler tick re-evaluates against the persisted schedule. So the post-restart mode is "config_default + first scheduler tick aligns to schedule". For a window that's currently active at boot time, this means there's a brief (≤30s) period where the controller runs `config_default` before the scheduler aligns it. Not a bug; worth noting.
- **`/control/param` has no GET endpoint.** Verified `schedule_windows` post-restart via `ros2 param get` over SSH with explicit CycloneDDS env. A future `/control/param GET` route would simplify smoke testing.

## Acceptance basis for Task 4 farmer attestation

- Both layers proven (hot + persist + restart survival).
- Chamber restored cleanly; no lingering perturbation.
- The only behavioral nuance worth the farmer's attention is gap-behaviour D-08 (above).

## Rollback recipe (if farmer wants schedule disabled later)

```bash
curl -X POST -H 'content-type: application/json' \
  http://elder-plops:8081/control/param \
  -d '{"node":"fc_controller","param":"schedule_windows","value":"[]"}'

curl -X POST -H 'content-type: application/json' \
  http://elder-plops:8081/control/persist \
  -d '{"node":"fc_controller","param":"schedule_windows","value":"[]"}'
```
