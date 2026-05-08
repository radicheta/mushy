---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: verifying
stopped_at: Completed 28-07-PLAN.md (awaiting human-verify checkpoint)
last_updated: "2026-05-08T00:35:22.919Z"
last_activity: 2026-05-08
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 17
  completed_plans: 17
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-02)

**Core value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.
**Current focus:** Phase 28 — mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con

## Current Position

Phase: 28 (mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con) — EXECUTING
Milestone: v1.5.0.1 → v1.5 — milestone v1.5.0.1 resilience-hotfix work complete; advancing to mode work

- Phase 27 — PID + slow-PWM: SHIPPED 2026-05-02
- Phase 27.1 — Edge buffering: SHIPPED 2026-05-03 over wg0 (BUF-04 organic attestation still pending — see 999.36)
- Phase 27.2 — fc-core systemd hardening: PARTIAL-SHIPPED 2026-05-07 (cold-reboot scenario 1 PASS; wg0-down-at-boot scenario re-filed under 999.28)
- Phase 27.3 — Sampling-rate reduction: MOOTED by wg0 transport switch
- Phase 27.4 — Netplan reconciliation: MOOTED in planned form

Plan: 7 of 7
Status: Phase complete — ready for verification
Last activity: 2026-05-08

Progress: [██████████] 100%

**Carried from v1.3 (not blocking v1.4):**

- 19 FarmOS admin actions — deferred to v1.5; gated on Zoy/farm-team availability
- 20 Alert cooldown tuning — deferred to v1.5; calendar-gated (Phase 17 live ≥1 week)
- ALRT-07 snooze receive-side — tracked as backlog 999.15 (signal-cli-rest-api linked-device limitation)

**v1.4 pre-gates to check before Phase 24:**

- ComfyUI on elder-plops promoted from dev-use to prod (systemd unit, restart policy, health check)
- Retention policy for continuous raw snapshots agreed with operator
- Farmer expectations set: v1.4 delivers detection + visibility, not autonomous intervention

## Performance Metrics

**Velocity:**

- Total plans completed: 72 (v1.0 + v1.1 + v1.2 + v1.2.1 + v1.3 Phase 17)
- Average duration: ~25 min/plan (estimated)
- v1.2 plans completed: 0

**Recent Trend:**

- v1.1: 6 plans in 2 days
- v1.2.1: 11 plans autonomous same-session
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Roadmap Evolution

- Phase 26 added: Dual sensor publishing + offline alarms — SHT30/SCD41 slot topics (fc1/temperature + fc1/humidity as slot 1 SHT30 w/ SCD41 fallback; fc1/temperature_2 + fc1/humidity_2 as slot 2 SCD41 always) + Signal alerts on sensor offline. Motivation: SCD41 RH suspected ~4% high vs external meters; need a live second opinion once SHT30 is replugged.

### Decisions

- [v1.1] fc-system-sync ships /etc config via git — wifi/systemd changes need only `git push fc1/prod`
- [v1.2] Compose v2 first — independent, unblocks FarmOS work on a clean stack
- [v1.2] Camera phase before FarmOS — daily snapshot depends on fc_camera; idle-rate trickle provides scheduled capture
- [v1.2] FarmOS daily report runs on elder-plops (not Pi) — pulls from TimescaleDB + Flask on 8765
- [Phase 14]: SOAK_PASS: true — canonical stall recovery confirmed in 9s via 1Hz graph-poll fix
- [Phase 15-sensor-warmup-grace-period]: SENS-01 promoted from backlog/out-of-scope to active v1.2.1 requirement with Phase 15 traceability
- [Phase 15]: SOAK_PASS: true — WARN->OK transition at 25s post-node-init; no humidifier actuation in grace window; Phase 16 sensor_health topic confirmed live
- [Phase 16-system-health-panel]: Flatten DiagnosticStatus KeyValue[] into plain JS object before WebSocket broadcast for easy browser consumption
- [Phase 16-system-health-panel]: rosReady flips true immediately before node.spin() so it reflects full subscription readiness
- [Phase 16-system-health-panel]: Camera feed light duplicated in strip rather than relocated — preserves inline context in camera panel during soak
- [Phase 16-system-health-panel]: Dedicated WS opened in health view for sensor_health — avoids reworking shared telemetry WS
- [Phase 16]: SMOKE_PASS: true — all 6 lights have labels, live data, and computable states on live stack
- [v1.3 roadmap]: Alert engine lives in bridge (alerter.js) not on Pi — Pi-offline detection requires elder-plops vantage point
- [v1.3 roadmap]: Farmer dashboard is vanilla HTML/CSS/JS served from bridge /farmer — no framework, no build step
- [v1.3 roadmap]: FarmOS data proxied server-side via GET /farmos/summary — avoids CORS and cookie-collision issues
- [v1.3 roadmap]: Phase 17 and Phase 18 are parallel-safe — alerter.js and farmer/index.html share no code
- [v1.3 roadmap]: Phase 19 depends on Phase 18 (extends existing farmer page); Phase 20 depends on Phase 17 being live ≥1 week
- [v1.4 phase-25]: backlog 999.15 rescoped from "unblock snooze receive" into full capture channel (text + audio + images → local Whisper → Anthropic LLM reply); farmOS event writes deferred to follow-up phase (seed SEED-002)
- [v1.4 phase-25]: LLM = Anthropic API; transcription = local dedicated container on elder-plops (no audio leaves the box); single-farmer model preserved (no multi-recipient this phase)
- [v1.4 phase-25]: SPEC.md lives at `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md` (renamed from `999.15-*` on 2026-04-20 so GSD tooling resolves `phase=25` correctly)
- Express 5 uses app.router (not app._router) for route stack inspection in tests
- ffmpeg requires -f mp4 explicit format when output path has non-.mp4 extension
- telemetry column is 'time' aliased as captured_at for db.js caller compatibility
- timelapse network_mode: host matches alerter pattern — TIMESCALE_HOST=localhost resolves via host namespace
- [Phase 25-03] Lazy faster-whisper import + dual-shape transcribe(string|object) bridges Wave 1 capture.js and Wave 0 RED test contracts
- [Phase 25-03] Smoke uses literal /data path (no .resolve()) — symlinked /data on elder-plops would defeat in-container V12 ALLOWED_ROOT
- [Phase 25-04] SYSTEM_PROMPT locked verbatim — changes require new plan; max_tokens=150 caps prompt-injection blast radius (D-12)
- [Phase 25-04] MAX_HISTORY_ROWS=20 cap on 24h history (D-10); slice(-20) keeps oldest-first
- [Phase 25-05] D-03 capture-error indicator narrowed at ship: row.degraded=true persists for transcribe failures (UAT-7) but NOT for LLM-compose failures (UAT-5) — fallback writes only the reply column. Operationally acceptable; gap tracked in deferred-items.md.
- [999.1-01] Extract migration helpers into schema_migration.js (vs guarding module.exports in index.js) — keeps test require pure since index.js calls rclnodejs.init() at top level
- Bridge buffer-replay poller live-path also uses ON CONFLICT DO NOTHING — backfill races with live inserts when reconnect happens mid-second.
- [Phase 28-02] Modes block landed under new fc_controller: scope (alongside /**:) — preserves D-04 back-compat for nodes that don't read modes; last-section-wins for any duplicates
- [Phase 28-02] active_mode: fruiting declared explicitly; D-04 fallback reserved only for stripped-modes-block forks
- [Phase 28-03] Mode-aware control hot path: ModeView + _resolve_active_mode (D-08) + band-aware error projection (D-09) + ramp-to-defended-edge (D-10) + nearest-defended-edge bypass (D-11). PID kernel math byte-identical to Phase 27.
- [Phase 28-03] D-04 back-compat triggered by NaN sentinel on band_low/band_high (math.isnan check); legacy target_humidity + humidity_tolerance synthesize fruiting-shape ModeView when YAML modes block absent.
- [Phase 28-04] current_mode topic + set_mode service + on_set_parameters_callback shipped — defense-in-depth PID range bounds at the rcl boundary mirror the bridge allowlist Phase 28-05 will enforce
- [Phase 28-04] Asymmetric republish: validator queues next-tick drain (rclpy applies param after callback returns); service handler publishes synchronously (param applied before set_parameters returns)
- [Phase 28-04] Rule 1 fix: get_parameters_by_prefix('modes.') returns empty in rclpy Jazzy with trailing dot; use 'modes' (no trailing dot)
- [Phase 28-05] Bridge POST /control/param mounted with lazy rosNode wrapper — pattern template for any future bridge ROS-client route; route registered statically, handler reads module-level rosNode at request time, 503 pre-init
- [Phase 28-05] Bridge allowlist range bounds duplicate Phase 28-04 controller validator (T-28-09 defense in depth) — pid_kp[0,5], pid_ki[0,1], pid_kd[0,20]
- [Phase 28-06] Layer 2 transport pivoted SSH→fc_buffer HTTP relay (D-B1) — bridge container has no ssh binary; fc_buffer owns atomic /var/lib/fc-core/runtime_overrides.yaml write with .bak retention; path allowlist via realpath() defeats traversal+symlink+prefix-lookalike (T-28-20)
- [Phase 28-07] Overlay scope = fc_controller only (D-17); other 5 nodes keep parameters=[LaunchConfiguration('config_file')] verbatim
- [Phase 28-07] PI_HOST default 172.16.10.5 (wg0); fc1-ts removed as stale post-v1.5.0.1 (memory feedback_ssh_tailscale)
- [Phase 28-07] colcon build order in deploy.sh = fc_msgs first, then fc_core (Pitfall 5 explicit)

### Pending Todos

- **Phase 25 pre-gate (NEXT SESSION):** spike `signal-cli` receive-unblock — recommended path is re-register `+59891840205` as primary using 4G router SIM SMS verification (NOT link mode). Receive 400 + identity-trust loss on alerter rebuild discovered live 2026-04-25 during Phase 26 deploy. R1 is load-bearing for the entire bidirectional capture channel; do NOT plan R2-R7 until the spike proves at least one path works. See `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md` § Pre-Gate.
- Phase 17 pre-gate: verify 4G router SMS exposure and complete Signal registration before writing alerter.js
- Phase 18 pre-gate: verify CORS from farmer phone Tailscale IP; audit bridge replay coverage for humidifier initial state
- Phase 19 pre-gate: confirm farm team readiness for FarmOS admin actions or document proxy-around path

### Blockers/Concerns

- **Phase 25 R1 unproven:** signal-cli receive returns HTTP 400 today (linked-secondary device limitation); without R1, none of the capture channel's downstream value is reachable. Requires SIM-bearing 4G router for primary re-registration spike.
- Phase 17: Signal primary-account registration on 4G router SIM is a manual pre-phase step (~1-2h); cannot begin coding until complete
- Phase 19: FarmOS admin actions (FC-1 asset, farmos_agent permissions) depend on farm team availability — document proxy-around path at phase start if admin access is delayed
- Phase 20: Cannot begin cooldown tuning until Phase 17 has been live for ≥1 week

## Deferred Items

Items acknowledged and deferred at v1.4 milestone close on 2026-05-01:

| Category | Item | Status | Note |
|----------|------|--------|------|
| verification | 11-VERIFICATION.md | human_needed | pre-v1.4 carry-forward |
| verification | 12-VERIFICATION.md | human_needed | pre-v1.4 carry-forward |
| verification | 13-VERIFICATION.md | gaps_found | pre-v1.4 carry-forward |
| verification | 16-VERIFICATION.md | human_needed | pre-v1.4 carry-forward |
| verification | 17-VERIFICATION.md | human_needed | pre-v1.4 carry-forward |
| verification | 23-VERIFICATION.md | human_needed | farmer-attested live; doc artifact pending cron + visual confirmation |
| uat | 12-HUMAN-UAT.md | partial — 5 pending | pre-v1.4 carry-forward |
| uat | 16-HUMAN-UAT.md | partial — 0 pending | doc-artifact stale |
| uat | 23-HUMAN-UAT.md | partial — 0 pending | farmer-attested; doc-artifact stale |
| uat | 23-UAT.md | partial — 0 pending | doc-artifact stale |
| uat | 26-HUMAN-UAT.md | partial — 2 pending | both pending items signal-cli-trust blocked, not Phase 26 substance (memory: project_signal_cli_link_gotchas) |
| seed | SEED-001 runtime config delivery | dormant | future-scoped |
| seed | SEED-002 farmOS event writer | dormant | Phase 25 follow-up |
| seed | SEED-003 farmer app MC section | dormant | future-scoped |

**Decision rationale:** all v1.2-era verification/UAT gaps were never material to v1.4 work. v1.4 ships with full farmer attestation on Phases 21-26. Documentation artifacts will be retroactively cleaned up alongside future related work, not as standalone backlog entries.
| Phase 999.1 P01 | 6 | 2 tasks | 4 files |
| Phase 999.1 P03 | 5m25s | 2 tasks | 4 files |
| Phase 28 P01 | 25min | 4 tasks | 8 files |
| Phase 28 P02 | 2m31s | 2 tasks | 2 files |
| Phase 28 P03 | 17min | 2 tasks | 3 files |
| Phase 28 P04 | 12min | 3 tasks | 2 files |
| Phase 28 P05 | 3min | 2 tasks | 3 files |
| Phase Phase 28 PP06 | 10min | 2 tasks tasks | 5 files files |
| Phase 28 P07 | 752s | 3 tasks | 2 files |

## Session Continuity

Last session: 2026-05-08T00:35:16.080Z
Stopped at: Completed 28-07-PLAN.md (awaiting human-verify checkpoint)
Next up: pick from { (a) close 27.2 SYS-01 + SYS-04, (b) cyclonedds-tailscale.xml → cyclonedds.xml rename, (c) PID Kp 0.5 → 0.35 retune per 2026-05-03 calibration notes, (d) resume v1.5 main with /gsd:discuss-phase 28 }

---
*Roadmap phases: v1.0 (1–8), v1.1 (9–10), v1.2 (11–13), v1.2.1 (14–16), v1.3 (17–20), v1.4 (21–26), v1.5 (27–31), v1.5.0.1 (27.1, 27.2)*
*Last updated: 2026-05-04 — v1.5.0.1 realignment after wg0 architectural detour*

**Planned Phase:** 28 (mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con) — 7 plans — 2026-05-07T22:48:42.388Z
