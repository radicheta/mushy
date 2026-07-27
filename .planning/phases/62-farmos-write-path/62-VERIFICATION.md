---
phase: 62-farmos-write-path
verified: 2026-06-29T00:16:34Z
status: passed
score: 5/5
overrides_applied: 0
---

# Phase 62: farmOS Write Path -- Verification Report

**Phase Goal:** The origin guard is committed first (preventing the shared-Timescale prod-leak), then confirmed drafts commit to farmOS via an httpx async client with byte-identical stable-identity upserts, the field-scoped image route, and the v1.11 CSV fidelity gate preserved.
**Verified:** 2026-06-29T00:16:34Z
**Status:** PASSED
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Origin guard committed first; a Python validation process cannot have its `signal_draft` rows drained by the live Node commit-watchdog (structural prevention) | VERIFIED | `migrations.py:358` adds `origin text NOT NULL DEFAULT 'node'`; `commit-db.js:59` has `AND origin != 'python'`; `commit_db.py` has 16 `origin='python'` stamps in SELECT + all write helpers; prod Node alerter confirmed running with guard (`62-01-SUMMARY.md` image `aa3da7d7d913`, `[commit-watchdog] started` log line) |
| 2 | Cross-language fixture proves byte-identical merge; running the Python commit path twice against dev farmOS produces 0 duplicate assets | VERIFIED | `merge_golden.json` has 8 cases (existing/incoming/merged/conflicts); live-fire run `lf_20260629_000934`: Run A created asset `f64fffa7-cf1f-4d31-b59f-76aedc018836`, Run B `asset_ids=[]`; name-filter re-query count == 1; test suite 645 passed |
| 3 | Confirmed seeding draft with attached image uploads via `POST /api/asset/{type}/{uuid}/image`; image appears on the `image` field in dev farmOS | VERIFIED | `files.py` posts to `{collection}/{uuid}/{field}` via `post_binary`; `/api/file/file` is absent from all commits; live-fire paper trail records `file_id ff60a5a3-4a26-4af9-8fa1-1d63309be4d0`; `commit_seeding_session.py:4` occurrences of `/api/asset/group`; independent JSON:API re-query confirmed `image` relationship present |
| 4 | CSV fidelity gate holds drafts as `fidelity_cross_check_unverified`; not committed; POY never silently committed as KOY | VERIFIED | `fidelity_gate.py` returns `hold_status='fidelity_cross_check_unverified'` + `ask_back_msg` on strain_mismatch; `commit_watchdog.py` calls `check_fidelity` before any router call (13 occurrences of `fidelity`); live-fire block `LF_20260629_000934_MISMATCH` held with `fidelity_cross_check_unverified`, 0 assets created |
| 5 | Curated-14-code strain resolver rejects unknown codes; POY->KOY silent-misattribution class is regression-guarded | VERIFIED | `strain_ask_back.py` exact-match resolver; `test_strain_poy_koy_regression.py` asserts `resolve_strain("POY", CURATED_14)["known"] is False` and `["code"] == "POY"`; test passes in 645-pass suite |

**Score:** 5/5 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/farm-agent/farm_agent/persistence/migrations.py` | origin column + Phase 40 commit columns | VERIFIED | `ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'` at line 358; all 6 Phase 40 columns (farmos_response, committed_at, commit_failed_reason, commit_attempt_count, committed_at_attempt, outcome_ack_sent_at); idx_signal_draft_status_confirmed index |
| `src/agents/alerter/src/farmos/commit-db.js` | Node watchdog origin-guarded | VERIFIED | `AND origin != 'python'` at line 59 (2 occurrences incl. comment); Node test asserts `origin='python'` row excluded |
| `src/farm-agent/farm_agent/farmos/client.py` | httpx farmOS client -- auth, retry, never-throws, octet-stream | VERIFIED | 331 lines; `user/login` x2, `application/octet-stream` x1, `X-CSRF-Token` x2; min_lines=120 requirement met |
| `src/farm-agent/farm_agent/farmos/merge.py` | `merge_asset_fields` + `IdentityMutationError` + name-based identity | VERIFIED | `def merge_asset_fields` at line 61; `class IdentityMutationError` at line 25; no `createHash`/hex-digest (name-based per D-05); 147 lines |
| `src/farm-agent/tests/fixtures/farmos/merge_golden.json` | Cross-language golden fixture >=6 cases | VERIFIED | 8 cases; keys: id/description/existing/incoming/merged/conflicts |
| `src/farm-agent/farm_agent/farmos/fidelity_gate.py` | `check_fidelity` + `render_fidelity_ask_back` + `load_fidelity_csv` | VERIFIED | All 3 functions present; `fidelity_cross_check_unverified` appears 5 times; `ask_back_msg` in return; `load_fidelity_csv` returns `[]` on missing file (D-07) |
| `src/farm-agent/tests/test_strain_poy_koy_regression.py` | POY->KOY regression guard | VERIFIED | Exists; 19 occurrences of `POY`; asserts `known=False` and `code='POY'` |
| `src/farm-agent/farm_agent/tenancy/tenant.py` | `fidelity_csv_path` field | VERIFIED | 3 occurrences (dataclass field + load assignment + resolver) |
| `src/farm-agent/farm_agent/farmos/qr.py` | `resolve_qr` + `bind_qr_on_create` | VERIFIED | `id_tag` 16 occurrences; `filter[id_tag.id][value]` present |
| `src/farm-agent/farm_agent/farmos/files.py` | `upload_field_attachment` field-scoped image upload | VERIFIED | `def upload_field_attachment` x5; `post_binary` x2; url pattern `{collection}/{uuid}/{field}` |
| `src/farm-agent/farm_agent/farmos/logs.py` | `create_log` + `upsert_log` + `LOG_STABLE_KEYS` | VERIFIED | `def upsert_log` x1; `mushy:draft:` x2; `filter[asset.id][value]` x1 |
| `src/farm-agent/farm_agent/farmos/assets.py` | `find_asset_by_name` + `upsert_fungi_asset` + LRU cache | VERIFIED | `def upsert_fungi_asset` x1; `filter[name][value]` x1; `mushy:draft:` x1 |
| `src/farm-agent/farm_agent/farmos/commits/normalize.py` | `normalize(draft)` -- pure, idempotent | VERIFIED | `def normalize` x1 |
| `src/farm-agent/farm_agent/farmos/commits/commit_router.py` | DISPATCH over all 6 log types | VERIFIED | `DISPATCH` dict: seeding/activity/input/observation/harvest/seeding_session; `commit()` guard + normalize + envelope |
| `src/farm-agent/farm_agent/farmos/commits/commit_seeding_session.py` | seeding_session handler + image attach + rollback | VERIFIED | `def commit_seeding_session` x1; `/api/asset/group` x4 |
| `src/farm-agent/farm_agent/farmos/commit_db.py` | origin-guarded Python commit-lifecycle DAO | VERIFIED | `origin='python'` x16 in find SELECT + acquire + mark_committed + requeue + mark_fidelity_hold |
| `src/farm-agent/farm_agent/farmos/commit_watchdog.py` | `commit_watchdog_loop` + `tick_once` + fidelity pre-gate | VERIFIED | `check_fidelity` x1; `fidelity` x13; never-throws loop present |
| `src/farm-agent/farm_agent/boot.py` | shared farmOS client + commit_watchdog task wiring | VERIFIED | `commit_watchdog_loop` x2 (import + create_task); `create_farmos_client` called; gated on `config.farmos_integration` |
| `src/farm-agent/tests/test_farmos_live_fire.py` | FWR_LIVE_FIRE opt-in live-fire test | VERIFIED | `FWR_LIVE_FIRE` x4; `@pytest.mark.skipif` guard; paper trail at `live-fire-trails/lf_20260629_000934.jsonl` |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Python commit_db | signal_draft SELECT | `WHERE status='confirmed' AND origin='python'` | VERIFIED | `commit_db.py:43` captures both clauses |
| Node findConfirmedCandidates | signal_draft | `AND origin != 'python'` | VERIFIED | `commit-db.js:59`; Node test asserts origin='python' rows excluded |
| commit_watchdog tick | fidelity_gate.check_fidelity | pre-commit gate hold | VERIFIED | `commit_watchdog.py` calls `check_fidelity` before `commit_router.commit`; fidelity mismatch transitions to `fidelity_cross_check_unverified` without touching the router |
| boot.py | commit_watchdog_loop | `asyncio.create_task` | VERIFIED | `boot.py:116-117`; gated on `config.farmos_integration`; cancel+await on shutdown |
| files.upload_field_attachment | farmOS POST {collection}/{uuid}/image | `client post_binary octet-stream` | VERIFIED | URL pattern confirmed; `/api/file/file` absent from all commit handlers (grep returned 0) |
| assets.upsert_fungi_asset | merge.merge_asset_fields | GET existing -> merge -> PATCH-or-noop | VERIFIED | `merge_asset_fields` imported and called in `assets.py` |
| commit_router.commit | commit_seeding/activity/input/observation/harvest/seeding_session | DISPATCH table + normalize() | VERIFIED | All 6 types in DISPATCH; normalize applied before dispatch |
| test_farmos_merge | merge_golden.json | `assert merge_asset_fields(existing, incoming).merged == golden.expected` | VERIFIED | 8 cross-language golden cases; test passes |

---

## Data-Flow Trace (Level 4)

The write path is not a renderer -- it is a commit pipeline. Data flow was proven live rather than through static analysis:

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `commit_db.find_confirmed_candidates` | signal_draft rows | psycopg3 SELECT WHERE status='confirmed' AND origin='python' | Yes -- live Timescale query | FLOWING |
| `commit_router.commit` | draft dict | `find_confirmed_candidates` -> `acquire_commit_lock` | Yes -- real draft data | FLOWING |
| `assets.upsert_fungi_asset` | asset JSON:API payload | farmOS GET (existing) + merge | Yes -- live-fire confirmed asset created | FLOWING |
| `files.upload_field_attachment` | image bytes | local file path read via `Path.read_bytes()` | Yes -- file_id returned and confirmed in live-fire | FLOWING |
| `fidelity_gate.check_fidelity` | CSV rows | `load_fidelity_csv(config.fidelity_csv_path)` | Yes -- fixture CSV loads; `[]` on missing (non-fatal) | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite passes (non-live-fire) | `cd src/farm-agent && uv run pytest -q` | 645 passed, 36 skipped in 12.92s | PASS |
| origin column in migrations | `grep -c "ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'" migrations.py` | 1 | PASS |
| Node SELECT origin-guarded | `grep -c "AND origin != 'python'" commit-db.js` | 2 | PASS |
| No legacy /api/file/file route | `grep -rc "/api/file/file" src/farm-agent/farm_agent/farmos/commits/` | 0 | PASS |
| DISPATCH covers all 6 log types | Inspected commit_router.py DISPATCH dict | seeding/activity/input/observation/harvest/seeding_session | PASS |
| commit_db origin stamps | `grep -c "origin='python'" commit_db.py` | 16 | PASS |
| Live-fire paper trail exists | `ls src/farm-agent/live-fire-trails/lf_20260629_000934.jsonl` | file present; contains run_a_asset_id, file_id, fidelity_hold_status | PASS |
| merge_golden.json case count | `python3 -c "import json; print(len(json.load(open('...'))))"` | 8 (>= 6 required) | PASS |

---

## Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| FWR-01 | 62-02, 62-05, 62-08, 62-09, 62-10, 62-11, 62-12 | httpx client, all log types, field-scoped image upload | SATISFIED | client.py 331 lines; all 6 handler files present; `/api/asset/{type}/{uuid}/image` route used; legacy route absent |
| FWR-02 | 62-03, 62-06, 62-07, 62-12 | Byte-identical upsert-by-stable-identity; 0 dupes on second run | SATISFIED | merge_golden.json 8 cases; live-fire 0 dupes; LOG_STABLE_KEYS seeding stable-key; LRU name caches |
| FWR-03 | 62-04, 62-11, 62-12 | Curated-14 + POY->KOY regression + CSV fidelity gate active in commit path | SATISFIED | fidelity_gate.py + test_strain_poy_koy_regression.py; gate wired before router in watchdog; live-fire fidelity hold confirmed |
| FWR-04 | 62-01, 62-10, 62-11 | Origin guard -- Python validation process never drained by live Node watchdog | SATISFIED | schema column + Node SELECT clause + Python DAO stamps + boot wiring; prod deploy confirmed |

All 4 phase requirements fully satisfied. No orphaned requirements.

---

## Decisions D-01..D-08 Direct Verification

Per phase instructions, these were verified directly in code (the decision-coverage gate was overridden during planning).

| Decision | Verification | Status |
|----------|-------------|--------|
| D-01: origin column + Node-watchdog patch | `migrations.py:358` has `origin text NOT NULL DEFAULT 'node'`; `commit-db.js:59` has `AND origin != 'python'` | VERIFIED |
| D-02: hard sequencing -- patched Node alerter redeployed before any Python confirmed-write | `62-01-SUMMARY.md` confirms Task 3 checkpoint executed: prod container `aa3da7d7d913` running with guard clause; `[commit-watchdog] started` log confirmed | VERIFIED |
| D-03: legacy/Node rows default to 'node' via column DEFAULT | `ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'` -- existing rows get DEFAULT 'node'; no backfill needed | VERIFIED |
| D-04: in-phase live-fire against dev :18080 (not deferred) | `test_farmos_live_fire.py` exists; paper trail `lf_20260629_000934.jsonl` present; run completed 2026-06-29 | VERIFIED |
| D-05: stable identity is name-based, not hex digest | `merge.py` has `IdentityMutationError` on name change; no `createHash`/hexdigest in farmos/; `findAssetByName` via `filter[name][value]` | VERIFIED |
| D-06: disagreement holds as fidelity_cross_check_unverified AND emits ask-back | `fidelity_gate.py:156-157` returns `hold_status='fidelity_cross_check_unverified'` + `ask_back_msg`; `commit_watchdog.py` transitions before any router call | VERIFIED |
| D-07: CSV non-authoritative; missing CSV returns [] (non-fatal) | `fidelity_gate.py:49,56,59` returns `[]` on missing/malformed CSV; absent block is a pass-through | VERIFIED |
| D-08: named POY->KOY regression fixture | `test_strain_poy_koy_regression.py` asserts `resolve_strain("POY", CURATED_14)["known"] is False` and `["code"] == "POY"`; passes in 645-pass suite | VERIFIED |

---

## Anti-Patterns Found

No blockers found.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `fidelity_gate.py` | 49, 56, 59 | `return []` | Info | Intentional non-fatal: `load_fidelity_csv` returns `[]` on missing/malformed CSV per D-07; absent rows pass through commit path |
| `commit_db.py` | 122, 127 | `return []` | Info | Intentional never-throws DAO: finder queries return `[]` on DB error, mirroring `confirm_repo.py` pattern |

No `TBD`, `FIXME`, or `XXX` markers found in any Phase 62 modified files.
No `return null` / `{}` / placeholder patterns in commit or farmos module files.
The `return []` occurrences above are documented never-throws fail-safe patterns, not stubs -- they are the D-07 / never-throws DAO contract.

---

## Known Follow-On (Not a Blocker)

**Config drift: `FARMOS_USERNAME` in `tenants/mossrock/config.yaml` says `farmos_agent` but working dev account is `mushy-bot`.**

Found and documented in `62-12-SUMMARY.md`. The write-path code is correct (`client.py` auth is a faithful port). The stale config field will cause auth 400 on a real alerter-py boot against farmOS until reconciled. Recommended follow-on: update `FARMOS_USERNAME` for mossrock tenant (and verify prod `:8082` account name). This is a config-management follow-on, not a code defect and not a gate on Phase 62 delivery.

---

## Human Verification Required

None. The in-phase live-fire (Plan 12) produced independent API corroboration for all three SCs (SC2/SC3/SC4):

- **SC2:** Name-filter re-query confirmed exactly 1 asset after both runs (Run B `asset_ids=[]`).
- **SC3:** `image` relationship present in JSON:API response with `file_id ff60a5a3-4a26-4af9-8fa1-1d63309be4d0`. Visual UI confirmation was performed in-session per operator context.
- **SC4:** Mismatch block `LF_20260629_000934_MISMATCH` returned `fidelity_hold_status='fidelity_cross_check_unverified'`; name-filter count == 0.

The plan's `checkpoint:human-verify` (Task 2 of Plan 12) was completed in-session with independent API corroboration. Per operator context note provided at verification time: "The dev :18080 live-fire (62-12) PASSED: SC2 (0-dup upsert), SC3 (image on image field), SC4 (fidelity hold) proven live and independently API-corroborated."

---

## Gaps Summary

No gaps. All 5 roadmap success criteria verified. All 4 FWR requirements satisfied. All 8 D-id decisions implemented directly in code. Test suite 645 passed, 36 skipped (live-fire skips without creds -- expected and correct). The phase goal is fully achieved.

---

_Verified: 2026-06-29T00:16:34Z_
_Verifier: Claude (gsd-verifier)_
