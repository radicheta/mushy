---
phase: 13-farmos-daily-report
plan: "02"
subsystem: farmos-agent
tags: [farmos, ros2, lifecycle, docker, apscheduler, timescaledb, compose]
dependency_graph:
  requires:
    - 13-01 (farmos_client, telemetry_query, report_builder, bridge /camera/latest.jpg)
  provides:
    - farmos-agent: running Docker service in compose stack
    - farmos_agent_node.py: ROS2 lifecycle node with daily scheduler
    - Dockerfile: ros:jazzy-ros-core based container image
    - docker-compose.yml: farmos-agent service definition
    - docker-compose.override.yml: host networking for farmos-agent
  affects:
    - docker-compose.yml
    - docker-compose.override.yml
tech_stack:
  added:
    - apscheduler (CronTrigger via apt, 06:00 wall-clock scheduling)
    - psycopg2 (TimescaleDB connection via apt)
    - ros:jazzy-ros-core (container base image)
  patterns:
    - ROS2 lifecycle node (configure -> activate -> execute_report)
    - APScheduler BackgroundScheduler with CronTrigger(hour=6)
    - Self-transition lifecycle (on_configure/on_activate called directly from main)
    - Camera snapshot with bridge-primary / disk-fallback pattern
    - Re-auth on 401 for FarmOS session recovery
    - Duplicate prevention via observation_exists_for_date before any write (D-09)
key_files:
  created:
    - src/farmos-agent/Dockerfile
    - src/farmos-agent/entrypoint.sh
    - src/farmos-agent/farmos_agent/farmos_agent_node.py
    - src/farmos-agent/farmos_agent/__init__.py
    - src/farmos-agent/tests/__init__.py
    - src/farmos-agent/package.xml
    - src/farmos-agent/setup.py
    - src/farmos-agent/setup.cfg
    - src/farmos-agent/resource/farmos_agent
  modified:
    - docker-compose.yml
    - docker-compose.override.yml
decisions:
  - "Self-transition lifecycle: on_configure/on_activate called directly from main() — no external lifecycle manager in container (A2 fallback from RESEARCH.md)"
  - "Camera snapshot: bridge /camera/latest.jpg primary, /data/snapshots disk fallback — bridge returned 503 in test (no live frame), disk fallback succeeded correctly"
  - "Photo upload skipped gracefully when FarmOS returns 403 (missing 'create log' permission for Vikki) — observation still created without image attachment"
metrics:
  duration_seconds: 420
  completed_date: "2026-04-13"
  tasks_completed: 2
  tasks_total: 2
  files_created: 9
  files_modified: 2
---

# Phase 13 Plan 02: FarmOS Agent ROS2 Node and Compose Integration Summary

**One-liner:** ROS2 lifecycle node on ros:jazzy-ros-core wired to APScheduler CronTrigger at 06:00, queries TimescaleDB, fetches camera snapshot, and posts daily observation to FC-1 in FarmOS — running in compose stack with host networking.

## What Was Built

**`farmos_agent_node.py`** — ROS2 lifecycle node integrating the Plan 01 library modules:

- `on_configure()`: Loads env vars (`FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD`, `TIMESCALE_HOST`, `TIMESCALE_PASSWORD`, `REPORT_TIMEZONE`, `BRIDGE_URL`). Opens psycopg2 connection with `connect_timeout=10`. Authenticates to FarmOS via `get_session()`. Resolves and caches FC-1 UUID via `get_asset_uuid()`. Returns SUCCESS or FAILURE.

- `on_activate()`: Creates `BackgroundScheduler`, adds job with `CronTrigger(hour=6, minute=0)`, starts scheduler. Logs "activated — daily report scheduled at 06:00".

- `on_deactivate()`: Shuts scheduler, closes DB connection cleanly.

- `execute_report()`: Outer wrapper with try/except — failure is logged but does not crash the node (T-13-07). Inner `_do_execute_report()` implements the full observe-synthesize-record loop:
  1. Compute yesterday's date in container timezone
  2. Duplicate check via `observation_exists_for_date()` — skip if exists (D-09)
  3. Observe: `query_daily_summary()` from TimescaleDB
  4. Observe: `_fetch_camera_snapshot()` — bridge `/camera/latest.jpg` primary, disk `/data/snapshots/fc1/{date}/` fallback
  5. Synthesize: `build_report_markdown()` for markdown table + anomaly flags
  6. Record: `upload_photo()` (graceful skip on failure)
  7. Record: `create_observation()` with name pattern `FC-1 Daily Report YYYY-MM-DD`

- `main()`: Self-transition pattern — calls `on_configure(None)` / `on_activate(None)` directly before `rclpy.spin()`.

**Dockerfile** — `ros:jazzy-ros-core` base, apt installs `ros-jazzy-rmw-cyclonedds-cpp`, `python3-requests`, `python3-psycopg2`, `python3-apscheduler`. No pip (PEP 668). `entrypoint.sh` sources ROS, sets PYTHONPATH, runs node.

**docker-compose.yml** — Added `farmos-agent` service with build context, `depends_on: [timescale, bridge]`, env vars (`FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD`, `TIMESCALE_HOST`, `TIMESCALE_PASSWORD`, `TZ`, `REPORT_TIMEZONE`, `BRIDGE_URL`), snapshot volume mount (`:ro`), `restart: unless-stopped`.

**docker-compose.override.yml** — Added `farmos-agent: network_mode: "host"` for localhost FarmOS:8082, TimescaleDB:5432, bridge:8081 access.

## Verification Results

| Check | Result |
|-------|--------|
| `docker compose build farmos-agent` | PASSED (exit 0) |
| Container lifecycle transitions logged | PASSED — "configured — FC-1 UUID: 3d6cc537..." + "activated — daily report scheduled at 06:00" |
| `execute_report()` manual trigger | PASSED — observation UUID `3baf38ce-7408-4baa-92d5-e390e285260b` |
| Observation name | PASSED — "FC-1 Daily Report 2026-04-12" |
| Duplicate prevention | PASSED — second trigger logged "already exists — skipping" |
| Camera bridge primary | PARTIAL — bridge returned 503 (no live frame); fallback succeeded |
| Camera disk fallback | PASSED — loaded `/data/snapshots/fc1/2026-04-12/2026-04-12T23-56-12-701Z.jpg` |
| Photo upload | FAILED — FarmOS 403 (see Known Limitations) |
| `docker compose ps farmos-agent` | PASSED — running |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Missing `__init__.py` files**
- **Found during:** Task 1 — Plan 01 summary listed them as created but they were not in the commit
- **Issue:** `farmos_agent/` and `tests/` directories lacked `__init__.py`, preventing Python package imports
- **Fix:** Created `src/farmos-agent/farmos_agent/__init__.py` and `src/farmos-agent/tests/__init__.py`
- **Files modified:** both files
- **Commit:** b17ef0a

## Known Limitations

**Photo upload blocked by FarmOS permissions (403 Forbidden)**

The FarmOS user "Vikki" receives a 403 when posting to `/api/log/observation/image`:

> "The current user is not permitted to upload a file for this field. The following permissions are required: 'administer log' OR 'create log'."

The `create_observation()` call succeeds (Vikki can write log--observation), but the file attachment endpoint requires an additional FarmOS role permission. The agent handles this gracefully — it logs a warning and creates the observation without an image. The grower will see the markdown table but no photo attachment.

**Resolution:** A FarmOS admin needs to grant Vikki the "create log" permission at `/admin/people/permissions`. This is a FarmOS UI action outside the scope of this plan.

## Threat Mitigations Applied

| Threat | Mitigation | Location |
|--------|-----------|----------|
| T-13-06 Credential disclosure | FARMOS_USERNAME/PASSWORD injected via compose env, never logged | `farmos_agent_node.py` — logger never references credential values |
| T-13-07 Denial of service | All HTTP calls have 10s/30s timeouts; execute_report wrapped in try/except; connect_timeout=10 on DB | `farmos_agent_node.py`, `farmos_client.py` |
| T-13-08 Repudiation | Accepted — passive reporting agent; failure logged in container logs | N/A |
| T-13-09 Elevation of privilege | Container runs as default ros:jazzy-ros-core user; FarmOS session scoped to log write only | Dockerfile (no USER override) |

## Known Stubs

None — the full observe-synthesize-record loop is implemented and verified against live FarmOS. Photo upload is blocked by permissions (documented above), not a stub.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. The farmos-agent connects outbound to existing localhost services only.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `src/farmos-agent/Dockerfile` | FOUND |
| `src/farmos-agent/entrypoint.sh` | FOUND |
| `src/farmos-agent/farmos_agent/farmos_agent_node.py` | FOUND |
| `src/farmos-agent/package.xml` | FOUND |
| `src/farmos-agent/setup.py` | FOUND |
| `src/farmos-agent/setup.cfg` | FOUND |
| `src/farmos-agent/resource/farmos_agent` | FOUND |
| `docker-compose.yml` contains farmos-agent | FOUND |
| `docker-compose.override.yml` contains farmos-agent | FOUND |
| Commit b17ef0a | FOUND |
| Container mushy-farmos-agent-1 running | VERIFIED |
| Observation in FarmOS (UUID 3baf38ce) | VERIFIED |
| Duplicate skip on second run | VERIFIED |
