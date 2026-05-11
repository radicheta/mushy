---
phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
verified: 2026-05-08T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 3
overrides:
  - must_have: "Layer 2 transport via SSH from bridge (D-17 original wording)"
    reason: "Bridge container has no ssh binary (probed live, exit 127). Layer 2 pivots to fc_buffer HTTP relay (172.16.10.5:8765); same end-state, smaller blast radius (no SSH key inside bridge container). Locked in 28-01-SPIKE.md D-B1."
    accepted_by: "Santi (operator)"
    accepted_at: "2026-05-07T20:00:00Z"
  - must_have: "Test overlay removed from fc1 after deploy"
    reason: "pid_kp=0.36 left in /var/lib/fc-core/runtime_overrides.yaml — within calibration band [0.35→0.36], operator decision; one-step revert via mv runtime_overrides.yaml{,.bak} + restart available."
    accepted_by: "Santi (operator)"
    accepted_at: "2026-05-08T00:33:00Z"
  - must_have: "ros2 service call /fc_controller/set_mode end-to-end smoke from fc1 SSH"
    reason: "Non-interactive SSH shell + DDS discovery races on wg0+CycloneDDS (rcl node's context is invalid, src/rcl/node.c:404). Service IS registered (ros2 service list on fc1 shows it) and same end-state is proven by Step 6 param-set path which routes through the identical on_set_parameters_callback. Filed in deferred-items.md as transport-fragility, not Phase 28 substance."
    accepted_by: "Santi (operator)"
    accepted_at: "2026-05-08T00:27:00Z"
gaps: []
deferred:
  - truth: "ros2 service call /fc_controller/set_mode end-to-end happy path from fc1 SSH shell"
    addressed_in: "999.28 (fc1 transport hardening) or future on-lab visit"
    evidence: "Documented in deferred-items.md as transport fragility; service surface itself is unit-tested GREEN in plan 28-04, registered in ros2 service list, and exercised through Layer-1 param-set path on live fc1."
human_verification: []
---

# Phase 28: Mode Primitive + 2 Baseline Modes + Runtime Config Delivery — Verification Report

**Phase Goal:** Wrap Phase 27's PID primitive in a named-mode abstraction (declarative YAML modes, live mode-switch service, `current_mode` topic, two baseline modes `fruiting`/`pinning`) and ship a runtime config delivery path (bridge HTTP → ROS2 SetParameters + persistence overlay) so mode/band tuning happens without a deploy cycle. PID kernel itself stays RH-targeted and unchanged.

**Verified:** 2026-05-08
**Status:** PASS
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (mapped to MODE-01..05)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 (MODE-01) | Controller exposes mode registry: `(target_humidity, band_low, band_high, defend_side, T_target_optional)` flattened into dotted-key ROS2 params | PASS | `fc_config.yaml:79-90` declares `modes.fruiting.*` + `modes.pinning.*` (5 keys × 2 modes); `fc_controller.py:21-32` defines `ModeView` dataclass with exact 5-field schema; `_resolve_active_mode` (line 356) consumes via `get_parameter('modes.{name}.{field}')`. SEED-004 schema honored verbatim. |
| 2 (MODE-02) | Two baseline modes shipped with farmer-locked v0 values (D-05/D-06) | PASS | `fc_config.yaml:80-84`: fruiting `target=0.96, band=[0.945, 0.975], defend=both, t_target=.nan` (D-05 verbatim). `fc_config.yaml:86-90`: pinning `target=0.85, band=[0.90, 0.99], defend=low, t_target=.nan` (D-06 verbatim). |
| 3 (MODE-03) | Farmer can switch active mode via ROS service call; takes effect on next control tick | PASS | `fc_controller.py:202-203` creates `set_mode` service typed `fc_msgs/SetMode`; `_handle_set_mode` (line 550) routes via `self.set_parameters(...)` so on_set_parameters_callback fires; `fc_msgs/srv/SetMode.srv` schema (`string name → bool success, string reason, fc_msgs/Mode active_mode`) lands in `src/chambers/fc-msgs/srv/SetMode.srv`. Service registered live on fc1 (Step 5 of plan-07; visible in `ros2 service list`). End-state proven via param-set path (live Step 6) — service-call SSH happy-path deferred per override #3. D-12 bumpless re-engage on swap implemented at line 588-616 (`_engage_pid_bumplessly` with `last_output=_last_published_duty`). |
| 4 (MODE-04) | Controller publishes `current_mode` topic (TRANSIENT_LOCAL) so downstream consumers read live mode without restart | PASS | `fc_controller.py:186-187` creates publisher on `fc1/control/current_mode` with TRANSIENT_LOCAL/RELIABLE/depth=1 QoS; `_build_mode_msg` (line 386) populates all 7 fc_msgs/Mode fields incl. `effective_since` and `source`; startup republish at line 257 mitigates Pitfall 2 (TRANSIENT_LOCAL doesn't persist across process restart). Live: journalctl line 00:25:58 + `ros2 topic echo` payload captured in 28-07-SUMMARY. |
| 5 (MODE-05) | Mode definitions runtime-tunable without a deploy cycle (Layer 1 hot apply + Layer 2 persistence) | PASS | **Layer 1**: `bridge/src/control_param.js` ALLOWLIST (lines 76-100) covers `active_mode`, all 10 mode shape keys × 2 modes, and pid_kp/ki/kd; `POST /control/param` mounted in `index.js`. Routes through rclnodejs SetParameters → controller's `on_set_parameters_callback` (`fc_controller.py:434`). **Layer 2**: `bridge/src/control_persist.js` writes via `makeHttpTransport` → `fc_buffer.py:297 POST /control/persist` → `_atomic_write_overlay` (`.tmp` + fsync + rename + `.bak` rotation, line 76-105) → `/var/lib/fc-core/runtime_overrides.yaml`. **Launch**: `fc.launch.py:18-21` conditionally appends overlay as 2nd `--params-file` for `fc_controller` only (rclpy last-wins). Live: overlay (`pid_kp=0.36`) survived restart per plan-07 verification. |

**Score:** 5/5 must-haves verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/chambers/fc-msgs/msg/Mode.msg` | 7 fields per D-13 | VERIFIED | Exact match: `name, target_humidity, band_low, band_high, defend_side, t_target, effective_since(builtin_interfaces/Time), source` |
| `src/chambers/fc-msgs/srv/SetMode.srv` | request `{name}` → response `{success, reason, active_mode}` | VERIFIED | Matches D-16 |
| `src/chambers/fc-msgs/package.xml` | ament_cmake + rosidl + builtin_interfaces depend | VERIFIED | `<member_of_group>rosidl_interface_packages</member_of_group>`, builtin_interfaces depend present |
| `src/chambers/fc-core/config/fc_config.yaml` modes block | D-05/D-06 values + D-04 backcompat preserved | VERIFIED | Modes block at lines 76-90 under `fc_controller:` scope; legacy `target_humidity: 0.96` + `humidity_tolerance: 0.015` retained in `/**:` scope (D-04 backcompat for nodes that don't read modes) |
| `src/chambers/fc-core/fc_core/fc_controller.py` ModeView/_resolve_active_mode/D-08..D-12 | All five surgery points | VERIFIED | ModeView (21-32), _resolve_active_mode (356), band-edge error projection (838-859, exact 4-case D-09), _ramp_setpoint_to_band (650), nearest-defended-edge bypass re-key (864-874, exact D-11), bumpless on swap via _last_published_duty (240-241, 616) |
| `fc_controller.py` on_set_parameters_callback validator | atomic batch + range bounds + active_mode membership | VERIFIED | `_validate_params` (434) builds post-batch view (`get_post`, line 457) for atomic invariants; band ordering 0≤bl<bh≤1 (477, 493); D-04 NaN-sentinel skip (471, 487); defend_side enum (500); pid_kp∈[0,5] / pid_ki∈[0,1] / pid_kd∈[0,20] (523-540) |
| `fc_controller.py` current_mode publisher TRANSIENT_LOCAL | D-14 | VERIFIED | actuator_qos reused (TRANSIENT_LOCAL/RELIABLE/depth=1) at line 186; startup republish at 257 |
| `fc_controller.py` `set_mode` service | D-16 | VERIFIED | `create_service(SetMode, 'set_mode', ...)` line 202 |
| `src/chambers/fc-core/launch/fc.launch.py` overlay | conditional, `fc_controller` only, after base | VERIFIED | Lines 18-21 honor `FC_RUNTIME_OVERLAY` env, `os.path.exists` gate (Pattern 3 — missing file MUST NOT fail launch), order = base then overlay (last-wins); other 5 nodes keep verbatim parameters list (D-17 narrow scope) |
| `src/mission-control/bridge/src/control_param.js` | Layer 1 allowlist + Pattern 4 SetParameters | VERIFIED | ALLOWLIST hardcoded (T-28-15), DECLARED_MODES + DEFEND_SIDES sets, MAX_PARAMS_PER_REQUEST=20 DoS cap, TIMEOUT_MS=3000, type-coercion via `expected_type` not JS typeof (Pattern 4 footgun closed) |
| `src/mission-control/bridge/src/control_persist.js` | Layer 2 forwards to fc_buffer HTTP, NOT ssh | VERIFIED | `makeHttpTransport` → `http://172.16.10.5:8765/control/persist` (lines 18-19, 95-119); no `child_process`/`ssh` references; reuses `control_param.validate` (single source of truth ALLOWLIST) |
| `src/chambers/fc-core/fc_core/fc_buffer.py` POST /control/persist | atomic write + .bak + path allowlist | VERIFIED | Route at line 297; `_atomic_write_overlay` (76-105) does `.tmp+fsync+rename` + `.bak` rotation; `_validate_overlay_path` (53) rejects `.bak`/`.tmp` suffixes (line 58) and uses `realpath()` (67) defeating symlink escape (T-28-20) |
| `scripts/pi-deploy/deploy.sh` | PI_HOST=172.16.10.5 + build fc_msgs+fc_core | VERIFIED | Line 5 `PI_HOST="${PI_HOST:-172.16.10.5}"` (memory `feedback_ssh_tailscale`); line 19 `colcon build --packages-select fc_msgs fc_core` (Pitfall 5) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Bridge `POST /control/param` | controller param store | rclnodejs SetParameters → on_set_parameters_callback | WIRED | Pattern 4 wire shape locked in 28-01-SPIKE D-A1; both layers enforce same range bounds (defense in depth) |
| Bridge `POST /control/persist` | fc1 overlay yaml | HTTP → fc_buffer:8765/control/persist → atomic write | WIRED | No SSH; HTTP relay confirmed in code (control_persist.js:18-19, 111) |
| `fc.launch.py` | overlay yaml | conditional 2nd --params-file | WIRED | os.path.exists gate; rclpy last-wins for duplicates |
| `set_mode` service | current_mode topic | _handle_set_mode → set_parameters → synchronous _publish_current_mode | WIRED | Synchronous publish path at line 580+ (param IS applied between set_parameters returning and the publish call); validator path queues next-tick drain via _pending_current_mode_republish |
| validator | current_mode republish | _pending_current_mode_republish → control_loop drain | WIRED | Line 744-747 in control_loop drains at top of every tick |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| current_mode publisher | mv = ModeView | _resolve_active_mode reads live ROS2 params | Yes — flat dotted-key params declared at startup; validator gates writes | FLOWING |
| Layer 1 hot apply | param store | rclnodejs createClient SetParameters → rcl SetParameters service | Yes — round-trip ~10ms (spike §A) | FLOWING |
| Layer 2 overlay | runtime_overrides.yaml | bridge → fc_buffer HTTP → atomic rename | Yes — proven live: pid_kp=0.36 survived restart | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command/Evidence | Result | Status |
|----------|-----------------|--------|--------|
| current_mode topic publishes | `ros2 topic echo /fc1/control/current_mode --once` (plan-07 Step 4) | Mode payload captured live | PASS |
| Startup republish | journalctl line 00:25:58: `[fc_controller] current_mode → fruiting [band 0.945–0.975, defend=both, source=config_default]` | log line present | PASS |
| Overlay survives restart | pid_kp=0.36 visible after fc-core restart (plan-07) | confirmed | PASS |
| pytest on fc1 | 86/86 GREEN (plan-07 Step 7) | mode + buffer + controller suite | PASS |
| jest local | 156/156 GREEN (plan-07 Step 8) | bridge full suite | PASS |
| `ros2 service call /set_mode` from SSH | DDS context invalidates pre-discovery | DEFERRED (override #3) | DEFERRED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MODE-01 | 28-02, 28-03 | Mode registry with SEED-004 schema flattened to dotted-key params | SATISFIED | fc_config.yaml modes block + ModeView + _resolve_active_mode |
| MODE-02 | 28-02, 28-03 | Two baseline modes (fruiting, pinning) with farmer-locked v0 values | SATISFIED | D-05/D-06 values verbatim in YAML |
| MODE-03 | 28-04 | Farmer can switch active mode via ROS service; effect on next tick | SATISFIED | set_mode service + bumpless re-engage; SSH happy-path deferred (override #3) |
| MODE-04 | 28-04 | current_mode topic with TRANSIENT_LOCAL durability | SATISFIED | publisher at line 186; live capture in plan-07 |
| MODE-05 | 28-05, 28-06, 28-07 | Runtime-tunable without deploy (Layer 1 hot + Layer 2 persistence) | SATISFIED | control_param.js + control_persist.js + fc_buffer.py routes + launch overlay |

### PID Kernel Invariant (D-09)

Critical invariant verified: PID kernel construction (`fc_controller.py:226-232`) is **byte-identical** to Phase 27 commit aeff734 (line 151-157):
- `simple_pid.PID` import from `fc_core.vendor.simple_pid` (unchanged, line 13)
- `output_limits=(0.0, 1.0)` (unchanged)
- `set_auto_mode(True, last_output=0.15)` default at fresh-engage (unchanged, plan 28-04 explicit decision)
- `git diff aeff734 HEAD -- fc_controller.py` shows no edits to PID instantiation, only callsite additions in branch logic (D-09 error projection wraps the kernel; doesn't replace it)

The mode-aware band projection is **upstream** of the PID call (`error_pct = (rh - mode.band_low) * 100.0` at line 839), preserving the kernel's contract.

### Defense-in-Depth Range Bounds (T-28-09)

Bounds match exactly between bridge ALLOWLIST and controller validator:

| Param | Bridge (`control_param.js`) | Controller (`_validate_params`) | Match |
|-------|----------------------------|--------------------------------|-------|
| pid_kp | `entryDoubleRange('pid_kp', 0, 5)` | `0.0 <= v <= 5.0` (line 524) | YES |
| pid_ki | `entryDoubleRange('pid_ki', 0, 1)` | `0.0 <= v <= 1.0` (line 530) | YES |
| pid_kd | `entryDoubleRange('pid_kd', 0, 20)` | `0.0 <= v <= 20.0` (line 536) | YES |
| target_humidity | `entryUnitDouble` [0,1] | `0.0 <= v <= 1.0` (line 508) | YES |
| band_low/high | `entryUnitDouble` [0,1] (per-param); cross-param invariant only on controller | atomic post-batch invariant 0≤bl<bh≤1 (line 477, 493) | YES (controller is strictly stronger — bridge can let through 0.5/0.5 batch which controller rejects atomically; this is correct: bridge bounds are necessary, controller invariant is sufficient) |
| defend_side | `DEFEND_SIDES = {low, high, both}` | `v not in ('low','high','both')` (line 501) | YES |
| active_mode | `DECLARED_MODES = ['fruiting','pinning']` (best-effort hardcoded; controller is final authority per plan-05 decision) | `v not in self._declared_mode_names()` (line 515) | YES — bridge best-effort, controller authoritative |
| t_target | `entryTtarget` (NaN or [0,40]) | (no controller-side range check) | Bridge stricter; acceptable since t_target is reserved-for-VPD (D-02), unused in v0 |

### Anti-Patterns Found

None blocking. Two notes:
- `fc_msgs/srv/SetMode.srv` and `msg/Mode.msg` in `package.xml` rely on rosidl_default_generators implicit msg/srv globbing (CMakeLists.txt does the explicit listing); not a defect.
- Test overlay `pid_kp=0.36` left on fc1 (override #2) — within calibration band, operator decision; one-step revert documented.

### Human Verification Required

None for the Phase 28 contract. Service-call-from-SSH happy path is deferred (override #3, deferred-items.md) — not blocking, addressed when fc1 transport is hardened or a lab visit is available.

### Gaps Summary

No goal-blocking gaps. Three accepted overrides documented in frontmatter cover the intentional deviations (Layer 2 transport pivot, test overlay retention, SSH service-call discovery race). MODE-01..05 all satisfied with byte-level evidence in code, live `ros2 topic echo` capture, 86/86 pytest + 156/156 jest GREEN, and PID kernel invariant verified via git diff.

---

*Verified: 2026-05-08*
*Verifier: Claude (gsd-verifier)*
