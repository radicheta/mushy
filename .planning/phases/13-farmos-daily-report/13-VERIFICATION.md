---
phase: 13-farmos-daily-report
verified: 2026-04-13T05:30:00Z
status: gaps_found
score: 2/4 must-haves verified
overrides_applied: 0
gaps:
  - truth: "FC-1 appears as a structure asset in FarmOS with correct name, location, and metadata"
    status: partial
    reason: "FC-1 exists as a structure asset (UUID 3d6cc537) with correct name and active status, but has no location set (Lab 1 / asset 26 not assigned) and no notes/metadata. FMOS-01 requires correct location and metadata."
    artifacts:
      - path: "FarmOS asset/28"
        issue: "location relationship is empty; notes field is None"
    missing:
      - "Set FC-1 location to Lab 1 (asset 26) in FarmOS UI or via API"
      - "Add sensor description notes to FC-1 asset in FarmOS UI"

  - truth: "Once per day a new observation log appears on FC-1 with an attached camera snapshot image"
    status: failed
    reason: "One observation exists ('FC-1 Daily Report 2026-04-12') but has zero attached images. Photo upload is blocked by a FarmOS permissions error (403 Forbidden) — Vikki's account lacks the 'create log' permission required to upload files to /api/log/observation/image."
    artifacts:
      - path: "FarmOS observation 3baf38ce"
        issue: "image relationship has 0 items; no camera snapshot attached"
      - path: "src/farmos-agent/farmos_agent/farmos_client.py"
        issue: "upload_photo() returns None on 403; observation created without image (documented known limitation in 13-02-SUMMARY)"
    missing:
      - "Grant Vikki the 'create log' permission in FarmOS at /admin/people/permissions"
      - "Verify photo attachment after permission is granted"

  - truth: "Observation includes correct avg/min/max humidity, CO2, temp, humidifier duty cycle from TimescaleDB"
    status: failed
    reason: "Observation exists and includes the markdown table, but humidity values are wrong. The bridge stores fc.humidity as percentage (e.g., 94.07 for 94.07%) but report_builder multiplies by 100 assuming decimal fraction input, producing 9407% instead of 94.1%. Live observation shows '9671.0%' for humidity avg. The anomaly flag fires incorrectly as a result. This is a data units mismatch bug confirmed against live TimescaleDB data."
    artifacts:
      - path: "src/farmos-agent/farmos_agent/report_builder.py"
        issue: "Line 17: humidity formatter uses 'lambda avg: f\"{round(avg * 100, 1)}\"' — multiplies by 100 but DB stores humidity already as percentage. Should be 'round(avg, 1)'."
      - path: "src/farmos-agent/farmos_agent/farmos_agent_node.py"
        issue: "execute_report passes raw DB values to build_report_markdown with no unit normalization"
    missing:
      - "Fix report_builder.py line 17: change humidity formatter from 'round(avg * 100, 1)' to 'round(avg, 1)'"
      - "Fix report_builder.py _fmt_metric: change 'round(value * 100, 1)' for fc.humidity to 'round(value, 1)'"
      - "Fix anomaly check in _detect_anomalies: humidity_target should be 82.0 (not 0.82) to match percentage storage, OR normalize in query_daily_summary before returning"
      - "Re-trigger execute_report after fix to produce a corrected observation"
human_verification:
  - test: "Confirm FC-1 location and metadata in FarmOS UI"
    expected: "FC-1 asset at http://10.68.155.50:8082/asset/28 shows Lab 1 as location and includes sensor description in notes field"
    why_human: "FarmOS UI state requires browser verification; JSON:API confirms location is unset"

  - test: "Grant FarmOS upload permission and verify photo attachment"
    expected: "After granting Vikki 'create log' permission at /admin/people/permissions, a manual execute_report() run attaches a JPEG snapshot to the observation"
    why_human: "FarmOS admin action required; cannot be automated without admin credentials"

  - test: "Verify corrected observation after humidity units fix"
    expected: "After fix, daily report shows humidity ~94% (not 9671%), temperature ~17C, CO2 ~476ppm, anomaly flag fires only when genuinely out of range"
    why_human: "Requires code fix + container rebuild + manual execute_report() trigger + FarmOS UI inspection"
---

# Phase 13: FarmOS Daily Report — Verification Report

**Phase Goal:** FC-1 exists as an asset in FarmOS and receives a daily observation log containing a camera snapshot and environment summary
**Verified:** 2026-04-13T05:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | FC-1 appears as structure asset with correct name, location, metadata | PARTIAL | Asset exists (UUID 3d6cc537, name "FC-1", active) but location empty, no notes |
| 2 | Observation log on FC-1 includes attached camera snapshot | FAILED | Observation 3baf38ce exists but has 0 images; upload_photo returns None due to FarmOS 403 |
| 3 | Observation includes correct env summary from TimescaleDB | FAILED | Table present but humidity values are 100x too large (9671% instead of ~96.7%) due to units mismatch |
| 4 | Service runs on elder-plops, survives restart without duplicate entries | VERIFIED | Container mushy-farmos-agent-1 running; duplicate skip logged on second trigger |

**Score:** 2/4 truths verified (SC1 partial, SC2 failed, SC3 failed, SC4 verified)

### Required Artifacts

#### Plan 01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/farmos-agent/farmos_agent/farmos_client.py` | FarmOS session auth + observation CRUD | VERIFIED | All 5 functions present; session-cookie auth, CSRF header, parameterized calls |
| `src/farmos-agent/farmos_agent/telemetry_query.py` | TimescaleDB daily aggregation | VERIFIED | query_daily_summary present; parameterized SQL with %s; ZoneInfo midnight boundary |
| `src/farmos-agent/farmos_agent/report_builder.py` | Markdown summary builder | STUB (data bug) | build_report_markdown present and structurally correct, but humidity units wrong |
| `src/farmos-agent/tests/test_farmos_client.py` | Unit tests for FarmOS client | MISSING | Never committed to HEAD branch; exists only in orphaned commit d725700 |
| `src/farmos-agent/tests/test_telemetry_query.py` | Unit tests for telemetry | MISSING | Never committed to HEAD branch |
| `src/farmos-agent/tests/test_report_builder.py` | Unit tests for report builder | MISSING | Never committed to HEAD branch |

#### Plan 02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/farmos-agent/Dockerfile` | Container image on ros:jazzy-ros-core | VERIFIED | FROM ros:jazzy-ros-core; python3-apscheduler, python3-psycopg2 via apt |
| `src/farmos-agent/farmos_agent/farmos_agent_node.py` | ROS2 lifecycle node + APScheduler | VERIFIED | FarmOSAgent class; CronTrigger(hour=6, minute=0); full execute_report loop |
| `src/farmos-agent/entrypoint.sh` | Container entrypoint | VERIFIED | Sources ROS2, sets PYTHONPATH, runs node |
| `docker-compose.yml` | farmos-agent service definition | VERIFIED | Service with build context, env vars, volume, restart: unless-stopped |
| `src/farmos-agent/package.xml` | ROS2 package manifest | VERIFIED | Exists with farmos_agent name |
| `src/farmos-agent/setup.py` | ROS2 Python package setup | VERIFIED | Exists |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| farmos_client.py | FarmOS /user/login | requests.Session POST | VERIFIED | `session.post(f"{farmos_url}/user/login"...)` found at line 29 |
| telemetry_query.py | TimescaleDB | parameterized SQL | VERIFIED | `%s` placeholders in SQL; psycopg2 connection via caller |
| bridge /camera/latest.jpg | latestFrame buffer | Express route alias | VERIFIED | Route at index.js:258 returns latestFrame as JPEG |
| farmos_agent_node.py | farmos_client.py | import in execute_report | VERIFIED | `from farmos_agent.farmos_client import ...` at line 26 |
| farmos_agent_node.py | telemetry_query.py | import in execute_report | VERIFIED | `from farmos_agent.telemetry_query import query_daily_summary` at line 33 |
| farmos_agent_node.py | report_builder.py | import in execute_report | VERIFIED | `from farmos_agent.report_builder import build_report_markdown` at line 34 |
| docker-compose.yml | src/farmos-agent/Dockerfile | build context | VERIFIED | `context: ./src/farmos-agent` in compose |
| farmos_agent_node.py | APScheduler CronTrigger | BackgroundScheduler on_activate | VERIFIED | `CronTrigger(hour=6, minute=0)` at line 114 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| farmos_agent_node.py | summary (telemetry) | query_daily_summary() → TimescaleDB | Yes — live rows confirmed | FLOWING |
| farmos_agent_node.py | jpeg_bytes (camera) | _fetch_camera_snapshot() → bridge or disk | Bridge 503 in current test; disk fallback succeeded | PARTIAL |
| report_builder.py | humidity display | summary_dict['fc.humidity']['avg'] | Value is correct raw (94.07) but multiplied by 100 in formatter | HOLLOW — units mismatch |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Container is running | `docker compose ps farmos-agent` | mushy-farmos-agent-1 Up | PASS |
| Lifecycle transitions logged | `docker compose logs farmos-agent` | "configured — FC-1 UUID: 3d6cc537..." + "activated — daily report scheduled at 06:00" | PASS |
| Observation exists in FarmOS | JSON:API query for "FC-1 Daily Report" | 1 observation found: "FC-1 Daily Report 2026-04-12" | PASS |
| Duplicate prevention | Second execute_report trigger (per SUMMARY) | Logged "already exists — skipping" | PASS (per SUMMARY — not re-verified live) |
| Camera snapshot attached | Observation image relationship | 0 images — 403 blocks upload | FAIL |
| Humidity values correct | FarmOS observation notes | 9671% shown (should be ~96.7%) | FAIL |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| FMOS-01 | 13-01, 13-02 | FC-1 exists as structure asset with correct location and metadata | PARTIAL | Asset exists (name, status correct); location unset, no notes |
| FMOS-02 | 13-01, 13-02 | Daily camera snapshot posted to FarmOS as observation on FC-1 | FAILED | Observation exists but has 0 attached images (FarmOS 403 blocks upload) |
| FMOS-03 | 13-01, 13-02 | Daily environment summary with avg/min/max humidity, CO2, temp, duty cycle, anomalies | FAILED | Table present but humidity values are 100x too large due to units mismatch |

### Anti-Patterns Found

| File | Location | Pattern | Severity | Impact |
|------|----------|---------|----------|--------|
| `report_builder.py` | line 17, `_fmt_metric` | Humidity multiplied by 100 but DB stores as percentage | Blocker | Displays 9671% instead of ~96.7% in FarmOS observation |
| `tests/test_farmos_client.py` | (missing) | Test file not committed to HEAD | Warning | 34 tests reported in SUMMARY never verifiable from HEAD; conftest.py exists but tests don't |
| `tests/test_telemetry_query.py` | (missing) | Test file not committed to HEAD | Warning | No automated coverage for telemetry boundary/timezone behavior |
| `tests/test_report_builder.py` | (missing) | Test file not committed to HEAD | Warning | Anomaly flag and formatting logic untestable |

### Human Verification Required

#### 1. FC-1 Location and Metadata

**Test:** Open http://10.68.155.50:8082/asset/28 in browser
**Expected:** Location field shows "Lab 1", notes field includes sensor description text
**Why human:** JSON:API confirms location is empty; FarmOS admin action needed to set it via UI

#### 2. FarmOS Upload Permission Grant

**Test:** Navigate to http://10.68.155.50:8082/admin/people/permissions as admin, find Vikki's role, enable "create log" permission
**Expected:** After granting permission and triggering execute_report(), observation at /asset/28 shows an attached JPEG camera snapshot
**Why human:** Requires FarmOS admin browser session; cannot be automated

#### 3. Corrected Observation After Humidity Fix

**Test:** After fixing report_builder.py humidity formatter and rebuilding (`docker compose up -d --build farmos-agent`), trigger a manual report and inspect the FarmOS observation
**Expected:** Humidity shows ~94% (not 9671%), temperature ~17C, CO2 ~476ppm; anomaly flag only fires if genuinely out of range
**Why human:** Requires code fix, rebuild, manual trigger, and visual FarmOS inspection

### Gaps Summary

Three gaps block full goal achievement:

**Gap 1 — FC-1 missing location and metadata (FMOS-01 partial)**
FC-1 exists as a named structure asset but has no location assignment (Lab 1 / asset 26 not set) and no notes/metadata. The FMOS-01 requirement explicitly requires "correct location and metadata." This is a FarmOS UI action, not a code change.

**Gap 2 — No camera snapshot in observation (FMOS-02 failed)**
Photo upload is blocked by a FarmOS permission error (403 Forbidden). The code handles the failure gracefully (logs warning, continues), but the observation has zero images. FMOS-02 requires a camera snapshot be attached. Resolution requires a FarmOS admin granting Vikki the "create log" permission.

**Gap 3 — Humidity values wrong 100x (FMOS-03 failed, data bug)**
The bridge stores `fc.humidity` as a percentage (e.g., `94.07` for 94.07% RH). The `report_builder.py` formats humidity by multiplying by 100 (assumes 0-1 decimal fraction), producing `9671.0%` instead of `96.7%`. The min/max values are also wrong. The anomaly flag fires incorrectly. This is a one-line code bug in `report_builder.py` line 17 and in the `_fmt_metric` function. The test fixtures in `conftest.py` use `0.823` for humidity (decimal fraction), masking the bug — but the test files themselves were never committed to HEAD.

**Root cause note:** Gaps 2 and 3 were both flagged in the code review (13-REVIEW.md) as CR-01 (upload_photo drops session — a different upload bug that may explain the 403) and IN-01 (humidity units mismatch). These were identified post-implementation but not closed before verification.

---

_Verified: 2026-04-13T05:30:00Z_
_Verifier: Claude (gsd-verifier)_
