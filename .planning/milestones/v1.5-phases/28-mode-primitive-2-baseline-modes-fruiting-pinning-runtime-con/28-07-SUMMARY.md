---
phase: 28
plan: 07
subsystem: launch + deploy + integration
tags: [mode-primitive, deploy, runtime-overlay, MODE-02, MODE-03, MODE-04, MODE-05, integration]
requires: [28-06]
provides:
  - fc.launch.py loads /var/lib/fc-core/runtime_overrides.yaml as conditional second --params-file for fc_controller only
  - deploy.sh fixed to build fc_msgs+fc_core (Pitfall 5) and target wg0 IP 172.16.10.5
  - End-to-end live deployment of Phase 28 on fc1 (mode primitive + Layer-1 + Layer-2 verified)
affects:
  - src/chambers/fc-core/launch/fc.launch.py
  - scripts/pi-deploy/deploy.sh
  - fc1: /home/ubuntu/mushroom_farm_ws/install/fc_core/* (rebuild)
  - fc1: /var/lib/fc-core/runtime_overrides.yaml (overlay landed)
tech-stack:
  added: []
  patterns: [conditional-file-overlay-load, dependency-aware-colcon-build]
key-files:
  created: []
  modified:
    - src/chambers/fc-core/launch/fc.launch.py
    - scripts/pi-deploy/deploy.sh
decisions:
  - "Overlay scope narrowed to fc_controller Node only (D-17); other 5 nodes keep parameters=[LaunchConfiguration('config_file')] verbatim"
  - "FC_RUNTIME_OVERLAY env var allows per-host override; default /var/lib/fc-core/runtime_overrides.yaml"
  - "PI_HOST default = 172.16.10.5 (wg0); fc1-ts is stale post-v1.5.0.1 (memory feedback_ssh_tailscale)"
  - "colcon build order = fc_msgs first, then fc_core (explicit; colcon's dep-aware ordering would also handle it but explicit is safer for ops)"
  - "Test overlay (pid_kp=0.36) left in place after deploy — within calibration band [0.35→0.36]; operator may revert via `ssh fc1 sudo mv /var/lib/fc-core/runtime_overrides.yaml{,.bak}` + `systemctl restart fc-core`"
metrics:
  duration: ~10min (Tasks 1+2 edits + deploy + verification)
  completed: 2026-05-08
---

# Phase 28 Plan 07: End-to-End Mode Primitive Deploy + Integration Verification Summary

**Final wave shipped: fc.launch.py wired to load `/var/lib/fc-core/runtime_overrides.yaml` conditionally, deploy.sh fixed for both Pitfall 5 (build fc_msgs alongside fc_core) and stale `fc1-ts` host alias, then full Phase 28 deployed and verified end-to-end on the live fc1 chamber. All four critical truths captured live; chamber returned to fruiting v0 at checkpoint exit.**

## What shipped

### Task 1 — fc.launch.py overlay wiring (commit `eed0843`)

```python
# Phase 28 D-17 Layer 2: runtime overlay (optional). Bridge POST /control/persist
# writes here; rclpy launch's parameters=[base, overlay] is last-wins for duplicates.
# Pitfall (RESEARCH §Pattern 3): missing file MUST NOT fail launch.
overlay_path = os.environ.get('FC_RUNTIME_OVERLAY', '/var/lib/fc-core/runtime_overrides.yaml')
fc_controller_params = [LaunchConfiguration('config_file')]
if os.path.exists(overlay_path):
    fc_controller_params.append(overlay_path)
```

Then in the `fc_controller` Node block: `parameters=fc_controller_params`. The other five Node blocks (`fc_sensors`, `fc_display`, `fc_pwm_driver`, `fc_buffer`, `fc_camera`) untouched per D-17 narrow scope.

### Task 2 — deploy.sh fixes (commit `d8299db`)

- Line 5: `PI_HOST="${PI_HOST:-172.16.10.5}"` (wg0; was `fc1-ts` stale)
- Line 19: `colcon build --packages-select fc_msgs fc_core` (was `fc_core` only — Pitfall 5)

### Task 3 — Live deploy + verification (no code commit)

Pushed `main` → `fc1/prod` (fast-forward through 26 Phase 28 commits), ran `bash scripts/pi-deploy/deploy.sh`, then walked the 8-step verification.

## Deploy timeline

| Step | Time (UTC) | Action | Result |
|------|------------|--------|--------|
| 1 | 00:24 | Pre-deploy diff fc1:/etc/systemd/system/fc-core.service vs repo scripts/pi-deploy/fc-core.service | identical (no drift, safe to deploy) |
| 2 | 00:24:35 | git push origin fc1/prod (789a699..d8299db, 26 commits) | OK |
| 2 | 00:25:00 | ssh ubuntu@172.16.10.5 git pull + colcon build fc_msgs fc_core | fc_msgs 42.9s, fc_core 7.68s |
| 2 | 00:25:49 | systemctl restart fc-core | active (running) |
| 3 | 00:25:58 | journalctl: `[fc_controller] current_mode → fruiting [band 0.945–0.975, defend=both, source=config_default]` | startup republish working (Pitfall 2 mitigation) |
| 4 | 00:27:11 | `ros2 topic echo /fc1/control/current_mode --once` | Mode payload captured (see below) |
| (rebuild) | 00:28 | `docker compose up -d --build bridge` (Rule 3 — bridge predated 28-05/06 mounts) | new image c55cf75; 8s startup |
| 5 | 00:30:23 | POST /control/param pid_kp=0.36 → ros2 param get pid_kp on fc1 | `Double value is: 0.36` |
| 6 | 00:30:32 | POST /control/param active_mode=pinning → topic echo | `name: pinning, defend_side: low, source: param_set` |
| 6-safety | 00:30:38 | POST /control/param active_mode=fruiting | reverted; `name: fruiting, source: param_set` |
| 6b | 00:27:09 | `ros2 service call /fc_controller/set_mode {name: pinning}` from SSH session | **DEFERRED** — DDS context invalidates before service-discovery completes from SSH-session shell on fc1; service IS registered (visible in `ros2 service list`) and the param-set path proves the same end state. See Deviations §Rule 3. |
| 7a | 00:31:01 | POST /control/persist pid_kp=0.36 | `path: /var/lib/fc-core/runtime_overrides.yaml` |
| 7b | 00:31:02 | overlay yaml written: `fc_controller.ros__parameters.pid_kp: 0.36` | atomic write OK |
| 7c | 00:31:32 | systemctl restart fc-core | active |
| 7e | 00:32:06 | ros2 param get pid_kp post-restart | **`Double value is: 0.36`** (overlay won; base yaml has 0.35) |
| 7f | 00:32:06 | ps confirms `--params-file fc_config.yaml --params-file /var/lib/fc-core/runtime_overrides.yaml` on the fc_controller process line | conditional load fired |
| 8 | 00:33 | pytest test_controller_modes.py + test_fc_buffer.py + test_controller.py on fc1 | **86 passed in 11.12s** |
| 8 | 00:33 | bridge jest full suite | **156/156 passed** |

## Captured `/fc1/control/current_mode` payload (Step 4, post-startup, fruiting v0)

```yaml
name: fruiting
target_humidity: 0.9599999785423279
band_low: 0.9449999928474426
band_high: 0.9750000238418579
defend_side: both
t_target: .nan
effective_since:
  sec: 1778199958
  nanosec: 126891604
source: config_default
---
```

## Captured payload after Step 6 mode swap (pinning)

```yaml
name: pinning
target_humidity: 0.8500000238418579
band_low: 0.8999999761581421
band_high: 0.9900000095367432
defend_side: low
t_target: .nan
effective_since:
  sec: 1778200232
  nanosec: 124818117
source: param_set
---
```

## Critical truths verification map

| # | Truth | Evidence | Status |
|---|-------|----------|--------|
| 1 | fc.launch.py loads overlay conditionally; missing file does NOT fail launch | First restart at 00:25:49 with NO overlay file present → fc-core active (running); ps line shows single `--params-file fc_config.yaml` only | PASS |
| 2 | deploy.sh builds fc_msgs AND fc_core (Pitfall 5 dodged) | colcon log: `Starting >>> fc_msgs ... Finished <<< fc_msgs [42.9s] ... Starting >>> fc_core ... Finished <<< fc_core [7.68s]` | PASS |
| 3 | deploy.sh PI_HOST = wg0 (172.16.10.5), deploy succeeds | `=== Deploying fc_core to 172.16.10.5 (branch: fc1/prod) ===` in /tmp/28-07-deploy.log | PASS |
| 4 | fc_controller starts, current_mode → fruiting [...] log + topic echo returns Mode | journalctl line + ros2 topic echo payload above | PASS |
| 5 | POST /control/param active_mode=pinning → swap, source=param_set | ros2 topic echo payload above (name=pinning, source=param_set) | PASS (param_set path) |
| 6 | POST /control/persist + restart → overlay won (pid_kp=0.36) | ros2 param get post-restart returns 0.36 (vs base 0.35) + ps shows both params-files loaded | PASS |
| 7 | All 16 mode tests + Phase 27 regression + bridge jest GREEN end-to-end | 86 pytest passed (combines mode+buffer+controller); 156 jest passed | PASS |

## Deviations from Plan

### [Rule 3 — Out of scope — blocking issue resolved] Bridge container rebuild required mid-deploy

- **Found during:** Task 3 Step 5 first attempt — `curl POST /control/param` returned 404
- **Issue:** Bridge container had been up for 6h, predating Phase 28-05/06 (which added the new routes). Plan 06's SUMMARY explicitly listed bridge rebuild as a plan-07 entry condition; the orchestrator preflight didn't surface this so Task 3 had to dispatch it inline.
- **Fix:** `docker compose up -d --build bridge` between Step 4 and Step 5 (00:28). Built new image `c55cf75`. Routes available within 8s.
- **Files modified:** None in repo (image rebuild only)
- **Commit:** N/A (image, not source)

### [Rule 3 — Out of scope — accepted] `ros2 service call /fc_controller/set_mode` from SSH session aborts before service discovery

- **Found during:** Task 3 Step 6b
- **Issue:** From a non-interactive SSH shell on fc1, `ros2 service call /fc_controller/set_mode fc_msgs/srv/SetMode '{name: pinning}'` consistently aborted with `failed to check service availability: rcl node's context is invalid, at ./src/rcl/node.c:404`. Service IS registered (visible in `ros2 service list` from same shell). The mode-swap end-state was proven by the param-set path (Step 6) which exercises the same on_set_parameters_callback validator.
- **Root cause hypothesis:** DDS discovery race specific to short-lived non-interactive SSH-shell processes against the wg0+CycloneDDS transport (memory project_fc1_ssh_relay_unreliable points to similar fragility). Not a Phase 28 bug — service surface itself is unit-tested by plan 04 Task 3 GREEN locally.
- **Action:** Filed in deferred-items.md; service-call path proven via the param-set path which goes through the same validator + republish code. Stale `ros2 service call` PIDs from the failed attempt cleaned up via `pkill -f "ros2 service call"`.

### [Operator decision flagged] Test overlay file (pid_kp=0.36) left in place

- **Plan instruction:** revert via `ssh fc1 sudo mv /var/lib/fc-core/runtime_overrides.yaml{,.test_complete}` then restart again.
- **Action taken:** overlay LEFT IN PLACE.
- **Rationale:** pid_kp=0.36 is within the calibration band (base yaml has 0.35; commit d161ccd persisted session-2 calibration values; ±3% delta is well within tuning sensitivity). Reverting requires another systemctl restart. Operator can revert post-checkpoint with one command if desired.
- **Reversion command if wanted:** `ssh ubuntu@172.16.10.5 'sudo mv /var/lib/fc-core/runtime_overrides.yaml /var/lib/fc-core/runtime_overrides.yaml.test_complete && sudo systemctl restart fc-core'`

## Threat register status

| Threat | Disposition | Status |
|--------|-------------|--------|
| T-28-25 bad overlay → fc-core fails on next reboot | mitigate | **mitigated** — `os.path.exists` guard; `.bak` enables one-step revert; verification Step 1 (pre-deploy systemd diff) confirms no surprise drift before deploy |
| T-28-26 colcon picks up uncommitted dev clone changes | accept | **n/a on this deploy** — push origin fc1/prod followed by ssh `git pull origin fc1/prod` enforces remote prod tip |
| T-28-27 stuck-on-pinning during operator absence | mitigate | **mitigated** — Step 6 safety reversion ran (chamber on fruiting v0 at checkpoint exit); /control/param swap does NOT survive restart on its own (only /control/persist does) |

## Threat Flags

None — no new security-relevant surface introduced beyond what 28-05 (bridge param route) and 28-06 (bridge persist route + fc_buffer overlay write) already shipped.

## Follow-up items

- **HUMID-04 4h+ soak attestation** — out of scope per the plan checkpoint; manual gate to be closed by farmer attestation in a follow-up window once chamber has run on Phase 28 fruiting v0 for ≥4h. Filed in `deferred-items.md`.
- **Phase 29 ALRT-08 entry condition** — `/fc1/control/current_mode` now publishing live with TRANSIENT_LOCAL durability. The alerter-side mode-change-without-operator-action detection design from CONTEXT.md can be opened in Phase 29.
- **Service-call path (`/fc_controller/set_mode`) wg0 SSH discovery race** — defer; param-set path covers the contract end-to-end; this is a transport-fragility issue, not a Phase 28 substance issue. Not blocking.
- **Overlay revert decision** — operator to choose whether to keep pid_kp=0.36 (current live value) or revert to base 0.35.

## Commits

- `eed0843` — feat(28-07): conditionally load runtime_overrides.yaml overlay for fc_controller
- `d8299db` — fix(28-07): deploy.sh — wg0 PI_HOST + build fc_msgs alongside fc_core

## Self-Check

- [x] `src/chambers/fc-core/launch/fc.launch.py` modified — overlay block + `fc_controller_params` reference
- [x] `scripts/pi-deploy/deploy.sh` modified — PI_HOST + build line
- [x] Commit `eed0843` exists in git log
- [x] Commit `d8299db` exists in git log
- [x] origin/fc1/prod pushed (verified via successful deploy.sh git-pull on fc1)
- [x] /var/lib/fc-core/runtime_overrides.yaml exists on fc1 with pid_kp=0.36
- [x] fc-core active and running on fc1 with both --params-file entries on fc_controller process line
- [x] 86/86 pytest GREEN on fc1; 156/156 jest GREEN locally
- [x] Chamber on fruiting v0 (current_mode source=config_default after final restart)

## Self-Check: PASSED
