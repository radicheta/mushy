# Requirements: v1.12 Farm-Agent Python Port

**Milestone goal:** Rewrite the live ~16k-LOC JS alerter/extraction stack (`src/agents/alerter/`) as a Python (asyncio) stack — Signal I/O, multimodal extractor, draft state machine, and farmOS commit path — validated against the live corpus and cut over in a single big-bang switch, with clean Foray-ready module seams.

**Strategy (locked 2026-06-14 with Santi):**
- **Big-bang rewrite** — build full Python stack, validate against corpus, single prod cutover (no dual-stack period on the shared TimescaleDB).
- **Port + opportunistic cleanup** — reproduce Node behavior except an explicit pre-accepted delta list (TZ Toronto→Montevideo, Phase-50 quote-threading fixes); fix obvious wrongs as encountered.
- **Foray-ready seams** — `chamber/` is the only mushy-private package; every other package is a Foray-extractable island (CI grep gate). Tenant primitive is the lowest dependency node.

**Research:** `.planning/research/SUMMARY.md` (+ STACK / FEATURES / ARCHITECTURE / PITFALLS), committed `c702eea`. HIGH confidence.

**Stack (locked targets):** Python 3.12 / asyncio, pydantic v2 (←zod), psycopg3 (←pg), anthropic AsyncAnthropic, httpx, websockets, signal-cli via raw JSON-RPC over UNIX socket, `python:3.12-slim` (no ROS), `uv` packaging.

**Hard invariants preserved:** v1.11 commit-time CSV fidelity hard gate; v1.10 upsert-by-stable-identity; NORTH-STAR farmer YES/NO/EDIT before every farmOS write.

---

## Active Requirements

### FND — Foundation (tenancy, persistence, config, schema-parity gate)

- [x] **FND-01**: Python package skeleton boots as a single asyncio daemon (`boot.py` is the only module importing across all packages); `uv sync` + `python:3.12-slim` Docker image builds and runs under compose.
- [x] **FND-02**: `tenancy/TenantConfig` loads layered YAML+env config; no business module reads `env` directly; secrets stay env-only.
- [x] **FND-03**: `persistence/` provides a shared psycopg3 async pool + idempotent migrations covering the existing tables (`signal_capture`, `signal_draft`, `signal_outbound`, commit/audit tables); schema additions are additive-only (no breaking change to the live schema the Node stack also reads).
- [x] **FND-04**: pydantic v2 draft schemas emit JSON Schema that structurally matches the zod-derived schema the Node extractor sends to Claude; a JSON-Schema structural-diff check passes as a ship gate before any LLM call (`extra='forbid'` on every nested model; cross-field validators ported).
- [x] **FND-05**: Foray seam is statically enforced — a CI check fails the build if any non-`chamber` package imports from `chamber/`.

### SIG — Signal I/O

- [ ] **SIG-01**: Python sends and receives Signal messages via signal-cli over the JSON-RPC UNIX socket (same compose topology), including attachment fetch, with send attribution verified by round-trip (not inferred from timing).
- [x] **SIG-02**: Outbound sends are persisted to `signal_outbound` (durable queue) and rate-capped; the rate-cap history is concurrency-safe under asyncio.
- [ ] **SIG-03**: Envelope routing reproduces multi-farmer behavior — replies go to `envelope.source`; DM vs group context is distinguished; group-ID `internal_id`↔`id` translation is ported (no silent group-message drops); unknown numbers tagged `(unassigned)`, never dropped.
- [ ] **SIG-04**: Native quote threading works on outbound acks, with the Phase-50 fixes folded in (`quote.timestamp` coerced via `int(str(ts))`, fail-open to unquoted send on invalid shape); verified live against signal-cli.

### CAP — Capture + Transcription

- [ ] **CAP-01**: Inbound envelopes are captured to `signal_capture` (ULID id) with attachments downloaded to disk; farmer slug resolved from the Signal number → farmOS people directory.
- [ ] **CAP-02**: Audio attachments are transcribed via the local Whisper client without blocking the event loop (off-loop execution); transcript feeds extraction alongside text + image.

### GATE — Event gate

- [ ] **GATE-01**: A rule pre-filter + Haiku classifier (forced tool-use, short timeout, fail-open) decides which inbound messages enter the extraction pipeline, reproducing the Node gate's accept/reject behavior.

### XTR — Extraction pipeline

- [ ] **XTR-01**: Multimodal extractor fuses text + audio transcript + image into a single draft via Claude tool-use against the pydantic schema, with cacheable system prompt + few-shot turns ported (prompt-cache breakpoints preserved).
- [ ] **XTR-02**: Schema-invalid model output triggers the same retry behavior; the multi-parent SeedingSession shape (N children from M>1 parents) and per-field provenance are reproduced.
- [ ] **XTR-03**: B5 block-name minting (`{YYMMDD}_{SPECIES3}_{SEQ}`, per-session SEQ) is reproduced; `BLOCK_NAME_RE` uses anchored full-match; drafts persist to `signal_draft` (hex-SHA id).

### CNF — Confirm loop

- [ ] **CNF-01**: The YES/NO/EDIT/expiry confirm state machine is reproduced as a pure function with table-driven 100% parity tests; a duplicate YES does not double-commit.
- [ ] **CNF-02**: Strain-confirm-before-mint, compact session-preview rendering, edit handler, and nudge/expire watchdog are reproduced; watchdog ticks are serialized (`while: await sleep; await tick`, conditional-UPDATE guard) — no asyncio race producing duplicate nudges/expires.

### FWR — farmOS write path

- [x] **FWR-01**: Confirmed drafts commit to farmOS via an httpx async client reproducing all log types and asset creates/patches, including the field-scoped image upload route (`POST /api/asset/{type}/{uuid}/image`).
- [x] **FWR-02**: Upsert-by-stable-identity is byte-identical to Node — a cross-language fixture proves the same input yields the same stable-identity digest (Node hex == Python hex); writes patch existing entities, never create duplicates.
- [x] **FWR-03**: Strain resolver reproduces curated-14-code exact matching + variant normalization (the POY-as-KOY class of bug is regression-guarded); the v1.11 commit-time CSV fidelity gate is preserved.
- [x] **FWR-04**: An **origin guard** is committed before any write path runs — a Python validation/shadow process never has its drafts drained by the live Node commit-watchdog (shared-prod-Timescale leak is structurally prevented).

### CHM — Chamber alerting (mushy-private)

- [ ] **CHM-01**: The ROS-bridge WebSocket client + alert state machine (RH out-of-band, pi-offline/chamber-dark, sensor staleness, humidifier-stuck) with cooldown/snooze/mute and daily heartbeat are reproduced in the `chamber/` package.
- [ ] **CHM-02**: Farmer-facing time/number formatting uses `ZoneInfo('America/Montevideo')` (the Toronto-since-Phase-13 bug is fixed) and round-number formatting; this TZ change is pre-declared as an intentional parity delta.

### PAR — Parity / validation gate

- [ ] **PAR-01**: A golden-corpus replay harness runs the Python extractor against a read-only snapshot DB on an isolated port (`:5434`) and field-diffs `draft_json` vs the stored Node output; the gate passes at ≥95% field match (the 10-page Phase-55B set + May-22 inoc session are named minimums).
- [ ] **PAR-02**: The intentional-delta list (TZ fix, quote-ts coercion, fmtNum edge cases) is formally enumerated and excluded from the parity threshold so legitimate fixes are not miscounted as failures.
- [ ] **PAR-03**: Confirm-FSM parity (100%, pure function) and farmOS-payload identity-field parity (100% on stable-identity fields, dry-run, no live write) pass before cutover.

### CUT — Cutover

- [ ] **CUT-01**: A documented stop-then-start cutover runbook drains/force-expires in-flight `awaiting_farmer` drafts, stops Node, starts Python (which drains the signal-cli backlog on boot); no dual-run window on the shared DB.
- [ ] **CUT-02**: Rollback is drilled and executable in under ~2 minutes from a tagged image (`stop alerter-py && start alerter`); both stacks share the same additive schema so either watchdog reads the other's rows correctly.
- [ ] **CUT-03**: A post-cutover observation window confirms live farmer traffic flows end-to-end (Signal → extract → confirm → farmOS) on the Python stack with no regression vs the Node baseline.

---

## Future Requirements (deferred)

- Full Foray repo extraction (Apache-2.0 carve-out, README/docs, public launch) — SEED-010; this milestone only builds the seams.
- v1.13 auto-commit narrowing — depends on the v1.11 confirm corpus.
- The 2 open 55B follow-ons (receipt dup false-positive, D-03 image-on-session) — fold in only if trivial during the relevant phase.
- Origin-guard generalization to a full dev/prod origin split (v1.13 watchdog-origin-guard candidate) — PAR/FWR ship the minimal guard.

## Out of Scope

- Porting `fc_core` / Mission Control / OpenMCT bridge / camera / VPS hub — these stay Node/ROS; only the alerter slice ports.
- Re-porting `src/farmos-agent/` — already Python; reference only.
- QR-scan binding flow — not exercised; multimodal-only is the commitment.
- Dual-stack / traffic-splitting between Node and Python — unsafe on the shared 30s-drain watchdog DB; big-bang cutover only.
- ML vision (contamination/pin detection) — needs camera-coverage prereq.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | Phase 56 | Complete |
| FND-02 | Phase 56 | Complete |
| FND-03 | Phase 56 | Complete |
| FND-04 | Phase 56 | Complete |
| FND-05 | Phase 56 | Complete |
| SIG-01 | Phase 57 | Pending |
| SIG-02 | Phase 57 | Complete |
| SIG-03 | Phase 57 | Pending |
| SIG-04 | Phase 57 | Pending |
| CAP-01 | Phase 58 | Pending |
| CAP-02 | Phase 58 | Pending |
| GATE-01 | Phase 59 | Pending |
| XTR-01 | Phase 60 | Pending |
| XTR-02 | Phase 60 | Pending |
| XTR-03 | Phase 60 | Pending |
| CNF-01 | Phase 61 | Pending |
| CNF-02 | Phase 61 | Pending |
| FWR-01 | Phase 62 | Complete |
| FWR-02 | Phase 62 | Complete |
| FWR-03 | Phase 62 | Complete |
| FWR-04 | Phase 62 | Complete |
| CHM-01 | Phase 63 | Pending |
| CHM-02 | Phase 63 | Pending |
| PAR-01 | Phase 64 | Pending |
| PAR-02 | Phase 64 | Pending |
| PAR-03 | Phase 64 | Pending |
| CUT-01 | Phase 65 | Pending |
| CUT-02 | Phase 65 | Pending |
| CUT-03 | Phase 65 | Pending |
