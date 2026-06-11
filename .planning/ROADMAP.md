# Roadmap: Mushroom Farm — FC-1 Humidity Control (and beyond)

## Milestones

- ✅ **v1.0 MVP — FC-1 Humidity Control** — Phases 1–8 (shipped 2026-04-11)
- ✅ **v1.1 Tech Debt & Connectivity** — Phases 9–10 (shipped 2026-04-12)
- ✅ **v1.2 FarmOS Integration & QoL** — Phases 11–13 (shipped 2026-04-13)
- ✅ **v1.2.1 Hotfix — camera stall + sensor warmup** — Phases 14–16 (shipped 2026-04-18)
- ✅ **v1.3 Alerts & Unified Farmer Dashboard** — Phases 17–18 (shipped 2026-04-19; Phases 19/20 externally gated → v1.5)
- ✅ **v1.4 Vision & Growth Insights** — Phases 21–26 (shipped 2026-05-01; Phase 24 deferred behind backlog 999.26 camera coverage)
- ✅ **v1.5.0.1 Resilience hotfix from 2026-05-02 incident** — Phases 27.1 + 27.2 (shipped 2026-05-07 via wg0 architectural detour; 27.3 + 27.4 MOOTED). See `.planning/milestones/v1.5.0.1-ROADMAP.md`.
- ✅ **v1.5 Analog Humidity Control & Condensation/Evaporation Forcing** — Phases 27–31 (shipped 2026-05-09; ALRT-10 calendar-deferred). See `.planning/milestones/v1.5-ROADMAP.md`.
- ✅ **v1.6 VPS Hub + Outage/Recovery Stack** — Phases 32–35 + 999.43.1 (shipped 2026-05-10/11; scaffolding deferred). See `.planning/milestones/v1.6-ROADMAP.md`.
- 🚧 **v1.7 Multimodal Signal → FarmOS Events** — Phases 36–43 (effectively shipped 2026-05-16; Phase 42 calendar-deferred — biological lifecycle)
- ✅ **v1.8 Event-gate + Durable `signal_outbound` (tenant-aware)** — Phases 44–46 (shipped 2026-05-23; OSS-Foray Option α — every PR ships tenant_id-aware from day one)
- ✅ **v1.9 Inoc-Session Correctness** — Phases 47–50 (shipped 2026-05-23; INOC-01..07 + QUOT-01..06 hermetic-attested; live-fire & May-22 reprocess operator-deferred via runbooks)
- ✅ **v1.10 Order-Independent Writes (upsert-by-stable-identity)** — Phase 51 (shipped 2026-05-24; UPSERT-01..07 all verified; live-fire on dev farmOS: 16 assets patched / 0 created, 11 logs patched / 0 created, zero duplicates). See `.planning/milestones/v1.10-ROADMAP.md`.
- 📋 **v1.10.1 Session-Entity Adoption (asset--group)** — Phase 52 (planned 2026-05-24; reverses Phase 48 "no session entity" interim now that farmos team enabled `farm_group` on dev+prod, commit `1857037`; session = `asset--group`, membership = `activity` log with `is_group_assignment=true`).
- 📋 **v1.11 2025-Notebook Backfill** — Phases 53–55 (planned 2026-05-24; runs the mushdatadump 2025 paper-log corpus through the now-unblocked extraction+upsert pipeline; gated on Phase 38 batch-mode fix + year-context shim).
- 📋 **v1.12 Farm-Agent Python Port** — Phases 56–? (planned 2026-05-24; ports the Node alerter/extraction stack to Python, unblocks Phase 50 wire-level quote-rendering bugs deferred from v1.9, sets up Foray v2.0 surface).
- 📋 **v1.13 Auto-Commit Narrowing** — Phases TBD (planned 2026-05-24; carves per-shape auto-commit lanes gated on ≥99% historical YES rate + n≥50, with UNDO + auto-demotion; structurally depends on v1.11 generating the confirm corpus).

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-8) — SHIPPED 2026-04-11</summary>

- [x] Phase 1: Pi Integration & Environment (5/5 plans) — 2026-03-29
- [x] Phase 2: Safety Hardening (4/4 plans) — 2026-03-30
- [x] Phase 3: Closed-Loop Control (3/3 plans) — 2026-04-04
- [x] Phase 4: Observability & Integration (2/2 plans) — 2026-04-04
- [x] Phase 5: Production Deployment (2/2 plans) — 2026-04-11 (grower-attested)
- [x] Phase 6: WireGuard / Tailscale ROS routing (3/3 plans) — 2026-03-29
- [x] Phase 7: Historical Data & OpenMCT time-series (2/2 plans) — 2026-04-07 (regression fixed 2026-04-11)
- [x] Phase 8: Pi Camera Feed in Mission Control (4/4 plans) — 2026-04-09

Grower verdict 2026-04-11: "better than the timer". Unexpected star of the
show: SCD41 CO2 readings (no prior CO2 instrumentation at the farm).

</details>

<details>
<summary>✅ v1.1 Tech Debt & Connectivity (Phases 9-10) — SHIPPED 2026-04-12</summary>

- [x] Phase 9: Connectivity & Boot Stability (4/4 plans) — 2026-04-11
- [x] Phase 10: Bridge QoS & MJPEG Delivery (2/2 plans) — 2026-04-12

Closed all v1.0 carryover tech debt (TDEBT-01/02/03) and established 4G
cellular connectivity (CONN-01). fc-system-sync ships /etc config via git.

</details>

<details>
<summary>✅ v1.2 FarmOS Integration & QoL (Phases 11-13) — SHIPPED 2026-04-13</summary>

- [x] Phase 11: Compose v2 Upgrade (1/1 plans) — 2026-04-13
- [x] Phase 12: Subscriber-Aware Camera (2/2 plans) — 2026-04-13
- [x] Phase 13: FarmOS Daily Report (4/4 plans) — 2026-04-13

Compose v2 on elder-plops, subscriber-aware camera (idle 1/hr, active 1fps),
FarmOS daily report agent (ROS2 lifecycle node, TimescaleDB aggregation,
camera snapshot). Known gaps: FarmOS admin actions pending (permissions,
FC-1 location), Phase 12 hardware UAT pending.

</details>

<details>
<summary>✅ v1.2.1 Hotfix — camera stall + sensor warmup (Phases 14-16) — SHIPPED 2026-04-18</summary>

- [x] Phase 14: fc_camera idle-mode stall hotfix (5/5 plans) — 2026-04-17
- [x] Phase 15: Sensor warm-up grace period (3/3 plans) — 2026-04-17
- [x] Phase 16: System health panel (3/3 plans + 16.1 replay shim) — 2026-04-18

Filed during a farmer debug session; shipped autonomously same-session with
farmer-attested "all green" on 2026-04-18. See `.planning/milestones/v1.2.1-ROADMAP.md`.

</details>

<details>
<summary>✅ v1.4 Vision & Growth Insights (Phases 21-26) — SHIPPED 2026-05-01</summary>

- [x] Phase 21: Camera history continuous persistence (4/4 plans) — 2026-04-19
- [x] Phase 22: Timeline scrubber + farmer story view (4/4 plans) — 2026-04-19
- [x] Phase 23: Time-lapse composition (ffmpeg) (3/3 plans) — 2026-04-27
- [ ] Phase 24: ML vision events via ComfyUI — **DEFERRED 2026-05-01** behind backlog 999.26 (camera coverage)
- [x] Phase 25: Bidirectional Signal — farmer↔robot capture channel (5/5 plans) — 2026-04-28 (7/7 farmer UATs PASS)
- [x] Phase 26: Dual sensor publishing + offline alarms — SHT30/SCD41 (3/3 plans) — 2026-04-29 (UAT-8 PASS)

CV pipeline foundation, bidirectional Signal "Field Notes" channel, dual-sensor visibility. SCD41 RH known to clip at 100% — SHT30 is RH source of truth. Phase 24 (ML vision) explicitly deferred behind camera coverage prereq. See `.planning/milestones/v1.4-ROADMAP.md`.

</details>

<details>
<summary>✅ v1.5.0.1 Resilience hotfix — Phases 27.1 + 27.2 — SHIPPED 2026-05-07 (PARTIAL)</summary>

Hotfix milestone driven by the 2026-05-02 blackout + DERP-relay incident. Original 4-phase shape was overtaken by an architectural detour: fc1 microSD replaced, rebuilt on home-LAN wifi with kernel-WG tunnel through pfSense (172.16.10.0/24); DDS switched from `tailscale0` to `wg0`. fc1 load avg 5+ → 0.41.

- [x] Phase 27.1: Edge buffering (4/4 plans) — shipped 2026-05-03 over wg0; BUF-04 attestation deferred → 999.36
- [x] Phase 27.2: fc-core systemd hardening (1/1 plan) — shipped 2026-05-07 (cold-reboot SYS-04 scenario 1 PASS 41s); SYS-04 scenario 2 deferred → 999.28
- [—] Phase 27.3: Sampling-rate reduction — MOOTED by transport switch
- [—] Phase 27.4: Netplan reconciliation — MOOTED until fc1 returns to farm-4G

See `.planning/milestones/v1.5.0.1-ROADMAP.md` and `.planning/milestones/v1.5.0.1-REQUIREMENTS.md` for the full archive.

</details>

<details>
<summary>✅ v1.5 Analog Humidity Control & Condensation/Evaporation Forcing (Phases 27-31) — SHIPPED 2026-05-09</summary>

- [x] Phase 27: PID + time-proportional duty-cycle primitive (5/5 plans) — 2026-05-02 (farmer-attested HUMID-04)
- [x] Phase 28: Mode primitive + 2 baseline modes + runtime config delivery (7/7 plans) — 2026-05-07/08 (MODE-01..05; 86 pytest + 156 jest GREEN)
- [x] Phase 29: Alerter mode awareness + cooldown tuning (7/7 plans) — 2026-05-08 (ALRT-08/09 ✓; ALRT-10 calendar-deferred to backlog 999.20)
- [x] Phase 30: Time-of-day mode scheduling (3/3 plans) — 2026-05-09 (SCHED-01..03; Layer 1+2 smoke PASSED; farmer attestation of 30-03-SMOKE.md pending)
- [x] Phase 31: Experimental forcing modes (4/4 plans) — 2026-05-09 (EXPT-01..03; bridge curl path PROVEN E2E; Signal command path blocked on pre-existing signal-cli deviceId=2)

16/17 requirements satisfied; 1 calendar-deferred (ALRT-10). Cross-phase integration verified live. See `.planning/milestones/v1.5-ROADMAP.md` and `.planning/v1.5-MILESTONE-AUDIT.md`.

</details>

<details>
<summary>✅ v1.6 VPS Hub + Outage/Recovery Stack (Phases 32-35 + 999.43.1) — SHIPPED 2026-05-10/11</summary>

- [x] Phase 32: VPS multi-purpose hub (WireGuard MVP) (1/1 plans) — 2026-05-10 (Hetzner CX22; wg-hub; fc1 + elder-plops + farmer #1 LIVE)
- [x] Phase 33: VPS heartbeat receiver + Tier 1 Signal alert (scaffold + deploy) — 2026-05-11 (Tier 1 E2E PROVEN)
- [x] Phase 999.43.1: ntfy.sh Tier 2 out-of-band push (promoted) — 2026-05-11 (Tier 2 E2E PROVEN; closes 11h-blind class)
- [x] Phase 34: VPS uptime-kuma outside-in monitoring (infra + seed) — 2026-05-11 (4 monitors UP)
- [x] Phase 35: VPS Tier A backup — small irreplaceable bits (ship) — 2026-05-11 (~20KB/day age-encrypted; SPOF id_ed25519 deferred)

Full retroactive snapshot: `.planning/milestones/v1.6-ROADMAP.md`. Companion 2026-05-11 backlog sweep closed 10 items (999.41/.22/.39/.40/.31/.32/.36/.24/.42/.49).

</details>

<details>
<summary>🚧 v1.7 Multimodal Signal → FarmOS Events (Phases 36-43) — IN PROGRESS</summary>

- [x] **Phase 36: Signal Pre-gate** — signal-cli primary re-registration; receive unblock; identity-trust verified (shipped 2026-05-13; SC#1 attested twice T0+T+38h; SC#2 closed 2026-05-16 via 2026-05-15 Vikki Rambo organic round-trip; SC#3 rebuild-trust PASS)
- [x] **Phase 37: Multi-farmer Routing** — DM routing to sender; group-thread participation; farmOS person lookup
- [x] **Phase 38: Extraction Pipeline** — schema-aware LLM extraction; multimodal fusion; confidence loop; lineage (reopened then re-closed 2026-05-12 via Plan 09: 95.8% schema conformance on 96-fixture eval including real prod inoc session)
- [x] **Phase 39: Farmer Confirmation Loop** — confirm-before-write; idempotent commit; EDIT loop; draft timeout (shipped 2026-05-13; 127 unit + 11 integration PASS; live-farmer UAT deferred to 39-RUNBOOK.md)
- [x] **Phase 40: FarmOS Write Path** — API client; asset + log creation; QR binding; photo upload; audit log (code-complete 2026-05-13; 92/92 unit PASS; live dev-farmOS integration + prod-fixture SHIP GATE deferred to operator per 40-RUNBOOK.md)
- [x] **Phase 41: Ingestion Harness** — synthetic corpus; paper-log replay; audio replay; cross-stream consistency (shipped 2026-05-13; 37 PASS + 5 operator-deferred live; mushdatadump-prod hand-labels + audio + paired-sessions in 41-RUNBOOK.md)
- [~] **Phase 42: SHI-on-Sawdust Pilot** — SCAFFOLDING SHIPPED 2026-05-13 (3 tools + 23 tests + RUNBOOK + PILOT-LOG + VERIFICATION); actual pilot run calendar-deferred 4-8 weeks per 42-VERIFICATION.md (status: human_needed). Operator drives PILOT-01..06 against real mushroom lifecycle.
- [x] **Phase 43: Phase 38↔40 Schema Normalizer + Chain Integration Tests** — router-side normalizer (Option A) + 5-log_type extractor→commit chain tests (Option C) per `.planning/notes/2026-05-16-schema-audit.md`. Filed 2026-05-16 as carryover from 2026-05-15 lion's-mane `commit_failed` regression. Ungated by farmer-facing acks per locked decision 2026-05-17. SHIPPED 2026-05-16 — 700 tests green; Test 2 is the named regression guard; SCHEMA-04 attested.

</details>

<details>
<summary>🚧 v1.8 Event-gate + Durable signal_outbound (tenant-aware) (Phases 44-45) — IN PROGRESS</summary>

Locked 2026-05-17 per `.planning/notes/2026-05-17-oss-foray-decision.md` and prior `[[project_2026_05_17_findings_discussion_decisions]]` memory. Bundles findings 7 (phantom drafts from chit-chat / is-this-an-event gate) + 1b (LLM outbound amnesia / durable signal_outbound) + 3 (NORTH-STAR commit_failed silent-reply ack). First milestone under OSS-Foray Option α — every new schema ships with `tenant_id` from day one so the v2.0 Foray Apache-2.0 extraction is a clean carve, not a 9-months-of-ALTERs ops event.

- [x] **Phase 44: Event-gate + durable `signal_outbound` (tenant-aware)** — 7/7 plans complete 2026-05-23. Rules-only event gate at `capture.js:147` + `signal_outbound(tenant_id, intent, ...)` table + Phase 37 prompt consumes `lastBotOutbound`; ship-gate is 100-capture hand-classification smoke from prod corpus (Plan-01); per-tenant config tree under `tenants/mossrock/`. Plan-04 operator-attested live-fire PASS 2026-05-23: 8/10 agreement (at floor), cache empirically verified (1/10 write + 9/10 read, ~$0.05). One Anthropic SDK-contract bug surfaced live and fixed (`1429684`: `signal` belongs in request-options arg, not body). v1.8 ship-ready pending prod alerter rebuild+deploy. References `.planning/notes/2026-05-17-is-this-an-event-gate.md` + `.planning/notes/2026-05-17-llm-outbound-amnesia.md`.
- [x] **Phase 45: NORTH-STAR commit_failed ack + replay outstanding silent-failure drafts (5/5 plans)** — SHIPPED 2026-05-23. Every terminal state post-farmer-YES now produces a farmer-facing reply on prod (T4 success + T6 failed). Original 2026-05-15 violation closed: Vikki + Santi acks delivered, 3 ack-debt extras swept to Santi (2026-05-13/15/21). ACK-01..04 satisfied. Follow-ons: runtime `sender_name` enrichment in commit-watchdog (renderer reads it but schema lacks it; backfill patched via SIGNAL_FARMER_MAP); ack-debt sweep tooling; Vikki farmer-paste verification (operator-deferred — receipt database-attested via signal_outbound row).
- [x] **Phase 46: Chamber-dark detector — real fc1-liveness signal + farmer-readable pi-offline message** — Shipped 2026-05-21. Live-fire attested Round 3 at T0+3min32s. Two extra bugs found and fixed during smoke: D-09 globals-shadow (commit `86d4340`) and D-10 oobN/oobWindowMin gate (commit `5f90cc7`). Hotfix from 2026-05-20 fc1 outage debug session. `isPiOffline` keys off alerter↔bridge WS + a one-shot `rosReady` boot flag; neither reflects fc1 publisher liveness, so during fc1's 10h47m blackout the only Signal alert that fired was "co2 sensor offline" (per-sensor, vague). Fix: bridge tracks `fc1LastMsgTs` across all fc1 topics + exposes in `/health`; alerter consumes as a third OR-trigger for `isPiOffline`; `formatProblem('pi')` becomes chamber-level using the `lastKnown` payload `state.js` already builds. References `.planning/debug/alerter-co2-only-not-pi.md`.

</details>

<details>
<summary>📋 v1.9 Inoc-Session Correctness (Phases 47-49) — SCAFFOLDED 2026-05-22; planning deferred until v1.8 ships</summary>

Driver: 2026-05-22 paper-log session exposed that Phase 38's eval set lacked the canonical multi-parent inoc shape (N children from M>1 parents in one session — *the* common shape per `[[project_inoc_shape_multi_parent_batch]]`). 10 of 11 bags fell on the floor. This milestone fixes the structural gap and adds real-session eval coverage. Ship gate: the May 22 audio+photo reprocessed end-to-end → 11 correctly-named seeding logs + 1 session asset in farmOS dev, lineage walks clean.

Honors locked schema (B5 SEQ per-session per 2026-05-22 clarification in farmos repo `8daea5b`, B7 native log types only, C4 multi-parent via log refs, C5 native-only). Operates under [[feedback_hard_rules_relaxed_when_farmer_is_santi]] — Phase 45 NORTH-STAR ack remains in v1.8 scope.

- [x] **Phase 47: Multi-source extraction fusion + groups-shape inoc draft (5/5 plans)** — SHIPPED 2026-05-23. New top-level `seeding_session` draft type with inline-provenance fields per Gray Area 1+2 locks. Live-fire on real 2026-05-22 captures (audio+photo+text from prod) recognized all 5 parents (`260304_SHI_5`, `260118_SHI_23`, `260118_SHI_26`, `260118_KOY_12`, `260425_KOY_4`) + correct 1/1/1/4/4 = 11 child distribution + emitted Gray-Area-3 ask-back path (model conservatively asked for starting SEQ rather than auto-deriving from row positions; friction-policy-correct). Conflict UX is silent-photo-wins per Gray Area 4 (overrides memory `[[extraction-holistic-multi-source-fusion]]` rule 2). Implements INOC-01,02,03,05; INOC-04 (single-parent legacy → groups.length===1) carries forward to Phase 48.
- [x] **Phase 48: Session entity + per-bag commit fan-out + session-shaped confirm preview (5/5 plans)** — SHIPPED 2026-05-23. `commitSeedingSession` handler with asset-first preflight + N-child fan-out + all-or-nothing orphan cleanup (reverse-order DELETE on partial failure). Session asset is anonymous `fungi` named `inoc YYYY-MM-DD` with `allowNoFungiType:true`. Each child seeding log carries `parent[]=[sourceBlock, sessionAsset]` (source primary, session secondary) per locked Gray Area B. Idempotency on `signal_draft.id` + cached `farmos_response` (Phase 40 design; no separate `signal_commit` table — CONTEXT memory drift reconciled). `renderSeedingSession` produces compact group-by-parent table with range-collapse + overflow folding, ASCII-only no em-dashes. Phase 45 ack contract extended with `seeding_session` LOG_TYPE_LABEL + 3 reasonMap entries + session-shaped success/failed renderer. Hermetic ship-gate: 7/7 integration tests green (May-22 happy path + single-parent legacy + partial-fail + double-YES idempotent); full `test/farmos` 207/207. Live-fire operator-deferred (48-LIVE-FIRE.md, gated `EVAL_RUN_LIVE=1`). Implements INOC-04, INOC-05, INOC-06.
- [x] **Phase 49: Real-session eval corpus + May 22 ship-gate reprocess (4/4 plans)** — SHIPPED 2026-05-23. `signal_draft` gains `discarded_reason` + `discarded_at` columns. CI eval corpus expands to 3 sessions under `test/eval/ingestion/fixtures/sessions/`: 2026-05-22 (named regression guard, 5 groups / 11 children), 2026-05-12 inoc-santi (named regression guard, Phase-38 Plan-09 hand labels), 2026-03-23 photo-absent synthetic-envelope (broaden corpus, exercises `needs_input='starting_seq'` path). New `sessions.test.js` (`it.each(NAMED)`) hermetic via mock-extractor, real extractor gated `EVAL_RUN_LIVE=1`. `scripts/discard-drafts.js` CLI: dry-run default + `--apply` + idempotent (`WHERE status != 'discarded'`) + 12/12 unit tests. `49-SHIP-GATE.md` operator runbook provides exact `psql`/`discard-drafts.js --apply`/EVAL_RUN_LIVE reprocess/lineage-walk/Phase-45-ack-verification commands for the May-22 reprocess to farmOS dev (operator-deferred per locked Gray Area D). INOC-07 hermetic-attested; live ship-gate ready-to-attest. Implements INOC-07.
- [x] **Phase 50: Signal-native quote threading for ack and reply routing (5/5 plans)** — SHIPPED 2026-05-23. Three new schema columns (`signal_outbound.signal_msg_ts`, `signal_capture.signal_msg_ts`, `signal_capture.{quote_msg_ts, quote_author_e164}`) plus a partial index on outbound. `signal.js send()` carries `quote:{timestamp, author, message}` payload through to /v2/send (spike-verified `0.14.2`); on success persists native ts. Outbound dispatch at the two highest-traffic acks (`send_commit_outcome_ack` + `send_confirm_ack`) fetches source capture quote target via `tryBuildQuoteForDraft`; FAIL-OPEN — null capture/ts logs warning, sends unquoted (no exception). Inbound receive-loop persists native + quote columns at capture time. New `findDraftByQuotedMsgTs` resolver. Routing patch in `receive-loop.js` implements CONTEXT D-04 algorithm verbatim: quote→actionable routes to that draft; quote→terminal dispatches `send_quote_closed` polite-close; quote→orphan or no-quote falls through; >1 active AND no quote fires `send_ask_back` numbered fallback. T-50-04-01 sender-equality spoof guard. 1024/1033 alerter tests green. QUOT-01..06 hermetic-attested. `50-LIVE-FIRE.md` operator runbook ready (10 numbered steps; 4 round-trip scenarios). Live-fire operator-deferred. Implements QUOT-01..06.

</details>

## v1.10.1 Session-Entity Adoption (Phase 52) — PLANNED 2026-05-24

**Driver:** farmOS team enabled the `farm_group` module on dev (`:18080`) and prod (`:8082`) farmOS — committed as `1857037` on the farmos repo. This reverses today's Phase 48 interim, where the seeding-session commit handler had to be stripped of its session-asset preflight after the original `asset--fungi` lock got HTTP-422'd by `fungi_type NOT NULL`. See `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-24-farm-group-enabled-reply-to-mushy.md` for the smoke evidence and the API-shape correction (there is no `log--group` bundle — canonical pattern is `log--activity` with `is_group_assignment: true`).

**Strategic role:** Drops cleanly into v1.11 backfill so every 2025 notebook session lands as a real persistent group entity from day one (much cheaper than retrofitting later). Also composes with `[[feedback_farmer_is_reality_source_of_truth]]` — session-level observations get a real entity to attach to.

**Boundary:** intentionally tiny. Only re-introduces the session-asset preflight (this time creating `asset--group`) and the membership-log call. Does not touch v1.11 backfill scope, does not touch the open Phase 38 batch-mode bugs, does not promote prod write (`FARMOS_INTEGRATION=0` stays).

### Phase 52: Session entity via asset--group + activity-log membership

**Goal:** A confirmed groups-shape draft commits with one `asset--group` named `inoc YYYY-MM-DD` as the session entity, plus N per-block seeding logs (one per child, parent = source block only), plus one `log--activity` with `is_group_assignment=true` that lists the N children under the session group. Children carry NO `parent[]` edge to the session — membership lives on the membership log, not on the asset.

**Requirements:**

- SESSION-01: `commit-seeding-session.js` preflight: lookup-or-create the session group asset by name (composes with Phase 51 upsert — group assets are upserted by name too). Anonymous-by-default; structured notes carry draft id provenance.
- SESSION-02: After children created, POST a single `log--activity` carrying `is_group_assignment: true`, `relationships.asset.data[]` = child UUIDs, `relationships.group.data[]` = [sessionGroupId], timestamp = the session event_date day-grain epoch the seeding logs already use.
- SESSION-03: Children's `parent[]` stays single-source (the source block). NO secondary parent edge to the session group. Lineage walk from a child returns its strain ancestry; "what session was this in?" answered by a query against the membership log.
- SESSION-04: All-or-nothing semantics preserved — if the membership log POST fails, the session asset + N children + N seeding logs all get reverse-order cleanup (Phase 48 partial-failure pattern extends to 1 extra entity + 1 extra log).
- SESSION-05: Idempotency preserved — duplicate YES on the same draft hits the cached farmos_response per Phase 40 audit; no double-creation of session asset or membership log.
- SESSION-06: Same-day collision naming — `inoc YYYY-MM-DD` then `inoc YYYY-MM-DD #2` etc. (carry the original Phase 48 `_resolveSessionName` logic, simplified for group assets).
- SESSION-07: Hermetic ship-gate — Phase 48 integration suite extended: 17 asset POSTs (1 group + 5 source + 11 children) + 12 logs (1 activity-with-flag + 11 seeding); 7/7 scenarios green including double-YES idempotent and partial-fail orphan cleanup.
- SESSION-08: Live-fire ship-gate — re-run `scripts/live-fire-48.js` (or sibling) against dev farmOS with the new shape; session group asset queryable, membership walk via `GET /api/log/activity?filter[is_group_assignment]=1&filter[asset.id]=<child>` returns the right group.

**Depends on:** farm_group enabled on both dev + prod (DONE — `1857037`). No active mushy-side blockers.

**Touches:** `src/agents/alerter/src/farmos/commits/commit-seeding-session.js`, new `src/agents/alerter/src/farmos/group-membership.js` (or extension of `logs.js`), `assets.js` group-asset helpers (likely a thin `upsertGroupAsset` sibling of `upsertFungiAsset`), tests across `test/farmos/`, possibly the audit-logger schema if "session group asset" becomes a logged dimension.

**Constraints:**

- Honors C4 (lineage via log refs, not asset properties) — membership lives on a log, not an asset field.
- Composes with Phase 51 upsert — group assets are content-addressable by name, same merge layer.
- Honors the substrate log-only lock — group asset is not a substrate, doesn't collide.
- Optional follow-on: backfill the 11 dev children from today's 48-LIVE-FIRE into a retro group (per the farmos-side note's open item #5). Not gating; can be done as a one-liner script during/after Phase 52 ships.

**Plans:** 5 plans

- [ ] 52-01-PLAN.md — groupAssets.js module (findGroupAssetByName + upsertGroupAsset + deleteGroupAsset)
- [ ] 52-02-PLAN.md — activityLogs.js module (createGroupAssignmentLog with is_group_assignment=true)
- [ ] 52-03-PLAN.md — re-introduce session preflight + membership log + collision naming + expanded rollback in commit-seeding-session.js
- [ ] 52-04-PLAN.md — hermetic integration tests at 17 assets + 12 logs; partial-failure + membership-log-failure + collision scenarios
- [ ] 52-05-PLAN.md — scripts/live-fire-52.js dev-farmOS ship-gate harness + 52-LIVE-FIRE.md runbook (operator-attested)

---

## v1.11 2025-Notebook Backfill (Phases 53–55) — PLANNED 2026-05-24

**Driver:** Phase 51 upsert layer (shipped 2026-05-24) structurally unblocks running the `/mnt/mossrock/shared/mushdatadump-prod/` 2025 paper-log corpus through the extraction+confirm+write pipeline without create-collisions against the May-22 stubs or any future captures. Today's prod write minted 4 stubs (`260304_SHI_5`, `260118_SHI_23`, `260118_SHI_26`, `260118_KOY_12`) carrying `STUB - awaits 2025-paper-scan backfill` markers — v1.11 is what makes them get *enriched* in place rather than just reused.

**Strategic role:** Generates the high-volume confirm corpus that v1.13 auto-commit narrowing structurally requires (today: 43 drafts in last 30d, ~44% commit rate — nowhere near the n≥50/shape × ≥99% bar). Also closes [[project_mushdatadump_is_2025_notebook]] (year hallucination) and the two open Phase 38 batch-mode findings filed 2026-05-24.

**Honors:** `[[feedback_smoke_before_expensive_batch]]` (5-10 pages first), `[[feedback_persist_paid_results_default]]` (per-call unique paths + JSONL append), `[[feedback_real_data_before_ship_gate_pass]]` (real notebook scans are the ship gate), `[[feedback_hard_rules_relaxed_when_farmer_is_santi]]` (bulk-backfill mode can auto-confirm under `--farmer=santi`).

**Phases:**

### Phase 53: Extraction prerequisites — year-context shim + Phase 38 batch-mode fixes

**Goal:** Close the three known extraction bugs that would corrupt a notebook backfill before any batch run touches farmOS.
**Requirements:**

- BACK-01: `corpus_context` extension lets a fixture/job pin `year=2025` so extractor stops hallucinating years on undated notebook pages.
- BACK-02: Phase 38 batch-mode no longer misroutes small multi-draft captures (closes `2026-05-24-phase38-batch-mode-misroutes-small-multi-draft-captures.md`).
- BACK-03: Photo-vs-paper-log classifier reins in eagerness (closes `2026-05-24-phase38-photo-vs-paper-log-classifier-too-eager.md`).
- BACK-04: Hermetic eval on 5-10 hand-labeled 2025 notebook pages PASSES before any batch run.

**Touches:** `src/agents/alerter/src/extraction/`, eval fixtures, possibly `signal_capture.corpus_context` column.
**Plans:** 4 plans

- [x] 53-01-PLAN.md — BACK-01 corpus_context JSONB column + pipeline/extractor plumbing (SHIPPED 2026-05-24, `bf721e2` + `9d25ec7`)
- [x] 53-02-PLAN.md — BACK-02 small-N multi-draft routing heuristic (drafts>5 OR conf<0.7 → batch; else N per-draft confirms) + DT-tubs regression (SHIPPED 2026-05-24, `9835caf`)
- [x] 53-03-PLAN.md — BACK-03 capture_kind prompt-only classifier (Option 1) + envelope schema + 2 new few-shots (SHIPPED 2026-05-24, `52f0874` + `673c413`)
- [x] 53-04-PLAN.md — BACK-04 hermetic eval gate on 5-10 hand-labeled 2025 notebook pages (Phase 54 unblocking gate) — SHIPPED 2026-05-24 (scaffolding `a2467ea` + 8-fixture corpus `cc95c8d`); 8/8 hermetic fixtures green; Phase 54 UNBLOCKED

### Phase 54: Backfill harness + dev-farmOS smoke (≤20 pages)

**Goal:** A scripted harness ingests N notebook pages from the `mushdatadump-prod/` corpus, runs them through extraction → confirm (auto-YES under `--bulk-backfill --farmer=santi`) → upsert into dev farmOS, with paid-LLM results persisted per-call.
**Requirements:**

- BACK-05: `scripts/backfill-notebook.js` (or sibling) iterates corpus pages, builds synthetic `signal_capture` rows with `corpus_context={year:2025, source:'paper_log'}`, dispatches through the normal pipeline.
- BACK-06: Bulk-backfill mode flag short-circuits CONF-01 YES requirement for `farmer=santi` only; every auto-confirmed draft still emits a farmer-facing summary (audit, not just silent write).
- BACK-07: Paid LLM responses persisted to `.planning/backfill/2025-notebook/<run-id>/responses.jsonl` (append-only, per-call unique).
- BACK-08: Smoke run on 10 representative pages produces correct stub-enrichment on the 4 May-22 ancestors (UUIDs byte-identical pre/post per Phase 51 contract). No duplicate assets created.

**Touches:** `scripts/`, possibly small alerter additions for the bulk-mode short-circuit. Path corrected from ROADMAP-original `mushdatadump-prod/` to actual corpus path `/mnt/slime-kingdom/shared/mushdatadump/jpeg/` (range IMG_3775..IMG_3861). BACK-08 stub-enrichment sub-clause resolved as N/A (May-22 stubs are 2026-dated, postdate 2025 notebook); substituted intra-cycle upsert-stability check against Phase 51 contract — same invariant, validated on existing data.
**Plans:** 6 plans

Plans:

- [x] 54-01-PLAN.md — backfill-notebook.js CLI core, prod-guard, santi-gate, page-range filter, synthetic-capture dispatch (BACK-05) — SHIPPED 2026-05-24 (`bfcde26`)
- [x] 54-02-PLAN.md — bulk-backfill short-circuit: auto-flip drafts to confirmed + commit-router dispatch + summaries.log audit (BACK-06) — SHIPPED 2026-05-24 (`99e3f98`)
- [x] 54-03-PLAN.md — paid-LLM observer hook on extractor + append-only responses.jsonl per run-id (BACK-07) — SHIPPED 2026-05-24 (`f4923e4`)
- [x] 54-04-PLAN.md — receipt.md builder: per-page + aggregate + Phase 51 upsert-stability check (BACK-08 part 1) — SHIPPED 2026-05-24 (`31b31bf`); BACK-08 stub-enrichment resolved as N/A, substituted intra-cycle upsert-stability
- [ ] 54-05-PLAN.md — Cycle 1 (5 pages) operator runbook + farmer checkpoint (BACK-08 part 2) — RUNBOOK authored 2026-05-24 (`31b31bf`); awaits operator real-run + farmer SIGN-OFF
- [x] 54-06-PLAN.md — Cycle 2 (20 pages) operator runbook + farmer checkpoint + Phase 55 unlock decision (BACK-08 part 3) — RUNBOOK authored 2026-05-24 (`31b31bf`); blocked on Cycle 1 SIGN-OFF (completed 2026-06-07)

### Phase 54.1: Strain-confirm before mint (INSERTED)

**Goal:** When extraction yields a fungi_type strain code that is NOT an exact match to the curated active strain set, hold it for a farmer double-check before minting a taxonomy term -- per-encounter ask-back in live capture, batched one-message confirm in backfill (hold drafts as needs_review, then a follow-up pass mints confirmed + remaps corrections + commits). Replaces the blind auto-mint that polluted dev farmOS with extraction variants (LIM/SHIITAKE/OYS for LIMA/SHI/POY). Unblocks a clean Cycle-1 / Phase-55 receipt.
**Requirements**: Locked design + scope in `.planning/todos/pending/2026-05-25-strain-confirm-before-mint.md` (context seed). Builds on the `ensureFungiTypeUuid` mechanism shipped in `c2af701` (currently gated off). Detection matches the curated 14-code set ([[project_mossrock_active_strain_codes]]), not live farmOS terms.
**Depends on:** Phase 54
**Plans:** 3/3 plans complete

Plans:

- [x] 54.1-01-PLAN.md — Strain resolver: exact-match an extraction code against the curated 14-set (config.strains); KNOWN vs UNKNOWN, no fuzzy auto-resolve (shared foundation)
- [x] 54.1-02-PLAN.md — Backfill path: hold unknown-strain drafts as needs_review + one batched Signal message + follow-up confirmed-mint/remap/commit pass
- [x] 54.1-03-PLAN.md — Live capture path: per-encounter strain ask-back via the Phase 39 confirm-loop; YES authorizes the per-draft mint, correction remaps to canonical

### Phase 55: Full corpus run + receipt

**Goal:** Run the full 2025 notebook corpus to dev farmOS, generate a receipt of every asset/log created or patched, decide whether to promote any subset to prod via upsert.
**Requirements:**

- BACK-09: Full corpus processed; receipt at `.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.md` + JSONL of UUIDs.
- BACK-10: Per-shape confirm-accuracy stats computed from the run (input to v1.13). Reports n_per_shape and YES rate (auto-YES counts here are not signal for v1.13 — v1.13 needs human-YES; bulk-backfill receipts are tagged accordingly).
- BACK-11: Prod-promotion decision documented (default: dev-only; prod write only if operator opts in per-session-class).

**Plans:** 2/2 plans complete

Plans:

- [x] 55-01-PLAN.md — harness --all-pages flag + build-backfill-receipt buildUuidJsonl/computePerShapeStats + .planning/notes/ copy-out + tagged BACK-10 section (BACK-09, BACK-10)
- [x] 55-02-PLAN.md — 55-FULL-CORPUS-RUNBOOK.md (GA1 isolation pre-flight + smoke-before-full + crash recovery) + 55-PROMOTION-DECISION.md dev-only default (BACK-11)

### Phase 55b: Fidelity / corpus-unblock (cross-check + F1/F2 session reconcile)

**Goal:** Land the blockers before the parked full-corpus run is safe to execute.
(1) Commit-time fidelity cross-check that HOLDS every entry not exact-verified against
the per-page CSV reading (`needs_review`, never hard-reject -- CSV is a fallible 2nd
interpretation). (2) F1+F2 reconcile surface: backfill per-block logs/assets group under
the inoc-session group asset (Phase 52 mechanism) with source notebook page image(s)
attached to the session asset (1..N pages; the inoc session, not the page, is the unit),
so a human reconciles a session 1:1 against the physical notebook. Re-scoped from the
original "per-tenant backfill / unknown-asset" placeholder (both absorbed elsewhere) with
Santi 2026-06-09. Context: `.planning/phases/55B-*/55B-CONTEXT.md`.

**Depends on:** Phase 55 (tooling + docs), Phase 52 (session group asset), Phase 51
(upsert), Phase 54.1 (needs_review hold). Private-files infra RESOLVED (2026-05-25).

**Plans:** 1/4 plans executed

Plans:
**Wave 1**

- [x] 55B-01-PLAN.md — Wave 0: patchGroupAssetFiles + RED test scaffolds (fidelity/aggregate/image) + A1 PATCH-associates-files dev smoke probe (FIDELITY-01/02, SESSION-01/02)
- [ ] 55B-02-PLAN.md — Commit-time CSV fidelity hold gate in processDraftsForCapture (buildCsvBudget + 3-branch hold) (FIDELITY-01, FIDELITY-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 55B-03-PLAN.md — Session routing (aggregateSeedingDraftsToSessionJson) + page-image attach on session group asset (SESSION-01/02/03)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 55B-04-PLAN.md — 5-page GA1-isolated re-smoke runbook + live gate (IMG_3776 mode-2 regression guard) (SMOKE-01, SESSION-03)

---

## v1.12 Farm-Agent Python Port (Phases 56–?) — PLANNED 2026-05-24

**Driver:** Phase 50 live-fire (2026-05-23/24) hit a wire-level Signal quote-rendering bug that REST 201s succeed but client-side renders unquoted. Fix-in-place means forking a Go wrapper of signal-cli — the entire stack is being replaced anyway. Per `2026-05-14-port-alerter-to-farm-agent-python.md`, port to Python with signal-cli library bindings (or alternative client) where quote-threading is first-class. Also absorbs `2026-05-24-signal-capture-missing-followup-messages.md`, `2026-05-24-phase50-quote-thread-missing-on-extraction-preview-and-ask-back.md`, `2026-05-24-phase50-extraction-preview-related-draft-id-null.md`, and `2026-05-21-alerter-tz-montevideo-and-local-time-rendering.md`.

**Strategic role:** Sets up the OSS-Foray v2.0 surface (Python is the Foray reference impl per [[project_2026_05_17_oss_foray_alpha_lock]]). Tenant_id-aware from day one (already paid the tax since v1.8).

**Hard constraint:** Atomic cutover with rollback. Node alerter is the current production farmer-facing pipeline; a botched cutover blacks out f1 alerts. Both stacks coexist behind a feature flag until live-fire attestation on f1 passes.

**Phases:** TBD during plan-phase. Likely 4-6 phases covering: capture+receive parity, extraction+confirm parity, write-path+upsert parity, quote-threading native, cutover + Node retire.

---

## v1.13 Auto-Commit Narrowing (Phases TBD) — PLANNED 2026-05-24

**Driver:** Today every farmOS write requires explicit farmer YES (CONF-01). The right north-star at v1.7, but every confirmed draft is a vote that the extractor got that shape right. With v1.11 generating hundreds of historical confirms, certain shapes will exceed >99% YES — and the YES tax becomes pure friction against `[[feedback_no_farmer_bookkeeping_tax]]`.

**Structural prerequisite:** v1.11 must ship first. Current data: 43 drafts last 30d, ~44% commit rate, no shape with n≥50. v1.11 produces the corpus this milestone narrows on.

**Honors:** OSS-Foray α — per-tenant opt-in, never cross-tenant defaults. Reversibility — auto-committed writes still send farmer-facing summaries with `UNDO <id>` within 1h. Demotion ratchet — shape's 7-day confirm rate <97% auto-demotes back to YES-required.

**Requirements (provisional):**

- AUTO-01: Per-draft "shape" classifier tags every extracted draft (`single-block-observation`, `multi-parent-inoc-session`, `harvest-bagging`, `activity-watering`, ...).
- AUTO-02: Per-shape historical accuracy table — YES rate, n, last-7d trend — computed nightly from `signal_draft` history.
- AUTO-03: Per-tenant + per-farmer opt-in config gates which shapes are eligible for auto-commit.
- AUTO-04: Auto-commit gate: shape eligible AND ≥99% historical YES AND n≥50 AND opted-in → write proceeds without farmer YES, farmer receives summary with `UNDO <id>` token.
- AUTO-05: `UNDO <id>` within 1h triggers Phase 51 upsert with `discarded_at` + `discarded_reason='farmer_undo'` cascade; outside 1h returns a polite-close with manual-correction guidance.
- AUTO-06: Auto-demotion: shape's 7-day rolling YES rate drops below 97% → automatically removed from auto-commit eligibility, farmer notified.
- AUTO-07: Ship-gate: at least 3 shapes auto-committing live to prod farmOS for ≥1 week with zero UNDOs in that window (or all UNDOs traced to a real extractor bug, fixed, shape re-promoted).

**Phases:** TBD during plan-phase. Likely 4-5 phases: classifier+accuracy table, opt-in config, auto-commit gate + UNDO handler, demotion monitor, live ship-gate.

---

### Phase 51: Order-independent farmOS writes — upsert-by-stable-identity + set-union merge

**Goal:** Make every farmOS write a content-addressable upsert keyed by the entity's natural identity, so processing events out of order produces the same final farmOS state as processing them chronologically. Backfill of the 2025-paper-log scan can land in any sequence relative to live captures; observations on yet-to-be-logged assets backfill instead of failing; partial stubs (today's May-22 ancestor placeholders) enrich in-place when the real history arrives.

**Driver:** 2026-05-24 conversation while running 48-LIVE-FIRE. The May-22 prod write needed 4 ancestor parent blocks (260304_SHI_5, 260118_SHI_23, 260118_SHI_26, 260118_KOY_12) that don't exist in prod farmOS because their Jan/Mar inoc sessions live in the 2025 paper notebook and haven't been scanned yet. Silently minting them now creates assets the future 2025-scan-backfill will collide with. The fix isn't a stub strategy — the fix is that ALL writes become merge-by-default so out-of-order arrival is structurally safe. Cross-refs: `[[feedback_farmer_is_reality_source_of_truth]]` (today's observation-of-unknown-asset principle), `.planning/notes/2026-05-24-v1.9-uat-findings.md` (observation-backfill todo), `.planning/notes/2026-05-24-session-as-asset-group-design.md` (composes with the asset--group work).

**Requirements:**

- UPSERT-01: `assets.upsertFungiAsset(client, opts)` — lookup by name → if found, PATCH merged fields → if not, POST. Returns same shape as `createFungiAsset`. All existing callers (`commit-seeding-session`, `commit-observation`, `commit-seeding`, future ones) route through this.
- UPSERT-02: `logs.upsertLog(client, type, opts)` — lookup by stable key (per-type rule, see below) → PATCH merged or POST. Seeding logs key = `(type='seeding', asset.id)` (B5: one inoc event per child).
- UPSERT-03: Merge rules per field type, codified in a `_mergeAssetFields(existing, incoming)` function. Array-valued ref fields (parent[], qr_codes[], farm_id_tag[]) = set-union. Scalar identity fields (name, type) = never mutated. Scalar non-identity (fungi_type, fungi_xing, status) = conflict-surface if differs, no silent overwrite. Notes = append-with-dedup OR structured notes_entries list (decide in plan).
- UPSERT-04: Optimistic concurrency via etag — PATCH carries `If-Match: <attrs.drupal_internal__revision_id or fetched etag>`; on 412 retry the GET + merge cycle once before failing.
- UPSERT-05: Stub-detection contract — assets minted as ancestor placeholders (today: notes contains "STUB awaits 2025-scan") are findable by a structured query. The upsert layer treats them as fully-mergeable on next encounter; no special STUB handling needed at the asset code path. Worth documenting that the marker exists so the 2025-scan-backfill author knows to look for it.
- UPSERT-06: Hermetic ship-gate. Property tests:
  - Order independence: for a randomized permutation of {May-22 inoc, Jan-18 inoc, Mar-04 inoc} writes, final farmOS state (asset count + parent[] sets + log count) is identical to the chronological order.
  - Stub enrichment: stub-then-real produces same final state as real-only.
  - Conflict surfacing: incoming `fungi_type=KOY` against existing `fungi_type=SHI` returns a structured conflict, not a silent overwrite.
- UPSERT-07: Live-fire ship-gate. Replay May-22 against dev with the stubs already in place (the 4 dev stubs after today's session, if we add the STUB marker); assert children's parent[] resolves to the existing stubs (no duplicates).

**Depends on:** none active. Composes with the asset--group design (Phase 52+ candidate); that work also flows through `upsertFungiAsset` / `logs.upsertLog`.

**Touches:** `src/agents/alerter/src/farmos/assets.js`, `src/agents/alerter/src/farmos/logs.js`, `src/agents/alerter/src/farmos/commits/commit-seeding-session.js`, `src/agents/alerter/src/farmos/commits/commit-observation.js`, `src/agents/alerter/src/farmos/commits/commit-seeding.js` (legacy), the audit log shape if upsert outcome (created/patched/noop) becomes a logged dimension, tests across `test/farmos/`.

**Constraints:**

- Honors `[[feedback_farmer_is_reality_source_of_truth]]` — observation on unknown asset becomes a real upsert path, not an error.
- Honors substrate log-only lock and C4 (lineage = log, not field) — the upsert is at the *asset+log* granularity, not at a lineage graph.
- Idempotency on `signal_draft.id` (Phase 40 audit) stays in place as a coarser safety net.
- farmOS JSON:API etag-on-PATCH is the concurrency primitive — no custom version columns.

**Plans:** 6/6 plans complete

Plans:

- [x] 51-01-wave0-infrastructure-PLAN.md — mock-client PATCH/delete/by-id/412 + client.js opts.headers + audit-logger outcome/conflicts/etag_source + fixture + dev-farmOS notes round-trip probe
- [x] 51-02-merge-pure-module-PLAN.md — merge.js pure module (mergeAssetFields + IdentityMutationError + STABLE_NOTES_SEPARATOR) with Jest coverage of all 5 rule classes + stub-marker preservation
- [x] 51-03-upsert-fungi-asset-PLAN.md — upsertFungiAsset + isStubAsset + STUB_BACKFILL_MARKER on assets.js with soft revision_id compare (UPSERT-04 degraded per RESEARCH)
- [x] 51-04-upsert-log-seeding-PLAN.md — upsertLog seeding + LOG_STABLE_KEYS table + LogIdentityCollision; non-seeding types preserve POST-only
- [x] 51-05-commit-migration-and-property-tests-PLAN.md — migrate commit-seeding-session + commit-seeding + commit-observation review; grep-gate clean; property tests (order-independence + stub-enrichment + conflict-surfacing, 20× permutations)
- [x] 51-06-live-fire-attestation-PLAN.md — scripts/live-fire-51.js sibling-copy of 48; human checkpoint to run against dev farmOS and commit receipt

### Phase 47: Multi-source extraction fusion + groups-shape inoc draft

**Goal:** A multimodal inoc capture (audio + photo of paper log + optional text) produces ONE draft in the groups shape (`{type: "seeding", event_date, groups: [{parent, species, qty, child_block_names[]}]}`) where each field carries provenance metadata (which source(s) contributed) and cross-source conflicts surface in the confirm UX rather than being silently picked.

**Depends on:** v1.8 (Phases 44+45) ships first. Composes with Phase 38's existing extractor scaffolding — extends, doesn't replace.

**Requirements:** INOC-01, INOC-02, INOC-03, INOC-05 (INOC-04 carry-forward to Phase 48)

**Success criteria (what must be TRUE):**

1. Replay the 2026-05-22 audio+photo turn through the new extractor → emits exactly one draft with 5 groups (3 SHI singles + 4 KOY-118-12 + 4 KOY-425-4), 11 children total, child names `260522_SHI_1..3` + `260522_KOY_4..11` (per-session SEQ from paper-log photo, not per-strain auto-generated).
2. Each field in the draft carries provenance — `parent` fields tagged with `source: audio`, `child_block_names` with `source: paper_log_photo`, with confidence per source.
3. A synthetic conflict fixture (audio says "118-23", photo says "118-25") flags the disagreement in the confirm preview with both values, never silently picks one.
4. A single-parent inoc session (legacy shape) still extracts cleanly into the groups shape (one group with qty=N).

**Touches:** `src/agents/alerter/src/extraction/prompts/system.js`, draft schema (likely a new groups-shape variant), `signal_draft.per_field_confidence` extended with source tracking, possibly `signal_capture` schema for cross-turn bundle tracking.

**Constraints:**

- Locked-schema-only output (no off-schema fields per C5).
- No auto-generated SEQ when paper-log photo absent — ask-back preferred over guessing per [[project_extraction_holistic_multi_source_fusion]].
- Honors B5 session-wide SEQ disambiguation ([[project_b5_seq_is_per_session_not_per_strain]]).

**Plans:** 5 plans

- [ ] 47-01-PLAN.md — New schemas (SeedingSession + Provenanced + ConflictEntry) + Draft union extension
- [ ] 47-02-PLAN.md — System prompt revision + May-22-shape multi-parent few-shot
- [ ] 47-03-PLAN.md — Pipeline starting_seq ask-back branch + seq-helper.js (Phase 48 reuse)
- [ ] 47-04-PLAN.md — Preview-builder seeding_session placeholder (Phase 48 ships real preview)
- [ ] 47-05-PLAN.md — Integration ship-gate (May 22 hermetic + live-fire) for INOC-01/02/03/05

### Phase 48: Session entity + per-bag commit fan-out + session-shaped confirm preview

**Goal:** A confirmed groups-shape draft commits to farmOS as N per-block `seeding` logs (one per child, each with its specific parent ref per B7) PLUS one anonymous `fungi` session asset that serves as secondary parent on every child block in the session. Confirm preview is session-shaped (compact group-by-parent table) so the farmer can cross-check against paper notebook and shelf in seconds.

**Depends on:** Phase 47 (groups-shape draft must exist before commit can fan it out).

**Requirements:** INOC-04, INOC-05, INOC-06

**Success criteria (what must be TRUE):**

1. A confirmed May-22-shape draft writes 11 `seeding` logs + 1 anonymous session asset to farmOS dev. Each child block's primary parent = its specific source block (audio-extracted); each child also references the session asset as a secondary parent.
2. Duplicate YES on the same draft produces no double-write (idempotency via draft UUID).
3. Lineage walk from any child block returns its specific parent AND the session asset cleanly; query "show me the May 22 inoc session" returns all 11 children.
4. Confirm preview renders compactly — 5-line group table (parent → qty → children), not a flat 11-row list. SEQ numbers visible per-bag for paper-comparison.
5. Single-parent legacy inoc still commits cleanly (one group → N children all sharing one parent → still gets a session asset for shape consistency).

**Touches:** `src/agents/alerter/src/farmos/`, `src/agents/alerter/src/confirm/`, the write path audited in Phase 40, possibly `signal_draft.farmer_facing_preview` rendering.

**Constraints:**

- Native log types only per C5 (`seeding` only; no custom session-log bundle).
- C4 lineage-via-log-refs preserved — session asset is a secondary `parent` ref on the child block, not a custom field.
- Composes with [[feedback_hard_rules_relaxed_when_farmer_is_santi]] — Phase 45 ack remains v1.8 scope.

**Plans:** TBD during plan-phase. Likely 4-5 plans.

### Phase 49: Real-session eval corpus + May 22 ship-gate reprocess

**Goal:** ≥3 real inoc sessions added to the CI eval corpus from `/mnt/mossrock/shared/mushdatadump-prod/` paper logs + paired audio when available; the 2026-05-22 session is the named regression guard; CI fails on any named-session regression. As the live ship-gate, the May 22 captured-but-failed drafts are marked discarded and the original audio+photo is reprocessed through the new pipeline to farmOS dev.

**Depends on:** Phase 47 (extraction), Phase 48 (commit). Cannot precede them.

**Requirements:** INOC-07

**Success criteria (what must be TRUE):**

1. CI eval suite includes ≥3 real inoc sessions with hand-labeled expected outputs (groups, child names, parents).
2. The 2026-05-22 session in the corpus emits 11 correctly-named blocks + correct parents + session asset; lineage walk returns clean.
3. The two failed May-22 drafts in production timescale (`e3a564d063d4…` and `6edaaba7deb0…`) are marked `discarded` with reason "superseded by Phase 49 reprocess".
4. The May 22 audio+photo reprocessed through the new pipeline lands all 11 logs + session asset in farmOS dev. Operator can query farmOS dev and reconstruct the session entirely from logs without referring to Signal.
5. CI eval pass-rate target: 100% on named-regression sessions; ≥90% schema conformance on the broader corpus.

**Touches:** `src/agents/alerter/test/` (eval corpus), `.planning/phases/49-*/`, maintenance scripts to mark stale drafts discarded.

**Constraints:**

- Honors [[feedback_real_data_before_ship_gate_pass]] — curated fixtures necessary, never sufficient. Real sessions are the ship gate.
- Honors [[feedback_smoke_before_expensive_batch]] — May 22 (1 session) before the full corpus.
- farmOS *dev* (not prod) is the write target. v1.9 doesn't auto-backfill prod farmOS with historical paper-log sessions.

**Plans:** TBD during plan-phase. Likely 3-4 plans.

### Phase 46: Chamber-dark detector — real fc1-liveness signal + farmer-readable pi-offline message

**Goal:** Make the alerter actually detect when fc1 stops publishing telemetry (regardless of bridge container health) and surface it to the farmer as a chamber-level "FC-1 offline, chamber uncontrolled" message rather than a per-sensor "co2 sensor offline".

**Hotfix trigger:** 2026-05-20 fc1 outage (13:04 → ~24:00 UTC, 10h47m). Farmer received only "co2 sensor offline" Signal alerts; no high-level chamber-dark notification ever fired. Root cause + fix direction documented in `.planning/debug/alerter-co2-only-not-pi.md` (`isPiOffline` keys off alerter↔bridge WS + boot-time `rosReady`, neither input reflects fc1 publisher liveness).

**Requirements:**

- CD-01: Bridge tracks `fc1LastMsgTs = max(ts)` across all subscribed fc1 topics (`humidity`, `temperature`, `humidity_2`, `temperature_2`, `co2`, `humidifier`, `humidifier_duty`, `sensor_health`, `pid_output`) and exposes `fc1.last_msg_ts` + `fc1.last_msg_age_sec` in `/health`.
- CD-02: Alerter consumes `fc1LastMsgTs` via the existing `pi_liveness` event path; `rules.js` `isPiOffline` gains a third OR-trigger `(now - fc1LastMsgTs) > piOfflineMin*60000`. Existing `wsConnected` / `rosConnected` triggers retained.
- CD-03: `message.js` `formatProblem({alertType:'pi'})` produces a chamber-level message (no em-dashes per `[[feedback_no_em_dashes_in_artifacts]]`) carrying last-known RH/T/timestamps from the `lastKnown` payload `state.js:513-520` already assembles. Suggested shape: `FC-1 offline ?? no telemetry XXm. chamber uncontrolled. last RH XX% @ HH:MM.`
- CD-04: Tests live before any rebuild. `rules.test.js` covers `isPiOffline` true when `fc1LastMsgTs` stale but WS+ROS appear connected. `state.test.js` covers `pi_liveness` event driving `perType.pi` to FIRING. Bridge test asserts `/health` exposes `fc1.last_msg_age_sec` and that it advances per subscribed topic.

**Depends on:** none active. Composes with closed 999.42 (per-sensor enable flags) — extends pi-level liveness on top of that.

**Touches:** `src/mission-control/bridge/src/index.js`, `src/agents/alerter/src/bridge-client.js`, `src/agents/alerter/src/rules.js`, `src/agents/alerter/src/message.js`, `src/agents/alerter/src/state.js`, plus 3 test files.

**Constraints:**

- elder-plops is dev+prod (no staging); rebuild of both bridge + alerter ships to f1 immediately. Tests green before rebuild.
- Atomic deploy: bridge and alerter changes must land together; bridge alone with no alerter consumer adds nothing; alerter alone with no bridge field crashes on null.
- Watch for stale `ALERT_SHT30_ENABLED=false` (lifted 2026-05-20 by this session) — when chamber-dark detector lands, the per-sensor SHT30 watchdog should *also* fire alongside it, not be the only chamber signal.

**Open design questions for discuss-phase:**

- Should `fc1LastMsgTs` be tracked per-topic with min-age aggregation, or just max-across-all? Affects whether a stuck single topic triggers chamber-dark when others are fresh.
- Cooldown semantics: does chamber-dark have its own cooldown distinct from the per-sensor cooldowns, or share the existing `ALERT_PI_OFFLINE_MIN`?
- Should the per-sensor alerts be suppressed when chamber-dark is firing (avoid spamming the farmer with co2/sht30/rh-OOB while pi is dark), or kept for diagnostic detail?

**Plans:** 3 plans

- [x] 46-01-PLAN.md — Bridge fc1LastMsgTs aggregator + /health.fc1 schema + bridge tests (CD-01, partial CD-04)
- [x] 46-02-PLAN.md — Alerter consumes fc1LastMsgTs; isPiOffline third OR-trigger; chamber-level pi message; per-sensor suppression; alerter tests (CD-02, CD-03, partial CD-04)
- [x] 46-03-PLAN.md — Atomic rebuild + Round 3 live-fire attestation; D-09 + D-10 fixes shipped during the attestation cycle (closes CD-01..CD-04)

### Phase 36: Signal Pre-gate

**Goal:** Unblock all Signal-driven downstream phases by re-registering the bot account as primary (deviceId=1) and verifying round-trip Signal receive + reply from at least two farmers.
**Depends on:** Nothing (first v1.7 phase; hard pre-gate per requirements)
**Requirements:** PRE-01, PRE-02
**Success Criteria** (what must be TRUE):

  1. Operator can send a Signal message to the bot and receive a reply in the same DM thread
  2. A second farmer sends a test message and receives a reply routed to their number (not farmer #1)
  3. Alerter container rebuild does not break identity trust (signal-cli /v1/identities check passes after rebuild)

**Plans:** 4 plans (all shipped 2026-05-13; SC#2 closed 2026-05-16 organically via 2026-05-15 Vikki Rambo round-trip)

- [x] 36-01-PLAN.md — Pre-flight snapshot + identity capture + Phase 35 coverage verdict + restore recipe
- [x] 36-02-PLAN.md — 36-RUNBOOK.md authored + live primary re-registration + kickoff message to farmers (interactive)
- [x] 36-03-PLAN.md — post-rebuild-trust-check.sh script + bats tests + alerter compose healthcheck wire-up
- [x] 36-04-PLAN.md — T0 round-trip + alerter rebuild attestation + T+24h re-run + final SC#1/2/3 attestation log

### Phase 37: Multi-farmer Routing

**Goal:** Bot replies to the correct farmer (envelope.source routing), participates correctly in the group thread without spamming, and tags every incoming message with the sender's farmOS person record.
**Depends on:** Phase 36 (receive must work before routing matters)
**Requirements:** ROUTE-01, ROUTE-02, ROUTE-03
**Success Criteria** (what must be TRUE):

  1. Farmer #2 DMs the bot; bot reply arrives on farmer #2's phone, not farmer #1's
  2. A message to the group thread produces no unsolicited reply; an @mention or command gets exactly one reply to the group
  3. Known farmer numbers resolve to farmOS person IDs in the message metadata; unknown number gets (unassigned) tag and message is not silently dropped

**Plans:** 4 plans

- [x] 37-01-PLAN.md — Wave 0 smoke probe + six group envelope fixtures + jest baseline
- [x] 37-02-PLAN.md — signal.js send({to}) refactor + config.js (SIGNAL_GROUP_ID, SIGNAL_FARMER_MAP) + capture-db.js ALTER TABLE migrations
- [x] 37-03-PLAN.md — receive-loop.js group gate + collectGroupTriggers + D-09 dedupe; capture.js replyTarget threading + farmer-map + new row fields
- [x] 37-04-PLAN.md — docker-compose env plumbing + index.js wire-up + 37-RUNBOOK.md + live A/B/D attestations PASS (C deferred to unit-test coverage)

### Phase 38: Extraction Pipeline

**Goal:** A multimodal message (text, audio, photo, or any combination) produces a structured JSON draft of farmOS assets and logs that conforms to the locked schema, or triggers a targeted ask-back when confidence is too low.
**Depends on:** Phase 37 (need sender identity before extraction can attribute the event)
**Requirements:** EXT-01, EXT-02, EXT-03, EXT-04, EXT-05
**Success Criteria** (what must be TRUE):

  1. A text message describing inoculation of SHI blocks produces a seeding log draft with block names matching the B5 convention (YYMMDD_SHI_SEQ)
  2. A voice note and a photo of the same session produce one combined draft, not two separate ones
  3. When a required field is ambiguous, bot sends a targeted Signal reply asking for it; draft completes after farmer responds
  4. A lineage cue ("from blocks 3, 4, and 5") extracts a multi-parent harvest batch ref per C4
  5. No off-schema fields appear in any extracted draft; all log types are native per C5

**Plans:** 9 plans, shipped. 38-01..06 (Waves 0-2), 38-07 (eval harness PASS in 38-EVAL-REPORT.md), 38-08 prod-log advisory superseded by 38-09 re-eval (Plan 09 ran 96-fixture re-eval -> PASS at 95.8% schema conformance 2026-05-12). See `.planning/phases/38-extraction-pipeline/`.

### Phase 39: Farmer Confirmation Loop

**Goal:** Every extraction draft requires explicit farmer YES before any farmOS write occurs; NO discards cleanly; EDIT loops back through the LLM; stale drafts never auto-commit.
**Depends on:** Phase 38 (need extraction before confirm loop can function)
**Requirements:** CONF-01, CONF-02, CONF-03, CONF-04, CONF-05
**Success Criteria** (what must be TRUE):

  1. After extraction, farmer receives a human-readable draft summary with YES/NO/EDIT reply instructions
  2. Sending YES once commits the draft; a second YES does not produce a duplicate write in farmOS
  3. NO discards the draft; bot confirms discard; original transcript remains in the Phase 25 capture store for audit
  4. EDIT with correction text produces a revised draft; EDIT is accepted at least 3 times before the bot escalates
  5. A draft with no response for 30 min gets one ping, then auto-discards with a note; it never auto-commits

**Plans:** 7 plans, all shipped 2026-05-13 (39-01..07). 127 unit + 11 integration PASS. Live-farmer UAT deferred per 39-RUNBOOK.md. See `.planning/phases/39-farmer-confirmation-loop/`.

### Phase 40: FarmOS Write Path

**Goal:** A confirmed draft writes the correct assets and logs to farmOS, is idempotent on retry, binds QR tags through farmos_asset_link, attaches photos, and every write is observable in the audit log.
**Depends on:** Phase 39 (writes only happen after confirm; can be developed in parallel against synthetic drafts)
**Requirements:** FOS-01, FOS-02, FOS-03, FOS-04, FOS-05, FOS-06
**Success Criteria** (what must be TRUE):

  1. A sterilization batch, block, harvest batch, and bag asset can each be created via API from a confirmed draft and appear in farmOS dev stack
  2. Re-confirming the same draft (duplicate YES) does not create duplicate assets or logs in farmOS
  3. A photo from the originating Signal message appears as a file attachment on the observation or harvest log in farmOS
  4. A QR code in a farmer message resolves to an existing block asset and appends a log to it rather than creating a new asset
  5. Operator can query one endpoint or log stream and see every farmOS write from the last 24h with draft UUID, farmer ID, and farmOS response

**Plans:** 8 plans, all shipped 2026-05-13 (40-01..08). 92/92 unit PASS; live dev-farmOS integration + prod-fixture SHIP GATE deferred to operator per 40-RUNBOOK.md. See `.planning/phases/40-farmos-write-path/`.
**Composes-with:** 999.2 (this phase is its closure)

### Phase 41: Ingestion Harness

**Goal:** The pipeline produces consistent, auditable output across three input modalities — synthetic fixtures, historical paper log photos, and existing audio recordings — with per-field accuracy measured against hand-labeled expected outputs.
**Depends on:** Phase 38 (extraction must work); parallel-safe with Phase 40 (harness exercises extraction without write path)
**Requirements:** INGEST-01, INGEST-02, INGEST-03, INGEST-04
**Success Criteria** (what must be TRUE):

  1. CI runs the synthetic fixture corpus; all expected outputs match and the test suite passes
  2. At least one batch of paper inoc log photos flows through the pipeline; a hand-labeled comparison report is produced showing per-field accuracy
  3. At least one set of existing audio recordings flows through Whisper plus extraction; comparison report produced
  4. The same underlying inoc session represented as both a paper-log photo and an audio recording produces identical seeding log content

**Plans:** 7 plans, all shipped 2026-05-13 (41-01..07). 37 PASS + 5 operator-deferred live. mushdatadump-prod hand-labels + audio + paired-sessions in 41-RUNBOOK.md. See `.planning/phases/41-ingestion-harness/`.

### Phase 42: SHI-on-Sawdust Pilot

**Goal:** One complete SHI-on-sawdust block lifecycle — sterilize through archive_spent — is driven end-to-end by Signal messages alone, with all writes verified in farmOS and the full lineage walk returning clean.
**Depends on:** Phase 40 (write path live), Phase 41 (ingestion harness validates extraction quality), Phase 39 (confirm loop required)
**Requirements:** PILOT-01, PILOT-02, PILOT-03, PILOT-04, PILOT-05, PILOT-06
**Success Criteria** (what must be TRUE):

  1. Sterilization batch appears in farmOS after a single Signal message describing the batch count (no form, no login required)
  2. After inoculation, one block asset exists in farmOS with species=SHI, substrate=sawdust, QR bound, and a seeding log pointing at the batch
  3. Cold_shock and fruiting transitions appear as activity and observation logs; current-stage derivation returns the correct stage at every checkpoint
  4. Harvest batch and at least one bag asset exist in farmOS after a harvest Signal message; bag asset is QR-bound
  5. Archive_spent activity log written on the block; lineage walk bag to harvest batch to block to sterilization batch returns clean with no broken refs
  6. Operator reconstructs the full lifecycle from farmOS logs alone without referring to Signal history

**Plans:** 3 plans scaffolded 2026-05-13 (42-01..03 + RUNBOOK + PILOT-LOG + VERIFICATION). Status: human_needed — actual pilot run calendar-deferred 4-8 weeks against real mushroom lifecycle. See `.planning/phases/42-shi-pilot/42-VERIFICATION.md`.

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Pi Integration & Environment | v1.0 | 5/5 | Complete | 2026-03-29 |
| 2. Safety Hardening | v1.0 | 4/4 | Complete | 2026-03-30 |
| 3. Closed-Loop Control | v1.0 | 3/3 | Complete | 2026-04-04 |
| 4. Observability & Integration | v1.0 | 2/2 | Complete | 2026-04-04 |
| 5. Production Deployment | v1.0 | 2/2 | Complete | 2026-04-11 |
| 6. WireGuard / Tailscale ROS routing | v1.0 | 3/3 | Complete | 2026-03-29 |
| 7. Historical Data & OpenMCT time-series | v1.0 | 2/2 | Complete | 2026-04-07 |
| 8. Pi Camera Feed in Mission Control | v1.0 | 4/4 | Complete | 2026-04-09 |
| 9. Connectivity & Boot Stability | v1.1 | 4/4 | Complete | 2026-04-11 |
| 10. Bridge QoS & MJPEG Delivery | v1.1 | 2/2 | Complete | 2026-04-12 |
| 11. Compose v2 Upgrade | v1.2 | 1/1 | Complete | 2026-04-13 |
| 12. Subscriber-Aware Camera | v1.2 | 2/2 | Complete | 2026-04-13 |
| 13. FarmOS Daily Report | v1.2 | 4/4 | Complete    | 2026-04-13 |
| 14. fc_camera idle-mode stall hotfix | v1.2.1 | 5/5 | Complete    | 2026-04-18 |
| 15. Sensor warm-up grace period | v1.2.1 | 3/3 | Complete    | 2026-04-18 |
| 16. System health panel | v1.2.1 | 3/3 | Complete    | 2026-04-18 |
| 17. Alert engine + Signal | v1.3 | 5/5 | Complete (ALRT-07 → 999.15) | 2026-04-18 |
| 18. Farmer dashboard API (UI delegated to farmOS team) | v1.3 | 1/1 | Complete — `/farmer/summary` live on bridge; farmOS UI owned by Zoy-side | 2026-04-19 |
| 19. FarmOS admin actions | v1.3 | — | Deferred to v1.5 — gated on Zoy/farm-team | — |
| 20. Alert cooldown tuning | v1.3 | — | Absorbed into Phase 29 (ALRT-08/09) — shipped 2026-05-08 | 2026-05-08 |
| 21. Camera history continuous persistence | v1.4 | 4/4 | Complete    | 2026-04-19 |
| 22. Timeline scrubber + farmer story view | v1.4 | 4/4 | Complete — data-surface shipped on elder-plops; farmOS owns UI (Zoy-side) | 2026-04-19 |
| 23. Time-lapse composition (ffmpeg) | v1.4 | 3/3 | Complete    | 2026-04-27 |
| 24. ML vision events via ComfyUI | v1.4 | — | Depends on 21; pre-gate: ComfyUI-as-prod hardening | — |
| 25. Bidirectional Signal — farmer↔robot capture channel | v1.4 | 5/5 | Complete — 7/7 farmer UATs PASS 2026-04-28; SEED-002 carries farmOS event writer | 2026-04-28 |
| 26. Dual sensor publishing + offline alarms (SHT30/SCD41) | v1.4 | 3/3 | Complete — UAT-8 PASS 2026-04-29 (farmer-eyeballed slot-1/slot-2 overlay, SCD41 clipping confirmed) | 2026-04-29 |
| 27. PID + time-proportional duty-cycle primitive | v1.5 | 5/5 | Complete    | 2026-05-02 |
| 27.1. Edge buffering — fc1 telemetry replay-on-reconnect | v1.5.0.1 | 4/4 | Complete — shipped via wg0 detour 2026-05-03 (BUF-04 attestation pending natural dropout) | 2026-05-03 |
| 27.2. fc-core systemd unit hardening | v1.5.0.1 | 1/1 | Complete (PARTIAL — cold-reboot SYS-04 PASS 2026-05-07; wg0-down-at-boot scenario deferred to 999.28) | 2026-05-07 |
| 27.3. Telemetry sampling-rate reduction | v1.5.0.1 | — | MOOTED 2026-05-03 by transport switch | — |
| 27.4. Repo netplan drift reconciliation | v1.5.0.1 | — | MOOTED 2026-05-03 in planned form (fc1 no longer on farm-4G); re-promote when fc1 returns to farm | — |
| 999.1. Edge buffering | backlog | — | Promoted to Phase 27.1 (v1.5.0.1) on 2026-05-02; shipped 2026-05-03 | — |
| 28. Mode primitive + baselines + runtime config delivery | v1.5 | 7/7 | Complete    | 2026-05-08 |
| 29. Alerter mode awareness + cooldown tuning | v1.5 | 7/7 | Complete    | 2026-05-08 |
| 30. Time-of-day mode scheduling | v1.5 | 3/3 | Complete (smoke PASSED, farmer attestation pending review of 30-03-SMOKE.md) | 2026-05-09 |
| 31. Experimental forcing modes (condensation/evaporation) | v1.5 | 4/4 | Complete (UAT partial — bridge path PROVEN; Signal E2E blocked on signal-cli primary re-reg) | 2026-05-09 |
| 32. VPS multi-purpose hub (WireGuard MVP) | v1.6 | 1/1 | Complete — farmer #1 reaching MC via VPS hub LIVE; fc1 + elder-plops + farmer1/2/3 peers configured; gumbald deferred (operator skip) | 2026-05-10 |
| 33. VPS heartbeat receiver + outage-alert relay | v1.6 | scaffold + deploy | Complete — Tier 1 E2E PROVEN (VPS detects 3min silence → bridge → signal-cli → operator phone) | 2026-05-11 |
| 999.43.1. ntfy.sh Tier 2 out-of-band alert channel | v1.6 | promoted | Complete — Tier 2 E2E PROVEN (induced Tier 1 fail → ntfy push delivered to operator phone). Closes the actual 11h-blind incident class. | 2026-05-11 |
| 34. VPS uptime-kuma outside-in monitoring | v1.6 | infra + seed | Complete — admin live, ntfy channel wired (same topic as 999.43.1), 4 monitors UP (fc1+elder-plops pings, MC HTTP, Bridge keyword); seed driven via uptime-kuma-api lib | 2026-05-11 |
| 35. VPS Tier A backup (small irreplaceable bits) | v1.6 | ship | Complete — `.env` files + fc1 runtime knobs + VPS heartbeat secrets nightly age-encrypted to VPS at 03:30. ~20KB/day. **Known SPOF: decrypt key is `~/.ssh/id_ed25519` on elder-plops, not backed up offline (operator-acknowledged, deferred).** 999.45 (Tier B + borg) still open for vfx-studio offsite. | 2026-05-11 |

### Phase 32: VPS multi-purpose hub (WireGuard MVP)

**Goal:** Stand up a public-facing infrastructure box (Hetzner CX22 Nuremberg, already provisioned 2026-05-09) hardened with UFW + fail2ban + key-only SSH + unattended-upgrades; install WireGuard hub on `10.66.0.0/24` port 51820/udp; connect fc1, elder-plops, gumbald (operator laptop), and zoy (beta-tester #1) as peers. Existing fc1↔elder-plops `wg0` LAN tunnel preserved (additive, not replacement). MVP scope only — heartbeat receiver / outside-in monitoring / offsite backups deferred to future phases (33+).

**Requirements:** None formally declared yet (v1.6 milestone scaffolding deferred — Phase 32 ran ahead of /gsd-new-milestone).

**CONTEXT.md:** `.planning/phases/32-vps-multi-purpose-hub/32-CONTEXT.md`. Sourced from DECISION-6 in `.planning/notes/2026-05-09-fire-conversation.md`.

**Dependencies:** None within v1.6. Loosely related to memories `project_fc1_link_architecture_options`, `project_fc1_cgnat_confirmed`, `project_2026_05_07_fc1_reboot_unrecoverable`, `project_2026_05_03_ssd_failure`, `feedback_stopping_tailscaled_kills_pid` (D-12 enforces existing-transport preservation).

**Plans:** 1 plan tonight; possible 2nd plan if scope creeps.

- [x] 32-01-PLAN.md — SHIPPED 2026-05-10. SSH bootstrap → hardening → WG hub → 5 peers (fc1, elder-plops, farmer1 LIVE, farmer2 + farmer3 configured for Signal delivery) → smoke + farmer #1 MC-via-VPS proven → runbook → commit. gumbald + 4th iOS device deferred. See `.planning/phases/32-vps-multi-purpose-hub/32-01-SUMMARY.md`.

### Phase 33: VPS heartbeat receiver + outage-alert relay — SHIPPED 2026-05-11

**Goal:** Stand up an out-of-band heartbeat receiver on the Phase 32 VPS that detects when monitored sources (fc1, elder-plops) go silent and fires Tier 1 Signal alerts via the elder-plops bridge over wg-hub. Mitigates the incident class documented in memory `project_2026_05_07_fc1_reboot_unrecoverable` (11h fc1 outage that nobody noticed because the in-house alerter was dead with the home network). Promotes backlog 999.43.

**Requirements:** None formally declared (v1.6 milestone scaffolding deferred per Phase 32 note).

**CONTEXT.md:** `.planning/phases/33-vps-heartbeat-receiver/33-CONTEXT.md` — decisions D-01..D-12 locked overnight 2026-05-10/11.

**Dependencies:** Phase 32 (WG hub) — receiver listens on `10.66.0.1:9000`, senders POST from `10.66.0.11`/`10.66.0.12`.

**Plans:** Scaffold-and-deploy (no formal plan files; HANDOFF + SUMMARY).

- [x] 33-SCAFFOLD — overnight 2026-05-10/11. Receiver code, sender shim, systemd unit, idempotent installer. See commit `d58390b`.
- [x] 33-DEPLOY — 2026-05-11. Bridge `/heartbeat-alert` endpoint added (D-09 corrected — bridge ≠ alerter network path), VPS install via `bash install.sh`, fc1 + elder-plops senders + systemd timers, real smoke (stop fc1 sender for >3min → operator phone receives Signal). See `.planning/phases/33-vps-heartbeat-receiver/33-SUMMARY.md` and commits `e97b499`, `6c27610`.
- [x] 999.43.1-PROMOTED — 2026-05-11. ntfy.sh wired as Tier 2 out-of-band channel; topic delivered to operator phone; Tier 2 fallback E2E proven by induced-Tier-1-failure smoke. See `.planning/phases/33-vps-heartbeat-receiver/999-43-1-SUMMARY.md`.

### Phase 34: VPS uptime-kuma outside-in monitoring — SHIPPED 2026-05-11

**Goal:** Stand up uptime-kuma on the Phase 32 VPS to catch the *outside-in* failure mode (host up but invisible from outside — the 2026-05-07 elder-plops state) that Phase 33 / 999.43.1 cannot see. Promotes backlog 999.44.

**Requirements:** None formally declared (v1.6 milestone scaffolding deferred per Phase 32 note).

**CONTEXT.md:** `.planning/phases/34-vps-uptime-kuma/34-CONTEXT.md` — decisions D-01..D-08, monitor seed table.

**Dependencies:** Phase 32 (WG hub) — UI bound to `10.66.0.1:3001`, NOT public.

**Plans:** Single deploy + operator UI setup.

- [x] 34-INFRA — 2026-05-11. docker engine installed on VPS; uptime-kuma container running; UFW opened on wg-hub interface for port 3001; reachability verified from elder-plops.
- [x] 34-SEED — 2026-05-11. Operator created admin in browser (~30s), then `vps/uptime-kuma/seed.py` (uptime-kuma-api / socket.io) drove notification channel + 4 monitors + test fire from elder-plops. ntfy push delivered to operator phone. 5th monitor (receiver self-check) deleted — Docker bridge can't reach the receiver's wg-hub binding locally; documented in `34-SUMMARY.md` "Deferred / discovered during deploy."

### Phase 35: VPS Tier A backup (small irreplaceable bits) — SHIPPED 2026-05-11

**Goal:** Close the painful half of `project_2026_05_03_ssd_failure` (env vars + chamber tuning knobs + secrets recovery) without committing the VPS to a 20+GB pg_dump backup-target role. "Empezar chiquito" subset of backlog 999.45 — Tier B (Timescale + farmOS db data) deferred until vfx studio offsite infra lands.

**Requirements:** None formally declared (v1.6 milestone scaffolding deferred per Phase 32 note).

**SUMMARY.md:** `.planning/phases/35-vps-tierA-backup/35-SUMMARY.md` — bundle contents, architecture, acceptance, **SPOF section.**

**Dependencies:** Phase 33 + 999.43.1 (failure path POSTs to bridge `/heartbeat-alert`); existing operator SSH keys + access to fc1 + VPS.

**Plans:** Single ship.

- [x] 35-SHIP — 2026-05-11. `scripts/backup-tierA/` (bash + systemd timer at 03:30 daily); `age` apt-installed on both ends; bundle: 5 source files (mushy `.env`, farmOS `.env`, fc1 `runtime_overrides.yaml`, fc1 heartbeat systemd units, VPS heartbeat HMAC + ntfy.env). First-run smoke: 20692-byte ciphertext on VPS at `/var/backups/mushy-tierA/`, decrypt round-trip verified, all 5 files + manifest intact. **Known SPOF (operator-acknowledged 2026-05-11, deferred):** `~/.ssh/id_ed25519` on elder-plops is the only key that decrypts; not backed up offline. Mitigation paths in 35-SUMMARY.md.

### Phase 27.1: Edge buffering — fc1 telemetry replay-on-reconnect — SHIPPED 2026-05-03

**Goal:** Close the visibility-during-VPN-dropout gap proven by the 2026-05-02 incident (~2h cumulative blackout where PID held the chamber but Mission Control had no idea what it was doing).

**What shipped (2026-05-03 over wg0, not tailscale0):** fc_buffer running on fc1 binding `172.16.10.5:8765`; bridge `FC1_BUFFER_URL=http://172.16.10.5:8765`; first backfill confirmed live; `buffer.sqlite` with WAL active; idempotent `(topic, time)` UNIQUE constraint deployed. BUF-04 induced-dropout test deferred to natural-event observation per plan-04 D-12.

**Requirements:** BUF-01..03 satisfied; BUF-04 acceptance pending natural-event attestation (induced-dropout test was via wg0 instead of Tailscale; original sudo-tailscale-down recipe no longer applicable). Eyeball-confirmed live working tonight by farmer.

**CONTEXT.md:** `.planning/phases/27.1-edge-buffering-fc1-telemetry-replay-on-reconnect/27.1-CONTEXT.md` (renamed from `999.1-...` 2026-05-02 during v1.5.0.1 init; commits on `main` referencing 999.1 plans are preserved as historical audit trail).

**Dependencies:** None within v1.5.0.1 (independent of 27.2/27.3/27.4 — composes naturally with 27.3 since less raw traffic per buffered minute = longer effective retention in same SQLite size).

**Plans:** 4 plans (3 already executed on `main`)

Plans:

- [x] 999.1-01-PLAN.md — Wave 1: pre-flight Timescale dedupe + idempotent UNIQUE (topic, time) migration in initDb() + shared config/buffered_topics.yaml manifest
- [x] 999.1-02-PLAN.md — Wave 2: implement fc_buffer ROS node (sqlite WAL + http.server on 100.96.239.75:8765 + 24h pruner) + setup.py entry_point + fc.launch.py wiring + systemd /var/lib/fc-core dir setup
- [x] 999.1-03-PLAN.md — Wave 2: bridge buffer_replay.js (30s poll, 15s timeout, ON CONFLICT DO NOTHING) + insertTelemetry timestamp refactor + msg.header.stamp on live RH/T paths + last_ingested_ns persistence to host volume
- [x] 27.1-04-PLAN.md — Wave 3: shipped 2026-05-03 via wg0 architectural detour (originally written for tailscale0; rewrote at deploy time). fc_buffer bound to 172.16.10.5:8765, bridge backfill verified, BUF-04 induced-dropout deferred to natural-event observation

### Phase 27.2: fc-core systemd unit hardening — survive blackout/boot races

**Goal:** Make fc-core's systemd unit survive the boot-time race the 2026-05-02 farm power outage exposed: tailscale0 link came up before acquiring an IPv4, fc-core's `ExecStartPre` only checked link presence, all 5 ROS nodes failed `rcl_create_node`, `ros2 launch` exited 0 (the known systemd trap), 5 retries in ~10s tripped `start-limit-hit`, service stayed dead 55min until manual `reset-failed && start`. Farmer-visible: "fc never came back after black out."

**Requirements (post-realignment 2026-05-03):**

- [x] **SYS-02** — `Restart=always` + `RestartSec=10` + `StartLimitIntervalSec=300` + `StartLimitBurst=5` already in `scripts/pi-deploy/fc-core.service` (live on fc1 after Wave 3 deploy).
- [x] **SYS-03** — Unit has explicit `After=wg-quick@wg0.service` and `Wants=wg-quick@wg0.service` (kernel-WG brings up wg0 at boot). IPv4 polling loop kept as belt-and-braces.
- [x] **SYS-01** — `ExecStartPre` waits for IPv4 on `wg0` via 60-attempt × 1s loop on `ip -4 addr show wg0 | grep -q inet` (already shipped via 27.1 transport switch commits; previous ROADMAP text describing `ip link show wg0` was stale).
- [~] **SYS-04** — Cold-reboot scenario 1: PASS attested 2026-05-07 (41s boot→active, evidence `.planning/phases/27.2-.../evidence/2026-05-07-cold-reboot-journal.log`). wg0-down-at-boot scenario 2: DEFERRED to 999.28 — validating the exact 2026-05-02 failure class is unrecoverable over wg0 (the link being tested is the recovery path); requires lab keyboard access.

**CONTEXT.md:** `.planning/phases/27.2-fc-core-systemd-unit-hardening/27.2-CONTEXT.md` (to be created in plan-phase).

**Dependencies:** Independent. Same family as 27.1 (outages should leave control intact and visibility recoverable, not require human intervention) and as 999.25 (fc-core init race — sister boot-time fragility on fc1).

**Plans:** 1 plan

Plans:

- [x] 27.2-01-PLAN.md — Edit fc-core.service (explicit After=/Wants=wg-quick@wg0.service), fix ROADMAP/REQUIREMENTS text, deploy, validate via cold reboot + wg0-down-at-boot scenarios, capture journalctl evidence (PARTIAL — Tasks 1+2 PASS; Task 3 wg0-down-at-boot deferred to 999.28; SUMMARY.md 2026-05-07)

### Phase 27.3: Telemetry sampling-rate reduction — MOOTED 2026-05-03

Original justification: tailscaled at 240% CPU on fc1's ARM core under DERP-only path → cut 5× by raising `sensor_read_interval` 2.0s → 10.0s.

**Why mooted:** the wg0 transport switch (commit `b79d9e4`) eliminated the saturation root cause — DDS no longer traverses Tailscale's userspace wireguard-go + DERP TLS, it rides kernel-WG directly between fc1 and elder-plops on the home LAN. fc1 load avg dropped from 5+ to 0.41. Tailscaled is disabled.

**What persists as backlog:** the underlying observation that 0.5Hz publish cadence is finer than the chamber's natural RC time constant (mister has ~5min rise/decay, sensor noise dominates short-window deltas anyway). Re-promote if 4G-credit pressure or alerter chart-resolution conversations bring it back.

### Phase 27.4: Repo netplan drift reconciliation — MOOTED 2026-05-03 (in planned form)

Original justification: align repo netplan with fc1's currently-running farm-4G clean state + add `eth0 dhcp4` so the wired path to the 4G router's LAN port works.

**Why mooted in planned form:** fc1 is no longer at the farm on 4G — it's on home-LAN wifi with kernel-WG to elder-plops while the SSD is procured. The drifted state captured in the original plan was a snapshot of the farm-4G config; that config will be re-applied when fc1 returns to the farm. Re-promote at that point.

**Carry-forward note:** the underlying anti-pattern (manual netplan edits on fc1 not reflected in the repo, fc-system-sync would clobber them) is permanent and worth re-addressing whenever fc1 returns to a 4G uplink.

| 36. Signal Pre-gate | v1.7 | 0/TBD | Not started | — |
| 37. Multi-farmer Routing | v1.7 | 0/TBD | Not started | — |
| 38. Extraction Pipeline | v1.7 | 7/8 | In Progress|  |
| 39. Farmer Confirmation Loop | v1.7 | 7/7 | Shipped 2026-05-13 | 127 unit + 11 integration PASS |
| 40. FarmOS Write Path | v1.7 | 8/8 | Code-complete 2026-05-13 | 92/92 unit PASS; live attestation pending |
| 41. Ingestion Harness | v1.7 | 7/7 | Shipped 2026-05-13 | 37 PASS + 5 operator-deferred |
| 42. SHI-on-Sawdust Pilot | v1.7 | 3/3 scaffold | Scaffold shipped 2026-05-13 | Pilot run deferred 4-8 wk (calendar) |

## Backlog (parking lot)

These are ideas captured during v1.0/v1.1 execution but not yet scoped into a
milestone. Promote with `/gsd:review-backlog` when ready.

- **Phase 999.1: Edge buffering — fc1-side ring buffer + replay on reconnect** — **CLOSED 2026-05-20** by Phase 28 (`fc_buffer.py` + bridge `buffer_replay.js`) + 999.36 cursor fix (commit `7660604`). Validated end-to-end by an 11h real cold-reboot outage on 2026-05-20 — ~10h of telemetry recovered automatically from fc1's on-disk buffer into Timescale, no manual ndjson/`\copy` recipe needed (contrast with 2026-05-07 incident which required manual recovery of 199,617 rows). Hourly counts post-recovery: every gap hour 15:00–22:00 UTC filled to expected ~1800 rows/hr. Sole loose end: 14:00 UTC hour landed at ~991/1800 rows (~55%); filed as 999.54 for low-pri investigation. See [[project_2026_05_20_fc_buffer_real_outage_validation]]. Original entry preserved: **PRIORITY BUMP 2026-05-02 (evening):** today's blackout-recovery session lost hours of telemetry forever — multiple multi-minute DERP-relay outages plus the 14:29→15:25 fc-core start-limit-hit window plus the wifi reassociation gap. With Phase 27 high-resolution PID telemetry, every dropout is a permanent hole in data we'd want for tuning, alerting, and post-mortem. The chamber controlled itself fine; we just have no idea what it actually did during ~2 hours of cumulative blackouts today. Wave 1+2 of the phase are already executed (commits `ad44a36..e8d15d0` on main, 8 commits, fc_buffer node + bridge replay poller GREEN); Wave 3 (deploy + soak + farmer attestation) is next. **Treat as the next thing to ship.** Original local SQLite/JSONL on fc1 captures all `fc.*` topics; on bridge reconnect, fc1 replays buffered points with original timestamps so Mission Control gets gap-fill instead of holes. **Earlier motivation 2026-05-02 morning:** ~13-min Tailscale dropout 00:19→00:32 UTC (PID held RH at 94.0±0.04% the whole time — control was unaffected, only visibility was lost). **Scope sketch:** (1) lightweight on-Pi store (sqlite or jsonl with size cap) for all `fc.*` topics keyed by `(topic, ts_ns)`; (2) bridge connection state observer on fc1 — when bridge reconnects, replay un-acked points oldest-first; (3) idempotent ingest on bridge/Timescale side (Timescale already accepts out-of-order inserts cleanly, `(topic, time)` key dedupes). **Compose with:** 999.27 (derived telemetry node — both touch the fc1 telemetry layer; sequence so derived metrics also get buffered), 999.25 (init race — buffer should survive fc-core restarts), 999.18 (true "last fresh" — replayed points should not poison sensor-health timestamps), 999.30 (sampling-rate reduction — composes naturally; less raw traffic per buffered minute = longer retention in same buffer size).
- **Phase 999.2: FarmOS integration** — **CLOSED by v1.7 (Phases 36–42).** Schema locked 2026-05-11 by joint session (farmos repo `d4e5a30`); C1–C5 farm-wide conventions + B1–B7 mushroom-specific bits + P1–P5 SHI-on-sawdust pilot scope all LOCKED. v1.7 exercises the schema and ships the multimodal extraction pipeline (photo + voice + text → LLM → farmOS writes) in one milestone. See v1.7 phases 36–42 above. Original framing: bridge into the farm-wide FarmOS instance for mushroom production tracking.
- **Phase 999.3: Alerts & notifications** — Signal bot for humidity/CO2/Pi-offline/actuator-stuck conditions. Foundation already in place (bridge `/health`, WebSocket broadcast, DB).
- **Phase 999.4: Environmental expansion — fan & light telemetry** — GPIO27 fan MOSFET + fan/light state publishers + Mission Control charts.
- **Phase 999.5: Vision — time-lapse & growth monitoring** — ffmpeg time-lapse composition, pinning/maturity detection, contamination alerts. Feeds Phase 999.3 for grower-facing pinning and "ready to pick" notifications.
- **Phase 999.6: Multi-chamber scaling** — parameterize chamber_id, enable FC-2/FC-3.
- **Phase 999.7: Farm rover** — mobile inspection/actuation platform (camera + airgun + misting nozzle) on a ROS2 rover. Depends on 999.5, 999.3, 999.6.
- ~~Phase 999.8~~ — **promoted to Phase 15** (v1.2.1 hotfix) 2026-04-17 at farmer's request.
- **Phase 999.9: PID + time-proportional humidity control** — replace bang-bang with a PID loop that outputs a 0–100% duty cycle, translated by the actuator layer into time-proportional on/off windows (HVAC-style slow PWM on the binary SSR mister). **Empirically justified 2026-04-11:** farmer calibration session proved bang-bang + 180s dwell has a structural regulation ceiling of ~±2% RH — dwell forces a +2.0% overshoot under a ±0.5% band, 4× the band width itself. Narrower bands provide no additional regulation benefit under the current control law. Full system-ID data (rise/decay rates, deadtime, step response, nonlinear gain scheduling implications, recommended time-proportional window length and interim operating band) captured in `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md` — feedback from the farmer/operator to the dev team. Touches `fc_controller.py` substantially, new actuator duty-cycle primitive, PID tuning params, test suite expansion. Interim band until this ships: `humidity_tolerance: 0.01` (±1%).
- **Phase 999.10: On-demand camera streaming (4G credit thrift)** — `fc_camera` currently publishes `/fc1/camera/compressed` continuously regardless of viewers. At 1 FPS × ~24 KB/frame that's ~2 GB/day of constant cellular traffic, most of it watching nothing. Farmer flagged 2026-04-11 — this will chew through the 4G hotspot credit. Interim workaround applied same day: `camera_fps` lowered from 1.0 → 0.0167 (~1 frame/min, ~35 MB/day), and `camera_fps` default in `fc_camera.py` changed to float to allow sub-1 values. Proper fix: make `fc_camera` subscriber-aware — idle (or drop to a trickle like 1/min) when `count_subscribers('/fc1/camera/compressed') == 0`, ramp to full configured rate when a Mission Control viewer connects. Bridge already owns the MJPEG client set and could hint via a ROS service call. Touches `fc_camera.py` (subscriber polling or service server), possibly `mission_control_bridge` (viewer-state signaling), `fc_config.yaml` (idle-rate param). Not a v1.0 blocker — the YAML workaround holds until 4G budget pressure forces the proper fix.
- **Phase 999.11: Farmer app (operator + grower UI)** — a dedicated app for the farmer's daily workflow: status glance, historical "story view", camera feed, parameter changes, "flag it" backlog capture. Mission Control (OpenMCT) is the engineer surface; the Farmer app is the operator/grower surface. Mobile-first, offline-tolerant over 4G, role-aware (operator vs grower modes). Captured from lived experience during the 2026-04-11 calibration session where Claude Code acted as an ad-hoc farmer app and exposed every gap. **Biggest lesson from that session:** sensor health must be so prominent it is impossible to ignore — today we calibrated against SCD41 humidity for 40 minutes without noticing SHT30 was offline. Full field notes with workflow moments, UI wishes, pitfall reminders, and a 3-item MVP prioritization are in `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md`. Depends on nothing strictly; composes well with 999.3 (alerts/Signal), 999.5 (vision/time-lapse), 999.10 (on-demand camera).
- **Phase 999.13: Upgrade docker-compose v1 → v2** — elder-plops runs compose 1.29.2 which hit a `ContainerConfig` KeyError during v1.1 bridge deploy (2026-04-12), requiring manual `docker rm -f` + recreate. Compose v2 (`docker compose` plugin) fixes this. Container names change from underscores to hyphens (`mushy_bridge_1` → `mushy-bridge-1`) — grep for hardcoded references first. Low risk, high annoyance reduction.
- **Phase 999.14: Camera history — continuous persistence + MC timeline scrubber** — Two issues surfaced during a farmer debug session 2026-04-17 (fc_camera idle-mode stall + discovery that Phase 12's subscriber-aware bridge means idle-pulse frames are never persisted when no one's watching). Original framing ("just index the existing files") was too narrow: indexing a discontinuous history gives a scrubber with blank hours. Real scope: (1) decide who persists idle frames — bridge stays at trickle subscription, or Pi-side history ring buffer, or dedicated archivist subscriber; (2) index in Timescale (`snapshots` table: camera_id, captured_at, file_path, bytes) alongside `saveSnapshot()` (`src/mission-control/bridge/src/index.js:381`); (3) MC timeline scrubber UI. Full findings and scope discussion in `.planning/phases/999.14-index-camera-snapshots-in-timescale/FINDINGS-2026-04-17.md`. Composes with 999.1 (edge-buffering), 999.5 (time-lapse), 999.11 (farmer app story view).
- ~~Phase 999.15~~ — **absorbed into Phase 25** (v1.4) 2026-04-20 after farmer-driven rescope from "unblock snooze receive" into full capture channel (text + audio + images → local Whisper → Anthropic LLM reply). SPEC: `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md`.
- **Phase 999.16: Mission Control chart downsampling — preserve truth, not averages** — Farmer flagged 2026-04-20: downsampled history charts show misleading values. Most obvious on the Humidifier chart (binary 0/1 state rendering as 0.2/0.4/0.6 stray values), same mechanism visible as noise spikes on RH/temp/CO2. Root cause is almost certainly `avg(value)` in the bridge's Timescale `time_bucket` history query — averaging a bucket that straddles a 0→1 transition produces fractional output, and averaging continuous series smooths real peaks/dips into noise-looking artifacts. Fix direction: for state/boolean series (humidifier, actuator states, sensor_health bits) use `last(value, ts)` or `max(value)` per bucket; for continuous series (RH, temp, CO2) use a min+max pair per bucket (LTTB-style) or simply a finer bucket. **Farmer explicitly OK with a performance hit for a better graph** — downsampling is currently too aggressive and removes useful detail. Touches bridge history endpoint (Timescale query), possibly OpenMCT plugin rendering if two points per bucket need to be drawn as a vertical line. Acceptance: humidifier chart shows only 0 or 1; RH/temp/CO2 detail at typical zoom matches the raw data shape.
- **Phase 999.17: Mission Control overlay plots — multiple series per graph** — Farmer request 2026-04-20 while reviewing the stacked Humidity/Temperature/CO2/Humidifier layout: wants to drop multiple curves into the same plot area instead of one-series-per-panel. Immediate use case is plotting SHT30 temp and SCD41 temp together (Phase 26 delivers `fc1/temperature` + `fc1/temperature_2`) so the farmer can eyeball sensor drift/agreement directly; same for RH once both slots exist. OpenMCT supports overlay plots natively via the Overlay Plot telemetry object — this may be purely a layout/config task (persist a Mission Control workspace with the desired overlays baked in) rather than a code change. Scope questions for planning: (1) one-off manual overlay layout saved into the OpenMCT config, or a programmatically-provisioned default layout; (2) whether bridge telemetry metadata (units, display ranges) needs tweaks so overlaid series share a sensible Y axis; (3) persistence/export of the farmer's chosen overlays so they survive container rebuilds. Composes with 999.16 (cleaner downsampled curves make overlays actually readable) and Phase 26 (dual slot topics are the first real payoff).
- **Phase 999.12: Weather telemetry enrichment** — poll Open-Meteo API from Mission Control side (sidecar container or bridge addition), write outdoor temp/humidity/pressure/precipitation to TimescaleDB, display alongside fc1 chamber data in Mission Control. Proxy for a local weather station until one is installed. Farmer request from first 24h of live data (2026-04-12): correlate outdoor conditions with chamber behavior (e.g. wet day → humidifier never fires, RH stays above 83%). Must NOT run on Pi — runs on elder-plops alongside existing Mission Control stack. Touches: new container or bridge module, TimescaleDB schema for weather table, Mission Control layout. Composes well with 999.11 (farmer app — weather context in "story view").
- **Phase 999.18: Sensor "Last fresh" wall-clock truth** — Surfaced live 2026-04-25 right after Phase 26 alerts started landing: alert says "Last fresh: 5m ago" for SHT30 even though it had been offline for *weeks*. Root cause: the alerter initializes `sht30LastSeenMs = nowMs` at boot (`src/agents/alerter/src/state.js:52-53`), so when the alerter boots into a state where the sensor is already offline, it has no record of when the sensor was actually last alive — it only measures "time since alerter started observing." Two fix shapes scoped during the same session: (a) **alerter-only quick fix** — initialize `*LastSeenMs = null`, drop the "Last fresh:" line when null or say "since alerter boot — true age unknown"; (b) **data-truthful fix (recommended)** — add `sht30_last_fresh_ns` / `scd41_last_fresh_ns` KeyValues to `fc_controller`'s `sensor_health` payload (controller already has `_last_sht30_timestamp`), alerter reads from sensor_health instead of computing locally. Survives alerter restarts; reflects the only process that actually knows the truth. Touches `src/chambers/fc-core/fc_core/fc_controller.py` + `src/agents/alerter/src/state.js` + `message.js` + Pi redeploy. Acceptance: when SHT30 has been offline for >X hours and alerter is freshly booted, the alert message reports a duration ≥ X (not "5m ago").
- **Phase 999.21: Timelapse resolution bump** — Farmer feedback 2026-04-28 after watching the first composed timelapse (`/data/timelapse/fc1/2026-04-27.mp4`, 250 frames, 554 KB): "resolution is a bit low, but other than that it's good." Three knobs to investigate before picking the fix path: (1) `fc_camera.py` capture resolution — the source frames; bumping affects live MC view and 4G credit too. (2) JPEG quality on the per-frame snapshots that ffmpeg consumes. (3) ffmpeg encode settings in the timelapse container (resolution, bitrate, codec). Cheapest fix is probably ffmpeg-side if source frames are already higher than what's being encoded. Composes with 999.10 (subscriber-aware camera lets us bump capture resolution without 4G cost during idle hours).
- **Phase 999.20: Alerter multi-farmer routing + group participation** — **CLOSED 2026-05-16: SUPERSEDED by Phase 37 (Multi-farmer Routing, shipped). Both sub-parts (a) reply routing + (b) group participation landed in Phase 37; SIGNAL_ADDITIONAL_SENDERS + SIGNAL_GROUP_ID + signal.js send({to}) refactor + capture-db group_id column all live. Phase 37 Plan 04 Task 3 (live attestations) is the only deferred piece, tracked in 37-RUNBOOK.md.** Original entry preserved below for context: **PRIORITY BUMP 2026-05-11.** Reproduced TWICE today during Phase 36 receive-channel verification: f2 (zoy, +59898018597) DM'd the bot with "pong P36-181143" → captured in `signal_capture` (sender=`+59898018597`) → LLM reply fired → reply landed on f1's phone (`+5...93012`), not zoy's. f1 saw three replies in a row to messages they didn't all send. Embarrassing, easily noticed. The Phase 36 commit `c8e9ac1` plumbed `SIGNAL_ADDITIONAL_SENDERS` through compose (so f2+f3 are now actually whitelisted in production), which makes this routing bug user-visible by default for the first time — previously zoy was invisible to the alerter so the bug was theoretical. Sub-part (a) Reply routing should land BEFORE the next farmer-facing capture feature; sub-part (b) Group chat is still future scope. Original entry preserved: Surfaced 2026-04-28 during Phase 25 UAT-6 follow-up. Two related gaps: (a) **Reply routing** — `signalClient.send()` always targets `SIGNAL_RECIPIENT` (farmer #1). Whitelist now accepts farmer #2 (zoy, +59898018597) and farmer #3 (+12019734942) via new `SIGNAL_ADDITIONAL_SENDERS` env (now plumbed through compose as of 2026-05-11 commit `c8e9ac1`), but if zoy DMs the bot, the LLM reply lands on farmer #1's phone. Fix: route replies to `envelope.source` (the actual sender) instead of a fixed recipient — touches `src/agents/alerter/src/capture.js:146` and the signal client's `send()` signature. (b) **Group chat participation** — there is a "Mushroom Farm" Signal group where all three farmers coordinate; most farm comms happen there, not in DMs. Bot should be able to listen + reply in that group. signal-cli supports group IDs via `groupId` in the dataMessage. Scope: receive-loop must whitelist the group ID (new env `SIGNAL_GROUP_ID`), reply path must send to the group (`signalClient.sendToGroup()`), and capture rows should record group context (new column `group_id` on `signal_capture` for analytics — distinguish "DM with farmer X" vs "group thread"). Open question: does the bot reply to every group message, only when @mentioned, or only for explicit commands? Default proposal: only commands (`mute`, slash-commands) + when its name is mentioned, to avoid spam. Composes with the deferred-items already logged for Phase 25 (degraded-flag persistence on LLM-failure path, llm_session_tag extraction, multi-envelope context).
- **Phase 999.22: BUG — Alerter ops thresholds must read from a single farmer-tunable source, not env** — **CLOSED 2026-05-08 by Phase 29** (alerter consumes mode-driven config via `/fc1/control/current_mode` + `alerter_mode_overrides` + `alerter_globals` topics; .env band-aids reverted). Original entry preserved: Surfaced 2026-04-28 across two farmer interactions in one session. **(1) RH target/band:** farmer changed `target_humidity` 0.90→0.94 + `humidity_tolerance` 0.01→0.015 via `ros2 param set` on `/fc_controller`. Controller picked it up live, but the alerter kept firing OOB pages against its own copy (`ALERT_RH_TARGET=90`, `ALERT_RH_BAND=3`). **(2) Pi/sensor offline thresholds:** farmer flagged that ~5min outages on a known-spotty 4G link aren't worth a page — wants ≥10min before alerting. Fixed downstream by bumping `ALERT_PI_OFFLINE_MIN=10` and `ALERT_SENSOR_OFFLINE_MIN=10` in `.env` and recreating alerter, but same anti-pattern: the farmer-tunable knob lives in elder-plops env, not in a farmer-facing surface. Same root cause: every farmer-meaningful threshold (RH target, RH band, pi offline min, sensor offline min — and likely future temp band, humidifier-stuck threshold, etc.) currently lives as alerter env duplicated from or independent of the controller, requiring `.env` + container recreate to tweak. Farmer (correctly) called this out — syncing env each time is the wrong solution. **Fix direction:** alerter reads ops thresholds from a single source per knob: RH target/band from `/fc_controller` ROS params (which farmer already tweaks live); offline minutes from controller params too OR a dedicated `farmos`/runtime config surface that the farmer app + alerter both consume. Two shapes for delivery: (a) subscribe to a ROS param-broadcast topic the controller publishes (cleanest for controller-owned params, requires controller-side work); (b) alerter polls the bridge for current values via a small endpoint (`/api/fc1/ops_config` covering all alerter-relevant knobs) — the bridge already speaks ROS. Touches `src/agents/alerter/src/config.js` (drop static env-fed thresholds, fetch dynamically), `src/agents/alerter/src/rules.js`/`message.js` (re-evaluate per-tick instead of capture-at-boot), possibly `src/mission-control/bridge/src/index.js` (new endpoint or ws message type), and the controller (expose offline-min knobs as ROS params if we go route-(a)). **Interim state on elder-plops `.env`:** `ALERT_RH_TARGET=94`, `ALERT_RH_BAND=3`, `ALERT_PI_OFFLINE_MIN=10`, `ALERT_SENSOR_OFFLINE_MIN=10` — keep these in sync with the live controller until the fix lands. **Acceptance:** any farmer-meaningful threshold change (RH target via `ros2 param set`, future farmer-app slider, etc.) is reflected in the alerter's next evaluation cycle with no container/env/restart action. **Composes with 999.23** — the dynamic-target work means the alerter's "current target" will change *over time within a single grow* (ramps, scheduled day/night cycles, fruiting-stage transitions), so reading-from-controller isn't an optimization, it's a correctness requirement. Whatever fix shape lands here should expose the *current effective values at evaluation time*, not a static-at-boot snapshot. **Sweep when fixing:** `src/agents/alerter/src/config.js` for any other farmer-meaningful knobs hiding in env (heartbeat hour, humidifier-stuck threshold, RH OOB grace, etc.) — pull them all to the same surface in one go.- **Phase 999.23: Dynamic RH target — schedules, ramps, stage-aware setpoints** — Farmer flagged 2026-04-28: the current single scalar `target_humidity` is fine for today but won't hold up. Real grows want (a) **scheduled modes** (e.g. "fruiting" 95% RH day / 90% night, "pinning" 98% for first 48h then taper, "incubation" 80% baseline), (b) **animated ramps** between setpoints instead of step changes (smooth transitions over minutes/hours so the bang-bang controller doesn't slam), and (c) **stage-aware presets** triggered by farmer action ("flag spawn-run start" → switch profile) or by elapsed time inside a stage. Groundwork lessons to apply *now* so we don't re-architect later: (1) the canonical target should be a *function of time* `target_humidity(t)`, not a constant — even today's static value should pass through that function (constant profile). (2) anything reading the target (alerter 999.22, farmer dashboard, history charts as a reference line, future PID 999.9) must read the *current effective value*, not a config snapshot. (3) keep schedule definition declarative (YAML/JSON profile per chamber per stage) — don't bake mode logic into the controller's Python. (4) profile changes should be a single farmer action (Signal command, farmer-app button, farmOS stage transition), not a redeploy. **Composes with:** 999.9 (PID — proper ramp tracking needs a non-bang-bang loop), 999.22 (alerter must already be reading from controller, not env, before targets start moving), 999.11 (farmer app — schedule editor UI), 999.16 (history charts should overlay the *moving* target line, not a flat one), Phase 26 (dual-sensor selection per stage — e.g. trust SCD41 RH during fruiting, SHT30 during incubation). **Acceptance (groundwork milestone, not full delivery):** controller exposes `current_target_humidity` and `current_humidity_band` as runtime-evolving params/topics; default profile is the existing constant; alerter + dashboards consume the current value; no more than one new abstraction in the controller (a `TargetProfile` strategy interface), keep the YAML for static-target users untouched.
- **Phase 999.24: fc_camera VideoCapture re-open on cap.read() failure** — **CLOSED 2026-05-11** (commit `884e108`). Auto-reopen after `camera_reopen_threshold` (default 5) consecutive cap.read() failures: cap.release() + reconstruct cv2.VideoCapture(device) with original width/height, exponential backoff (1s→2s→…cap 60s) on reopen failure. New unit test `TestCameraReopenOnStuckRead` mocks stuck→good VideoCapture instances and asserts release+swap+counter-reset. 16/16 test_camera.py PASS locally. Sensor_health `camera_fresh` emission deferred (composes with 999.18). Original entry preserved: Surfaced 2026-04-29: snapshots chip went red after ~24h of zero captures. Root cause was fc_camera spamming `cap.read() failed, skipping frame` continuously since Apr 28 ~13:09 UTC with no recovery — the loop in `fc_camera.py:152-155` just logs warn + returns; never releases or re-opens the `cv2.VideoCapture` handle. USB camera was still enumerated (`/dev/video0` present, `lsusb` showed Microdia 0c45:636b) so a `systemctl restart fc-core` recovered it cleanly — confirms the fix shape is software-only re-open, not hardware reseat. Memory's "Phase 12 9s recovery" covered a *different* stall mode (idle/inactive timer, not cap.read). **Fix:** after N consecutive cap.read() failures (say 5 — i.e. 5 sec at active fps), `cap.release()` + reconstruct `cv2.VideoCapture(device)`, re-apply width/height/buffer settings; if reopen fails, exponential backoff retry. Don't swallow indefinite failure — emit a `sensor_health` KeyValue (`camera_fresh: false`) once the stall exceeds a threshold so the alerter (Phase 999.18-shape) can page. Acceptance: yank+replug the USB cam at the chamber → fc_camera resumes publishing within 30s without a service restart; snapshots chip stays green. Touches `src/chambers/fc-core/fc_core/fc_camera.py` + a small unit test that mocks `cap.read()` returning False and asserts re-open is attempted. Composes with 999.18 (true-age tracking — alerter should know "camera last fresh: X mins ago" not "since alerter boot").
- **Phase 999.25: fc-core CycloneDDS-over-Tailscale init race at startup** — Surfaced during 2026-04-29 sensor-offline-alarm investigation. Journalctl shows the `rmw_create_node: failed to create domain, error Error` cluster (e.g. Apr 27 18:52 + 19:24 UTC) where all four nodes (`fc_sensors`, `fc_controller`, `fc_display`, `fc_camera`) exit 1 in lockstep, plus periodic `Sensor data stale — humidifier OFF for safety` events when `fc_sensors` alone dies and the controller stays up but goes stale (Apr 24 ~03:43, Apr 28 ~06:42). 7-day rate is roughly 2–3 brief outages/week, each ~1 minute downtime under the new `Restart=always` (which is masking, not fixing). Almost certainly a startup ordering race: fc-core boots before `tailscale0` + `cyclonedds-tailscale.xml`'s peer endpoints are reachable, so `rmw_create_node` fails on the first DDS domain join. The systemd unit (`fc-core.service`) currently has `Restart=always` + a hard 20s `startup_grace_period` in the controller, but no `After=` / `Wants=` / `ExecStartPre=` gate on Tailscale or DDS readiness. Each crash → sensors stale → alerter pages (now ≥10 min, but still pages on a real long outage). **Fix direction:** (a) `After=tailscaled.service` + `Wants=tailscaled.service` on `fc-core.service` so systemd serialises the dependency. (b) `ExecStartPre=/usr/bin/tailscale status --self=true --peers=false` (or a small wait-for-peer script) that polls until the Tailscale data-plane is up. (c) consider giving CycloneDDS a longer `peer.discovery_timeout` for the cold-boot case. (d) emit a `fc_init_failed` boot counter to `sensor_health` so we can graph crash frequency post-fix. Touches `scripts/pi-deploy/systemd/fc-core.service` (the Pi-deployed unit; remember `feedback_diff_repo_vs_pi_systemd` — the live unit may have drifted), possibly a small `scripts/pi-deploy/wait-for-tailscale.sh` helper. Acceptance: zero `rmw_create_node: failed to create domain` events over 14 consecutive days post-deploy; sensor-stale events <1/week (i.e. only real network/i2c hiccups, not init races). Composes with 999.18 (alerter "Last fresh" should make crash-vs-network distinguishable from the farmer's perspective).
- **Phase 999.19: Alert link → real farmer destination** — Surfaced 2026-04-25: alerter `DASHBOARD_URL` linked to `/farmer` on the bridge, but Phase 18 only built `/farmer/summary` (a JSON API for farmOS to consume) — no HTML page at `/farmer` ever existed. Farmer tapped the link from Signal and got "Cannot GET /farmer." Patched same session by repointing to OpenMCT (`http://100.96.10.66:8080/`) which is reachable on the tailnet and shows live dashboards, but per `project_phase18_22_farmos_proxy_architecture` the long-term farmer destination is the farmOS "story view" (Zoy-side, page path TBD). Decision needed when farmOS story view is ready: switch DASHBOARD_URL to that page so the alert link lands on the farmer-friendly UI, not the operator-facing OpenMCT. Trivial config change — `src/agents/alerter/src/config.js` + `docker-compose.override.yml`. Acceptance: tapping the alert link from the farmer's phone lands on the farmer dashboard (whatever its final URL), not OpenMCT.
- **Phase 999.27: Derived telemetry channel — bridge-side `fc_metrics` module** — Surfaced 2026-05-01 during Phase 27 deploy; **architecture revised 2026-05-02 (farmer call): bridge-side, NOT a new fc1 ROS node.** Farmer asked for a delta-t / error parameter on the OpenMCT charts; the right shape is a derived-telemetry sidecar. **2026-05-02 decision:** compute derived values inside the bridge (JS module subscribed to raw topic stream the bridge already consumes), write directly to Timescale + broadcast on WS to OpenMCT. **Reasoning for bridge-side:** (a) bridge already subscribes to every raw topic, (b) elder-plops has the CPU/RAM headroom, (c) iterating on a new metric = `docker compose up -d --build bridge` (seconds) instead of `git push fc1/prod` + deploy.sh + 999.25 init-race risk, (d) no ROS-side consumers of derived topics on the near-term roadmap (alerter is WS-only per 999.1 RESEARCH §Q10), so the "ROS-native lifecycle" argument doesn't pay rent yet. **MUST be replay-aware:** when 999.1 buffer backfills 13min of raw T/RH/PID into Timescale post-Tailscale-dropout, the derivation pipeline must compute derived values for those backfilled timestamps too — otherwise raw series fill in but derived series stay as holes. Bake retroactive derivation into the design from day one. **v1 metric set (mushroom-relevant):** (1) `humidity_error` = humidity − humidity_target — direct PID error visualization, the trigger for this phase; (2) `vpd` (kPa, function of T+RH) — true driver of mushroom moisture exchange, more useful than RH alone; (3) `dew_point` (°C, T+RH) — condensation risk on chamber walls / camera lens; (4) `abs_humidity` (g/m³, T+RH) — what the humidifier actually has to add when temperature swings; (5) `humidity_rate` (%/min, smoothed RH rolling window) — spot leaks/stalls before they hit the band. **Touches:** new `src/chambers/fc-core/fc_core/fc_metrics.py` ROS node + `setup.py` entry_point + `launch/fc.launch.py` wiring (mirrors Plan 27-02 pattern), `src/mission-control/bridge/src/index.js` `ALLOWED_TOPICS` + 5 subscriptions, `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` SENSORS + fieldToKey, RED tests then GREEN. **Composes with:** 999.17 (overlay plots — VPD overlaid on RH+target tells the real story), 999.22 (alerter must read derived values dynamically — VPD-out-of-range is a nicer alert than RH-out-of-range), 999.23 (when target becomes time-varying, humidity_error has to be re-derived per-tick from current effective target). **Acceptance:** five derived topics live on fc1, persisting to Timescale, visible on OpenMCT with correct units; VPD chart matches a hand-calculated value within ±0.05 kPa for a known T/RH pair.
- **Phase 999.26: Camera coverage prerequisite for vision (roaming or multi-cam)** — Surfaced 2026-05-01 when farmer reviewed Phase 24 scope and called the blocker: a single fixed FC-1 camera only frames a fraction of substrate, so ML vision alerts (pinning, contamination) on that footprint are a demo, not a field-useful tool. Phase 24 (ML vision via ComfyUI) is deferred behind this. Two viable shapes to weigh during planning: (a) **roaming cam** — the farm-rover seed (999.7) carries a single camera through the chamber on a schedule, captures pose-tagged frames covering all shelves; reuses any servo/motion work; one camera to maintain but mechanical complexity and a moving part in a high-RH environment. (b) **multi-cam** — N fixed cameras (one per shelf or per chamber zone), each publishing to a slot topic; reuses the existing `fc_camera` node pattern (parameterize device + camera_id), Phase 21 persistence and Phase 22 scrubber generalize over multiple `camera_id`s; more hardware + more 4G traffic but no mechanical risk. Either path needs: persistence/index extended to multi-camera (`snapshots` table already has `camera_id`), Mission Control + farmer-app UI extended to pick/switch camera, time-lapse composition extended per-camera, vision-agent (Phase 24 follow-up) able to fan out per-camera. Composes with: Phase 24 (the consumer that unblocks), 999.6 (multi-chamber scaling — same pattern), 999.7 (rover — overlaps with shape-(a)), Phase 21/22/23 (persistence, scrubber, timelapse all need camera_id awareness). Pre-decision when promoted: roaming-vs-multi-cam tradeoff with farmer in the loop (mechanical risk vs hardware/cost vs operational complexity).

- **Phase 999.28: fc-core systemd unit hardening — survive blackout/boot races** — Surfaced 2026-05-02 after a farm power outage. fc1 booted, `tailscale0` link came up before acquiring an IPv4. fc-core's `ExecStartPre` only checks `ip link show tailscale0` (link presence), so launch fired while CycloneDDS still reported "tailscale0: does not match an available interface". All 5 ROS nodes failed `rcl_create_node`; `ros2 launch` exited 0 (the known systemd trap captured in `feedback_systemd_restart_ros2_launch`); 5 retries in ~10s tripped `start-limit-hit`; service stayed dead 55min until manual `systemctl reset-failed && systemctl start fc-core`. Farmer-visible: "fc never came back after black out." **Scope:** (1) `ExecStartPre` waits for tailscale0 to have an IPv4 address, not just link existence (e.g. loop on `ip -4 addr show tailscale0 | grep -q inet`); (2) apply the existing Restart=always + `RestartSec` + wider `StartLimitInterval`/`StartLimitBurst` lesson — fc-core unit on the Pi predates that fix; (3) consider `After=`/`Wants=tailscaled.service` or a dedicated tailscale-ready oneshot; (4) audit other fc1 systemd units (fc-update, anything else binding DDS to tailscale0) for the same race. **Out of scope:** changing CycloneDDS interface binding away from tailscale0 — that's the deliberate VPN-only design from the farm connectivity work. **Validation:** simulate by stopping tailscaled and rebooting the Pi; confirm fc-core waits and comes up green without manual intervention. **Composes with:** 999.25 (init race — same family of boot-time fragility on fc1), 999.1 (edge buffering — outages should leave control intact and visibility recoverable, not require a human to notice).

- **Phase 999.29: Replace rolling-duty cap with max-continuous-on + forced cool-down** — Surfaced 2026-05-02 during today's blackout + uplink-instability incident. Chamber RH sat at 68–80% (target 94%) with PID demanding `duty=1.0` continuously for hours. `fc_pwm_driver` enforces a rolling 5-min duty cap D-12 (default `max_duty_5min_avg=0.40` — see `src/chambers/fc-core/fc_core/fc_pwm_driver.py:35-41` + back-solve at `:119-121`). At cap=0.40 the chamber recovers at ~0.5%/min, so a 26% deficit takes nearly an hour to close — every minute below target is mushroom-welfare risk. **Hotfix shipped:** raised cap to 0.90 on fc1/prod (commit `ad949c6` 2026-05-02); this permanently loosens a steady-state safety to cover what is actually a transient recovery scenario.

  **Preferred design (farmer call 2026-05-02):** retire the rolling-average cap entirely and replace with a **max-continuous-on with forced cool-down**: humidifier is allowed to run continuously up to `max_continuous_on_seconds` (e.g. 45 min), then is forced OFF for at least `forced_cooldown_seconds` (e.g. 3 min) before it may run again. Effective max duty in extreme demand ≈ 94% (45/48), ample for recovery from any plausible deficit, while still guaranteeing the mister gets a periodic break to bleed thermal/mechanical load. Steady-state behavior: PID typically demands 5–30% duty, so windows are short and the cool-down rule essentially never engages — i.e. it imposes no penalty on normal operation. Concrete and explainable: "max 45 min on, then 3 min off" is a sentence; "rolling 5-min average duty cap with back-solve" needs a paragraph.

  **Scope sketch:** retire `max_duty_5min_avg`; new params `max_continuous_on_seconds` + `forced_cooldown_seconds` + the `_window_on_seconds` back-solve goes away (windows still exist, just no cap rule on top). State machine in `_tick`: track `_continuous_on_seconds` (incremented when relay is high, reset to 0 on every OFF edge); when `_continuous_on_seconds >= max_continuous_on_seconds`, force OFF and start `_cooldown_remaining = forced_cooldown_seconds`; while `_cooldown_remaining > 0`, override duty to 0 regardless of PID demand. Tests: continuous-on hits cap → forced OFF; cool-down completes → resumes; PID asks for 0.5 forever → never trips cap (windows have built-in offs); rapid demand changes → no missed cool-downs.

  **Validation:** induce a 25% RH deficit (door open then closed), confirm chamber recovers at ≥ ~1.0%/min vs the ~0.5%/min seen today with cap=0.40; confirm during a real long demand period that the forced 3-min off does happen on schedule.

  **Source for 45/3 numbers:** farmer's gut estimate (confirmed 2026-05-02), not from a hardware spec or empirical thermal test. Treat as starting point, not gospel — pre-planning task: check the actual mister hardware spec for max-continuous-duty rating + run a single soak test (run the mister for 60+ min, watch for thermal trip / output degradation / water-pump strain) before locking values into the plan.

  **Fallback design** (if the max-on approach turns out to have an edge case): the original conditional-recovery-mode shape — keep cap=0.40 steady-state but auto-lift to ~0.95 when `|humidity_error| > 0.05` with hysteresis. Documented here for contrast; not the primary plan.

  **Out of scope:** removing all duty protection; UI-tunable cap (lands via Phase 28 Mode primitive anyway).

  **Composes with:** Phase 28 (mode primitive — cool-down params could be per-mode), 999.27 (derived telemetry — `humidity_error` and `humidifier_continuous_on_seconds` are nice things to chart), 999.28 (fc-core systemd hardening — same family of blackout-recovery resilience).

  **Concrete trigger:** today's outage proved cap=0.40 is an active hazard during recovery; until this ships we run with cap=0.90 in steady state (less protection in steady state) or revert to 0.40 and accept slow recovery on every future blackout.

- **Phase 999.31: BUG — `fc_pwm_driver` duty-history deque size mismatches its 5-min comment** — **CLOSED 2026-05-11** (commit `b8faf81`). Applied option (a): `maxlen = ceil(300 / pwm_window_seconds)` so deque actually covers ≥5 min instead of ~10h. Added `test_duty_history_maxlen_matches_5min_window` asserting maxlen=3 at default 120s window. Tests NOT run locally — ROS Jazzy not installed on elder-plops; verify via colcon on fc1 before pushing to fc1/prod. Original entry preserved: Surfaced 2026-05-04 during PID tuning + RH setpoint bump (94% → 97%). `fc_pwm_driver.py:83` declares `self._duty_history = deque(maxlen=300)` with comment "5min @ 1Hz tick", but appends happen once per **window rollover** (every `pwm_window_seconds = 120s`), not at 1Hz. Effective rolling window is therefore 300 × 120s = **~10 hours**, not 5 minutes. The cap (`max_duty_5min_avg = 0.90`) still converges — the back-solve in `:119-121` keeps long-run average ≤ cap — but: (1) the param name lies (it's a 10h average, not 5min); (2) recovery dynamics differ from intent — a single short high-duty burst gets averaged against many hours of low-duty windows, so the cap engages much later than a true 5-min window would; (3) on cold start the deque is empty, so the first ~5 windows are uncapped (matching the comment for the wrong reason). **Fix options:** (a) change `maxlen` to `int(300 / pwm_window_seconds)` (= 2 or 3 entries) so the rolling window matches the param name; (b) keep the deque at 300 but rename the param + comment to match reality (10h average duty cap); (c) move the cap rule to a wall-clock-bounded window instead of an entry-count deque. **Likely subsumed by 999.29** — that phase retires `max_duty_5min_avg` entirely in favor of max-continuous-on + forced cool-down, which sidesteps this bug. **If 999.29 ships first, close this as obsolete.** Otherwise: trivial 1-line fix (option a), worth doing because the comment lies to the next reader and the cap behaves differently than its name implies. Touches `src/chambers/fc-core/fc_core/fc_pwm_driver.py:83` + `test/test_pwm_driver.py` (add a test that pumps N windows of duty=1.0 and asserts cap engages on the (n+1)th, where n matches the documented window). **Composes with:** 999.29 (the structural fix that makes this moot), 999.27 (derived telemetry — `humidifier_continuous_on_seconds` would be a better metric than rolling-average anyway).

- **Phase 999.32: BUG — `pid_derivative_filter_tau` declared but never wired into PID** — **CLOSED 2026-05-11** (commit `cd60801`). Applied option (a): external LPF on PID's derivative term in fc_controller, vendored simple_pid untouched. Filter math `alpha = dt/(tau+dt); d_filt += alpha*(d_raw - d_filt)` runs after every PID call; `_d_filtered` resets to 0 on every (re-)engage path. tau=0 disables filtering live. Default tau=10s retained per user opt-in. Tests: 2 new in test_pid_kernel.py (filter attenuation + tau=0 passthrough); all 8 PID kernel tests PASS locally. ⚠ Full fc_controller suite not run (ROS not on elder-plops); verify via colcon test on fc1 before letting fc-update.service auto-deploy. Farmer's "no prod changes during tuning" caveat acknowledged — user explicitly opted into active-filter ship 2026-05-11. Original entry preserved: Surfaced 2026-05-04 while diagnosing noisy PID output during second-day calibration session. `src/chambers/fc-core/config/fc_config.yaml` declares `pid_derivative_filter_tau: 10.0` and `fc_controller.py:42` reads it into the param table, but it is **never passed to or used by the PID**. The vendored `fc_core/vendor/simple_pid/pid.py` has zero references to derivative filtering — `grep -n "derivative_filter\|d_filter\|filter_tau\|tau"` across both files returns only the param declaration line. The `PID(...)` constructor at `fc_controller.py:151-161` doesn't pass it; the live-reload block at `:419-421` only refreshes Kp/Ki/Kd. **Effect:** since Phase 27 shipped, the PID has been running with raw, unfiltered derivative — sensor jitter at the 5Hz tick scale gets multiplied by Kd=4.0 directly. With ~±0.02 %/s tick-to-tick variation on smoothed-but-not-filtered RH, D contribution swings ~±8 % duty per tick. This is the dominant noise source on `pid_output` — far louder than the P contribution (~±2 % at Kp=0.35) or I term. **Why it wasn't noticed earlier:** (a) Phase 27 calibration happened at higher Kp where P-noise dominated optically; (b) the median-filter on input (`_humidity_buffer`, deque maxlen=5) absorbs single-sample spikes so the input *looks* clean — but median doesn't smooth tick-to-tick walk, which is what hurts derivative; (c) the param was specced and named, easy to assume "10s filter is on" when reading the config without grepping the call site. **Fix options (in order of effort):** (a) **add a low-pass on dRH/dt before the PID call** in `fc_controller.py` — ~5 lines, uses the existing param, leaves vendored library untouched (recommended); (b) patch the vendored `simple_pid/pid.py` to support a derivative filter (~1 line in `_compute`, but taints the vendored library); (c) replace `simple_pid` with a controller that supports derivative filtering natively (cleanest, most invasive). **Acceptance:** with `pid_derivative_filter_tau=10.0` and Kd=4.0, observed `pid_output` noise during steady-state holds drops by ≥3× compared to current behavior; D term still responds to real RH transients (e.g. door open) within ~10–20 s. Add a unit test that pumps a synthetic noisy RH series + step disturbance and asserts both noise rejection and step responsiveness. **Composes with:** the next-session PID retune (filing this fixes the noise before any Kd-lowering experiment, which would otherwise conflate two effects), 999.27 (derived telemetry — `humidity_rate` published as a smoothed series would let the alerter and dashboards consume the same filtered signal the PID uses, single-source-of-truth). **Decision deferred:** whether to patch this in v1.5.0.1 or wait for next-weekend tuning session — filed 2026-05-04 with explicit "do not change prod code while live-tuning" guidance from farmer.

- **Phase 999.30: Reduce telemetry sampling rate to relieve DERP-relay pressure** — Surfaced 2026-05-02 evening after diagnosing tailscaled at 240% CPU on fc1 (load avg 4.7 across 4 cores) when polled from elder-plops over the lossy São Paulo DERP relay. Hypothesis: every 5Hz humidity publish + control-loop chatter has to traverse Tailscale → DERP → elder-plops; with the relay dropping packets, DDS reliable QoS forces aggressive retransmits and tailscaled pays the CPU cost. Reducing publish cadence from `sensor_read_interval: 2.0` (every 2s, 0.5Hz) to ~10s (0.1Hz) cuts the per-second packet volume 5×, which should drop tailscaled CPU well below the saturation point and free up Pi headroom. **Touches:** `src/chambers/fc-core/config/fc_config.yaml` `sensor_read_interval` (currently 2.0); possibly the `control_interval: 1.0` and `display_interval: 1.0` if we want to slow those too — separate decision, since control_interval is a real control-loop knob (slowing it changes PID dynamics, not just visibility cadence). **Implications to think through during planning:** (1) Phase 27 PID tuning was done at 2s interval — slowing to 10s changes the discrete-time response and may need re-tuning; recommend keeping `control_interval` fast and only slowing `sensor_read_interval` (the publish cadence to Mission Control), if that's actually how the code is wired. Read `fc_sensors.py` + `fc_controller.py` to verify the two are decoupled before planning. (2) Alerter "last fresh" sensitivity — Phase 26 alerter uses sensor_health timestamps; slower publish = larger natural gap before "stale" — needs new `sensor_stale_timeout` (currently 10.0s, would have to be at least 2× new publish interval). (3) Mission Control chart resolution — farmer's UI gets 5× coarser; with 999.16 downsampling already in flight this may compound. **Composes with:** 999.1 (edge buffering — fewer raw points per minute = longer effective buffer in same SQLite size; ratio improves), 999.27 (derived telemetry — bridge-side derivation runs at the publish cadence, so cost goes down too), 999.28 (systemd hardening — same family of "make fc1 robust against bad uplink"). **Out of scope:** changing the DERP relay choice (Tailscale auto-selects; could be forced via `--exit-node` but that's its own decision tree); compressing DDS payloads. **Validation:** before/after tailscaled CPU + load-avg measurement when poked from elder-plops; chamber RH chart still readable in Mission Control with 5× coarser samples; alerter doesn't fire false-positive "sensor stale".

- **Phase 999.33: Digital twin / simulation of FC chamber for offline control development** — Surfaced 2026-05-04 during PID calibration session 2. Today produced *six* substantive control-design artifacts (Kp tuning, capacity envelope, two flavors of overshoot, integrator-driven limit cycle, derivative-filter bug, feedforward case) — all of them required real chamber + a live grow + ambient temperature swings + farmer presence. Iteration cadence: ~1 idea per real-world day, gated on actual weather. **Strategic ask:** stand up a digital twin so we can iterate control logic at 100× real-time, validate against historical data, and stop blocking on live-grow exposure for tuning experiments. **What we have for system ID** (calibrated empirically today, 2026-05-04): chamber V = 5.76 m³ (2.4 × 1.2 × 2.0 m grow tent), m_air ≈ 7 kg, mister output M ≈ 6 g/min, dead time θ ≈ 50 s (impulse), chamber τ ≈ 10 min (1st-order), 19-min sustained-disturbance lag (suggests 2nd-order dynamics under perturbation), leakage L scales 3.5× from cold-dry to warm-wet (matches saturation-pressure-differential physics). All in `docs/pid_calibration_notes.md` "Chamber Dynamics" section. Plant model is approximately: `dRH/dt = (M·duty − L·(P_v_in − P_v_out)) / (m_air × dRH/dw_at_T) − dT/dt × dRH/dT_at_constant_water` — a 1st-order ODE with temperature as an exogenous disturbance. **Two implementation shapes:**

  **(a) Lightweight Python sim — recommended start.** Pure ODE in `fc_core/sim/chamber_model.py`, parameterized by the system-ID numbers above. Hooks into the existing `simulation_mode: true` path in `fc_config.yaml`. Replaces the current "no-op simulator" (which today just returns canned sensor values) with a physics model that responds to actuator commands. Inputs: actuator state (humidifier on/off, fan duty), exogenous T(t) (replay from Timescale or synthetic curve). Outputs: RH(t), with realistic dead time + lag. **Cost:** maybe 200 lines of Python + tests; days, not weeks. **Wins:** (1) every `colcon test` cycle exercises the controller against a realistic plant; (2) replay any historical incident — feed today's T(t) trace and run alternate Kp/Ki/Kd to see if the limit cycle goes away; (3) test 999.29 max-continuous-on, 999.32 derivative filter, gain scheduling, MPC, all without touching live; (4) CI gate: every PR runs a 24-h synthetic grow and asserts RH-error stays in band; (5) farmer-facing "what-if" demos.

  **(b) Gazebo full digital twin — bigger, longer payoff.** Stand up the FC-1 tent geometry in Gazebo with thermal/humidity plugins, sensor models for SHT30/SCD41 with realistic noise + lag, USB-camera plugin, ROS2 bridge so `fc_core` runs unchanged against the simulated chamber. **Cost:** weeks of work, real Gazebo expertise required (thermal/humidity plugins are not stock — need custom ROS2 sensor plugins or hooking in our Python ODE behind a Gazebo facade). **Wins beyond shape (a):** (1) multi-chamber and rover scenarios (composes with 999.6 multi-chamber, 999.7 rover); (2) camera vision pipeline can be tested in sim (composes with Phase 24 ML vision, 999.26 camera coverage); (3) sensor-placement experiments (where to put SHT30 in a 2 m tall tent); (4) farmer training / demo without burning real grow time; (5) reusable for future hardware (when we add condensation forcing, fans, etc.).

  **Recommendation: do (a) now, plan for (b) when multi-chamber or vision testing become hot.** Shape (a) gives us the offline iteration speed that's the immediate pain point; shape (b) is justified only when we have spatial/sensor/vision questions Python can't answer. The two are compatible — (a)'s ODE can be the physics engine inside (b)'s Gazebo plugin later.

  **Pre-requisite for (a):** finalize the chamber model. Today's numbers are first-pass — would benefit from a deliberate system-ID session: induce known step disturbances (open the door, run mister at duty=0.3 vs 0.7, watch decay) at multiple operating points to fit a proper `M(T), L(T,RH_in,T_out)` model. Or skip the formal ID and just use the empirical first-pass model + tune to match this week's Timescale archive.

  **Composes with:** 999.27 (derived telemetry — sim outputs feed the same `vpd`, `dew_point`, `humidity_error` pipeline, single-source-of-truth for "what would the bridge see"), 999.6 (multi-chamber scaling — sim is the prerequisite for safe scaling tests, can't risk real chambers), 999.7 (rover — physical sim shines here), 999.29 (max-continuous-on cap — validate in sim before live), 999.32 (derivative filter — verify in sim first), Phase 24 (ML vision — sim camera enables vision testing without farm visits).

  **Anti-scope:** not a "smart greenhouse" simulator with biology — no mushroom growth model, no contamination dynamics. Just chamber thermodynamics + actuator response. Mushroom-side modeling is a separate (much harder) ask; punt.

  **Acceptance for shape (a):** running `colcon test --packages-select fc_core` includes a "24-h grow simulation" that loops the controller against the ODE chamber, assert RH stays within ±1% of target across a synthetic ambient-temp curve mirroring a real Uruguay autumn day; tests pass with current Kp=0.35 / Ki=0.002 / Kd=4.0 gains and reproduce the limit cycles we observed today (i.e., the sim is faithful enough to show the same failure modes). **Acceptance for shape (b):** deferred — shape (b) gates on a concrete use case (multi-chamber, vision, etc.).

  **Filed 2026-05-04 evening** — the day's calibration session was rate-limited by ambient temperature, weather, and farmer availability. Sim would change that.

- **Phase 999.34: Periodic SHT30 heater cycle to clear membrane condensation** — Surfaced 2026-05-04 evening. SHT30 datasheet recommends running the on-die heater periodically when the sensor is exposed to sustained high humidity; FC-1 sits at 94–96% RH effectively 24/7, exactly the stress regime where membrane condensation causes the RH reading to drift positive (sensor reads near-saturated even when the air isn't). The heater is **already accessible** — `adafruit_sht31d` exposes it as `self.sht.heater = True/False`, no driver work needed. Heater raises *sensor* T by ~0.5–1.5 °C for ~3.6 mA at 3.3 V; chamber bulk T is unaffected, but the sensor's own T+RH readings are corrupted during heating + ~30 s recovery before they re-equilibrate. Fits cleanly into our quiet-window cadence (chamber inertia τ ≈ 10 min means controller can hold last-duty for 30 s with negligible RH impact).

  **Implementation surface:** `src/chambers/fc-core/fc_core/fc_sensors.py` (new periodic-heater scheduler + `sensor_health.heater_active` flag), `src/chambers/fc-core/fc_core/fc_controller.py` (hold-last-duty when `heater_active=true`, do not enter safe-state), `src/agents/alerter/src/rules.js` (suppress "sensor stale" / OOB alarms during heater + recovery window), bridge / Mission Control plugin (annotate or mask heater windows on charts so the corrupted readings don't look like real anomalies).

  **Open design questions for planning** (each with a recommended default; resolve during discuss-phase):

  1. **Cadence:** nightly fixed schedule (default: 03:00 UYT, chamber quiet, low duty, no farmer attention) vs condition-triggered (e.g., RH > 95% sustained 24h, or "RH reading hasn't moved more than 0.05% in N minutes" as a stuck-membrane heuristic) vs both. Recommended default: nightly fixed first; add condition-trigger later if drift evidence emerges.

  2. **Pulse duration + recovery:** 1 s heater on, then ignore sensor readings post-heat. Datasheet ranges 1–3 s pulses. **Live test 2026-05-04 22:02 UTC measured numbers** with 3 s pulse: sensor T peak +0.73 °C (14.58 vs 13.85 baseline, well within datasheet 0.5–1.5 °C); RH dipped -0.55 % (95.83 vs 96.39); **T recovery to baseline: ~60 s; RH recovery to baseline trend: ~150 s (2.5 min)**. RH recovery is the binding constraint — *not* 30 s as initially specified. Default updated: **1 s pulse, hold-last-duty for 180 s** (3 min), or condition-driven release (T within 0.05 °C of pre-pulse and slope ~0). 1 s pulse on a clean (uncondensed) sensor likely shortens RH recovery somewhat — re-measure after first nightly pulse on production sensor.

  3. **Controller behavior during cycle:** hold last duty (recommended — chamber inertia tolerates 3 min of open-loop fine) vs go to safe-state OFF (rejected — would cause unnecessary RH dip) vs continue PID against last-good-reading (rejected — controller would drift on stale data). Default: hold-last-duty for the full heater + recovery window. **Live test confirmed this is non-optional**: the same 22:02 UTC pulse, with no controller guard in place, caused the PID to spike duty from 0 → ~**0.85** for ~60 s in response to the synthetic RH dip. In active control during a daytime warm-up regime, that spurious 0.85 spike for ~1 min would inject ~5 g of extra water and produce a ~0.6 % real RH overshoot — directly re-triggering the integrator-driven cycle the day's tuning work was meant to fix. **Heater feature without controller guard is net-negative**; both must ship together. (Bug 999.32 unfiltered derivative compounds this — D-term saw the synthetic falling-RH and slammed duty up; once 999.32 ships the spurious spike will be smaller but still present from P+I terms.)

  4. **Sensor health propagation:** new `sensor_health` field `heater_active: bool` and `heater_recovery_until: timestamp` so consumers (controller, alerter, bridge, derivation pipelines from 999.27) all know to ignore that window. Single source of truth, set/cleared by `fc_sensors`.

  5. **Multi-sensor failover behavior during cycle:** Phase 26's slot-1 fallback chain currently goes SHT30 → SCD41. If SCD41 is alive, should we fail over to it during the SHT30 heater window? Caveat: SCD41 RH clips at 100% (`project_phase26_sht30_happy_path_unverified`), so during high-humidity (which is exactly when we want to run the heater), the SCD41 fallback is *worse* than holding last-duty. Recommended default: do NOT fail over to SCD41 during heater window; just freeze readings. Compose with: any future multi-SHT30 setup (a redundant SHT30 head would let us heater-cycle one while reading the other — explicit multi-sensor design).

  6. **Telemetry visibility:** publish a `fc.sensor_heater_active` boolean topic so Mission Control can show vertical-line annotations on charts; Timescale rows during the window get marked (either skip insert, or insert with quality flag). Default: skip insert during heater + recovery → users see a small data gap rather than a corrupt spike. Composes with 999.27 derived telemetry — derivations must respect the gap.

  **Composes with:**

  - **Phase 26** (sensor freshness / dual-sensor) — heater_active is a freshness state, fits the same pattern
  - **999.22** (alerter must read ops state from controller, not env) — heater suppression must be controller-driven, can't be env-pinned
  - **999.27** (derived telemetry) — VPD/dew_point/humidity_rate must skip heater windows
  - **999.32** (derivative filter) — must reset / pause derivative computation across heater windows so the post-recovery jump doesn't get treated as a real RH transient
  - **Phase 28** (mode primitive) — heater cadence could be per-mode (more aggressive in `fruiting`, dormant in `incubation`)

  **Out of scope:** any change to SCD41 behavior (it has its own self-calibration; not part of this phase). Any cross-sensor reasoning ("infer SHT30 drift by comparing to SCD41") — that's its own backlog if it's worth it.

  **Acceptance:** (1) nightly heater pulse at 03:00 UYT visible in Timescale as a marked gap; (2) RH chart in Mission Control shows annotation, not corrupt spike; (3) controller duty stays at pre-cycle value through window; (4) alerter does not fire during the heater window; (5) post-window RH reading is within 0.1 % of pre-window value (i.e., heater isn't introducing observable drift in a non-condensed sensor); (6) over a 30-day soak, observe whether the *delta* between SHT30 and SCD41 RH narrows (evidence the heater is clearing real condensation drift) — this is the long-run proof.

  **Filed 2026-05-04 evening** — adjacent to the calibration work but architecturally orthogonal to the PID retune. Could ship independently of the Saturday filter+Kd retune work.

- **Phase 999.35: Daily maintenance agent — log triage + alerter self-pathology detection + TLDR digest** — Surfaced 2026-05-06 by farmer/lead-dev's "I waited to see how long until you noticed" test, which we failed: the alerter spammed identical hourly CRITICALs for 10+ hours and *we* (the system, not the human) did not catch it. Pattern borrowed from other Santi projects: a once-daily agent that reads logs across the stack (alerter, bridge, fc-core journal, timescale, signal-cli) and emits a TLDR digest (email or Signal) summarizing health, anomalies, and "things you'd want to know but might miss." Two distinct value props bundled here because they share the same agent surface:

  **(a) Alerter self-pathology detection** (this incident's direct ask). Identical-message clockwork alarms — same body text, same severity, fired at exact `cooldownMin` spacing for ≥3 cycles with no underlying-state change in the data — are a self-evident bug. The agent should detect this pattern and either auto-snooze the type, or emit a meta-alert ("alerter is misbehaving on alertType=sht30: 10 consecutive CRITICALs at 60-min spacing, zero state change in /fc1/sensor_health values"). This is the cheapest, highest-value check; do it first.

  **(b) Daily maintenance digest.** Broader pattern: scan last 24h of `journalctl -u fc-core`, `docker logs mushy-{alerter,bridge}`, signal-cli logs, timescale ingest stats, and produce a one-page TLDR. Sections to include (recommended defaults; refine in discuss-phase): unexpected restarts, error/warn-rate deltas vs prior 7-day baseline, alert volume per type with trend, sensor freshness anomalies, telemetry gaps (Timescale row-count per topic per hour vs baseline), DERP relay / Tailscale CPU spikes, disk usage on /data and /var, container restart counts, signal-cli send failures. Delivery: email (already have SMTP? check) or Signal as a single low-priority digest message ("[DAILY] FC-1 health 2026-05-06 — 3 nuggets, 0 concerns. Open: ..."). Cadence: 03:00 UYT (chamber quiet, fits the 999.34 nightly slot).

  **Implementation surface options** (each with tradeoffs — resolve in discuss-phase):

  1. **Standalone container** `mushy-maintenance-1` (Node or Python), reads container logs via Docker socket + ssh fc1 for journalctl + Timescale via SQL. Sends one digest. Cleanest separation; new container.
  2. **New responsibility on existing alerter** — alerter already has Signal egress + bridge subscription + Timescale; add a daily cron + log-tail handlers. Less new infra; conflates "real-time alerts" with "daily report" (probably bad — different failure modes).
  3. **Anthropic-API-backed agent** — feed last 24h of logs into Claude with a "produce a maintenance TLDR" prompt; LLM does pattern detection. Already have `ANTHROPIC_API_KEY` in `.env`. Riskier (cost + reliability + nondeterminism) but matches the "agent" framing from other projects and would catch novel pathologies the rule-based version misses. Could ship rule-based first (a) + LLM digest later (b).

  **Recommended shape:** standalone container; rule-based detector for (a) ships first (one-week win); LLM-summarizer for (b) ships second once we have the log-pipeline. Compose: rules surface concrete pathology, LLM writes the prose summary.

  **Composes with:** this whole backlog cluster — 999.22 (alerter ops thresholds in env, hard to tune, agent should flag staleness), 999.27 (derived telemetry — agent consumes the same series), 999.28 (systemd hardening — agent should flag start-limit-hit / unexpected restart loops), today's `project_alerter_watchdog_quiet_topic_bug` (the agent would have caught this in <24h instead of waiting on a human).

  **Out of scope:** real-time alerting (alerter owns that); UI dashboards (Mission Control owns that); auto-remediation (read-only digest first; auto-actions are a separate decision tree).

  **Acceptance:** (1) detector fires when the alerter sends ≥3 identical CRITICALs at exact cooldownMin spacing with no underlying state change → emits meta-alert + auto-snoozes the type; (2) daily digest delivered at 03:00 UYT covering the 8 baseline sections above; (3) digest delivery survives a 24h fc1 outage (i.e., it runs from elder-plops, not the Pi); (4) farmer can read the digest in <60s and know whether to investigate; (5) **negative test:** stage a synthetic identical-clockwork alarm pattern in a soak environment and confirm the agent catches it in <2 cycles.

  **Filed 2026-05-06 evening** — incident-driven; user noted "on other projects we have an automatic 'maintenance agent' that goes around once a day or so, reads logs and sends an email with a TLDR etc" — pattern is proven, not greenfield design.

- **Phase 999.36: BUG — bridge buffer-replay cursor advances on live WS inserts; ship the deferred BUF-04 induced-dropout test alongside the fix** — **CLOSED 2026-05-11** (commit `7660604`). Removed the live-insert `advanceLastIngested` call; cursor now advances only inside buffer_replay.js's poll-batch path. Steady-state cost: a few duplicate rows per 30s window, deduped server-side by `(topic, time)` UNIQUE + `ON CONFLICT DO NOTHING`. BUF-04 induced-dropout integration test still deferred (needs running infra to repro); next real reconnect will validate. Bridge jest 234/236 (2 pre-existing failures unrelated). Original entry preserved: Surfaced 2026-05-07 morning, after the overnight cold-reboot incident left fc1 unreachable for ~11h while continuing to control the chamber locally and buffer all telemetry. When fc1 came back, *zero* of the 199,621 buffered rows backfilled — bridge stayed at "live messages only," gap stayed empty in Timescale until manually pulled via curl + psql staging table. Root cause is `src/mission-control/bridge/src/index.js:609-613`: every successful live WS insert calls `buffer_replay.advanceLastIngested(...)` with `tsNs` from the live message header. So the first live message after reconnect (timestamped *now*) jumps the cursor over the entire gap; the next 30s `/telemetry/since?ts=N` poll asks fc_buffer for "newer than now," gets the latest 3 rows, declares itself caught up. The optimization defeats buffer-replay during the exact scenario it was designed for. **Fix shape:** remove the live-insert cursor-advance call. Cursor advances only on successful buffer-replay polls (which already track `maxTs` per batch). Steady-state cost: a few rows per 30s window the bridge has already seen, deduped by the existing `(topic, time)` UNIQUE constraint via `ON CONFLICT DO NOTHING`. Negligible; trade for correctness on every reconnect forever. **Why it shipped without being caught:** Phase 27.1 plan-04 deferred BUF-04 (induced-dropout test) to "natural-event observation per plan-04 D-12." That test *is* the test of buffer-replay's primary code path. Without it the feature was unit-tested but never validated end-to-end against a real reconnect. **Phase scope:** (a) remove the live-insert cursor-advance call at index.js:613; (b) add an integration test that stops the bridge's WS subscription, lets fc_buffer accumulate rows, resumes the WS, and asserts Timescale ends up with the full gap (this is the deferred BUF-04 induced-dropout test, written properly this time — composable into the bridge's existing `test/` suite); (c) document the manual recovery recipe (already captured in memory `project_bridge_buffer_replay_cursor_bug` as a stopgap until the fix lands). **Acceptance:** stop bridge → wait 30 min → fc_buffer accumulates ~5400 rows of fc.humidity / fc.temperature / etc → restart bridge → within 2 minutes Timescale has every row in the gap window with no manual intervention; the integration test in (b) passes in CI. **Touches:** `src/mission-control/bridge/src/index.js`, `src/mission-control/bridge/src/buffer_replay.js`, `src/mission-control/bridge/test/`. **Composes with:** 999.27 (derived telemetry — replay-aware derivation depends on the raw replay actually working), 999.37 (deferred-validation audit — this is one of its findings), Phase 27.1 (the original buffer-replay phase that incompletely shipped).

- **Phase 999.37: Audit "deferred to natural event / convenient occasion" validations across the roadmap** — Surfaced 2026-05-07 post-mortem after 999.36 root-caused to a deferred BUF-04 test. Pattern: a phase scopes a key validation (the test that would catch the failure mode the phase is hardening against), then defers it to "natural-event observation" or "next time we're at the farm" or "cheap to do once X is in place." The deferral is rational *that day* — running the test risks the same outage we're hardening against, or it requires conditions we don't currently have — but the followup never gets re-scheduled, and the feature ships untested against its primary code path. Confirmed instances so far: BUF-04 induced-dropout (Phase 27.1 plan-04 D-12, deferred 2026-05-03; latent bug surfaced 2026-05-07 — see 999.36); SYS-04 validation reboot (Phase 27.2, deferred until "fc1 on fresh microSD," then surfaced 2026-05-07 cold-reboot test that exposed wifi config drift instead). **Scope:** (a) one-pass audit of every shipped phase's plans, looking for `deferred`, `natural event`, `out of scope for this phase`, `cheap to do later`, `defer to follow-up`, similar phrases; (b) categorize each: (i) genuinely safe to defer indefinitely (one-off concerns, low blast radius), (ii) needs to be re-scheduled with a concrete trigger (date or condition), (iii) was the test of a primary code path and should be pulled forward as a fix-now item (file as 999.x); (c) update each affected phase's SUMMARY/ROADMAP entry with the explicit re-schedule status. **Why this matters:** a deferred validation is not a tested feature. The phase's "shipped" status is overclaiming. This pattern compounds across phases — each one feels small, but cumulatively the roadmap has untested code paths shipping under the cover of "we'll get to it." **Acceptance:** a `.planning/notes/2026-05-XX-deferred-validation-audit.md` listing every deferred validation found, its current status, and the concrete next action for each. Each (iii)-classified item gets a 999.x backlog entry filed at audit time. No code changes from this phase itself; outputs are the audit doc + new backlog items. **Composes with:** 999.36 (the trigger), `feedback_run_verifications_yourself` memory (related — same anti-pattern in a single-task scope: skipping a verification that's awkward but cheap). **Filed 2026-05-07.**

- **Phase 999.39: BUG — alerter "humidifier stuck ON" fires during fc1 offline windows; pi-offline alert lacks last-known state** — **CLOSED 2026-05-08 by Phase 29** (D-04 bundled into plan 29-05; `isHumidifierStuck` gates on `wsConnected` + `humidifierLastMsgTs`; `formatProblem(pi)` carries Last sample summary; smoke-tested on fc1). Original entry preserved: Surfaced 2026-05-07 by farmer report after the overnight 11h fc1 outage (see `project_2026_05_07_fc1_reboot_unrecoverable`). During the offline window, the alerter sent CRITICAL "humidifier stuck ON" alarms even though fc1 was unreachable and the alerter had no fresh humidifier or RH data — the readings were the last cached values from before the WS dropped. **Root cause:** `src/agents/alerter/src/rules.js:47` `isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config })` has zero liveness inputs. As long as the cached `humidifierOnSinceMs` is non-null and wallclock keeps advancing, the rule fires; cached `currentRh` stays frozen so `rhRise < 3.0` is trivially true. The rule cannot distinguish "humidifier truly stuck" from "we have no idea what's going on." Memory `project_alerter_is_ws_only` already flagged this class — alerter never queries Timescale and treats stale cache as truth. **Compounding gap:** when the pi-offline alert *does* fire (`message.js:60-64` `formatProblem` for `alertType === 'pi'`), it only prints `Last seen: <relative>`. The farmer wants situational context: last known humidifier ON/OFF, last RH%, last temp, with a wallclock timestamp. **Better message shape:** `[PROBLEM · CRITICAL] FC-1 · Pi offline\nLast seen: 8h 14m ago (22:14)\nLast known: humidifier ON, RH 87.2%, T 21.4°C\nOpen: <dashboard>`. **Phase scope:** (a) gate `isHumidifierStuck` (and any other actuator/process-derived rule that uses cached state) on liveness — pass `wsConnected` and `humidifierLastMsgTs` into the rule; suppress when WS disconnected OR humidifier topic stale beyond `sensorOfflineMin`/dedicated `humidifierStaleMin`; (b) extend the `pi` alert formatter (`formatProblem` and the corresponding fields-builder in `index.js`) to carry last-known summary fields (rh, temp, humidifier state, wallclock timestamp of last sample) and render them in the message; (c) audit other rules in `rules.js` (`isRhOob`, `isHumidifierStuck`) for the same offline-blind class — `isPiOffline` and `isSensorSilent` are already liveness-aware by construction, but RH-OOB during pi-offline is the same anti-pattern (cached RH frozen at last-known-OOB value would re-fire OOB alerts as wallclock advances; check whether dedup catches this or it bleeds through). **Acceptance:** (1) reproduce the bug — disconnect bridge WS, leave alerter running with cached humidifierOnSinceMs in the past, advance time past `humidifierStuckMin`, confirm a current build emits the false-stuck alert; (2) ship the gate + add a unit test in `rules.test.js` asserting `isHumidifierStuck` returns false when `wsConnected: false` or `humidifierLastMsgTs` older than threshold, regardless of cached times; (3) ship the pi-alert message extension + a `message.test.js` snapshot that includes last-known fields; (4) re-run reproduction → confirm no false stuck-on, and the pi-offline alert now carries last-known humidifier/RH/T. **Touches:** `src/agents/alerter/src/rules.js`, `src/agents/alerter/src/index.js` (or wherever rule inputs are assembled — likely the same place `humidifierLastMsgTs` already flows from `bridge-client.js`), `src/agents/alerter/src/message.js`, `src/agents/alerter/test/rules.test.js`, `src/agents/alerter/test/message.test.js`. **Composes with:** 999.22 (alerter ops thresholds in env, hard to tune — same module of code, fix together if scope allows), 999.27 (derived telemetry — once a "freshness/liveness" channel exists in derived telemetry, alerter can consume that single source of truth), 999.35 (daily maintenance digest — meta-watchdog would have caught this hourly-false-CRITICAL pathology in <24h), `project_alerter_watchdog_quiet_topic_bug` (sibling pattern — alerter watchdog firing on stale cached freshness; same family of "alerter trusts its cache too much"). **Filed 2026-05-07.**

- **Phase 999.38: Wifi-config preflight + repo netplan drift reconciliation (un-moot 27.4)** — Surfaced 2026-05-07 morning. Phase 27.4 ("Repo netplan drift reconciliation") was MOOTED 2026-05-03 because "fc1 is currently on home-LAN wifi via kernel-WG, not at the farm on 4G; the dropped-mossrock-west / no-99-static.yaml drift was a farm-4G-setup story." Three days later that mooting cost an 11-hour fc1 outage: when fc1 was at the lab on `mossrock-west` and we triggered a remote reboot for the 27.2 SYS-04 validation, the netplan in repo (`scripts/pi-deploy/etc/netplan/60-wifi.yaml`) only declared `mossrock-lab` and `mossrock-starlink`. wlan0 came up at the radio level but never associated to any AP, fc1 had no upstream, no SSH, no Tailscale fallback (disabled by 27.1 transport switch). Chamber kept controlling locally; we just couldn't see it. Fix shipped 2026-05-07 (commit `789a699` — added `mossrock-west` to repo, pushed to fc1/prod) but that's a one-SSID hotfix, not the structural answer. **Phase scope (two parts that should ship together):** (a) **Wifi-config preflight** — codify a 30-second check that runs *before* any remote reboot: diff the SSIDs declared in `scripts/pi-deploy/etc/netplan/60-wifi.yaml` against the SSID currently associated on fc1 (`iw dev wlan0 link | grep SSID:`). If "currently associated" ≠ "any declared," **stop and re-validate** before rebooting — the box is alive only because of post-deploy hand-fixes that won't survive the reboot. Add this as a documented pre-flight in the deploy.sh script and reference it in any future "reboot fc1" plan recipe. (b) **Catch-up netplan drift reconciliation** (the original 27.4 scope, no longer mooted): audit live `/etc/netplan/*.yaml` + `/etc/NetworkManager/system-connections/*` + `/etc/wpa_supplicant/wpa_supplicant.conf` against repo. Reconcile any drift. Document expected SSIDs per location (chamber: `mossrock-lab`; main infra: `mossrock-starlink`; lab: `mossrock-west`). Decide whether to also add static-IP / 99-static.yaml stanzas the original 27.4 contemplated, or leave fc1 on DHCP. **Acceptance:** (1) preflight script exists and is referenced in deploy.sh + any 27.x plan involving reboot; (2) live `/etc/netplan/60-wifi.yaml` matches `scripts/pi-deploy/etc/netplan/60-wifi.yaml` byte-for-byte; (3) test plan: power-cycle fc1 at each known location and verify it associates within 60s on the expected SSID without manual intervention (this is the netplan equivalent of SYS-04). **Touches:** `scripts/pi-deploy/etc/netplan/60-wifi.yaml`, `scripts/pi-deploy/deploy.sh`, possibly a new `scripts/pi-deploy/preflight-wifi.sh`. **Composes with:** 999.28 (fc-core systemd hardening — same family of "make fc1 robust against boot races"; netplan readiness is upstream of wg0 readiness), `feedback_diff_repo_vs_pi_systemd` (memory — generalize to netplan/wpa_supplicant/NetworkManager, not just systemd units). **Promotes:** Phase 27.4 (un-moot the underlying need; this is the new home for that scope).

- **Phase 999.40: Bridge QoS profile drift — extract `humidifierQos` / `sensorHealthQos` to module-scope shared constant** — **CLOSED 2026-05-11** (commit `092f43f`). Consolidated to a single `transientLocalQos` const at the previous `humidifierQos` location; all 9 callsites (humidifier, humidifier_duty, humidity_target, pid_output, sensor_health, current_mode_json, alerter_mode_overrides, alerter_globals, experiment_event) now reference it. Bridge jest counts unchanged (234 passed before+after; 2 pre-existing failures in control_experiment.test.js are unrelated). Original entry preserved: Surfaced during Phase 29 review (2026-05-08). Bridge `src/mission-control/bridge/src/index.js` carries two near-identical TRANSIENT_LOCAL/RELIABLE/depth=1 QoS objects (`humidifierQos` and `sensorHealthQos`) inline; Phase 29 introduces 3 more subscribers using the same profile (current_mode, alerter_mode_overrides, alerter_globals) and re-uses `humidifierQos` rather than spawn a 6th duplicate, but the underlying duplication remains pre-existing drift. **Scope:** lift the profile to a single named module-scope constant (e.g. `transientLocalQos`); replace all five+ usages; assert profile equality via a small test. **Why deferred from Phase 29:** out-of-scope per phase boundary (29 ships behavior, not refactor). **Acceptance:** one named constant; zero inline duplicates; bridge jest still green. **Touches:** `src/mission-control/bridge/src/index.js`. **Filed 2026-05-08 during Phase 29 review.**

- **Phase 999.41: BUG — PID bumpless re-engage hardcodes `last_output=0.15` regardless of in-band restart state** — **CLOSED 2026-05-11.** Already fixed by Phase 29 DEFER-29-01 (shipped 2026-05-08, verified live on fc1 same day — see `.planning/phases/29-.../29-07-SUMMARY.md:65` and `29-VERIFICATION.md:72`). `_engage_pid_bumplessly` no longer carries a `0.15` default — all 5 callers explicitly pass `self._last_published_duty` (init 0.0 at `fc_controller.py:379`). This 999.41 entry was filed 2026-05-09 from stale memory after the fix had already landed under the Phase 29 deferred bucket. Original entry preserved for context: Surfaced 2026-05-08 during Phase 28 D-10 investigation (memory `project_phase28_d10_target_semantics`). When `fc_controller` re-engages PID after a band exit/re-entry, the bumpless-transfer block at `fc_controller.py:973` initializes `last_output = 0.15` as a hardcoded constant. If RH is in-band at restart, this value defines the controller's effective steady-state duty floor — duty stays pinned at 0.15 until band exit forces a recompute. Effect: on boot or after any restart that finds RH already in-band, the humidifier runs at 15% duty whether it needs to or not, ignoring true PID demand. **Fix shape:** read current PID demand at re-engage time (or seed from `last_known_demand` persisted via 999.36-style replay) instead of constant 0.15; if no prior demand exists, choose a duty consistent with the I-term and current error, not a magic number. **Acceptance:** restart fc-core with RH inside the operating band; observe duty settles to PID-computed value within 1 control window, not 0.15. Add a unit test in `test_fc_controller.py` that constructs a controller, triggers re-engage path with `current_humidity ≈ target`, and asserts last_output is not the hardcoded 0.15 sentinel. **Touches:** `src/chambers/fc-core/fc_core/fc_controller.py:973` and adjacent re-engage logic + test. **Composes with:** 999.32 (derivative filter — both are "PID corner-case correctness" issues), 999.27 (derived telemetry — `humidity_error` history is what bumpless re-engage should be reading from). **Filed 2026-05-09 during v1.4-and-below cleanup sweep.**

- **Phase 999.42: BUG — alerter watchdog uses `sht30_fresh` as controller liveness ping → hourly false alarms** — **CLOSED 2026-05-11** (commit `20d8339`). Added per-sensor enable flags `sht30Enabled` / `scd41Enabled` (env: `ALERT_SHT30_ENABLED` / `ALERT_SCD41_ENABLED`, both default true). State machine skips eval entirely when a sensor is disabled. Operator deploy action: set `ALERT_SHT30_ENABLED=false` in elder-plops .env (mute SHT30) and revert `ALERT_SENSOR_OFFLINE_MIN` from 1440 back to 5 (restore real SCD41 watchdog). 3 new tests in state.test.js (sht30/scd41 enable=false suppresses, sensor_freshness path respects flag). Alerter jest 212/216 (4 pre-existing failures unrelated). Meta-watchdog half (`feedback_alerter_needs_meta_watchdog`) remains as scope inside 999.35 daily-maintenance digest. Original entry preserved: Surfaced 2026-05-06 (band-aided same day with `ALERT_SENSOR_OFFLINE_MIN=1440` in `.env`). Memory `project_alerter_watchdog_quiet_topic_bug` + `feedback_alerter_needs_meta_watchdog`. The alerter's controller-liveness watchdog conflates "controller is alive" with "SHT30 sensor topic is fresh"; when SHT30 is physically disconnected (the production state since 2026-04-11 — memory: SCD41 is sole humidity source), the topic is permanently silent and the watchdog fires on its own clock. Result: identical hourly CRITICAL alarms for hours-to-days while the controller is actually healthy. **Two-part fix:** (a) **structural:** add a true heartbeat from `fc_controller` (e.g. `/fc1/controller_heartbeat` topic at 1Hz), have the alerter watchdog consume that instead of `sht30_fresh`; OR drop the alerter-side controller watchdog entirely and rely on `fc.sensor_health` which is already controller-driven. (b) **meta-watchdog (memory `feedback_alerter_needs_meta_watchdog`):** detect "alerter is sending identical CRITICAL alarms on a fixed cadence" as a self-pathology — this is what 999.35 daily-maintenance digest is the right home for, but a faster-loop check belongs alongside the structural fix. **Why this matters:** the band-aid (`ALERT_SENSOR_OFFLINE_MIN=1440`) silences the symptom for 24h but masks any *real* sensor outage for the same window — the env knob is in tension with correctness. **Acceptance:** revert `ALERT_SENSOR_OFFLINE_MIN` to a sane default (≤30 min); confirm zero false alarms over 7 days with SHT30 still physically disconnected; introduce a SHT30 reseat test → confirm alarm fires when controller heartbeat actually drops. **Touches:** `src/agents/alerter/src/rules.js`, `src/agents/alerter/src/state.js` (or wherever the watchdog computes), possibly `src/chambers/fc-core/fc_core/fc_controller.py` (heartbeat publisher), `src/mission-control/bridge/src/index.js` (heartbeat subscription). **Composes with:** 999.27 (derived telemetry — heartbeat is naturally a derived/liveness channel), 999.35 (daily maintenance digest — meta-watchdog half), 999.39 (sibling — same "alerter trusts cache too much" family; fix together if scope allows). **Filed 2026-05-09 during v1.4-and-below cleanup sweep.**

- **Phase 999.43: VPS heartbeat receiver + outage-alert relay** — **CLOSED 2026-05-11 by Phase 33 (Tier 1 only).** Tier 2 out-of-band push moved to 999.43.1 below. Original entry preserved for context: Filed 2026-05-10 as deferred from Phase 32 (DECISION-6 workload #3, the highest-value piece beyond WG hub itself). **Why this matters:** memory `project_2026_05_07_fc1_reboot_unrecoverable` documents an 11-hour fc1 outage that nobody noticed because the in-house alerter was dead with the home network. The VPS — independent of farm wifi, 4G hotspot, home pfSense, or elder-plops — is the only thing that can scream when *everything else* dies. **Scope:** (1) tiny long-running service on VPS (Node.js or Python single-file, systemd unit) that listens for hourly POST `/heartbeat` from fc1 + elder-plops + bridge + alerter; (2) tracks last-seen-per-source in a sqlite or flat file; (3) when a source's last-seen exceeds threshold (e.g. 2× expected interval = 2 hrs for hourly, 5 min for control loop), fires Signal/email/SMS to the operator + farmers; (4) self-pathology check: if VPS itself can't deliver, fall through to a secondary channel (e.g. send to all farmers, not just primary). **Endpoint shape:** simple HTTPS POST `{"source": "fc1", "ts": "...", "extras": {"fc-core": "active", "rh": 0.96}}` on the public IP (or a subdomain when DNS lands). **Sender side:** systemd timer or cron on each source that POSTs every interval. **Composes with:** Phase 32 (uses the same VPS), 999.42 (heartbeat is the structural fix for the alerter-watchdog SHT30-fresh bug too — fc1's heartbeat publisher feeds both), 999.27 (derived telemetry — heartbeat is a natural derived/liveness channel). **Acceptance:** simulate fc1 going offline → operator gets a Signal alert from the VPS within 2× heartbeat interval. **Touches:** new `vps/heartbeat-receiver/` service + sender shims on fc1 + elder-plops + alerter container.

- **Phase 999.43.1: ntfy.sh out-of-band Tier 2 alert channel** — **CLOSED 2026-05-11 by Phase 33 promotion** (see `.planning/phases/33-vps-heartbeat-receiver/999-43-1-SUMMARY.md`). Original entry preserved: **THIS IS THE ACTUAL MITIGATION** of the 11h-blind incident class (memory `project_2026_05_07_fc1_reboot_unrecoverable`). Phase 33 shipped Tier 1 (VPS → wg-hub → bridge → signal-cli → operator phone) — but Tier 1 only works *when the home network is reachable*, which is exactly the case Tier 2 covers. When fc1 + elder-plops are both dead with the home wifi/4G, Tier 1 is unreachable and the Phase 33 receiver currently logs `OUT_OF_BAND_ALERT_MISSED` to `/var/lib/mushy-heartbeat/alerts.log` on the VPS — silent unless someone reads the log. **Scope:** install ntfy.sh client on the operator phone, generate a unique topic, configure VPS receiver to push there as Tier 2. ntfy is free, no account, no SMS cost, ~5min on each end. **Failure mode for Tier 2 (covered, third tier maybe):** ntfy.sh is centralized — if their service is down at the same moment, Tier 2 fails. Mitigation: secondary push via Twilio SMS or Apprise multi-channel; defer until needed. **Touches:** `vps/heartbeat-receiver/index.js` `dispatchAlertTier2()` (currently a placeholder), VPS env / secret for ntfy topic, ntfy app on operator phone. **Acceptance:** unplug elder-plops from home wifi (or stop bridge container) → operator phone receives ntfy push within 4 minutes (3min staleness + 30s detector tick + Tier 1 timeout fallback). **Composes with:** 999.43 (parent), 999.44 (uptime-kuma — different signal but same operator-notification fan-out). **Filed 2026-05-11 during Phase 33 deploy.**

- **Phase 999.44: VPS outside-in monitoring (uptime-kuma)** — **CLOSED 2026-05-11 by Phase 34 (infra deployed; operator UI setup pending — uptime-kuma owns its own credentials by design).** Original entry preserved: Filed 2026-05-10 as deferred from Phase 32 (DECISION-6 workload #2). uptime-kuma is a self-hosted Pingdom-alike that runs as a single Docker container, polls HTTP/TCP/ping endpoints, and surfaces a status page + alerts. **Killer combo with 999.43:** heartbeat catches "source went silent;" uptime-kuma catches "source is reachable from inside but invisible from outside" (the failure mode that hit 2026-05-07 — elder-plops was up on LAN but the world couldn't see it). **Scope:** docker-compose service on VPS; check fc1 via wg-hub (`ping 10.66.0.11`), elder-plops via wg-hub + via public WAN IP (detect outside-in failure separately from box-down), MC openmct port `:8080` (HTTP 200 expected), bridge `:8081/health` (JSON shape), signal-cli health, farmOS daily report endpoint when 999.2 ships. Public status page optional — useful for farmer-tester onboarding ("the chamber is up" without needing WG). **Composes with:** 999.43 (different signal: external reachability vs source-self-reported liveness), Phase 32 (rides the WG hub for inside-the-network checks). **Acceptance:** dashboard up at `http://10.66.0.1:3001/` (over wg-hub) showing all monitored endpoints; alert fires on simulated outage within 2 polling intervals. **Touches:** new `vps/uptime-kuma/` compose service + public DNS later if status-page-public is desired.

- **Phase 999.45: VPS offsite backups (borgbackup or restic)** — **RESEARCH COMPLETE 2026-05-11** — see `.planning/phases/999-45-backup-tooling/RESEARCH.md`. **Recommendation: borg 1.4** (apt on both ends; zstd compression doubles retention inside the 20GB VPS budget; restic's jammy apt is stale 0.12.1 from 2021; restic's multi-host dedup advantage is moot since elder-plops is the sole sender). Implementation deferred to a future ship-phase. Original entry preserved: Filed 2026-05-10 as deferred from Phase 32 (DECISION-6 workload #4). Mitigates `project_2026_05_03_ssd_failure` (SD card died; recovery required full rebuild from scratch). Mushy Timescale ~1.2 GB; daily diff ~200-500 MB compressed; ~30-90 days retention fits in the VPS's 20 GB budget comfortably. farmOS db too. **Scope:** (1) borgbackup or restic on VPS as receiving target; (2) nightly cron on elder-plops that pushes `pg_dump` of Timescale + farmOS dbs + key file paths (camera snapshots metadata, runtime_overrides.yaml on fc1) over SSH; (3) retention policy (keep daily x N, weekly x M, monthly x K); (4) **restore drill** — quarterly test that we can actually restore a known db dump and bring up a parallel mushy stack from it, not just "we have backups." **borg vs restic** is a cheap-to-defer decision; both are append-only encrypted incremental backup systems with active maintenance. borg is older/more battle-tested; restic is newer/more flexible (multi-backend including S3/B2 if we ever want geographic diversification). **Acceptance:** automated nightly backup runs for 7 days; restore drill produces a working Timescale instance with last-7-days data on a fresh box (or a sandbox container). **Composes with:** Phase 32 (rides the VPS), `project_2026_05_03_ssd_failure` (the incident this addresses).

- **Phase 999.46: fc1 CycloneDDS multi-interface binding — prep for farm-4G return** — **RESEARCH COMPLETE 2026-05-11** — see `.planning/phases/999-46-cyclonedds-multi-iface/RESEARCH.md`. **Proposed config:** add `<NetworkInterface name="wg-hub" priority="0" presence_required="false"/>` alongside `wg0` (priority="10") on both fc1 + elder-plops, plus 2 new wg-hub `<Peer>` entries. Cost-based path selection prefers wg0 (5ms LAN) over wg-hub (250ms VPS) when both healthy. **Highest-risk failure mode (F3, must-not-skip):** boot race — CycloneDDS defaults `presence_required="true"` would refuse-to-start fc-core if wg-hub is missing at boot. The `presence_required="false"` line is the load-bearing diff. Implementation deferred to a future ship-phase (test plan documented; needs lab-side validation per `feedback_fc1_remote_action_preflight_protocol`). Original entry preserved: Filed 2026-05-10 as a Phase 32 follow-up. **Why this is a real blocker, not a nice-to-have:** Phase 32 added wg-hub on fc1 alongside the existing wg0 LAN tunnel. Currently `/etc/cyclonedds.xml` on fc1 binds DDS to `wg0` only — fine while fc1 is on home LAN. When fc1 physically moves back to the farm on 4G, wg0 loses its peer (elder-plops is no longer on the same LAN) and DDS goes silent — `fc-core` would still run, but bridge and alerter lose all telemetry. `project_fc1_link_architecture_options` and `project_fc1_cgnat_confirmed` document why this matters: VPS hub is the *only* viable path back to 4G. **Scope:** (a) update `/etc/cyclonedds.xml` to allow DDS on both `wg0` AND `wg-hub` (CycloneDDS supports interface allowlists); (b) verify both paths work simultaneously while fc1 is still on home LAN (no production impact); (c) document the fallback ordering — elder-plops is reachable from fc1 over BOTH wg0 (5ms LAN) and wg-hub (240ms via Nuremberg), DDS should prefer wg0 when available; (d) test plan: `ip link set wg0 down` on fc1, observe DDS continues over wg-hub, observe RTT increase but functional control loop, restore wg0; (e) when fc1 physically moves to farm 4G, simply turn off wg0 and DDS automatically rides wg-hub. **Acceptance:** with both interfaces up, telemetry flows; with wg0 down, telemetry continues over wg-hub with degraded latency (240ms) but no data loss; control loop stable. **Touches:** `/etc/cyclonedds.xml` on fc1 (and `~/.config/cyclonedds.xml` on elder-plops/bridge for symmetry). **Composes with:** Phase 32 (the hub it depends on), `feedback_stopping_tailscaled_kills_pid` (lesson: don't break DDS by changing transport without testing), 999.43 (heartbeat — both fail modes get reported correctly).

- **Phase 999.47: gumbald wg-hub peer (operator laptop)** — Filed 2026-05-10 as deferred from Phase 32. Pure operator convenience: when home LAN dies (or operator is on the road), gumbald can ssh into fc1 and elder-plops via the VPS hub instead of needing them to be on the same physical network. **Scope:** generate gumbald keypair locally, send pubkey to VPS, add as peer at `10.66.0.10/32`, configure systemd-networkd or NetworkManager to bring up wg-hub at boot, document the per-host SSH config that uses `IdentitiesOnly yes` (memory `feedback_ssh_agent_overflow_use_identitiesonly`) and falls through to the VPS-routed IPs when LAN paths fail. **Acceptance:** with home LAN unplugged, `ssh ubuntu@10.66.0.11` (fc1 over hub) and `ssh santi@10.66.0.12` (elder-plops over hub) both work. Bonus: a `~/.ssh/config` that tries LAN first, falls through to hub. **Composes with:** Phase 32 (the hub), 32-RUNBOOK (uses the documented add-peer recipe). **Effort:** ~5 min once hub is live.

- **Phase 999.48: 4th shared iOS device wg-hub peer** — Filed 2026-05-10 as deferred from Phase 32. The 4th farm device (shared iOS, used by multiple operators on-site) has reserved IP `10.66.0.23` but was not configured during the all-nighter (operator wanted to set up named individual devices first). **Scope:** generate keypair on VPS (the device itself doesn't need to generate keys for this use case), build .conf + PNG QR via the standard 32-RUNBOOK recipe, deliver to the device when in hand, scan + activate. **Acceptance:** device on `10.66.0.23` reaches MC via hub. **Touches:** ~3 min at the keyboard. **Compose:** Phase 32 (RUNBOOK).

- **Phase 999.49: BUG — PID integrator never decays in-band; controller over-humidifies at residual I-term** — **CLOSED 2026-05-11** (commit `805f904`). Applied option (a) integrator decay. New param `pid_integrator_decay_tau` (default 1200s = 20min); when in-band branch fires (`error_pct==0`), `_pid._integral *= exp(-dt/tau)` runs before the PID call. tau=0 disables. 2 new tests in test_pid_kernel.py covering decay-when-in-band and no-decay-when-OOB; all 10 PID kernel tests PASS locally. Needs fc1 colcon verification before fc-update auto-deploys. Original entry preserved: Surfaced 2026-05-11 by farmer observing `humidifier_duty` stuck at `0.2782707214355469` (byte-identical samples) for hours. **Root cause:** Phase 28 D-09 band-aware error projection feeds `error_pct = 0.0` to the PID when RH is in-band (`fc_controller.py:1685`). With error=0 every tick: `P=Kp*0=0`, `I` grows by `Ki*0*dt=0` (frozen at its current value), `D=Kd*d_input/dt → 0` (constant input → d_input=0). Output collapses to `I_term` indefinitely. After a below-band recovery, the I-term sits at whatever value pumped RH back into band — and stays there forever as long as RH remains in-band. **Live evidence 2026-05-11:** fc1 had been holding RH ≈ 97.14% (well above midband 0.96) with duty=28% for 1d3h. Restart with `_last_published_duty=0.0` proved the chamber's passive RH equilibrium is ~95.6% (band_low+0.011) at duty=0%. The 28% steady-state was the controller over-humidifying to defend an artificially high RH, NOT chamber demand. **Energy/cost impact:** modest — 28% duty is ~33s on per 120s window, vs. 0% needed. Multiply over weeks. **Fix shapes (pick during plan-phase, not now):** (a) **integrator decay when in-band** — apply a slow exponential decay to `_pid._integral` each tick when `error_pct == 0`, time constant on the order of `pwm_window_seconds × 10` so it doesn't fight legitimate steady-state demand; (b) **band-centric error in-band** — instead of `error_pct = 0.0`, feed a small `error_pct = (rh - mode.target) * 100 * k` with `k < 1` so PID is gently attracted to midband (composes with `pid_setpoint_ramp_seconds`); (c) **reset I-term on every band entry** — simplest but loses anti-windup carry-over for legitimate steady demand; (d) **passive-equilibrium auto-zero** — track time-in-band; after T_in_band > threshold, decay I toward 0 (controller eventually learns "we don't need duty here"). **Composes with:** 999.32 (LPF) — both are PID corner-case correctness fixes; 999.23 (dynamic target — schedules/ramps will worsen this since RH "in-band" relative to band X may be "off-target" relative to active stage); `project_phase28_d10_target_semantics` (the D-10/D-09 design memory). **Acceptance:** after a forced below-band excursion (e.g. open chamber door), once RH returns and dwells in-band for 30+ min, duty trends back toward the chamber's passive equilibrium for that RH (≤5% in fc1's current setup) rather than staying pinned at the recovery-spike value. **Touches:** `src/chambers/fc-core/fc_core/fc_controller.py` PID tick loop. **Filed 2026-05-11 immediately after live observation + post-restart confirmation.**

- **Phase 999.50: ROS Jazzy deprecation — replace `ROS_LOCALHOST_ONLY` with `ROS_AUTOMATIC_DISCOVERY_RANGE` + `ROS_STATIC_PEERS`** — **CLOSED 2026-05-20** (Theme C / sprint commit). Replaced `ROS_LOCALHOST_ONLY=0` with `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` in all 4 locations (`setup.sh:22`, `docker-compose.yml:16`, `scripts/pi-deploy/fc-core.service:12`, `docs/pi-setup/dev-workflow.md:95`) plus `CLAUDE.md:32`. Did NOT add `ROS_STATIC_PEERS` — fc1 and elder-plops share wg0 subnet `172.16.10.0/24`, and CycloneDDS handles its own peer enumeration via `/etc/cyclonedds.xml` on fc1, so SUBNET range is sufficient. Validation deferred: not rebuilt yet (bridge rebuild affects prod per [[project_elder_plops_dual_role]]); fc1 systemd change ships only via explicit fc1/prod push + deploy.sh per [[feedback_deploy_method]]. **Acceptance check on next bridge rebuild + fc1 deploy:** no `ROS_LOCALHOST_ONLY is deprecated` warning in bridge logs or fc-core journal; `ros2 topic list` from elder-plops still sees all `/fc1/*` topics. Original entry preserved: Surfaced 2026-05-11 during bridge restart logs: `[WARN] [rcl]: ROS_LOCALHOST_ONLY is deprecated but still honored if it is enabled. Use ROS_AUTOMATIC_DISCOVERY_RANGE and ROS_STATIC_PEERS instead.` The env var is set in two places: (1) `docker-compose.yml:16` (`ROS_LOCALHOST_ONLY=0` for the ros-core service block) and (2) `setup.sh:22` (`export ROS_LOCALHOST_ONLY=0  # Allow external connections`). Project policy per CLAUDE.md is "Allow external ROS connections" so the current value `=0` (meaning "do not restrict to localhost") is correct intent. New API equivalent: `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` (or `SYSTEM_DEFAULT`) is roughly the spiritual successor; `ROS_STATIC_PEERS` is for explicitly enumerating off-subnet peers. Since fc1↔elder-plops uses CycloneDDS over wg0 (different subnet, peer relationship), the right combo is probably `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` + add fc1's wg0 IP (`172.16.10.5`) to `ROS_STATIC_PEERS` on elder-plops, and symmetrically on fc1. **Scope:** (a) read up on the ROS 2 Jazzy discovery model changes; (b) decide whether SUBNET or SYSTEM_DEFAULT range is right for the dev+prod elder-plops + fc1 + farmer-app + future-multi-chamber topology; (c) update `docker-compose.yml:16`, `setup.sh:22`, and any systemd EnvironmentFile on fc1 (`fc-core.service` env) that exports `ROS_LOCALHOST_ONLY`; (d) verify bridge logs no longer warn and DDS discovery still works fc1↔elder-plops. **Risk:** misconfigured static peers + restrictive range could break DDS discovery in subtle ways (silent telemetry loss like the 2026-05-02 blackout class). **Acceptance:** bridge restart shows no deprecation warning; `ros2 topic list` from elder-plops still sees all `/fc1/*` topics; control loop unaffected for 1 hour soak. **Touches:** `docker-compose.yml`, `setup.sh`, possibly `scripts/pi-deploy/etc/systemd/system/fc-core.service`. **Composes with:** 999.46 (CycloneDDS multi-interface — same family of "DDS discovery on a non-trivial network"; ship together if both reach plan-phase). **Filed 2026-05-11.**

- **Phase 999.51: Stale test debt — alerter integration suite hang** — Surfaced 2026-05-11 (filed); re-scoped 2026-05-19 after partial paydown. Original entry described 6 stale jest failures across bridge + alerter; verification on 2026-05-19 found only 2 of them still reproducible, 1 already moot, and 3 transformed into a new symptom (suite hang). Live status:
  - **bridge `test/control_experiment.test.js` (2 failures) — CLOSED 2026-05-19** in commit `f1a4331`. Test assertions realigned with the un-namespaced live service paths the bridge has used since `control_experiment.js:92-94` workaround (2026-05-09). Bridge suite now 234/236 (2 remaining failures are unrelated pre-existing `burn_bar.test.js` jimp-v1 ESM dynamic-import / `--experimental-vm-modules` config issue — out of scope for this entry; consider filing as 999.54 if pursued). See `.planning/quick/260518-tcj-999-51-mechanical-bridge-srvname-fix/`.
  - **alerter `test/config.test.js` (1 failure) — MOOT 2026-05-19**. Backlog claimed `config.js:67` defaults to `http://100.96.10.66:8080/`; live `config.js:93` already reads `http://elder-plops-ts:8081/farmer`, exactly what the test expects. `npx jest test/config.test.js` -- 32/32 green with no code change. Likely fixed between 2026-05-11 and 2026-05-19 in an unrelated commit; not investigated further.
  - **alerter `test/integration.test.js` (3 failures) — OPEN, ROOT CAUSE UNKNOWN**. As of 2026-05-19 the suite no longer fails with the 2026-05-11 assertion-mismatch shape (`signalServer.sent.length` after 2000-3000ms waitFor). It hangs: jest child process exits but the npm exec parent never returns, even past 120s. Reproduced twice. This is a new symptom, not the original failure mode; the Phase 29 mode-driven config-migration hypothesis the backlog entry recorded may or may not still apply. **Next pass needs to diagnose the hang first** before assuming the original root cause holds. Memory `[[project_2026_05_19_alerter_integration_hang]]` captures the distinction.
  - **Why this matters:** Same anti-pattern argument as the 2026-05-11 filing — carrying a red/hung suite as baseline hides future regressions (see 999.36 buffer-replay, 999.41/.49 bumpless-re-engage). The hang is arguably worse than the original 3 failures because it stalls any future full-suite run, not just signals red.
  - **Scope (remaining):** ~30-90min depending on hang root cause. Likely candidates: leaked timer/interval keeping the node process alive past test completion, mock server not shutting down, or a `waitFor` predicate that resolves but leaves a pending promise. Start with `--detectOpenHandles` and `--forceExit` to characterize, then drill into the specific failing-three test names.
  - **Acceptance (remaining):** `cd src/agents/alerter && npx jest test/integration.test.js` returns within 30s with 0 failures. Full alerter suite already 702/710 GREEN (8 skipped, 0 failed) as of 2026-05-19 after 999.53 landed — only the integration suite is the open item.
  - **Touches:** `src/agents/alerter/test/integration.test.js`, possibly test helpers/fixtures alongside, possibly jest config (`--detectOpenHandles`/`--forceExit` decision).
  - **Composes with:** `feedback_run_verifications_yourself`, 999.37 (deferred-validation sibling). **Filed 2026-05-11; partial paydown + re-scope 2026-05-19.**

- **Phase 999.53: Persist Anthropic token usage in `signal_capture` for $/day cost visibility** — Filed 2026-05-17 during the credit-exhaust outage (alerter degraded ~midday; every inbound message returned a generic 69-char fallback because Anthropic returned 400 "credit balance too low" — see today's outage logs). The outage surfaced that we have **no usage telemetry**: `signal_capture` has columns for `llm_reply` / `degraded` but no token columns, and the alerter discards `msg.usage` at both LLM call sites. The only place token counts persist is the Phase 38 eval JSONLs (`.planning/phases/38-extraction-pipeline/38-EVAL-REPORT-*.jsonl`, 103 records, ~$5.26 of known eval cost) — prod spend can only be estimated from call counts. **Scope:** (a) `capture-db.js` — idempotent `ALTER TABLE IF NOT EXISTS` adding `input_tokens int`, `output_tokens int`, `cache_creation_input_tokens int`, `cache_read_input_tokens int`, `model text`; (b) `llm-client.js` compose() (~line 77) — return `msg.usage` + `msg.model` in the success branch (currently dropped); (c) `capture.js` Step 7 (~line 200) — extend the `llm_reply` UPDATE to bind the 5 new cols from the `llmClient.compose()` result; (d) extractor path (`capture.js:148`) — `extractionPipeline.enqueue` is fire-and-forget so `extractor.js`'s already-returned `usage` is lost; v1 fix is have the pipeline UPDATE `signal_capture` by capture id when the call resolves (defer a separate `extraction_runs` table until extractor grows multiple call sites); (e) one observability view `v_llm_cost_daily` aggregating in/out/cache tokens with sonnet-4-6 pricing ($3 / $15 / $3.75 / $0.30 per MTok) → `approx_usd` per day. **Tests:** extractor round-trips usage (extend `test/extraction/extractor.test.js`); fake llmClient round-trips usage into the UPDATE; idempotent ALTER covered by existing initDb test pattern. **Out of scope:** backfill of the 64 existing NULL rows (the report-style estimate already covers them); cost-threshold alerting (separate conversation); per-farmer breakdown view (ad-hoc `GROUP BY sender` works). **Acceptance:** new captures land with non-NULL token counts; `SELECT * FROM v_llm_cost_daily;` shows a per-day $/cost row. **Touches:** `src/agents/alerter/src/capture-db.js`, `src/agents/alerter/src/llm-client.js`, `src/agents/alerter/src/capture.js`, `src/agents/alerter/src/extraction/pipeline.js` (or wherever `extractionPipeline.enqueue` resolves), plus the view DDL in the same initDb block. **Composes with:** Phase 38 (the only other place usage was ever observed); 999.51 (test-debt — this adds tests, doesn't pay it down). **Effort:** ~50 LOC; fits `/gsd-quick` when promoted.

- **Phase 999.54: BUG — fc_buffer relay leaves a partial hour mid-gap after multi-hour outage** — Filed 2026-05-20 from real outage validation (see [[project_2026_05_20_fc_buffer_real_outage_validation]]). After fc1's ~11h cold-reboot outage 2026-05-20 13:04 → 2026-05-21 00:00 UTC, the bridge buffer-replay poller ran to completion and filled every gap hour 15:00–22:00 UTC to the expected ~1800 rows/hr, **except hour 14:00 UTC which only reached ~991/1800 rows** (~55%). Adjacent hours (13:00 = 122 rows = the 4 min pre-crash, expected; 15:00+ = clean) bracket cleanly, so this is not a pre-crash artifact. **Three suspects worth checking:** (a) fc1 crash-loop / partial-publish window during the actual death sequence — buffer would simply have nothing to replay (in which case "not a bug, expected"); (b) one chunk failed to transfer + cursor advanced past it (cursor logic regression — the same family as 999.36 which we believed fixed by commit `7660604`); (c) the BUF-04 "induced-dropout under live-WS race" edge case that 999.36 said still needed an explicit test — never written. **Investigation steps:** (1) SSH fc1, query its sqlite directly — `sqlite3 /var/lib/fc_buffer/buffer.db "SELECT count(*) FROM telemetry WHERE topic='fc.temperature' AND ts_ns BETWEEN <14:00 UTC ns> AND <15:00 UTC ns>;"` — tells you if fc1 itself had the data; (2) if fc1 has ~1800 rows but Timescale has ~991, the relay skipped a chunk (cursor regression — escalate); if both have ~991, fc1 was crash-looping during 14:00 (close as "expected, not a bug"); (3) regardless of outcome, this is exactly the missing BUF-04 induced-dropout test 999.36 deferred — promote that test to ship alongside the fix or the close. **Acceptance:** root cause identified + either (close as expected behavior with a one-line note on `buffer_replay.js`) or (a real chunk-loss fix + the BUF-04 test). **Touches:** investigation only initially; if regression → `src/mission-control/bridge/src/buffer_replay.js` + new `test/bridge/buffer_replay.induced_dropout.test.js`. **Composes with:** 999.36 (FIXED but apparently incomplete coverage), 999.1 (parent edge-buffering phase — should be marked CLOSED in this roadmap pass; today's validation closes it). **Effort:** ~2h investigation; fix scope depends on outcome. **Priority:** LOW — overall fc_buffer recovery worked, this is a 5% data-completeness loss in one isolated hour. File alongside the broader closure of 999.1 / 999.36.

- **Phase 999.52: Phase 35 Tier A missing signal-cli account state — extend bundle to include `mushy_signal-cli-data` volume** — **CLOSED 2026-05-20** (Theme C / sprint commit). Added a stage step that tarballs the volume via a transient `alpine:3` container (no sudo needed) into `$WORK/payload/elder-plops/signal-cli-data.tar.gz`. Smoke-tested in isolation: 119 MB compressed, 168 files including `accounts.json` + `account.db` + avatars. Note: real-world size (119 MB) is larger than the 2026-05-11 estimate (~30 MB compressed) — the SQLite files don't compress further. With default `RETENTION_DAYS=30`, that's ~3.6 GB sitting on the VPS (Hetzner CX22, ~8.7% of disk). Acceptable but worth keeping an eye on if retention bumps up. Bundles every night, no on-change check (simple > clever). Volume read-only mounted so the live signal-cli container is unaffected during the snapshot. Validation deferred: actual nightly run will fire via `mushy-tierA-backup.timer` overnight. Original entry preserved: Surfaced 2026-05-11 during Phase 36 Plan 36-01 pre-flight (`.planning/phases/36-signal-pre-gate/36-01-preflight-snapshot.md`). Phase 35 Tier A backup script (`scripts/backup-tierA/mushy-tierA-backup.sh`) bundles `.env` files + fc1 runtime overrides + VPS heartbeat secrets — it does NOT include the signal-cli docker volume. Loss of `mushy_signal-cli-data` would force full re-registration + re-link of all farmer trust (a multi-hour painful reconstruction — exactly the class Phase 35 is supposed to prevent). The Phase 36 local tarball at `/mnt/slime-kingdom/mushy-backups/signal-cli-data-YYYYMMDD.tar.gz` is the ONLY rollback path until this lands. **Scope:** (a) add a stage step that tarballs the `mushy_signal-cli-data` docker volume into `$WORK/payload/elder-plops/signal-cli-data.tar` (or .tar.gz to save bytes — the volume is ~99M today, well within Tier A "small irreplaceable" budget if compressed); (b) decide whether to bundle every night or only on-change (a simple `docker volume inspect` mtime check is fine); (c) verify the encrypted bundle decrypts + restores the volume in a smoke test on the operator side. **Acceptance:** next nightly Tier A bundle on the VPS contains `payload/elder-plops/signal-cli-data.tar(.gz)`; manual decrypt + extract reproduces a functional volume in a test docker container. **Touches:** `scripts/backup-tierA/mushy-tierA-backup.sh` only (no compose changes needed). **Composes with:** 999.45 (Tier B + borg offsite — same family of "what irreplaceable state are we still missing"). **Filed 2026-05-11 during Phase 36 Plan 36-01 pre-flight.**

### Phase 43: Phase 38<->40 Schema Normalizer + Chain Integration Tests

**Goal:** Eliminate the extractor<->commit shape mismatch that caused the 2026-05-15 lion's-mane `commit_failed` regression. Insert a router-side normalizer (Option A from `.planning/notes/2026-05-16-schema-audit.md`) that translates extractor-shape (`asset_ref`/`event_timestamp`/`name`/`source_block_refs`/`qty_g`/`recipe_lot`) to commit-shape (`qr_codes`/`timestamp`/`activity_subtype`/`source_qr_codes`/`bags`/`notes`) per log_type. Add extractor->commit chain integration tests (Option C) covering all 5 log_types, with Test 2 (activity-relocate via lion's-mane transcript) as the named 2026-05-15 regression guard. Ungated by farmer-facing acks per locked decision 2026-05-17 (`project_2026_05_17_findings_discussion_decisions.md`).
**Requirements:** SCHEMA-01 (every log_type round-trips extractor->normalizer->commit without terminal field-shape failure), SCHEMA-02 (a real extractor draft for activity-relocate commits end-to-end against mock farmOS), SCHEMA-03 (normalize.js is idempotent: commit-shape input passes through unchanged), SCHEMA-04 (5 chain tests live under `test/farmos/integration/` and run by default, no `FARMOS_INTEGRATION=1` gate)
**Depends on:** Phase 40 (the commit handlers being normalized) and Phase 38 (the extractor-shape contract)
**Open design questions for discuss-phase** (from `.planning/notes/2026-05-16-schema-audit.md` section 3.A):

  1. harvest `source_block_refs` (block names) vs `source_qr_codes` -- extend `qr.resolveQr` to handle block names, or add parallel resolve-by-name path?
  2. seeding `batch_name` (sterilization) vs `parent_batch_name` (lineage) -- keep distinct, fold, or defer until pasteurization log lands?
  3. input `recipe_lot` vs `input_ingredients` -- extend commit-input to read recipe_lot, or just append to notes?
  4. harvest `qty_g` (single number) vs `bags` (multi-bag w/ QR+weight) -- extractor schema extension or farmer UX change? (audit calls this out of scope for same-week-fix; file as v1.8 candidate)

**Reference:** `.planning/notes/2026-05-16-schema-audit.md` (full audit; verdict: 4 of 5 log_types wire-incompatible end-to-end; recommends A + C bundled, ~1d combined)
**Plans:** 6 plans (all shipped 2026-05-16)
Plans:

- [x] 43-01-PLAN.md -- normalize.js + unit tests (incl. SCHEMA-03 idempotency)
- [x] 43-02-PLAN.md -- qr.js name-on-miss fallback (D-06)
- [x] 43-03-PLAN.md -- wire normalize() into commit-router.js (D-02, 1-line)
- [x] 43-04-PLAN.md -- locate + document 2026-05-15 lion's-mane transcript (D-16)
- [x] 43-05-PLAN.md -- 5 chain integration tests under test/farmos/integration/
- [x] 43-06-PLAN.md -- SCHEMA-04 default-run attestation

### Phase 44: Event-gate + Durable `signal_outbound` (tenant-aware)

**Goal:** Stop burning paid Sonnet on chit-chat and stop the alerter from being amnesiac about its own outbound messages. Insert a rules-only event-gate at `capture.js:147` (fast-path POSITIVE: image/audio/strain-code/block-name/long-text; fast-path NEGATIVE: short ack within 30m of `attestation_kickoff`; gray-zone falls through to extractor for v1, escalates to Haiku 4.5 pre-classifier only if Plan-03 audit shows >30% residual phantom rate). Persist every `signalClient.send` to a new `signal_outbound(tenant_id, intent, ...)` table so Phase 37's conversational LLM can see what the bot already said. First milestone under OSS-Foray Option α: the new table ships with `tenant_id text NOT NULL` indexed from day one; Mossrock-specific config (farmer phone map, strain codes) starts migrating into `tenants/mossrock/`.
**Depends on:** Phase 43 (schema normalizer in place — gate must not regress chain tests)
**Requirements (proposed; lock at discuss-phase):** GATE-01 (zero farmer-facing preview pings on hand-labeled chit-chat in 100-capture smoke), GATE-02 (>=95% event recall on same smoke), OUTBOUND-01 (every `signalClient.send` writes one row to `signal_outbound` with intent tag — 14 call sites enumerated, see `.planning/notes/2026-05-17-signal-outbound-schema-audit.md`), OUTBOUND-02 (Phase 37 `fmtHistory` reads `signal_outbound` and surfaces `lastBotOutbound` to the LLM prompt — closes finding 1b), TENANT-01 (`signal_outbound.tenant_id` indexed; `tenants/mossrock/` directory exists with at least one config key moved in)
**Open design questions for discuss-phase:**

  1. Rules-only first vs. Haiku 4.5 pre-classifier from day one? (Note 2026-05-17 recommends rules-first, audit one week, add Haiku only if residual phantom rate justifies the paid surface — `feedback_smoke_before_expensive_batch`.)
  2. Should the gate ALSO gate the Phase 37 LLM-convo `compose` call at `capture.js:168`? (Out of scope for finding 7 proper; cheap to bundle.)
  3. Tenant-id retrofit for existing tables (`signal_capture`, `signal_draft`) — defer to v2.0 extraction or do it now? (Default: defer per OSS-Foray decision; new tables only in v1.8.)
  4. What's in `tenants/mossrock/` for v1.8? SIGNAL_FARMER_MAP at minimum; SHI/SH2/KOY/MAI/MALI/KOS/DT/CAS/CAZ/WIN/ALM/MOR/BP/LIMA strain vocab; Anthropic key + farmOS endpoint pointer? Decide at discuss-phase.

**Ship-gate (per `feedback_real_data_before_ship_gate_pass`):** 100-capture hand-classification smoke from prod (Plan-01) drawn from live Timescale `signal_capture` rows on elder-plops (frozen `/mnt/mossrock/shared/mushdatadump-prod/` corpus is only 3 rows; see `.planning/notes/2026-05-17-prod-corpus-survey.md`). Stratified per 2026-05-17 distribution: 36 hard-event / 28 confirm / 8 phantom-ack / 8 UX-meta / 12 soft-obs / 8 greetings.
**References:**

- `.planning/notes/2026-05-17-is-this-an-event-gate.md` (finding 7 design)
- `.planning/notes/2026-05-17-llm-outbound-amnesia.md` (finding 1b design)
- `.planning/notes/2026-05-17-oss-foray-decision.md` (Option α tenant constraint)
- `.planning/notes/2026-05-17-signal-outbound-schema-audit.md` (current-state map)
- `.planning/notes/2026-05-17-prod-corpus-survey.md` (Plan-01 sourcing)
- `.planning/notes/2026-05-17-tenant-id-retrofit-map.md` (tenant boundary inventory)
- SEED-010 (Foray extraction trigger)

**Plans:** 6/7 plans executed

- [x] 44-00-PLAN.md — Wave 0 scaffolding (.gitignore + yaml dep + 8 test stubs)
- [x] 44-01-PLAN.md — 100-capture hand-classified smoke fixture (operator manual ship-gate)
- [x] 44-02-PLAN.md — signal_outbound DDL + DAO + signal.js single persistence hook (OUTBOUND-01, TENANT-01)
- [x] 44-03-PLAN.md — Wire intent + sourceModule across all 14 send sites (OUTBOUND-01)
- [ ] 44-04-PLAN.md — event-gate (rules + Haiku 4.5 classifier) + capture.js wiring + extraction_gate column + smoke harness (GATE-01, GATE-02)
- [x] 44-05-PLAN.md — fmtHistory stream merge + lastBotOutbound prompt field (OUTBOUND-02)
- [x] 44-06-PLAN.md — tenants/mossrock/ config tree + layered config.js loader (TENANT-01)

### Phase 45: NORTH-STAR commit_failed ack + replay outstanding silent-failure drafts

**Goal:** Close the NORTH-STAR violation that surfaced 2026-05-15 (Vikki Rambo `commit_failed` on `observation_requires_target` went unreplied; farmer said YES and got silence). Every terminal state in the confirm/commit state machine MUST produce a farmer-facing reply — success AND failure paths. Then live-fire replay the two outstanding silent-failure drafts as UAT.
**Depends on:** Phase 44 (signal_outbound table is the natural place to log the ack send; not strictly required but bundles naturally — confirm at discuss-phase)
**Requirements (proposed; lock at discuss-phase):** ACK-01 (no terminal state in the confirm/commit machine is silent post-YES — enumerated and tested), ACK-02 (replay of draft `b8a1e586` Vikki Rambo through the fixed path produces an English-default farmer-facing reply on the failure path — Vikki is English-first per `[[farmer-language-stacks]]`), ACK-03 (replay of draft `1fb28e70` Santi LIMA likewise), ACK-04 (idempotency: a retried commit does not double-send the ack)
**Reference:** `.planning/notes/2026-05-17-northstar-commit-failed-reply.md` + `.planning/notes/2026-05-17-northstar-ack-sketch.md` (impl-sketch produced by overnight research) + memory `[[feedback_no_silent_failure_after_farmer_confirm]]`
**Plans:** 5 plans

- [ ] 45-01-PLAN.md — Schema: signal_draft.outcome_ack_sent_at + tryMarkOutcomeAckSent idempotency primitive (ACK-04)
- [ ] 45-02-PLAN.md — commit-outcome-preview.js renderer: 10 templates + 3 farm-level + 8-code reasonMap (ACK-01)
- [ ] 45-03-PLAN.md — edit-handler Option X: commit_failed → EDIT → awaiting_farmer transition (ACK-01)
- [ ] 45-04-PLAN.md — Wire T4+T6 dispatch hooks + outboundConfirm plumbing + signal_outbound logging (ACK-01, ACK-04)
- [ ] 45-05-PLAN.md — Live-fire UAT: backfill replay of Vikki + Santi drafts (ACK-02, ACK-03)

---
*Roadmap created 2026-03-28. v1.4 shipped 2026-05-01. v1.5 shipped 2026-05-09. v1.6 shipped 2026-05-11. v1.7 effectively shipped 2026-05-16 (Phase 42 calendar-deferred). v1.8 scaffolded 2026-05-17.*
