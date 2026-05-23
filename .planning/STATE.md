---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: Event-gate + Durable signal_outbound (tenant-aware)
status: Phase 44 7/7 done; 44-04 event-gate shipped + operator-attested live-fire PASS (8/10, cache empirically verified); v1.8 ship-ready pending prod alerter rebuild+deploy
last_updated: "2026-05-23T04:00:00.000Z"
last_activity: 2026-05-23
progress:
  total_phases: 26
  completed_phases: 4
  total_plans: 64
  completed_plans: 31
  percent: 48
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-08)

**Core value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.
**Current focus:** Phase 46 SHIPPED 2026-05-21. Next up: choose between Phase 44 (v1.8 first phase) and the sht30 watchdog structural fix.

## Current Position

Phase: 44 — **7/7 COMPLETE 2026-05-23.** Plan-04 event-gate shipped; operator-attested live-fire PASS 8/10 (at floor) with cache empirically verified (1/10 write, 9/10 read, ~$0.05). One bug surfaced live and fixed: Anthropic SDK contract — `signal` belongs in request-options arg, not body params (commit `1429684`). v1.8 ship-ready pending prod alerter rebuild+deploy.

Phase: 46 — **SHIPPED 2026-05-21.** Live-fire attested Round 3 at T0+3min32s. Two extra bugs found and fixed in-flight: D-09 globals-shadow (`86d4340`) + D-10 oobN/oobWindowMin gate (`5f90cc7`). Two backlog items left as todos.
Plan: 3 of 3 complete (46-01, 46-02, 46-03)
Milestone: v1.7 -- Multimodal Signal to FarmOS Events. **Effectively shipped.** Phases 36-43 all complete; only Phase 42 (SHI-on-Sawdust pilot) remains as a calendar-bound human-driven run (3-4wk colonize). Re-audited 2026-05-15.
Last activity: 2026-05-22

**Phase 46 close-out (final):**

- 46-01 shipped 2026-05-21 (bridge fc1LastMsgTs aggregator; 241/241 tests)
- 46-02 shipped 2026-05-21 (alerter chamber-dark wiring; 720/728 tests)
- 46-03 shipped 2026-05-21 with 3-round live-fire:
  - Round 1 (16:27Z–16:54Z): exposed wiring bug (`index.js:227` destructure-drop); fixed in `206f202`. Surfaced D-09 (globals shadow env).
  - Round 2 (18:02Z–18:08Z): D-09 fix shipped (`86d4340`, hard 3-min threshold for fc1LastMsgTs branch). Attestation initially declared PASS but RETRACTED (`52c1d50`) — the 91-char send was sht30 boot-watchdog, not chamber-dark pi. Surfaced D-10 (oobN/oobWindowMin gate blocks fast pi FIRING).
  - Round 3 (23:11Z–23:28Z): D-10 fix shipped (`5f90cc7`, piCfg override). 148-char chamber-dark message at T0+3min32s; ZERO per-sensor sends in silence window; 85-char recovery message on fc1 republish. Farmer paste-back of message body verified verbatim 2026-05-21 ~23:30Z. CD-01..CD-04 all ATTESTED. **Ship-gate RELEASED.**

**Backlog from Phase 46 (do not block ship):**

- `.planning/todos/pending/2026-05-21-alerter-tz-montevideo-and-local-time-rendering.md` — TZ Toronto→Montevideo + hhmm() local-time rendering (currently `@ HH:MM` in chamber-dark message is UTC)
- `[[project_alerter_watchdog_quiet_topic_bug]]` — sht30 structural fix (band-aid restored 2026-05-21 to 1440min)
- Captured memories: `[[project-phase46-d09-globals-shadow-env]]`, `[[feedback-unit-tests-dont-catch-wiring]]`, `[[feedback-verify-signal-send-attribution]]`, `[[project-alerter-tz-toronto-legacy]]`
- Operator-window protocol superseded by live-fire log in 46-03-SMOKE.md
  "Live-fire Attestation" section.

- Don Santiago was the farmer for this smoke (`+59892893012` per
  `[[project_farmer_phone_map]]`); responded "Great" to a sht30 noise alert
  at 16:41:42Z; no out-of-band farmer-paste needed.

**Next milestone (v1.8) is scoped + locked** per 2026-05-17 findings discussion:

1. Phase 1: Event-gate + durable `signal_outbound` table (bundles findings 7 + 1b; ~4-5d). Plan-01 task is the 100-capture hand-classification smoke from `mushdatadump-prod` (per [[smoke-before-expensive-batch]]).
2. Phase 2+: NORTH-STAR commit_failed silent-reply ack fix (finding 3); replay outstanding silent-failure drafts `b8a1e586` (Vikki Rambo) + `1fb28e70` (Santi LIMA) as live-fire UAT.

Reference: [[project_2026_05_17_findings_discussion_decisions]] memory + `.planning/notes/2026-05-17-*.md` research notes.

**Phase 43 (Schema Normalizer) shipped 2026-05-16** — 700 tests green, SCHEMA-01..04 PASS, REVIEW + VERIFICATION artifacts committed.

**Overnight research kicked off as background agents** (results expected by morning):

- `.planning/notes/2026-05-16-schema-audit.md` (Agent A: Phase 38<->Phase 40 schema diff per log_type)
- `.planning/notes/2026-05-16-farmos-no-target-and-strain-coverage.md` (Agent B: farmOS no-target patterns + active-strain coverage gap)

Phase 38 close audit (Plan 09 trail):

- Plan 09 ran 96-fixture re-eval (95 curated + 1 real prod session) -> PASS at 95.8% schema conformance
- Bugs fixed in cycle: whisper GPU drift (restart + cache volume), pipeline image-wire (a04a6bc), fake-green whisper /health (deep probe), extractor maxTokens 2048 -> 16384 default, species-vocab gap (winecap->WIN), harness-pipeline parity (loadImageBlocks exported), real-session fixture in ship-gate denominator, whisper hallucination tail (VAD filter)
- Plan 08 (prod-log advisory eval) superseded by Plan 09
- Total Plan 09 spend: ## Current Position

0.91 paid Anthropic ($5.65 FAIL run-1 + $0.51 smoke + $4.75 PASS run-2)

- Paper trail in .planning/phases/38-extraction-pipeline/38-EVAL-REPORT-plan07.md | -plan09-smoke.md | -plan09-run1-FAIL.md | -plan09-run2-PASS.md
- Prod inoc session corpus at /mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/

Autonomous task #2 (Phase 39 -> 42 v1.7 close): READY to resume; awaiting user signal to re-launch (session has been long, user may want a break).

Phase 37 Plan 04 remains PARTIAL — Tasks 1+2 shipped (7b7256c, 7bff438); Task 3 live attestations deferred to operator per 37-RUNBOOK.md.

Plan 04 progress:

- Task 1 (index.js wire-up + compose env plumbing) — commit 7b7256c
- Task 2 (37-RUNBOOK.md authored) — commit 7bff438
- Task 3 (live attestations A/B/C/D + Phase 33 E) — DEFERRED to operator (cannot be automated; requires three live farmers + operator-authored .env)

## Previous Milestones

**v1.6 — VPS Hub + Outage/Recovery Stack (Shipped 2026-05-10/11; scaffolding deferred)**

**v1.5 shipped 2026-05-09** (audit: `.planning/v1.5-MILESTONE-AUDIT.md`, status tech_debt — 16/17 reqs):
Phases 27 (PID), 28 (mode primitive), 29 (alerter modes), 30 (schedule), 31 (forcing modes).

**v1.6 progress (no REQUIREMENTS.md yet):**

- Phase 32 — VPS multi-purpose hub (WireGuard MVP): SHIPPED 2026-05-10. Hetzner CX22; wg-hub `10.66.0.0/24`; fc1 + elder-plops + farmer #1 (LIVE) + farmers #2/#3 configured.
- Phase 33 — VPS heartbeat receiver + Tier 1 Signal alert: SHIPPED 2026-05-11. Closes backlog 999.43 Tier 1.
- Phase 999.43.1 — ntfy.sh Tier 2 out-of-band push: SHIPPED 2026-05-11 (promoted from backlog). Closes the actual 11h-blind incident class.
- Phase 34 — VPS uptime-kuma outside-in monitoring: SHIPPED 2026-05-11. 4 monitors UP.
- Phase 35 — VPS Tier A backup (age-encrypted nightly tarball): SHIPPED 2026-05-11. ~20KB/day. ⚠ SPOF: `id_ed25519` decrypt key not yet offline (operator-acknowledged, deferred).

**2026-05-11 backlog sweep:** closed 10 items end-to-end (999.41/.22/.39/.40/.31/.32/.36/.24/.42/.49) + filed 999.50 + SEED-009. 5 prod changes deployed live to fc1.

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

- Total plans completed: 79 (v1.0 + v1.1 + v1.2 + v1.2.1 + v1.3 Phase 17)
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
- [37-02] signal.js uses isStringTarget/isGroupTarget boolean discriminators (functional equivalent of PATTERNS.md typeof inline check; required for invalid-target validation gate)
- [37-03] @-prefix-aware command regex + status keyword dropped (no handler exists in snooze.js)
- [37-04] SIGNAL_GROUP_ID is the bare internal_id form, NOT the prefixed group.<...> id form — alerter signal.js wraps internally. 37-SMOKE Probe A documented the 400 failure when passing the prefixed form; 37-RUNBOOK §2 calls this out explicitly.
- [37-04] Boot-log lines `[boot] signal defaultTarget = …` + `[boot] farmer-map entries = N` are operator-visible mitigation for T-37-04-01 (wrong-group leak) and T-37-04-03 (slug-typo mis-attribution); 37-RUNBOOK §5 makes both lines a hard pre-attestation gate.
- [37-04] Tasks 1+2 executed sequentially on main; Task 3 (live attestations) deferred to operator — requires three live farmers + operator-authored .env, none automatable from executor seat.
- [38-01] ObservationLogBase exported (no .refine) alongside ObservationLog (with .refine) — Zod discriminatedUnion requires pure z.object inputs; downstream validator must re-apply state-or-notes check when type==='observation'.
- [38-01] DRAFT_JSON_SCHEMA shape is `{$ref: '#/definitions/Draft', definitions: {Draft: {anyOf: [...]}}}` -- draft-7, Anthropic-compatible as a single JSON object; Plan 03 passes verbatim as tools[0].input_schema.
- [38-01] Activity name enum hardcoded to 7 values (sterilize, sterilize_failed, water, relocate, cold_shock, archive_spent, contam) per CONTEXT D-04.
- [Phase ?]: [38-04] 3-turn cap semantics: currentTurns+1 >= maxAskbackTurns triggers needs_review (off-by-one fix vs plan text)
- [Phase ?]: [38-04] fmtNum exported from message.js (was internal); preview-builder requires it per plan key_links
- [38-07] Plan 03 shipped two API-shape bugs that mocked-client unit tests didn't catch: (a) zod-to-json-schema named output is {$ref, definitions} but Anthropic input_schema requires top-level type=object (fix: inlineTopLevelRef in extractor.buildToolSpec); (b) few-shot tool_use blocks had no matching tool_result in following user turns (fix: tool_result blocks closing tu_fewshot_1/2 in system.js + tu_fewshot_3 prepended in extractor.buildInitialUserContent). Backlog candidate: live-API smoke test in CI/pre-deploy.
- [38-07] Ground-truth adaptation: mushdatadump v1.6 CSVs are page-grain (829 entries across 73 JPEGs), NOT per-image. Aligning rows to JPEG regions requires OCR (out of scope). Eval reduced to per-image schema-validity + B5 regex-validity + confidence calibration; richer per-event ground truth deferred to Plan 08.
- [38-07] Eval verdict: PASS (100% schema conformance, 100% combined field-or-ask-back across 73 fixtures; 48/73 produced regex-valid B5 block_names; wall time 742s; cost ~$1-3 with prompt caching).
- [Phase ?]: 44-05: D-17 supersession — fmtHistory stops reading signal_capture.llm_reply (column kept for audit)
- [Phase ?]: 44-05: D-18 truncation — inbound 200ch / outbound 400ch per-stream caps in merged fmtHistory
- [Phase ?]: 44-05: D-19 prompt field — lastBotOutbound rendered as distinct '## Last thing you said to the farmer' block
- [Phase ?]: Phase 44-06 path B: alerter secrets via env_file — tenants/mossrock/secrets.env (required:false); root .env retains shared secrets until v1.9
- [v1.8 lesson, 44-04]: Anthropic SDK contract surprise — `signal` belongs in the request-options second arg of `client.messages.create(body, opts)`, NOT inside `body`. The SDK strict-validates the body schema and rejects unknown keys with 400 `invalid_request_error`. jest.fn() unit mocks accept any param shape, so this is invisible until a real SDK touches a real API. Caught by EVAL_RUN_LIVE=1 live-fire on round 1; fixed in `1429684` (test flipped from codifying-the-bug to asserting-SDK-correct-shape). Reinforces [[feedback_unit_tests_dont_catch_wiring]] — live-fire is the real ship-gate.

### Pending Todos

- **Phase 25 pre-gate (NEXT SESSION):** spike `signal-cli` receive-unblock — recommended path is re-register `+59891840205` as primary using 4G router SIM SMS verification (NOT link mode). Receive 400 + identity-trust loss on alerter rebuild discovered live 2026-04-25 during Phase 26 deploy. R1 is load-bearing for the entire bidirectional capture channel; do NOT plan R2-R7 until the spike proves at least one path works. See `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md` § Pre-Gate.
- Phase 17 pre-gate: verify 4G router SMS exposure and complete Signal registration before writing alerter.js
- Phase 18 pre-gate: verify CORS from farmer phone Tailscale IP; audit bridge replay coverage for humidifier initial state
- Phase 19 pre-gate: confirm farm team readiness for FarmOS admin actions or document proxy-around path

### Blockers/Concerns

- **Phase 46 D-09 (HUMAN DECISION):** runtime globals `pi_offline_min=15` from
  `src/chambers/fc-core/config/fc_config.yaml:137` (TRANSIENT_LOCAL replayed
  by bridge to alerter) makes chamber-dark TTF ~23min minimum, structurally
  too slow for the deterministic data-flow trigger. Need either: (a) hard-code
  <3min in `rules.js:isPiOffline` fc1LastMsgTs branch independent of
  `piOfflineMin`, (b) introduce a separate `fc1_dark_min` global, or
  (c) treat env-var as a hard floor that globals cannot exceed. Decision
  required before CD-02/CD-03 fully close. See 46-03-SMOKE.md "D-09 finding".

- **Phase 25 R1 unproven:** signal-cli receive returns HTTP 400 today (linked-secondary device limitation); without R1, none of the capture channel's downstream value is reachable. Requires SIM-bearing 4G router for primary re-registration spike.
- Phase 17: Signal primary-account registration on 4G router SIM is a manual pre-phase step (~1-2h); cannot begin coding until complete
- Phase 19: FarmOS admin actions (FC-1 asset, farmos_agent permissions) depend on farm team availability — document proxy-around path at phase start if admin access is delayed
- Phase 20: Cannot begin cooldown tuning until Phase 17 has been live for ≥1 week

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260518-tbi | 999.53: persist Anthropic token usage in signal_capture for cost visibility | 2026-05-19 | a3ec164 | [260518-tbi-999-53-persist-anthropic-token-usage-in-](./quick/260518-tbi-999-53-persist-anthropic-token-usage-in-/) |
| 260518-tcj | 999.51 (partial): align bridge control_experiment test srvName with live un-namespaced paths | 2026-05-19 | f1a4331 | [260518-tcj-999-51-mechanical-bridge-srvname-fix](./quick/260518-tcj-999-51-mechanical-bridge-srvname-fix/) |
| Phase 44 P00 | 5min | 4 tasks | 11 files |
| Phase 44 P05 | 12min | 2 tasks | 5 files |
| Phase 44 P06 | 25 | 3 tasks | 7 files |
| Phase 44 P03 | 5m44s | 2 tasks | 9 files |

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
| Phase Phase 37 P02 P37-02 | 12min | 3 tasks | 6 files |
| Phase 37 P03 | 25min | 3 tasks | 4 files |
| Phase 38 P01 | 12min | 3 tasks | 8 files |
| Phase 38 P04 | 25min | 3 tasks | 7 files |
| Phase 38 P06 | 8min | 2 tasks | 3 files |
| Phase 38 P07 | 70min | 2 of 3 tasks | 9 files (incl. 2 Plan 03 Rule 1 fixes) |

## Session Continuity

Last session: 2026-05-23T04:00:00.000Z
Next up: v1.8 ship cutover — rebuild+deploy alerter on elder-plops (`docker compose up -d --build alerter`) to ship Phase 44 event-gate to prod; confirm boot logs + first capture; optional 24-h soak before declaring v1.8 shipped. Then Phase 45 (NORTH-STAR commit_failed ack + replay outstanding silent-failure drafts).

Previously: kick off v1.8 Phase 1 (event-gate + signal_outbound). Plan-01 = 100-capture hand-classification smoke from mushdatadump-prod, BEFORE spec-locking the gate. Reference notes:

  - .planning/notes/2026-05-17-is-this-an-event-gate.md (event-gate design)
  - .planning/notes/2026-05-17-llm-outbound-amnesia.md (signal_outbound table shape)
  - [[project_2026_05_17_findings_discussion_decisions]] (scope lock)

v1.7 phase order (hard sequencing):
  Phase 36: Signal Pre-gate — MUST ship before anything else (PRE-01/02)
  Phase 37: Multi-farmer Routing — MUST ship before extraction (ROUTE-01..03)
  Phase 38: Extraction Pipeline — can start after 37 (EXT-01..05)
  Phase 39: Farmer Confirmation Loop — after 38 (CONF-01..05)
  Phase 40: FarmOS Write Path — after 39; parallel-safe with 38/39 against fixtures (FOS-01..06)
  Phase 41: Ingestion Harness — after 38; parallel-safe with 40 (INGEST-01..04)
  Phase 42: SHI-on-Sawdust Pilot — last; requires 40+41+39 (PILOT-01..06)

---
*Roadmap phases: v1.0 (1–8), v1.1 (9–10), v1.2 (11–13), v1.2.1 (14–16), v1.3 (17–20), v1.4 (21–26), v1.5 (27–31), v1.5.0.1 (27.1, 27.2), v1.6 (32–35 + 999.43.1) — scaffolding deferred*
*Last updated: 2026-05-11 — post v1.6 outage+recovery stack ship + backlog sweep*

**Last completed:** Phase 35 (vps-tierA-backup) SHIPPED 2026-05-11

**Planned Phase:** 37 (multi-farmer-routing) — 4 plans — 2026-05-11T20:23:31.281Z
