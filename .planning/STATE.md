---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: completed
stopped_at: Phase 999.1 context gathered
last_updated: "2026-05-02T03:07:24.780Z"
last_activity: 2026-05-02
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 9
  completed_plans: 5
  percent: 56
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.
**Current focus:** Phase 27 — pid-time-proportional-duty-cycle-primitive

## Current Position

Milestone: v1.4 — Vision & Growth Insights (5 phases, 2 complete)
Phase: 27
Plan: Not started
Status: Milestone complete
Last activity: 2026-05-02

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

## Session Continuity

Last session: --stopped-at
Stopped at: Phase 999.1 context gathered
Next up: Phase 25 pre-gate spike (signal-cli primary re-registration via 4G router SIM) — must close before `/gsd:plan-phase 25`

---
*Roadmap phases: v1.0 (1–8), v1.1 (9–10), v1.2 (11–13), v1.2.1 (14–16), v1.3 (17–20)*
*Last updated: 2026-04-18 — v1.3 roadmap created*

**Planned Phase:** 999.1 (edge-buffering) — 4 plans — 2026-05-02T03:07:24.774Z
