# Phase 62: farmOS Write Path - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Confirmed `signal_draft` rows commit to farmOS via a ported async (httpx) client:
origin-guarded against the live Node prod-leak, byte-identical stable-identity
upsert (no duplicates on re-run), field-scoped image upload, and a CSV fidelity
gate that holds disagreements instead of silently misattributing strains. Faithful
port of the Node `src/agents/alerter/src/farmos/` tree.

**In scope:** origin guard (column + Node-watchdog patch + deploy), httpx farmOS
client (session-cookie + CSRF), commit router + per-type handlers, `merge.py`
(name-based stable identity), asset/log upsert primitives, field-scoped image
upload, CSV fidelity gate with farmer ask-back, curated-14 strain resolver +
POY->KOY regression fixture, boot wiring (shared httpx client + commit-watchdog task).

**Out of scope:** chamber alerter (Phase 63), parity gate harness (Phase 64),
cutover/rollback (Phase 65), and any broadening of the v1.11 backfill fidelity model.
</domain>

<decisions>
## Implementation Decisions

### Origin guard (FIRST commit — SC1)
- **D-01:** Mechanism = `origin` column **+ live Node-watchdog patch**. Add
  `origin text NOT NULL DEFAULT 'node'` to `signal_draft` (idempotent
  `ADD COLUMN IF NOT EXISTS`); Python commit writes set `origin='python'`; the
  Node commit-watchdog SELECT (`commit-db.js:47-60`) gains `AND origin != 'python'`.
  This pulls the v1.13 backlog item ([[project_v113_watchdog_origin_guard_candidate]])
  forward into Phase 62 deliberately.
- **D-02 (HARD SEQUENCING CONSTRAINT):** The structural guarantee only holds once
  the **patched Node watchdog is deployed to prod**. Therefore the order is fixed:
  (1) migration adds `origin` column, (2) Node watchdog patched with the
  `AND origin != 'python'` clause, (3) Node alerter **redeployed to prod** — ALL
  before any Python process is allowed to write `status='confirmed'` to the shared
  Timescale. Until step 3 is live, Python validation must not touch shared
  `signal_draft`. Runner: mushy side edits + deploys the Node alerter
  ([[feedback_cross_repo_runner_must_be_named]]).
- **D-03:** Node watchdog default behavior is preserved for legacy rows: existing
  rows get `origin='node'` via the column DEFAULT, so the Node watchdog continues
  to drain them unchanged. No backfill needed.

### Live-fire scope (SC2 / SC3)
- **D-04:** **In-phase live-fire against dev farmOS `:18080`** (NOT deferred to an
  operator step as phases 58-60 did). Phase verification runs the Python commit
  path twice against dev and asserts: (a) 0 duplicate `asset--fungi` created on the
  second run (upsert-by-name), (b) the uploaded image appears on the asset's `image`
  field. Dev creds are resolved ([[project_dev_farmos_18080_rejects_prod_bot_creds]]).
  Rationale: [[feedback_unit_tests_dont_catch_wiring]] — the write path is exactly
  the kind of wiring seam unit tests miss.

### Stable identity (SC2 wording reconciliation)
- **D-05:** Stable identity is **name-based, NOT a hex digest.** Confirmed from code:
  `merge.js` is a pure field-merge where `name` is an identity scalar that throws
  on mutation (`IdentityMutationError`); identity lookup is `findAssetByName()`
  (`/api/asset/fungi?filter[name][value]=<enc>`). There is no `createHash`/digest
  anywhere in `farmos/`. **ROADMAP SC2 wording ("same stable-identity hex digest
  from merge.js and merge.py") is inaccurate and should be reconciled** to:
  "the Python `merge.py` produces a byte-identical merged JSON:API payload to Node
  `merge.js` for the same input, and the name-based lookup yields 0 duplicate assets
  on a second commit." `merge.py` must replicate exactly: array-ref set-union by id
  (`parent`/`qr_codes`/`farm_id_tag`), scalar singleton rels
  (`fungi_type`/`fungi_xing`: null=take, equal=noop, differ=conflict-keep-existing),
  scalar attr (`status`), notes split-dedup-join on `\n---\n`, and the
  `mushy:draft:{draftId}` notes marker.

### CSV fidelity gate (SC4)
- **D-06:** On block-name vs CSV disagreement: hold the draft as
  `fidelity_cross_check_unverified` (new status string, add to schema) **AND send a
  farmer ask-back** — not a silent hold ([[feedback_no_silent_failure_after_farmer_confirm]],
  [[feedback_farmer_is_reality_source_of_truth]]). The draft is NOT committed to
  farmOS until resolved. This prevents POY-committed-as-KOY
  ([[project_backfill_extraction_fidelity_38pct_silent_misattribution]]).
- **D-07:** CSV is loaded from the **prod CSV path at boot** in production; tests use
  a fixture CSV. CSV remains NON-authoritative — it is a second interpretation, so on
  disagreement the gate FLAGS/holds for human review, never silent hard-reject
  ([[project_backfill_csv_is_not_ground_truth]]).
- **D-08:** Curated-14 strain resolver (`confirm/strain_ask_back.py:88-111`) already
  rejects unknown codes; Phase 62 adds a **named POY->KOY regression fixture** asserting
  POY is never silently resolved to KOY.

### Claude's Discretion
- Exact `commit_watchdog_loop` poll interval and task wiring in `boot.py` (mirror the
  Node `COMMIT_WATCHDOG_INTERVAL_MS=30000` and Phase 57-60 `asyncio.create_task` pattern).
- httpx client retry/backoff constants — mirror Node (`10s timeout`, `3x` backoff 1s/4s/16s)
  unless research finds a reason to diverge.
- Fixture CSV contents/shape and the precise ask-back message wording.

### Folded Todos
- **`2026-05-24-observation-of-unknown-asset-should-backfill-not-fail.md`** — unknown
  asset on commit should mint-with-confirm, not fail. Fits the write-path commit
  behavior; aligns with D-06/D-08 backfill-don't-reject posture
  ([[feedback_farmer_is_reality_source_of_truth]]).
- **`2026-05-24-eval-strain-regex-rejects-ca3-wedge.md`** — strain-code resolver
  rejection class; covered by the curated-14 resolver + POY->KOY fixture (D-08).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Node source-of-truth (faithful-port targets)
- `src/agents/alerter/src/farmos/merge.js` — pure field-merge; name-based identity (D-05)
- `src/agents/alerter/src/farmos/client.js` §13-196 — session-cookie + CSRF, never-throws client
- `src/agents/alerter/src/farmos/assets.js` §48-61 — `findAssetByName` (`filter[name][value]`)
- `src/agents/alerter/src/farmos/logs.js` §42-48, §155-209 — `LOG_STABLE_KEYS`, upsert-by-stable-key (seeding only)
- `src/agents/alerter/src/farmos/files.js` §56-115 — `uploadFieldAttachment` (field-scoped octet-stream)
- `src/agents/alerter/src/farmos/commit-db.js` §47-60 — Node commit-watchdog SELECT (origin-guard target)
- `src/agents/alerter/src/farmos/commits/commit-router.js` §1-70 + `commit-seeding.js` §1-93 — router + per-type handler
- `src/agents/alerter/src/farmos/commits/normalize.js` — extractor->commit shape normalizer

### Python reuse (port scaffolding)
- `capture/transcribe_client.py` §28-92 — httpx never-throws factory pattern
- `gate/classifier.py` §74-100 — async httpx POST pattern
- `confirm/confirm_repo.py` — never-throws DAO + rowcount guards; commit-trigger marker (61-CONTEXT.md §16-20)
- `confirm/strain_ask_back.py` §88-111 — curated-14 resolver
- `persistence/migrations.py` §150-217 — `signal_draft` schema (origin column lands here)
- `persistence/pool.py`, `boot.py` — pool + `asyncio.create_task` wiring

### Phase / schema docs
- `.planning/phases/62-farmos-write-path/62-SCOUT.md` — the pre-discuss scout map
- `.planning/phases/61-confirm-loop/61-CONTEXT.md` §16-20 — commit-trigger marker contract
- `.planning/ROADMAP.md` §398-414 — Phase 62 goal + SCs (NOTE SC2 wording reconciliation, D-05)
- `.planning/REQUIREMENTS.md` — FWR-01..04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- httpx never-throws client factory: `capture/transcribe_client.py:28-92` — clone for farmOS client
- Async POST + JSON parse: `gate/classifier.py:74-100`
- Never-throws DAO + rowcount guards: `confirm/confirm_repo.py`
- Curated-14 resolver (exact-match, rejects unknown): `confirm/strain_ask_back.py:88-111`

### Established Patterns
- Faithful-port discipline: the Node `farmos/` tree is source of truth; replicate
  field semantics byte-for-byte (merge rules, stable keys, JSON:API content type).
- Phase 57-60 boot wiring: shared client + `asyncio.create_task` background loop in `boot.py`.
- Fail-open DAOs mask schema bugs ([[feedback_fail_open_masks_schema_bugs]]) — verify >=1
  real asset/log row writes after the upsert change (the in-phase dev live-fire, D-04).

### Integration Points
- Phase 61 emits `confirmed` + commit-trigger marker -> Phase 62 commit-watchdog consumes it.
- New `origin` column on `signal_draft` (`migrations.py`) — shared with the live Node watchdog.
- Shared TimescaleDB is the coexistence surface; D-02 sequencing is the safety boundary.

</code_context>

<specifics>
## Specific Ideas

- Image upload uses the field-scoped route `POST /api/asset/{type}/{uuid}/image`
  (octet-stream + `Content-Disposition: file; filename=...`), single call that
  creates+links. The `image` field — NOT `file` (jpg rejected 422), NOT
  `POST /api/file/file` (415). [[project_farmos_image_upload_needs_field_scoped_route]]
- Draft-tracking marker appended to notes: `mushy:draft:{draftId}`.
- dev `:18080` vs prod `:8082`, both API-named "Mossrock"
  ([[reference_farmos_dev_vs_prod_on_elder_plops]]).

</specifics>

<deferred>
## Deferred Ideas

- **Node-side coexistence beyond the watchdog clause** (broader dev/prod isolation,
  e.g. permanent :5434 split for all validation) — Phase 64 parity gate already
  mandates :5434 isolation; no extra work needed in 62.
- **CSV ask-back conversational resolution flow** (farmer replies to a fidelity
  ask-back and the draft auto-resolves) — Phase 62 holds + asks; the reply-handling
  FSM extension, if any, is a follow-on.

### Reviewed Todos (not folded)
- `2026-05-14-port-alerter-to-farm-agent-python.md` — the umbrella v1.12 port todo;
  tracked at milestone level, not folded into this single phase.
- `2026-05-24-mc-vpd-display-and-control-buttons.md` — Mission Control UI work; out of
  scope (matched only on "live/write/path" keywords).

</deferred>

---

*Phase: 62-farmos-write-path*
*Context gathered: 2026-06-28*
