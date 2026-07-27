# Phase 62 — farmOS Write Path: Scout Findings (pre-discuss)

**Captured:** 2026-06-28 (autonomous run paused here for context budget; NOT yet discussed/planned)
**Plane:** MUSHY-2 (In Progress). Reqs FWR-01..04. Planner model: opus.
**Next step on resume:** run smart-discuss using this scout → write 62-CONTEXT.md → research → pattern-map → plan → checker → execute. (Same rhythm as phases 58-61.)

This is the decision-oriented map from the Explore scout. The Node `src/agents/alerter/src/farmos/`
tree is the source of truth (faithful port).

## 1. Origin guard (prod-leak prevention) — FIRST COMMIT
- Leak: Node commit-watchdog `src/agents/alerter/src/farmos/commit-db.js:47-60` (`SELECT * FROM signal_draft WHERE status='confirmed' ORDER BY confirmed_at ASC LIMIT $1`), polls ~30s (COMMIT_WATCHDOG_INTERVAL_MS=30000), points at PROD :8082. A Python process flipping drafts to `confirmed` in the shared TimescaleDB gets them drained to prod.
- No `origin`/`created_by` column exists yet on signal_draft (migrations.py:150-217).
- Fix (first commit): add `origin text NOT NULL DEFAULT 'node'` (idempotent ADD COLUMN IF NOT EXISTS); Python writes set `origin='python'`; Node watchdog SELECT must become `... AND origin != 'python'` (Node-side change — v1.13 backlog candidate). If the Node watchdog can't be changed in this phase, the guard must be structural another way (separate status, or isolated :5434 DB).
- Memories: [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]], [[project_v113_watchdog_origin_guard_candidate]].

## 2. farmOS commit path + stable-identity upsert (BYTE-IDENTICAL)
- Client: `farmos/client.js:13-196` — session-cookie + X-CSRF-Token (`POST /user/login?_format=json`); dev :18080 / prod :8082 via FARMOS_URL; never-throws `{ok,status,body,latencyMs}`, 10s timeout + 3x backoff (1s/4s/16s). Port as httpx.AsyncClient (Phase 57-60 pattern).
- Stable identity is NOT a computed hash — it's the farmOS **name field lookup**: `findAssetByName()` `assets.js:48-61` via `/api/asset/fungi?filter[name][value]=<enc>`; seeding log stable key `type='log--seeding' AND asset.id==blockId` (`logs.js:45-48`). Python must replicate name normalization + the `filter[name][value]` query + response parsing EXACTLY so a 2nd run creates 0 duplicates. (NOTE: the ROADMAP SC says "same stable-identity hex digest from Node merge.js and Python merge.py" — but the scout found Node uses name-lookup, not a digest. RESOLVE in discuss: either there IS a digest in merge.js to port, or the SC wording needs reconciling to "name-based stable identity". Re-read merge.js:1-133 carefully.)
- merge.js:1-133 fields: name (identity); fungi_type/fungi_xing (scalar singleton rel); parent/qr_codes/farm_id_tag (array set-union); status (scalar); notes (split-dedup-join on `\n---\n`). Draft-tracking: append `mushy:draft:{draftId}` to notes.
- Endpoints: assets `POST/PATCH /api/asset/fungi/{uuid}`; logs `POST/PATCH /api/log/{type}/{uuid}`; JSON:API (`application/vnd.api+json`).
- Commit router: `farmos/commits/commit-router.js:1-70`; per-type `commit-seeding.js:1-93` etc.

## 3. Field-scoped image upload
- Broken: `POST /api/file/file` octet-stream → 415 (dev AND prod). Correct: `POST /api/asset/{type}/{uuid}/{field}` octet-stream, single call (creates+links). Photos on `image` field (`file` rejects jpg, 422).
- Node: `files.js:56-115` `uploadFieldAttachment(client, collectionPath, uuid, field, absPath, filename)` → url `${collectionPath}/${uuid}/${field}`, POST octet-stream + `Content-Disposition: file; filename=...`, extract file id (single vs array, lines 61-68).
- Python: create asset → extract uuid → httpx POST content=bytes, header octet-stream, timeout 30s → parse JSON:API id.
- Memory: [[project_farmos_image_upload_needs_field_scoped_route]].

## 4. v1.11 CSV fidelity gate (commit-time blocker)
- A draft whose block name disagrees with the ground-truth CSV is held as `fidelity_cross_check_unverified` (NEW status string, not in schema yet) and NOT committed → prevents POY committed silently as KOY.
- CSV is NOT authoritative — second interpretation of the notebooks ([[project_backfill_csv_is_not_ground_truth]]); ~38% disagreement in the Phase-55 audit ([[project_backfill_extraction_fidelity_38pct_silent_misattribution]]). So on disagreement: FLAG/hold for human review, never silent hard-reject.
- Gate sits in the commit path BEFORE the farmOS call. Open Qs: CSV path (prod vs fixture); load at boot vs fixture; hold vs farmer ask-back.

## 5. Python side
- Reuse: `capture/transcribe_client.py:28-92` (httpx never-throws factory), `gate/classifier.py:74-100` (async POST), `confirm/confirm_repo.py` (never-throws DAO + rowcount guards), `persistence/pool.py`, `boot.py` (asyncio.create_task wiring).
- Phase 61 emits `confirmed` + a commit-trigger marker — THIS phase consumes it (see 61-CONTEXT.md lines 16-20 for the marker contract; confirm exact mechanism in confirm_repo.py).
- Curated-14 resolver already exists: `confirm/strain_ask_back.py:88-111` (exact-match, rejects unknown). Phase 62 needs a named POY→KOY regression fixture.
- To BUILD: farmOS httpx client; commit router; per-type commit handlers; merge module (byte-identical); asset/log primitives (upsert_fungi_asset, find_asset_by_name, upsert_log, upload_field_attachment); CSV fidelity gate; boot wiring (shared httpx client + commit_watchdog_loop task).

## Open design decisions for discuss (the ones to surface to Santi)
1. **Origin-guard mechanism:** `origin` column + Node-watchdog `AND origin!='python'` (needs a Node-side change), vs a new draft status, vs isolated :5434 DB. Which is the structural guard committed first?
2. **Real dev-farmOS (:18080) commit — live-fire or in-phase?** 58/59/60 deferred their real-model runs. Phase 62's upsert/image/fidelity SCs arguably NEED a real dev-farmOS commit. Decide: in-phase live-fire against dev :18080, or hermetic-mock + deferred operator live-fire (consistent with prior phases). NOTE the dev farmOS creds were resolved ([[project_dev_farmos_18080_rejects_prod_bot_creds]] RESOLVED) so a dev live-fire is feasible.
3. **Stable identity = name-lookup vs digest** — reconcile the ROADMAP SC ("hex digest") against the Node reality (name-based). Re-read merge.js.
4. **CSV gate** — CSV source path, boot-load vs fixture, hold vs ask-back.
5. **POY→KOY regression fixture** — name + shape.

## Reference: dev vs prod farmOS — [[reference_farmos_dev_vs_prod_on_elder_plops]] (:18080 dev, :8082 prod, both API-name "Mossrock").
