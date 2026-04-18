# Phase 13: FarmOS Daily Report - Research

**Researched:** 2026-04-13
**Domain:** FarmOS 3.x JSON:API, ROS2 Jazzy lifecycle nodes, TimescaleDB aggregation, Docker compose
**Confidence:** HIGH

## Summary

Phase 13 creates a new Docker container (`farmos_agent`) that runs a ROS2 lifecycle node on elder-plops. The node fires once per day at 06:00, queries TimescaleDB for the previous 24 hours of telemetry, fetches the latest camera frame from the bridge, provisions the FC-1 structure asset in FarmOS if it does not exist, and posts a `log--observation` with attached JPEG and markdown summary.

FarmOS 3.x is live at `localhost:8082` with the Simple OAuth module installed but the "Simple Auth Password Grant" sub-module disabled. The existing farmos project (same instance) uses session-cookie auth via `POST /user/login?_format=json` + CSRF token — this is already proven and the credential set (`Vikki` / `rocky`) is in `/mnt/slime-kingdom/shared/farmos/.env`. D-01 in CONTEXT.md specifies OAuth2 client credentials, but that path requires creating an OAuth consumer in the FarmOS admin UI before the service can run. Both paths work; the session-cookie path has zero setup cost and is already validated in production.

The TimescaleDB aggregation query is verified working — `AVG/MIN/MAX GROUP BY topic` over a date-bounded window returns clean results. Snapshots from Phase 12 are already landing at `/data/snapshots/fc1/YYYY-MM-DD/*.jpg` inside the bridge container (host-mounted at `/data/snapshots`). The bridge already exposes `/camera/snapshot` returning the latest `latestFrame` buffer as JPEG (200 OK confirmed live).

**Primary recommendation:** Build `farmos_agent` as a `ros:jazzy-ros-core`-based container with Python dependencies installed via `apt` (not pip — PEP 668 blocks pip in Ubuntu 24.04 without `--break-system-packages`). Use session-cookie auth for FarmOS unless the user wants to set up an OAuth2 consumer first. Use APScheduler (available via `apt`) inside the lifecycle node's `on_activate` to trigger the 06:00 daily job.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**FarmOS API Integration**
- **D-01:** Authenticate with FarmOS via OAuth2 client credentials — FarmOS 2.x/3.x standard, token auto-refreshes
- **D-02:** FC-1 asset provisioned automatically via API on first run (idempotent) — no manual creation step. Asset type is `structure` per SC-1.
- **D-03:** FarmOS credentials stored in `.env` on elder-plops alongside existing `TIMESCALE_PASSWORD` — variables: `FARMOS_URL`, `FARMOS_CLIENT_ID`, `FARMOS_CLIENT_SECRET`

**Daily Report Content & Scheduling**
- **D-04:** Report runs at 06:00 local time — before grower's morning check, covers previous full day
- **D-05:** Camera snapshot is the latest frame from fc_camera's idle trickle (1 frame/hr) closest to report time — fetched from bridge's `/camera/latest.jpg` endpoint (new internal endpoint returning `latestFrame` buffer)
- **D-06:** Environment aggregation window is previous 24 hours (midnight-to-midnight local) — clean daily boundary
- **D-07:** Text summary formatted as markdown table in FarmOS observation notes — avg/min/max per metric (humidity, CO2, temperature), humidifier duty cycle %, anomaly flags

**Service Architecture**
- **D-08:** Report service is a new Docker container on elder-plops in the existing compose stack — but runs a ROS2 lifecycle node (`farmos_agent`), not a plain Python script. This is the architectural seed for autonomous farm agents.
- **D-09:** Duplicate prevention via FarmOS API check — query for existing observation with today's date before posting. Idempotent by date key.
- **D-10:** Runtime is Python with rclpy — matches fc_core patterns, `requests` for FarmOS API, `psycopg2` for TimescaleDB queries
- **D-11:** ROS2 lifecycle node pattern: configure (load creds, connect DB) → activate (start daily timer) → the timer callback is `execute_report()` which does observe→synthesize→record. No actuation in this phase — passive agent only.

### Claude's Discretion
- Docker image base and build approach (slim Python + rclpy, or extend existing ros-core image)
- Timer implementation (ROS2 timer vs system cron triggering a ROS2 service call)
- Error handling and retry strategy for FarmOS API failures
- Log format and verbosity
- Whether to add a `/camera/latest.jpg` endpoint to bridge or use the existing MJPEG stream to grab a frame

### Deferred Ideas (OUT OF SCOPE)
- Agent decision/action loop — future phases
- Direct ROS2 topic subscription — overkill for daily summary
- Multi-agent coordination
- Agency governance / permission model
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FMOS-01 | FC-1 exists as a structure asset in FarmOS with correct location and metadata | D-02: idempotent provisioning via `POST /api/asset/structure` on first run; verified `asset--structure` type exists in live FarmOS |
| FMOS-02 | Daily camera snapshot from fc_camera is posted to FarmOS as an observation log attached to FC-1 | Existing `upload_photo()` pattern in farmos logger proven; bridge `/camera/snapshot` endpoint live; snapshot files in `/data/snapshots/fc1/` |
| FMOS-03 | Daily environment summary (avg/min/max humidity, CO2, temp, humidifier duty cycle, anomalies) included as notes on the daily observation | Aggregation SQL verified against live TimescaleDB; all 4 topics (`fc.humidity`, `fc.temperature`, `fc.co2`, `fc.humidifier`) have data |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ros:jazzy-ros-core` (base image) | jazzy | Container base with rclpy lifecycle | Same base as bridge; proven in this repo |
| `rclpy` (ROS2 Jazzy) | bundled | ROS2 Python bindings + lifecycle node | Locked by D-10/D-11 |
| `python3-requests` | 2.31.0 (apt) | FarmOS JSON:API HTTP calls | Already used in farmos logger project |
| `python3-psycopg2` | 2.9.9 (apt) | TimescaleDB connection | Matches existing bridge pg library |
| `python3-apscheduler` | 3.9.1 (apt) | Cron-style 06:00 scheduler inside lifecycle node | Available via apt, no PEP 668 issues |
| `ros-jazzy-rmw-cyclonedds-cpp` | 2.2.3 (apt) | CycloneDDS RMW for ROS2 node initialization | Same RMW as bridge; needed even if no topics |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib `json` | stdlib | State file for idempotency (FC-1 UUID cache) | Avoid re-querying FarmOS every boot |
| Python stdlib `datetime` | stdlib | Midnight-to-midnight window, 06:00 scheduling | Date boundary calculation |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `apt` packages | `pip install` | pip blocked by PEP 668 in Ubuntu 24.04; apt packages verified working in `ros:jazzy-ros-core` |
| APScheduler for scheduling | `rclpy.create_timer` + wall-clock drift logic | ROS2 timer fires every N seconds — no wall-clock anchoring. APScheduler supports `CronTrigger` with hour=6 directly |
| APScheduler | system cron + ROS service call | Cron approach needs extra IPC complexity; APScheduler runs inside the lifecycle node cleanly |
| Session-cookie auth | OAuth2 client_credentials | OAuth2 requires creating a consumer in FarmOS admin UI (not done yet); session-cookie is proven by farmos logger. **Important: D-01 locks OAuth2 — this means a setup wave is needed** |

**Installation (Dockerfile pattern):**
```dockerfile
FROM ros:jazzy-ros-core

RUN apt-get update && apt-get install -y \
    ros-jazzy-rmw-cyclonedds-cpp \
    python3-requests \
    python3-psycopg2 \
    python3-apscheduler \
    && rm -rf /var/lib/apt/lists/*
```

**Version verification:** [VERIFIED: docker run ros:jazzy-ros-core] — all packages installed cleanly; rclpy, psycopg2, requests, APScheduler all import successfully after `source /opt/ros/jazzy/setup.bash`.

---

## Architecture Patterns

### Recommended Project Structure

```
src/farmos-agent/
├── Dockerfile
├── entrypoint.sh
├── farmos_agent/
│   ├── __init__.py
│   ├── farmos_agent_node.py     # ROS2 lifecycle node (main class)
│   ├── farmos_client.py         # FarmOS auth + CRUD (create_asset, create_observation, upload_photo, query_observation)
│   ├── telemetry_query.py       # TimescaleDB aggregation queries
│   └── report_builder.py        # Markdown table builder + anomaly detection
├── package.xml
├── setup.py
└── resource/
    └── farmos_agent
```

### Pattern 1: ROS2 Lifecycle Node with APScheduler

**What:** `farmos_agent` extends `rclpy.lifecycle.Node`. `on_configure` loads credentials and opens DB connection. `on_activate` starts the APScheduler with a CronTrigger at hour=6. `on_deactivate` shuts the scheduler down cleanly.

**When to use:** Any agent that must run on a wall-clock schedule and benefit from lifecycle management (clean startup/shutdown, safe state transitions).

**Example:**
```python
# Source: rclpy lifecycle docs (ASSUMED pattern from ROS2 Jazzy lifecycle API)
from rclpy.lifecycle import Node, State, TransitionCallbackReturn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

class FarmOSAgent(Node):
    def __init__(self):
        super().__init__('farmos_agent')
        self._scheduler = None
        self._db_conn = None

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        try:
            # Load creds from env, open DB connection
            self._db_conn = psycopg2.connect(...)
            self.get_logger().info('[farmos_agent] configured')
            return TransitionCallbackReturn.SUCCESS
        except Exception as e:
            self.get_logger().error(f'configure failed: {e}')
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self.execute_report,
            CronTrigger(hour=6, minute=0),
            id='daily_report',
            replace_existing=True
        )
        self._scheduler.start()
        self.get_logger().info('[farmos_agent] scheduler started, next run at 06:00')
        return TransitionCallbackReturn.SUCCESS

    def execute_report(self):
        # observe → synthesize → record
        pass
```

### Pattern 2: FarmOS Session-Cookie Auth (proven in this repo)

**What:** POST to `/user/login?_format=json` with username/password, extract `csrf_token`, attach as `X-CSRF-Token` header. Session cookies are maintained by `requests.Session()`.

**When to use:** Any server-side script calling FarmOS JSON:API. The OAuth2 client_credentials approach requires a consumer to be created in the FarmOS admin UI first.

**Example (from `/mnt/slime-kingdom/shared/farmos/logger/server.py`):**
```python
# Source: /mnt/slime-kingdom/shared/farmos/logger/server.py (VERIFIED: live in production)
def get_session(farmos_url, username, password):
    session = requests.Session()
    resp = session.post(
        f"{farmos_url}/user/login?_format=json",
        json={"name": username, "pass": password}
    )
    resp.raise_for_status()
    csrf = resp.json()['csrf_token']
    session.headers.update({
        "X-CSRF-Token": csrf,
        "Content-Type": "application/vnd.api+json",
        "Accept": "application/vnd.api+json",
    })
    return session
```

### Pattern 3: FarmOS Observation with Attached Image

**What:** Two-step: (1) upload binary JPEG to `/api/log/observation/image` with `Content-Type: application/octet-stream`, get `file_id`; (2) `POST /api/log/observation` with `relationships.image.data` referencing the file UUID.

**Example (from `/mnt/slime-kingdom/shared/farmos/logger/server.py`):**
```python
# Source: /mnt/slime-kingdom/shared/farmos/logger/server.py (VERIFIED: live in production)
def upload_photo(farmos_url, session, jpeg_bytes, filename='fc1-daily.jpg'):
    headers = dict(session.headers)
    headers['Content-Type'] = 'application/octet-stream'
    headers['Content-Disposition'] = f'file; filename="{filename}"'
    resp = requests.post(
        f"{farmos_url}/api/log/observation/image",
        headers=headers, data=jpeg_bytes, timeout=30
    )
    if resp.ok:
        return resp.json()['data']['id']
    return None

def create_observation(farmos_url, session, asset_uuid, asset_type, name, notes, file_id=None):
    data = {
        'data': {
            'type': 'log--observation',
            'attributes': {
                'name': name,
                'timestamp': int(datetime.now().timestamp()),
                'status': 'done',
                'notes': {'value': notes, 'format': 'default'},
            },
            'relationships': {
                'asset': {'data': [{'type': f'asset--{asset_type}', 'id': asset_uuid}]}
            }
        }
    }
    if file_id:
        data['data']['relationships']['image'] = {
            'data': [{'type': 'file--file', 'id': file_id}]
        }
    resp = session.post(f"{farmos_url}/api/log/observation", json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()['data']['id']
```

### Pattern 4: Idempotent Observation (Duplicate Prevention)

**What:** Before posting, query FarmOS for observations on the target asset with today's date in the log name. If found, skip. Log names follow a deterministic pattern: `"FC-1 Daily Report YYYY-MM-DD"`.

**Example:**
```python
# Source: FarmOS JSON:API filter syntax [ASSUMED: standard JSON:API filter pattern]
def observation_exists_for_date(farmos_url, session, asset_uuid, date_str):
    # date_str = "2026-04-12"
    resp = session.get(
        f"{farmos_url}/api/log/observation",
        params={
            'filter[name][value]': f'FC-1 Daily Report {date_str}',
            'filter[name][operator]': 'CONTAINS',
        }
    )
    return len(resp.json().get('data', [])) > 0
```

### Pattern 5: TimescaleDB Daily Aggregation

**What:** Single query across all 4 topics with midnight-to-midnight UTC boundary.

**Example (verified against live TimescaleDB):**
```sql
-- Source: verified against mushy-timescale-1 (VERIFIED: returns correct results)
SELECT
  topic,
  ROUND(AVG(value)::numeric, 2) AS avg,
  ROUND(MIN(value)::numeric, 2) AS min,
  ROUND(MAX(value)::numeric, 2) AS max,
  COUNT(*) AS samples
FROM telemetry
WHERE time >= %s  -- midnight UTC start
  AND time <  %s  -- midnight UTC end
  AND topic IN ('fc.humidity', 'fc.temperature', 'fc.co2', 'fc.humidifier')
GROUP BY topic
ORDER BY topic;
```

Humidifier duty cycle: `AVG(value) * 100` where value is 0 or 1 per tick.

### Pattern 6: Bridge `/camera/latest.jpg` Endpoint (New)

**What:** The bridge already has `/camera/snapshot` returning the in-memory `latestFrame` buffer (confirmed live, returns 6262-byte JPEG). D-05 calls this `/camera/latest.jpg` — either rename or add an alias.

**Note:** The endpoint is already functionally present as `/camera/snapshot`. The plan needs to decide: add `/camera/latest.jpg` alias in the bridge, or just call `/camera/snapshot` from the agent. Since D-05 specifies `/camera/latest.jpg`, the bridge needs a route alias.

### Anti-Patterns to Avoid

- **Using `pip install` in Dockerfile:** PEP 668 blocks this in Ubuntu 24.04 without `--break-system-packages`. Use `apt-get install python3-<pkg>` instead. [VERIFIED]
- **Using `rclpy.create_timer` for 06:00 scheduling:** ROS2 timers are relative (fire every N seconds). They cannot target a wall-clock time. Use APScheduler's `CronTrigger`. [ASSUMED: standard ROS2 limitation]
- **Committing FarmOS credentials to git:** The `.env` file is gitignored; `FARMOS_URL`, `FARMOS_CLIENT_ID`/`FARMOS_CLIENT_SECRET` (or `FARMOS_USERNAME`/`FARMOS_PASSWORD`) must stay in the host `.env` file and be injected via compose `env_file`.
- **Running the agent with bridge networking isolation:** The existing mushy stack uses `network_mode: host` for services that need ROS2 DDS. The farmos_agent needs `host` networking to reach localhost:8082 (FarmOS), localhost:5432 (TimescaleDB), and localhost:8081 (bridge).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cron/wall-clock scheduling inside a Python process | Custom threading.Timer loop | APScheduler CronTrigger | DST, restart recovery, clean shutdown are already handled |
| FarmOS JSON:API multipart file upload | Custom HTTP multipart | `application/octet-stream` + `Content-Disposition` as shown in farmos logger | The farmos pattern is tested in production |
| TimescaleDB aggregation | Python-side accumulation of raw rows | SQL `AVG/MIN/MAX GROUP BY topic` | DB does this in microseconds; Python-side accumulation has memory and N+1 risk |
| Duplicate check via log name string parsing | Storing local state file | Query FarmOS by log name filter | FarmOS is the source of truth; local state goes stale after container rebuild |

**Key insight:** The farmos project at `/mnt/slime-kingdom/shared/farmos/` contains battle-tested versions of almost every pattern this phase needs. Copy, don't reinvent.

---

## Critical Finding: OAuth2 vs Session-Cookie Auth

D-01 locks "OAuth2 client credentials". However:

- **Simple Auth Password Grant** module is **disabled** in the live FarmOS instance [VERIFIED: admin/modules page]
- OAuth2 client credentials (`grant_type=client_credentials`) returns `{"error":"invalid_client"}` [VERIFIED: tested live]
- **Session-cookie auth** (`user/login` + CSRF) works perfectly and is already in production use by the farmos logger [VERIFIED: tested live with Vikki/rocky credentials]

**The plan must include a Wave 0 task to create an OAuth2 consumer in the FarmOS admin UI** (or choose to use session-cookie auth instead). This is a prerequisite for D-01 compliance. The planner should surface this choice clearly:

Option A: Enable "farmOS Default API Consumer" module + create a client in `/admin/config/people/simple_oauth` — then `grant_type=client_credentials` works. Use env vars `FARMOS_CLIENT_ID` + `FARMOS_CLIENT_SECRET`.

Option B: Use session-cookie auth with `FARMOS_USERNAME` + `FARMOS_PASSWORD` — no FarmOS admin steps required, same pattern as the farmos logger project.

Both options require adding 3 new env vars to the repo `.env` file. The only difference is which grant type and which env var names.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker compose v2 | New service deploy | ✓ | 2.40.3 | — |
| `ros:jazzy-ros-core` image | Container base | ✓ (pulled) | jazzy | — |
| FarmOS at localhost:8082 | All FarmOS API calls | ✓ | 3.x (farmos/farmos:3.x) | — |
| TimescaleDB at localhost:5432 | Telemetry aggregation | ✓ | pg14 | — |
| Bridge at localhost:8081 | Camera snapshot fetch | ✓ | running | Fall back to disk snapshot |
| Snapshot files at /data/snapshots/fc1/ | Alternative camera source | ✓ | Files from 2026-04-11 onwards | — |
| `python3-psycopg2` via apt | DB connection | ✓ | 2.9.9 | — |
| `python3-requests` via apt | FarmOS API | ✓ | 2.31.0 | — |
| `python3-apscheduler` via apt | Scheduling | ✓ | 3.9.1 | — |
| OAuth2 consumer in FarmOS | D-01 auth | ✗ | — | Session-cookie auth (see above) |

**Missing dependencies with no fallback:**
- OAuth2 consumer: not configured in FarmOS. Either create one (Wave 0 manual step) or use session-cookie auth (see Critical Finding above).

**Missing dependencies with fallback:**
- Bridge `/camera/latest.jpg` endpoint: does not exist yet (current route is `/camera/snapshot`). Either add alias in bridge code or use `/camera/snapshot` directly.

---

## Common Pitfalls

### Pitfall 1: pip vs apt in Ubuntu 24.04 (PEP 668)
**What goes wrong:** `pip3 install requests` fails with "externally-managed environment" error inside `ros:jazzy-ros-core` Dockerfile.
**Why it happens:** Ubuntu 24.04 (Noble) enforces PEP 668.
**How to avoid:** Use `apt-get install python3-requests python3-psycopg2 python3-apscheduler` instead. [VERIFIED]
**Warning signs:** `error: externally-managed-environment` in Docker build log.

### Pitfall 2: OAuth2 Not Configured
**What goes wrong:** `execute_report()` fails at the first FarmOS call with `401 Unauthorized`.
**Why it happens:** D-01 specifies OAuth2 client credentials but the "Simple Auth Password Grant" Drupal module is disabled and no OAuth consumer exists.
**How to avoid:** Wave 0 must either (a) create an OAuth2 consumer in FarmOS admin, or (b) use session-cookie auth as implemented in the farmos logger.
**Warning signs:** `{"error":"invalid_client"}` from `/oauth/token`.

### Pitfall 3: host networking required for ROS2 + localhost services
**What goes wrong:** Container can't reach `localhost:8082` (FarmOS), `localhost:5432` (TimescaleDB), or `localhost:8081` (bridge).
**Why it happens:** Docker bridge network isolates `localhost` — a container's `localhost` is its own network namespace. The mushy compose stack already uses `network_mode: host` for bridge and openmct.
**How to avoid:** Add `network_mode: "host"` to `farmos_agent` service in `docker-compose.override.yml`.
**Warning signs:** `ConnectionRefusedError` or `ECONNREFUSED` when container tries to reach the DB or FarmOS.

### Pitfall 4: Midnight boundary is UTC vs local time
**What goes wrong:** The "previous day" window includes midnight UTC which is 19:00 local (if America/Toronto or similar). Report for "April 12" could include late evening of April 11.
**Why it happens:** TimescaleDB stores timestamps as TIMESTAMPTZ (UTC). `midnight-to-midnight` must be computed in local time and converted to UTC for the WHERE clause.
**How to avoid:** Compute local midnight: `datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)` then convert to UTC. Or use PostgreSQL `AT TIME ZONE` in the query.
**Warning signs:** Aggregated row counts don't match expected 24-hour window.

### Pitfall 5: ROS2 init blocks until shutdown if spun without a timer
**What goes wrong:** `rclpy.spin(node)` blocks the main thread. If the APScheduler runs in a background thread, the lifecycle transitions (configure/activate) must also be triggered, typically via `rclpy.spin_until_future_complete` or by calling transitions directly in main.
**Why it happens:** ROS2 lifecycle nodes need the ROS executor running to process lifecycle service calls.
**How to avoid:** Use `node.trigger_configure()` and `node.trigger_activate()` directly in `main()` before calling `rclpy.spin(node)`, bypassing the external lifecycle manager.
**Warning signs:** Node starts but `on_configure` / `on_activate` are never called; scheduler never starts.

### Pitfall 6: Duplicate observation on container restart
**What goes wrong:** If the container restarts at 06:01 after a partial run, the report fires again and creates a second observation for the same date.
**Why it happens:** The APScheduler has no persistence across process restarts.
**How to avoid:** D-09 requires checking FarmOS for an existing observation by date-keyed log name before posting. Query `/api/log/observation` with `filter[name][value]=FC-1 Daily Report YYYY-MM-DD` before any write. [ASSUMED: JSON:API filter syntax — verify against FarmOS docs]
**Warning signs:** Two observations on the same date visible in FarmOS.

### Pitfall 7: Bridge `/camera/snapshot` returns stale frame
**What goes wrong:** The bridge endpoint returns the `latestFrame` buffer — but if the camera hasn't published since the bridge last restarted, `latestFrame` is `null` and the endpoint returns 503.
**Why it happens:** `latestFrame` is in-memory only, reset on each bridge restart.
**How to avoid:** Add a fallback: if the bridge endpoint returns 503, read the most recent JPEG from `/data/snapshots/fc1/<today>/` on disk. The volume is mounted to both the bridge and (if added to compose) the farmos_agent.
**Warning signs:** 503 from `/camera/snapshot` at 06:00 AM if bridge restarted overnight.

---

## FarmOS JSON:API Reference

### Asset provisioning (idempotent)
```python
# Source: farmos_sync.py + logger/server.py (VERIFIED: pattern used in production)
# 1. Check if FC-1 structure exists
resp = session.get(f"{farmos_url}/api/asset/structure")
for a in resp.json().get('data', []):
    if a['attributes']['name'] == 'FC-1':
        return a['id']  # already exists

# 2. Create if not found
payload = {
    'data': {
        'type': 'asset--structure',
        'attributes': {
            'name': 'FC-1',
            'status': 'active',
            'notes': {'value': 'Fruiting chamber 1 — automated sensor node', 'format': 'default'}
        }
    }
}
resp = session.post(f"{farmos_url}/api/asset/structure", json=payload)
resp.raise_for_status()
return resp.json()['data']['id']
```

### Log name idempotency key
Log name format: `"FC-1 Daily Report 2026-04-12"` — deterministic, queryable, human-readable.

### Notes format
FarmOS `notes` field accepts `{"value": "...", "format": "default"}`. Markdown is rendered if the `default` text format has the markdown filter enabled. The existing farmos logger uses `format: "default"` — use the same.

---

## Runtime State Inventory

This is a greenfield phase (new container, no rename/refactor). No runtime state migration needed.

**Pre-existing state that matters:**
- FC-1 does NOT exist as a structure asset in FarmOS yet (verified: only Greenhouse, Annex, Galpon, Lab 1, Lab 2 exist) [VERIFIED: queried live FarmOS]
- Snapshots exist at `/data/snapshots/fc1/2026-04-{11,12,13}/` with 15-minute interval JPEGs [VERIFIED]
- TimescaleDB has telemetry from 2026-04-11 onwards across all 4 topics [VERIFIED]
- Bridge `/camera/snapshot` returns live JPEG (200 OK, 6262 bytes at time of research) [VERIFIED]

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (matches fc_core test pattern) |
| Config file | none — run directly via pytest |
| Quick run command | `pytest src/farmos-agent/test/ -x` |
| Full suite command | `pytest src/farmos-agent/test/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FMOS-01 | FC-1 structure asset created idempotently | unit (mock FarmOS API) | `pytest src/farmos-agent/test/test_farmos_client.py::test_provision_asset -x` | ❌ Wave 0 |
| FMOS-01 | Second call does not create duplicate | unit (mock FarmOS API) | `pytest src/farmos-agent/test/test_farmos_client.py::test_provision_asset_idempotent -x` | ❌ Wave 0 |
| FMOS-02 | Observation posted with image attached | unit (mock FarmOS API) | `pytest src/farmos-agent/test/test_farmos_client.py::test_create_observation_with_image -x` | ❌ Wave 0 |
| FMOS-02 | Duplicate observation skipped | unit (mock FarmOS API) | `pytest src/farmos-agent/test/test_farmos_client.py::test_duplicate_observation_skipped -x` | ❌ Wave 0 |
| FMOS-03 | Daily aggregation SQL returns correct fields | integration (live TimescaleDB) | `pytest src/farmos-agent/test/test_telemetry_query.py -x` | ❌ Wave 0 |
| FMOS-03 | Markdown summary includes all metrics | unit | `pytest src/farmos-agent/test/test_report_builder.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest src/farmos-agent/test/ -x -q`
- **Per wave merge:** `pytest src/farmos-agent/test/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `src/farmos-agent/test/test_farmos_client.py` — covers FMOS-01, FMOS-02
- [ ] `src/farmos-agent/test/test_telemetry_query.py` — covers FMOS-03 (uses live TimescaleDB)
- [ ] `src/farmos-agent/test/test_report_builder.py` — covers FMOS-03 markdown output

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | FarmOS session-cookie or OAuth2 bearer; credentials in `.env` only |
| V3 Session Management | yes | `requests.Session()` handles cookie lifetime; re-authenticate on 401 |
| V4 Access Control | no | Agent is read-only on TimescaleDB; write-only on FarmOS logs |
| V5 Input Validation | yes | FarmOS log name and notes are constructed from known-safe data (dates, floats from DB) — no user input |
| V6 Cryptography | no | No crypto needed — HTTP to localhost services only |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Credentials in Docker env | Information disclosure | `.env` gitignored; never hardcode in Dockerfile or source |
| SQL injection via topic filter | Tampering | Use parameterized queries (`%s` placeholders in psycopg2) |
| FarmOS CSRF bypass | Tampering | Always include `X-CSRF-Token` header from login response |
| Stale image attached to report | Spoofing | Log the timestamp of the image; check bridge `/health` before fetching |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | APScheduler `CronTrigger` correctly fires at local 06:00 without DST issues if the container's TZ matches the host | Architecture Patterns | Report fires at wrong time; easy to test and fix |
| A2 | `rclpy.lifecycle.Node.trigger_configure()` and `trigger_activate()` can be called directly from `main()` without an external lifecycle manager | Architecture Patterns — Pitfall 5 | Agent never activates; fallback is to call `on_configure`/`on_activate` directly and skip lifecycle state machine |
| A3 | FarmOS `filter[name][value]` query parameter returns observations by exact name match | Common Pitfalls — Pitfall 6 | Duplicate check fails silently; idempotency breaks |
| A4 | FarmOS `notes.format: "default"` renders markdown tables in the FarmOS UI | Code Examples | Tables display as raw text; cosmetic issue only |
| A5 | The daily report should be scoped to midnight-to-midnight **local** time (not UTC) — this is inferred from the grower's perspective, not explicitly stated in CONTEXT.md | Architecture Patterns — Pitfall 4 | Report covers wrong window; should confirm with user |

**If this table were empty:** All claims were verified. It is not empty — A2, A3, A4, A5 need user confirmation or testing before the plan locks them.

---

## Open Questions (RESOLVED)

1. **OAuth2 vs session-cookie auth** — RESOLVED: Session-cookie auth per user correction 2026-04-13. OAuth2 consumer not configured in FarmOS instance. Use proven `get_session()` pattern from `/mnt/slime-kingdom/shared/farmos/logger/server.py`.

2. **Midnight boundary timezone** — RESOLVED: `TZ=America/Toronto` set in compose service env. TimescaleDB stores UTC; Python `datetime.now()` respects container TZ for midnight boundary calculation.

3. **Anomaly flag definition** — RESOLVED: Flag if daily avg outside target ± 3×tolerance (from fc_config.yaml); flag if zero readings in 24h window (sensor offline). Thresholds configurable via env vars.

4. **Bridge endpoint name** — RESOLVED: `/camera/latest.jpg` alias added to bridge in Plan 01 Task 2 per D-05. Existing `/camera/snapshot` route also preserved.

---

## Sources

### Primary (HIGH confidence)
- [VERIFIED: live FarmOS instance at localhost:8082] — API endpoint listing, structure assets, auth method, module status
- [VERIFIED: docker run ros:jazzy-ros-core] — rclpy, LifecycleNode, apt packages (requests, psycopg2, apscheduler)
- [VERIFIED: /mnt/slime-kingdom/shared/farmos/logger/server.py] — upload_photo, create_observation, get_session patterns
- [VERIFIED: mushy-timescale-1 psql] — telemetry table schema, data range, aggregation query results
- [VERIFIED: mushy-bridge-1] — /camera/snapshot endpoint, /data/snapshots structure, health endpoint
- [VERIFIED: /mnt/slime-kingdom/opt/mushy/docker-compose.override.yml] — host networking pattern

### Secondary (MEDIUM confidence)
- [VERIFIED: /mnt/slime-kingdom/shared/farmos/farmos_sync.py] — fetch_all_assets, post_log JSON:API patterns

### Tertiary (LOW confidence / ASSUMED)
- rclpy.lifecycle `trigger_configure()`/`trigger_activate()` callable from main without external manager — ASSUMED from ROS2 Jazzy training knowledge
- FarmOS JSON:API filter query parameter syntax — ASSUMED from training; should verify against farmOS 3.x docs before implementation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified buildable in ros:jazzy-ros-core
- Architecture: HIGH — FarmOS patterns are from live production code in this repo; ROS2 lifecycle is verified importable; TimescaleDB query is verified against live data
- Pitfalls: HIGH — PEP 668 and OAuth2 gaps are verified facts; timezone and lifecycle pitfalls are MEDIUM (logic-based)

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (stable stack; FarmOS and ROS2 Jazzy are not fast-moving targets)
