# Phase 49: Real-session eval corpus + May 22 ship-gate reprocess — Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Source:** Auto-mode discuss (gsd-autonomous). Decisions derive from ROADMAP success criteria + locked v1.9 schema memories + prior Phase 47/48 corpus patterns.

<domain>
## Phase Boundary

The third and final phase of v1.9. Phases 47+48 shipped the *capability* (multi-source extraction → session-shaped draft → fan-out commit). Phase 49 ships the *evidence* + the *live ship-gate*:

1. **Real-session eval corpus** — ≥3 real inoc sessions from `/mnt/mossrock/shared/mushdatadump-prod/` added to the CI eval suite under `src/agents/alerter/test/eval/ingestion/fixtures/` (or a new `sessions/` subdir). Each session has: audio file (m4a/aac), paper-log photo(s) (jpg), hand-labeled ground truth JSON (expected groups + child names + parents + session date). The 2026-05-22 session is the named regression guard; CI fails if any named session regresses.
2. **CI gate wiring** — a `sessions.test.js` (sibling of `paperlog.test.js` / `audio.test.js` / `crossstream.test.js`) iterates the corpus, runs each fixture end-to-end through `pipeline-adapter.js`, and asserts the extracted `seeding_session` draft matches the hand-labeled ground truth (parents recognized, child SEQ allocation, qty distribution, conflict-resolution policy). Failure on any named session = CI red.
3. **May 22 ship-gate reprocess** — the *live* ship-gate for v1.9: an operator-driven runbook (`49-SHIP-GATE.md`) that (a) marks the two captured-but-failed May-22 production drafts `e3a564d063d4…` and `6edaaba7deb0…` as `discarded` with reason "superseded by Phase 49 reprocess", (b) re-runs the May 22 audio+photo through the new pipeline pointed at farmOS dev, and (c) attests 11 logs + 1 fungi session asset landed cleanly and a lineage walk reconstructs the session from logs alone.
4. **Discarded-draft maintenance** — a small admin script (`scripts/discard-drafts.js` or extend an existing maintenance helper) that takes a list of draft UUIDs + a reason and writes `status='discarded'` + `discarded_reason` to `signal_draft`. Reusable beyond this phase for future stale-draft sweeps.

In scope:
- Corpus shape: 3 named sessions minimum. 2026-05-22 mandatory; ≥2 others to be selected from `mushdatadump-prod` paper logs (e.g., the 2026-05-12 inoc-santi session under `/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/` and one selected from `2026-05-13_backlog_unprocessed/` if it's an inoc session — otherwise a synthetic single-parent or smaller-cardinality real session from the broader dump). Selection criteria: must exercise at least one of {multi-parent multi-strain, single-parent legacy, photo-absent ask-back} per session.
- Ground-truth schema: a `ground-truth.json` next to each fixture with the expected `seeding_session` Zod-validated draft shape (5 groups for May-22; whatever shape applies for others).
- CI test pattern: mirrors `paperlog.test.js` — sequential, deterministic, no real LLM calls (uses the existing mock-extractor pipeline where applicable, OR the real extractor behind an `EVAL_RUN_LIVE=1` env flag mirroring Phase 47-05 + Phase 48-05).
- Eval scoring: schema-conformance (does the draft validate?) + value-equality (do the named fields match ground truth?) + ≥90% schema-conformance bar on the broader (non-named) corpus.
- Ship-gate runbook (`49-SHIP-GATE.md`): full step-by-step `curl`/`signal-cli`/`docker compose exec`/`psql` commands an operator runs against the production alerter pointed at farmOS dev (NOT prod farmOS — v1.9 doesn't auto-backfill prod with historical paper-log sessions).
- Discard script: idempotent (re-running on already-discarded drafts is a no-op).

Out of scope:
- Bulk prod backfill (mark-discarded + reprocess) of ALL historical failed inoc drafts. v1.9 scope is the two named May-22 drafts only.
- Auto-discarded-draft sweep cron (manual operator invocation suffices for first ship).
- Real-time eval-pass-rate dashboards / Grafana wiring.
- Multi-session-bundle continuity (turn 1 + turn 2 same session).
- Cross-language audio (Vikki Cantonese, Selina yue) — corpus is initially Santi/Spanish/English. Future phase.

Out of scope (deferred entirely):
- Live-fire of Phase 48 commit handler against PROD farmOS. Phase 48's live-fire stays operator-deferred per its runbook.
- Hand-labeling sessions not yet in `mushdatadump-prod` — corpus is a snapshot, expands as new prod sessions arrive.
</domain>

<decisions>
## Implementation Decisions

### Gray Area A — Corpus layout
**Lock: new subdir `test/eval/ingestion/fixtures/sessions/` with one folder per session**, each containing `audio.{m4a,aac}` (optional), `paper-log.jpg` (optional), `ground-truth.json` (required), and `MANIFEST.md` documenting capture date/source/notes. Loaded by a new `sessions-loader.js` sibling of `fixtures-loader.js`. Mirrors the existing `paperlog`/`audio` corpus shape — no novel structure.

### Gray Area B — Eval test architecture
**Lock: a new `test/eval/ingestion/sessions.test.js`** that:
- Reads all session fixtures from the loader.
- For each: builds the pipeline input (audio + photo blocks), runs `pipeline-adapter.run()` with the *real* extractor when `EVAL_RUN_LIVE=1` set, otherwise with the mock-extractor that returns the pre-recorded extraction (so CI stays cheap + deterministic).
- Asserts the resulting `signal_draft.draft_json` matches `ground-truth.json` on `{type, event_date, groups[].parent.value, groups[].species.value, groups[].qty.value, groups[].child_block_names.value}`.
- Named sessions (May-22 + at least one other tagged `regression_guard: true` in MANIFEST.md): test is `it.each(NAMED)` — any failure fails CI hard.
- Unnamed corpus sessions: `it.each(CORPUS)` with `≥90%` aggregate schema-conformance bar; individual failures log but don't red CI (mirrors Phase 38 Plan-09 pattern).

### Gray Area C — Ground-truth schema
**Lock: `ground-truth.json` is a literal `seeding_session` draft JSON** (matches the Zod schema from Phase 47), additionally tagged with `meta: { capture_date, source_path, regression_guard: boolean, notes }`. No bespoke comparison schema — equality against a validated `seeding_session` is the canonical assertion.

### Gray Area D — May 22 ship-gate execution mode
**Lock: operator-driven runbook**, not auto-run. The runbook (`49-SHIP-GATE.md`) provides exact commands. Auto-running against farmOS dev from CI requires shipping a dev-farmOS deploy + secret-injection contract that v1.9 doesn't carve. Phase 49 ships the *capability* to re-run; the operator executes once and attests.

### Gray Area E — Discard mechanism
**Lock: standalone script `scripts/discard-drafts.js`** that takes `--uuid <uuid> [--uuid <uuid>…]` + `--reason "<text>"` args, opens a transactional update against `signal_draft` (using the same pg pool config as the alerter), and writes `status='discarded', discarded_reason='<text>', discarded_at=now()`. Idempotent (`WHERE status != 'discarded'`). Logs each affected row to stdout. Re-usable.

Schema delta: `signal_draft` may need `discarded_reason TEXT NULL` + `discarded_at TIMESTAMPTZ NULL` columns if not already present. Migration ships in 49-01.

### Gray Area F — Eval-corpus selection beyond May 22
**Lock: 2026-05-12 inoc-santi session** (from `/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/`) is the second named regression guard — it's the prod inoc session already used as Phase 38 Plan-09's real-data fixture, so its hand labels are known. **Third session** is chosen from `mushdatadump-prod/2026-05-13_backlog_unprocessed/` if any of those captures is an inoc session; otherwise picked from a smaller real inoc session in the broader `mushdatadump` (NFS) corpus. Selection is the planner's call during plan-phase; both 2026-05-22 and 2026-05-12 are the mandatory named pair regardless.

### Other locked policies (carried from project memory)

- **No silent failure** — `[[feedback_no_silent_failure_after_farmer_confirm]]` applies to the ship-gate too: ack contract Phase-48 wired must round-trip for both success and failed terminal states during the reprocess.
- **Never overwrite paid live-API results** — `[[feedback_persist_paid_results_default]]`: the May-22 reprocess output gets a unique JSONL path under `mushdatadump-prod/2026-05-22_inoc_santi_reprocess_v1.9/` so we don't clobber the original failed run.
- **Smoke before expensive batch** — `[[feedback_smoke_before_expensive_batch]]`: ship-gate is a 1-session smoke (May 22), not the full N-session corpus. The corpus expansion to 3+ sessions is the CI guard, not the ship-gate.
- **Real data ≥ curated** — `[[feedback_real_data_before_ship_gate_pass]]`: named regression sessions ARE real data; that's the whole point of this phase.
- **Tenant-aware** — Option α: `signal_draft.tenant_id` already exists per Phase 44; new columns get `default 'mossrock'`.
- **mushdatadump = 2025 notebook** — `[[project_mushdatadump_is_2025_notebook]]`: ignore the "no year on pages" hallucination class; ground-truth dates are operator-attested in MANIFEST.md.

</decisions>

<code_context>
## Existing Code Insights

- `src/agents/alerter/test/eval/ingestion/` has the existing eval scaffolding: `pipeline-adapter.js`, `fixtures-loader.js`, `cross-stream.js`, `paperlog.test.js`, `audio.test.js`, `crossstream.test.js`. Phase 49 adds `sessions-loader.js` + `sessions.test.js`.
- `src/agents/alerter/test/eval/ingestion/fixtures/` is where new `sessions/` subdir goes.
- `src/agents/alerter/scripts/` (if exists) or `src/agents/alerter/bin/` is where `discard-drafts.js` lands.
- `signal_draft` table schema lives in the alerter's migration directory (likely `src/agents/alerter/migrations/` or similar — researcher will confirm). Migration adds `discarded_reason` + `discarded_at` columns if missing.
- Ship-gate runbook follows the `47-LIVE-FIRE.md` / `48-LIVE-FIRE.md` shape.

</code_context>

<specifics>
## Specific Ideas

- May-22 session in the corpus carries the full audio (`HOZad9ymvNJTXmRREgcW.m4a` from prod corpus) + paper-log photo (`XAbzzUidkLR3irhVmjea.jpg`) — both already exist under `mushdatadump-prod` (operator copied them as Phase 47 live-fire input).
- Ground-truth for May 22: 5 groups: SHI×1 from `260304_SHI_5`, SHI×1 from `260118_SHI_23`, SHI×1 from `260118_SHI_26`, KOY×4 from `260118_KOY_12`, KOY×4 from `260425_KOY_4`; children `260522_SHI_1..3` + `260522_KOY_4..11`; event_date 2026-05-22.
- May-12 session: hand labels from Phase 38 Plan-09 already exist; reuse them.
- The two failed drafts to discard: `e3a564d063d4…` and `6edaaba7deb0…` (per ROADMAP Phase 49 description).

</specifics>

<deferred>
## Deferred Ideas

- Cross-language audio corpus (Vikki/Selina).
- Auto-discard cron sweep.
- Bulk historical paper-log backfill into prod farmOS.
- Multi-turn bundle continuity.
- Eval-pass-rate dashboards.

</deferred>

<canonical_refs>
## Canonical Refs

- `.planning/phases/47-multi-source-extraction-fusion-groups-shape-inoc-draft/` — Phase 47 extraction
- `.planning/phases/48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/` — Phase 48 commit
- `.planning/phases/38-extraction-pipeline/` — prior eval-corpus pattern (Plan-09)
- `/mnt/mossrock/shared/mushdatadump-prod/` — prod corpus root
- `src/agents/alerter/test/eval/ingestion/` — existing eval scaffolding
- `[[project_inoc_shape_multi_parent_batch]]`, `[[project_b5_seq_is_per_session_not_per_strain]]`, `[[project_session_is_production_shape_per_bag_is_storage]]`
- `[[feedback_real_data_before_ship_gate_pass]]`, `[[feedback_smoke_before_expensive_batch]]`, `[[feedback_persist_paid_results_default]]`
- `[[project_phase38_production_logs_available]]` — prod corpus path

</canonical_refs>
