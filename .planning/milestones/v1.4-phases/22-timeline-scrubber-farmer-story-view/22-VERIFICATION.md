---
phase: 22-timeline-scrubber-farmer-story-view
verified: 2026-04-19T18:20:00Z
status: passed
score: 11/11 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
---

# Phase 22: Timeline scrubber + farmer story view — Verification Report

**Phase Goal:** Farmer can scrub hours/days of footage with sensor overlays on a phone — **mushy-side scope = data surface only** (D-01). Delivers `/camera/frame` + burnt-in snapshot sidecar + CLAUDE-SYNC handoff to Zoy/farmOS for the UI.

**Verified:** 2026-04-19T18:20:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Bridge container rebuilt with jimp + new routes + burnt mount, running on elder-plops | ✓ VERIFIED | `docker ps`: `mushy-bridge-1 Up 9 minutes mushy-bridge`; image sha256 `c75342dd…ad3e3f` per 22-04 SUMMARY |
| 2 | `/data/snapshots-burnt/fc1/<today>/` contains burnt JPEGs produced post-rebuild | ✓ VERIFIED | 2 burnt files dated 18:14 and 18:19 UTC today (51214 + 50603 bytes); raw twin present at each timestamp |
| 3 | GET `/camera/frame?at=<recent>&camera_id=fc1` returns 200 `image/jpeg` with burnt overlay | ✓ VERIFIED | Live curl: 200, 50603 B, `Content-Type: image/jpeg`, `Cache-Control: public, max-age=3600`, `X-Captured-At: 2026-04-19T18:19:19.920Z`, `file` confirms JPEG 640×480 |
| 4 | `?raw=true` returns 200 image/jpeg from raw tree (distinct from burnt) | ✓ VERIFIED | Live curl: 200, 29578 B; sha256 `fa185bed…` differs from burnt sha256 `851135d4…` — overlay bytes are real |
| 5 | Out-of-tolerance-window returns 404 | ✓ VERIFIED | `at=2000-01-01T00:00:00Z` → 404 |
| 6 | Missing/invalid params return 400; wrong camera_id returns 400 | ✓ VERIFIED | no-at → 400; `at=not-a-date` → 400; `camera_id=evil` → 400 |
| 7 | Burnt bar renders null sensor values as `—` (gap-over-noise, D-03) | ✓ VERIFIED | burn_bar.js `fmtNum`/`fmtHum` return `'—'` for null/undefined/NaN; 2 dedicated unit tests; 54/54 jest suite passes |
| 8 | DB schema unchanged — `snapshots.file_path` still stores RAW path | ✓ VERIFIED | `grep -c "CREATE TABLE IF NOT EXISTS snapshots"` = 1; INSERT statement byte-identical (SUMMARY 22-02 grep receipts); `/camera/history` response unchanged (11 items in last hour, Phase 21 regression-free) |
| 9 | Raw write + DB insert never blocked by burnt write failure | ✓ VERIFIED | Burnt write inside fire-and-forget IIFE with internal try/catch; `rawBuf = latestFrame` pinned before async; bridge logs clean of any `[camera/burnt] write failed` / `burn failed` in last 15 min |
| 10 | `runPrune` mirror-deletes burnt twin alongside raw | ✓ VERIFIED | `retention.js` has `rawDir`/`burntDir` params with startsWith-guarded path swap; 3 new retention tests (happy-path, ENOENT non-fatal, back-compat); `index.js:717` passes both dirs |
| 11 | CLAUDE-SYNC Phase 22 entry documents the as-shipped contract for Zoy | ✓ VERIFIED | `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` has 9 `/camera/frame` references + `## 2026-04-19 — as-shipped addendum` signed `— radicheta-side Claude`; committed as `933ea85` in farmos repo |

**Score:** 11/11 truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/mission-control/bridge/package.json` | jimp dep present | ✓ VERIFIED | `"jimp": "^1.6.1"` present |
| `docker-compose.yml` | SNAPSHOT_BURNT_DIR env + burnt mount | ✓ VERIFIED | L24 env, L32 mount |
| `docker-compose.override.yml` | burnt mount for host-networked bridge | ✓ VERIFIED | L16 mount |
| `src/mission-control/bridge/src/burn_bar.js` | Pure formatBarText + burnBar | ✓ VERIFIED | 2279 bytes; exports formatBarText, burnBar, fmtNum, fmtHum; uses en-dash for nulls |
| `src/mission-control/bridge/src/frame_validate.js` | validateFrameParams | ✓ VERIFIED | 949 bytes; strict `raw === 'true'`; allowlist camera_id; no file_path pass-through |
| `src/mission-control/bridge/src/index.js` | SNAPSHOT_BURNT_DIR + saveSnapshot burn wiring + /camera/frame route | ✓ VERIFIED | imports L11–12, env L68–70, FRAME_TOLERANCE_MS L89, saveSnapshot burnt IIFE L165+, route L449 |
| `src/mission-control/bridge/src/retention.js` | mirror-delete burnt twin | ✓ VERIFIED | rawDir/burntDir params + startsWith swap; 12 retention tests pass |
| `test/burn_bar.test.js` + `test/frame_validate.test.js` | Unit tests pass | ✓ VERIFIED | 8 + 10 tests, all green in 54/54 suite |
| `/data/snapshots-burnt/fc1/<today>/` | burnt JPEGs produced live | ✓ VERIFIED | 18:14 + 18:19 UTC files present, size delta +21 KB from overlay |
| `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` | Phase 22 entry documenting contract | ✓ VERIFIED | 9 `/camera/frame` refs; as-shipped addendum signed; farmos commit 933ea85 |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `saveSnapshot()` | `burnBar() + fs.writeFile(burntPath)` | fire-and-forget IIFE after raw write | ✓ WIRED | Code present at index.js L165+; live burnt files appearing every 5-min cycle |
| `burn_bar.js` | `latestTelemetry` cache | pure function; index.js reads cache, passes values in | ✓ WIRED | index.js L~171 reads `latestTelemetry.humidity?.value` etc. and passes to `formatBarText` |
| `GET /camera/frame` | snapshots DB | closest-at-or-before pool.query bounded by FRAME_TOLERANCE_MS | ✓ WIRED | Live 200 returns with `X-Captured-At` header reflecting actual captured_at |
| `GET /camera/frame` | disk JPEG (burnt or raw) | `fs.readFile(srcPath)` after path-prefix swap | ✓ WIRED | Live curl returns valid JPEG bytes matching on-disk file sizes |
| burnt-path derivation | `SNAPSHOT_BURNT_DIR` env | `row.file_path.replace(SNAPSHOT_DIR, SNAPSHOT_BURNT_DIR)` with startsWith guard | ✓ WIRED | Burnt curl response sha256 distinct from raw — confirms burnt tree is actually read |
| `runPrune()` | burnt twin unlink | path swap mirror-delete | ✓ WIRED | rawDir/burntDir wired through index.js:717 prunerArgs; retention tests cover happy-path + ENOENT |
| elder-plops bridge container | `/data/snapshots-burnt/fc1` | live docker bind-mount | ✓ WIRED | `docker inspect` confirms mount + env; live burnt files writing |
| farmOS/Zoy repo | `/camera/frame` contract | CLAUDE-SYNC.md entry | ✓ WIRED | 9 references + addendum; farmos repo commit 933ea85 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `/camera/frame` burnt response | JPEG bytes from `/data/snapshots-burnt/.../*.jpg` | bridge `saveSnapshot` writes every 5 min | ROS camera topic → latestFrame → jimp burn → disk; live file sizes 50603 B, 51214 B | ✓ FLOWING |
| `/camera/frame` raw response | JPEG bytes from `/data/snapshots/.../*.jpg` | Phase 21 saveSnapshot raw path | ROS → disk, unchanged from Phase 21; live 29578 B, 30034 B | ✓ FLOWING |
| burn_bar overlay text | `latestTelemetry.{humidity,temperature,co2,humidifier}` | ROS subscriptions populated by Phase 18 | SUMMARY 22-04 reports "all fields populated with real values" on sample frame: `RH 85.6% · T 22.3°C · CO₂ 482.0ppm · HUM ON` | ✓ FLOWING |
| `X-Captured-At` header | `row.captured_at` from DB | TimescaleDB snapshots hypertable | Live header: `2026-04-19T18:19:19.920Z` matches actual file mtime | ✓ FLOWING |

All data surfaces deliver real, non-static data end-to-end.

### Behavioral Spot-Checks

| # | Behavior | Command | Result | Status |
|---|---|---|---|---|
| 1 | Missing at → 400 | `curl -w '%{http_code}' '…/camera/frame?camera_id=fc1'` | `400` | ✓ PASS |
| 2 | Invalid at → 400 | `?at=not-a-date&camera_id=fc1` | `400` | ✓ PASS |
| 3 | Wrong camera_id → 400 | `?at=<now>&camera_id=evil` | `400` | ✓ PASS |
| 4 | Out-of-window → 404 | `?at=2000-01-01T00:00:00Z&camera_id=fc1` | `404` | ✓ PASS |
| 5 | Recent burnt default → 200 JPEG | `?at=<now Z>&camera_id=fc1` | `200`, 50603 B, `image/jpeg`, valid JPEG 640×480, X-Captured-At present | ✓ PASS |
| 6 | Recent raw → 200 distinct JPEG | `?at=<now Z>&camera_id=fc1&raw=true` | `200`, 29578 B, distinct sha256 from burnt | ✓ PASS |
| 7 | /camera/history regression | `?from=1h-ago&to=now` | 200 JSON, 11 items, matches Phase 21 shape | ✓ PASS |
| 8 | Bridge logs clean | `docker logs --since 15m \| grep error\|fail` | empty | ✓ PASS |
| 9 | Bridge jest suite | `npm test` | 54/54 passed (5 suites) | ✓ PASS |
| 10 | On-disk raw/burnt parity | `ls /data/snapshots{,-burnt}/fc1/<today>/` | both have 18:14 + 18:19 UTC entries with identical filenames | ✓ PASS |

### Scope-Out Compliance

Context declares these out-of-scope; verified they stayed out:

| Out-of-scope item | Kept out? | Evidence |
|---|---|---|
| Scrubber UI / slider / jump buttons (farmOS-side) | ✓ | `grep -r "scrubber\|story-view\|farmer/story"` in bridge/src only finds comments referencing farmOS-side consumer, no UI code |
| Pi-side `fc_camera` burn-in (D-05 rejected) | ✓ | `git log --since 2026-04-19 -- src/chambers/` shows no commits |
| Server-side join `/camera/story?from=&to=` (D-04 rejected) | ✓ | No such route in index.js |
| Multi-chamber generalization beyond existing `camera_id` param | ✓ | Only `fc1` allowlisted in validateFrameParams; deferred to 999.6 |
| Retroactive burn-in of pre-phase snapshots | ✓ | Burnt tree starts 2026-04-19 18:14 UTC (deploy-forward only); older raw frames still raw-only |
| `src/docker-compose.yml` edits (deprecated per CLAUDE.md) | ✓ | Not in this phase's file_modified lists; untouched |
| Time-lapse (Phase 23), ML vision (Phase 24) | ✓ | No ffmpeg/ComfyUI wiring in this phase |

### Requirements Coverage

PLAN frontmatter `requirements: []` for all four plans — phase has no explicit REQUIREMENTS.md IDs. Coverage is goal-level (phase 22 ROADMAP entry), which is reinterpreted in CONTEXT D-01 as data-surface-only and fully satisfied above.

### Anti-Patterns Found

None blocking. Spot-scan of modified files:

| Concern | Finding |
|---|---|
| TODO/FIXME in new code | none in burn_bar.js, frame_validate.js, or new index.js/retention.js blocks |
| Empty-return stubs | none; every response path returns real data or a specific error |
| Hardcoded empty data | none; `[]`/`{}` defaults only in test fixtures |
| Console.log-only handlers | Errors log AND route to correct HTTP status; no "log and pretend it worked" |
| Path traversal | Explicitly mitigated: `startsWith(SNAPSHOT_DIR)` guard on burnt swap; no `file_path` query param accepted |

### Human Verification Required

None blocking. Per user's `feedback_verify_user_surface_before_uat` directive, the visual check of the burnt overlay was performed by the executor in 22-04 (sample at `/tmp/phase22-burnt-sample.jpg`, approved). The farmer UAT Signal ping is intentionally deferred because **the farmer does not own this UI** — it is a data surface for Zoy/farmOS to consume. Post-phase, once Zoy lands the scrubber UI, a joint UAT will be the appropriate checkpoint.

### Gaps Summary

No gaps. Phase achieved its goal as scoped:

- Data surface (`/camera/frame` + burnt sidecar) is live and serving real frames with real sensor overlays.
- All seven scope-out items stayed out.
- Phase 21 `/camera/history` is regression-free.
- Phase 24 `?raw=true` escape hatch works — ML training data is not poisoned.
- Zoy-side handoff landed in CLAUDE-SYNC with as-shipped specifics (tolerance window, headers, error shapes, URL-encoding gotcha).
- Gap-over-noise rule honored (null sensors render as `—`).
- D-03 schema preservation confirmed (DB stores raw path; burnt twin derived by path swap).

Phase ready for `/gsd:complete-phase 22`.

---

*Verified: 2026-04-19T18:20:00Z*
*Verifier: Claude (gsd-verifier)*
