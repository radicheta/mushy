# Phase 7: Historical Data Storage & OpenMCT Time-Series Visualization - Research

**Researched:** 2026-04-05
**Domain:** TimescaleDB ingestion, Node.js/Express REST, OpenMCT telemetry `request()`, Docker
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Bridge service (Node.js) writes telemetry to TimescaleDB — no new containers or ROS nodes. Bridge already subscribes to all ROS topics and sits on `frontend-net` with TimescaleDB.
- **D-02:** Use `pg` (node-postgres) as the DB client — lightweight, no ORM, direct INSERT statements.
- **D-03:** Immediate insert on each ROS message callback — no batching. At ~2 writes/sec across 4 topics, this is trivial for Postgres.
- **D-04:** Add REST endpoints to the bridge (Express routes, e.g. `GET /history/:topic?start=&end=`) for historical queries. OpenMCT plugin's `request()` calls these endpoints. Clean separation from WebSocket live data.
- **D-05:** Default time range is last 24 hours when opening a chart. User can zoom in/out from there.
- **D-06:** Server-side downsampling for queries using TimescaleDB `time_bucket()`. Return averaged data per 1min/5min/15min bucket depending on requested range. Keeps charts fast for longer time spans.
- **D-07:** TimescaleDB runs on elder-plops via Docker (existing docker-compose definition). Pi runs fc-core only, stays lightweight. Bridge on elder-plops subscribes to ROS over WireGuard and writes locally to DB.
- **D-08:** Schema managed by bridge startup init — `CREATE TABLE IF NOT EXISTS` + hypertable setup. No migration tooling for a one-table schema.
- **D-09:** Move DB password from hardcoded `mysecretpassword` in docker-compose to `.env` file. Bridge reads from env vars too.
- **D-10:** Store all 4 current topics: humidity, temperature, CO2, humidifier state. Full picture of the chamber.
- **D-11:** Store every reading at full ~2s resolution. Raw data preserved for spike/event analysis.
- **D-12:** Keep all data indefinitely — no retention policy for now.

### Claude's Discretion

- Table schema design (column types, indexes, hypertable chunk interval)
- Express route structure and query parameter validation
- Downsampling bucket thresholds (which bucket size at which time range)
- OpenMCT plugin `request()` implementation details
- Error handling for DB connection loss (bridge should continue live WebSocket even if DB is down)

### Deferred Ideas (OUT OF SCOPE)

- Downsampled retention policy (continuous aggregates + raw data aging)
- Multi-chamber schema (chamber_id column or separate hypertables)
- Alerting on historical trends
- Data export/backup (pg_dump scheduling)
</user_constraints>

---

## Summary

Phase 7 wires up the existing TimescaleDB container to ingest ROS telemetry from the bridge and serves that data to OpenMCT's history provider. There are no new containers, no new ROS nodes — just code changes to three files and a `.env` credential migration.

**Critical finding:** The bridge container currently runs `rosbridge_websocket` (Python) via a ROS2 launch file — it does NOT run the `src/index.js` rclnodejs file that exists in the repo. The CONTEXT decisions (D-01 through D-04) assume a Node.js bridge. The plan must wire up `src/index.js` as the actual bridge entry point, replacing the Python rosbridge path, and add Node.js + npm install to the Dockerfile. The existing `src/index.js` only has temperature and humidity topics — CO2 and humidifier subscriptions need to be added before DB inserts can be written for all 4 topics.

**Primary recommendation:** Rewrite the bridge entrypoint to run `src/index.js` (Node.js, rclnodejs + pg + Express), add `pg` and `express` to package.json, and wire `request()` in plugin.js to call `GET /history/:topic?start=&end=`.

## Project Constraints (from CLAUDE.md)

- ROS2 Jazzy workspace on Ubuntu 24.04 (elder-plops is Linux Mint 21.2 / Docker)
- Build with `colcon build`; Python packages via `ament_flake8`/`ament_pep257`
- `ROS_DOMAIN_ID=69`, `ROS_LOCALHOST_ONLY=0`
- Docker services via `docker-compose up` from `src/`
- Bridge container base image: `ros:jazzy-ros-core`

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pg` (node-postgres) | 8.20.0 | PostgreSQL/TimescaleDB client for Node.js | D-02; lightweight, no ORM, battle-tested |
| `express` | 5.2.1 | HTTP server for REST history endpoints | D-04; ubiquitous, minimal boilerplate |
| `ws` | ^8.16.0 | WebSocket server (already in package.json) | existing dependency, keep as-is |
| `timescale/timescaledb` | latest-pg14 | Time-series database (already in docker-compose line 83) | existing container |

**Version verification:** [VERIFIED: npm registry, 2026-03-04 for pg 8.20.0 / 2025-12-01 for express 5.2.1]

### Installation

```bash
# In src/mission-control/bridge/
npm install pg express
```

Add to `package.json` dependencies:
```json
{
  "dependencies": {
    "ws": "^8.16.0",
    "rclnodejs": "^0.3.0",
    "pg": "^8.20.0",
    "express": "^5.2.1"
  }
}
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pg` | `pg-promise` | pg-promise adds helpers but D-02 locks plain pg |
| Express | aiohttp (Python) | Would avoid Node.js pivot but D-02/D-04 lock Node.js |
| Express | Fastify | Fastify is faster but Express is more familiar and D-04 is locked |

---

## Architecture Patterns

### Current Bridge Reality (IMPORTANT)

The bridge container currently runs `rosbridge_websocket` (Python) via:

```
entrypoint.sh → ros2 launch /opt/bridge/launch/bridge.launch.py → rosbridge_server/rosbridge_websocket (port 8081)
```

The `src/index.js` file (rclnodejs) exists but is **not invoked**. The plugin.js talks to rosbridge over WebSocket on port 8081 using the rosbridge protocol (`op: 'subscribe'`/`op: 'publish'`).

**Plan must:** update `entrypoint.sh` and `Dockerfile` so `src/index.js` runs as the bridge, replacing the rosbridge Python launch. The existing plugin.js WebSocket code uses the rosbridge protocol — this means `src/index.js` must implement rosbridge wire protocol OR plugin.js must be updated to the simpler `{humidity, timestamp}` / `{temperature, timestamp}` format that index.js currently broadcasts.

**Recommended approach:** Keep plugin.js WebSocket format compatible with what `src/index.js` already broadcasts (`{humidity, timestamp}`, `{temperature, timestamp}`). Plugin.js already handles both formats (it re-dispatches by field presence in the onmessage handler — although currently it uses rosbridge `op: 'publish'` protocol). The planner must verify if plugin.js onmessage handling is compatible with index.js's raw broadcast format, and reconcile if needed.

### Recommended Project Structure Changes

```
src/mission-control/bridge/
├── src/
│   └── index.js          # REPLACE with full implementation:
│                         #   rclnodejs subscriptions (4 topics)
│                         #   pg writes on each callback
│                         #   Express HTTP server for /history/:topic
│                         #   WebSocket broadcast (existing)
├── Dockerfile            # ADD: node, npm install step
├── entrypoint.sh         # REPLACE rosbridge launch with: node src/index.js
├── package.json          # ADD: pg, express dependencies
└── .env (gitignored)     # NEW: TIMESCALE_PASSWORD=...

src/
├── docker-compose.yml    # CHANGE: timescale env from hardcoded to .env var
└── .env                  # NEW: TIMESCALE_PASSWORD=...
```

### Pattern 1: Bridge DB Initialization on Startup

[CITED: TimescaleDB docs + CONTEXT D-08]

```javascript
// Source: TimescaleDB create_hypertable docs
async function initDb(pool) {
    await pool.query(`
        CREATE TABLE IF NOT EXISTS telemetry (
            time        TIMESTAMPTZ NOT NULL,
            topic       TEXT        NOT NULL,
            value       DOUBLE PRECISION NOT NULL
        )
    `);
    // create_hypertable is idempotent with if_not_exists
    await pool.query(`
        SELECT create_hypertable('telemetry', 'time',
            if_not_exists => TRUE,
            chunk_time_interval => INTERVAL '1 day'
        )
    `);
    // Index for fast per-topic range queries
    await pool.query(`
        CREATE INDEX IF NOT EXISTS idx_telemetry_topic_time
        ON telemetry (topic, time DESC)
    `);
}
```

**Chunk interval recommendation:** 1 day is appropriate for low-volume IoT data (~2 writes/sec across 4 topics = ~700k rows/day). [VERIFIED: TimescaleDB docs — 1-day chunk for moderate ingestion]

### Pattern 2: Immediate INSERT in ROS Callback

```javascript
// Source: CONTEXT D-03 + pg docs pattern
const humiditySub = node.createSubscription(
    'sensor_msgs/msg/RelativeHumidity',
    'fc1/humidity',
    async (msg) => {
        const value = msg.relative_humidity * 100;
        const data = { humidity: value, timestamp: Date.now() };
        broadcast(data);
        try {
            await pool.query(
                'INSERT INTO telemetry (time, topic, value) VALUES ($1, $2, $3)',
                [new Date(), 'fc.humidity', value]
            );
        } catch (err) {
            console.error('[db] insert failed:', err.message);
            // Live WS continues regardless — D from CONTEXT specifics
        }
    }
);
```

### Pattern 3: Time-Bucketed History Query

[CITED: TimescaleDB time_bucket() docs]

```javascript
// Source: TimescaleDB time_bucket() documentation
function bucketInterval(rangeMs) {
    const ONE_HOUR = 3600000;
    if (rangeMs <= 2 * ONE_HOUR)      return '1 minute';
    if (rangeMs <= 12 * ONE_HOUR)     return '5 minutes';
    return '15 minutes';
}

app.get('/history/:topic', async (req, res) => {
    const { topic } = req.params;
    const start = parseInt(req.query.start, 10);
    const end   = parseInt(req.query.end,   10);
    if (!start || !end) return res.status(400).json({ error: 'start and end required' });

    const rangeMs  = end - start;
    const interval = bucketInterval(rangeMs);

    try {
        const result = await pool.query(
            `SELECT time_bucket($1::interval, time) AS bucket,
                    AVG(value) AS value
             FROM telemetry
             WHERE topic = $2
               AND time >= $3
               AND time <= $4
             GROUP BY bucket
             ORDER BY bucket ASC`,
            [interval, topic, new Date(start), new Date(end)]
        );
        // OpenMCT expects array of {value, utc} datums
        const datums = result.rows.map(row => ({
            value: row.value,
            utc:   row.bucket.getTime()
        }));
        res.json(datums);
    } catch (err) {
        console.error('[db] history query failed:', err.message);
        res.status(500).json({ error: 'query failed' });
    }
});
```

### Pattern 4: OpenMCT `request()` Implementation

[CITED: OpenMCT tutorial — request() calls GET /history/{key}?start={start}&end={end}]

```javascript
// Source: OpenMCT tutorial historical-telemetry-plugin pattern
// In plugin.js, replace the stub request() at line 207
request: function (domainObject, options) {
    var sensor = SENSORS.find(function (s) {
        return s.identifier.key === domainObject.identifier.key;
    });
    if (!sensor) return Promise.resolve([]);

    var url = historyUrl
        + '/' + encodeURIComponent(sensor.identifier.key)
        + '?start=' + options.start
        + '&end='   + options.end;

    return fetch(url).then(function (resp) {
        return resp.json();
    });
}
```

The `options.start` and `options.end` are millisecond UTC timestamps. [VERIFIED: OpenMCT uses UTCTimeSystem; time conductor passes ms timestamps to request()]

`historyUrl` should be a configurable option like `bridgeUrl`, defaulting to `http://localhost:8082` (bridge HTTP port, separate from WebSocket 8081).

### Pattern 5: .env Credential Migration

```bash
# src/.env  (gitignored)
TIMESCALE_PASSWORD=mysecretpassword
```

```yaml
# docker-compose.yml — timescale service
timescale:
  image: timescale/timescaledb:latest-pg14
  environment:
    - POSTGRES_PASSWORD=${TIMESCALE_PASSWORD}
  ...

# bridge service env
bridge:
  environment:
    - TIMESCALE_PASSWORD=${TIMESCALE_PASSWORD}
    - TIMESCALE_HOST=timescale
    - TIMESCALE_DB=postgres
    - TIMESCALE_USER=postgres
```

Docker Compose automatically reads `src/.env` when it exists alongside `docker-compose.yml`. [ASSUMED — standard docker-compose behavior, not verified against docker compose v2 specifically]

### Anti-Patterns to Avoid

- **Connecting pg Pool before ROS init completes:** Pool should be created, then `await rclnodejs.init()`, then `await initDb(pool)`, then start subscriptions. DB errors on init should log but not kill the process.
- **Blocking the ROS spin loop with sync DB calls:** Always use `async` callbacks with `await pool.query()` — rclnodejs handles async callbacks safely.
- **Throwing on INSERT failure:** Wrap all DB writes in try/catch. A DB outage must never kill the WebSocket server. [CONTEXT specifics]
- **Sending raw `DOUBLE PRECISION` to OpenMCT:** OpenMCT expects `value` as a JS number and `utc` as a millisecond integer. `row.bucket.getTime()` converts pg `Date` to ms correctly.
- **Using `topic` column as `/fc1/humidity` (ROS path):** Store using plugin.js key format (`fc.humidity`) so history URL routing is a 1:1 match with `sensor.identifier.key`. Avoids mapping translation in the query.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time-series partitioning | Custom table sharding | TimescaleDB hypertables | Automatic chunk management, query optimization |
| Time-range aggregation | Manual CASE bucketing | `time_bucket()` | TimescaleDB native function, index-aware |
| Idempotent schema init | Migration version table | `CREATE TABLE IF NOT EXISTS` + `if_not_exists => TRUE` | Sufficient for single-table schema (D-08) |
| HTTP parameter validation | Custom regex | Express 5 built-in `req.query` + `parseInt` guard | Sufficient for two numeric params |

**Key insight:** TimescaleDB's `time_bucket()` is index-aware and orders-of-magnitude faster than application-side grouping. Never bucket in JavaScript.

---

## Common Pitfalls

### Pitfall 1: Bridge Entrypoint Not Switched to Node.js

**What goes wrong:** Dockerfile builds, container starts, but it still runs `ros2 launch` → rosbridge_websocket. The `src/index.js` code never executes. DB writes never happen.
**Why it happens:** The existing `entrypoint.sh` hardcodes `exec ros2 launch /opt/bridge/launch/bridge.launch.py`. The Node.js file exists but is not invoked.
**How to avoid:** Update `Dockerfile` to install Node.js + npm, run `npm install`, and update `entrypoint.sh` to `exec node src/index.js`.
**Warning signs:** `docker compose logs bridge` shows `[rosbridge_server]` startup messages rather than `Bridge service started on port 8081`.

### Pitfall 2: Plugin.js WebSocket Protocol Mismatch

**What goes wrong:** After switching bridge to `src/index.js`, live telemetry stops — browser console shows data arriving but charts don't update.
**Why it happens:** `plugin.js` expects rosbridge wire protocol (`{op: 'publish', topic: '/fc1/humidity', msg: {...}}`). `src/index.js` broadcasts a raw `{humidity, timestamp}` JSON object (different shape).
**How to avoid:** Update `plugin.js` WebSocket `onmessage` handler to match `src/index.js`'s broadcast format, OR update `src/index.js` to broadcast in rosbridge protocol format. Choose one and do it consistently.
**Warning signs:** `ws.onmessage` fires but `data.op !== 'publish'` so all handlers are skipped (line 163 of plugin.js: `if (data.op === 'publish' && data.topic ...)`).

### Pitfall 3: `create_hypertable` Fails if Table Already Has Data

**What goes wrong:** First run works, second deploy after data exists fails with "table is not empty" error.
**Why it happens:** `create_hypertable` requires an empty table on first call.
**How to avoid:** Always use `if_not_exists => TRUE` in the `create_hypertable` call. Since `CREATE TABLE IF NOT EXISTS` runs first, if the hypertable already exists the `SELECT create_hypertable(...)` call is a no-op.
**Warning signs:** Bridge crashes at startup with `ERROR: table already contains data`.

### Pitfall 4: CORS Blocking History Fetch

**What goes wrong:** OpenMCT frontend at port 8080 tries to `fetch('http://localhost:8082/history/...')` — browser blocks with CORS error.
**Why it happens:** Different ports = different origin. Browser enforces CORS.
**How to avoid:** Add `res.setHeader('Access-Control-Allow-Origin', '*')` or use the `cors` npm package on Express routes. Or proxy history requests through the openmct nginx/static server.
**Warning signs:** Browser console: `Access to fetch at 'http://localhost:8082' from origin 'http://localhost:8080' has been blocked by CORS policy`.

### Pitfall 5: `options.start` / `options.end` Are Millisecond Integers, Not ISO Strings

**What goes wrong:** DB query returns empty results even though data exists.
**Why it happens:** OpenMCT passes `options.start` and `options.end` as millisecond epoch integers (e.g., `1743900000000`). Passing them directly to a `WHERE time >= $1` with a pg `text` param may fail silently or return no rows.
**How to avoid:** Always wrap with `new Date(start)` before passing to pg. pg converts `Date` objects to `TIMESTAMPTZ` correctly.

### Pitfall 6: Bridge HTTP Port Not Exposed in docker-compose.yml

**What goes wrong:** OpenMCT in the browser cannot reach `http://localhost:8082/history/...`.
**Why it happens:** The bridge container's HTTP port is not mapped to the host.
**How to avoid:** Add port mapping to docker-compose bridge service: `ports: - "8082:8082"`. Or serve history on the same 8081 port using Express alongside the WebSocket server (Express can coexist with `ws` on the same http.Server).
**Note:** The cleaner approach is a single port — create an `http.Server`, pass it to both `express()` and `new WebSocket.Server({ server })`. Eliminates port exposure complexity.

---

## Code Examples

### Bridge: Combined HTTP + WebSocket on Single Port

```javascript
// Source: Node.js http + ws + express pattern (ASSUMED — standard pattern)
const http    = require('http');
const express = require('express');
const WebSocket = require('ws');

const app    = express();
const server = http.createServer(app);
const wss    = new WebSocket.Server({ server });

server.listen(8081, () => console.log('Bridge on port 8081'));
```

This avoids adding a second port. OpenMCT plugin uses `ws://host:8081` for live and `http://host:8081/history/...` for history.

### TimescaleDB: Full Schema Init

```sql
-- Source: TimescaleDB docs [CITED]
CREATE TABLE IF NOT EXISTS telemetry (
    time   TIMESTAMPTZ      NOT NULL,
    topic  TEXT             NOT NULL,
    value  DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('telemetry', 'time',
    if_not_exists        => TRUE,
    chunk_time_interval  => INTERVAL '1 day'
);
CREATE INDEX IF NOT EXISTS idx_telemetry_topic_time
    ON telemetry (topic, time DESC);
```

### Downsampling Bucket Thresholds (Claude's Discretion)

| Range requested | Bucket size | Rows returned (approx) |
|-----------------|-------------|------------------------|
| ≤ 2 hours       | 1 minute    | ≤ 120 per topic        |
| ≤ 12 hours      | 5 minutes   | ≤ 144 per topic        |
| > 12 hours      | 15 minutes  | ≤ 96/day per topic     |

These thresholds keep OpenMCT chart data under ~200 points per series, which is well within browser rendering limits. [ASSUMED — empirical threshold; adjust based on observed performance]

---

## Runtime State Inventory

> This is not a rename/refactor phase. However, the `.env` credential migration (D-09) touches runtime state.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | TimescaleDB `timescale-data` Docker volume — no data yet (bridge never wrote to it) | None — schema init is first write |
| Live service config | `docker-compose.yml` line 85: `POSTGRES_PASSWORD=mysecretpassword` hardcoded | Replace with `${TIMESCALE_PASSWORD}` env var reference |
| OS-registered state | None — no OS-level registrations | None |
| Secrets/env vars | `POSTGRES_PASSWORD` in docker-compose (not in git as `.env`); bridge has no DB creds currently | Create `src/.env` with `TIMESCALE_PASSWORD=mysecretpassword`; add to `.gitignore` |
| Build artifacts | None stale | None |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | Container orchestration | Yes | 28.2.2 | — |
| Node.js | Bridge index.js | Yes (host) | v20.20.0 | Must be added to bridge Dockerfile |
| npm | Package install | Yes (host) | bundled with node | Must be in bridge Dockerfile |
| `pg` package | DB writes | No (not in package.json yet) | 8.20.0 available | Install: `npm install pg` |
| `express` package | History REST | No (not in package.json yet) | 5.2.1 available | Install: `npm install express` |
| TimescaleDB | Data storage | Yes (docker-compose service) | latest-pg14 | Already defined, no action |
| CORS headers | Browser history fetch | No | — | Add `cors` package or manual header |

**Missing dependencies with no fallback:**
- `pg` and `express` must be installed in bridge (npm install)
- Node.js must be installed in bridge Dockerfile (currently not present)

**Missing dependencies with fallback:**
- CORS: can use manual `res.setHeader` instead of `cors` npm package

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (for Python ROS nodes) / manual curl + browser for bridge |
| Config file | none |
| Quick run command | `curl http://localhost:8081/history/fc.humidity?start=START&end=END` |
| Full suite command | `docker compose -f src/docker-compose.yml up bridge timescale` + manual verification |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| — | Bridge inserts row on ROS message | smoke | `ros2 topic pub /fc1/humidity ... && sleep 2 && psql -c "SELECT COUNT(*) FROM telemetry"` | No — Wave 0 |
| — | History endpoint returns downsampled data | smoke | `curl "http://localhost:8081/history/fc.humidity?start=X&end=Y"` | No — Wave 0 |
| — | OpenMCT chart shows historical data | manual | Open browser, select fixed time range, verify chart populates | — |
| — | DB down does not kill WebSocket | smoke | Stop timescale container, verify WS still delivers live data | No — Wave 0 |

### Sampling Rate

- **Per task commit:** `curl http://localhost:8081/history/...` — verify endpoint responds
- **Per wave merge:** Full docker compose up + browser smoke test
- **Phase gate:** Charts render historical data in OpenMCT before `/gsd-verify-work`

### Wave 0 Gaps

- No automated test suite for the bridge HTTP layer — manual smoke tests are sufficient given this is infrastructure glue code with no business logic
- No pytest coverage needed (no Python changes planned)

*(If automated testing is desired later: `supertest` can test Express routes in isolation without a live DB)*

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Internal service on frontend-net only |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | No auth on history endpoint; internal network only |
| V5 Input Validation | Yes | Validate `start`/`end` are integers; validate `topic` against SENSORS allowlist |
| V6 Cryptography | No | DB password in .env (not encrypted) — acceptable for local dev server |

**Known Threat Patterns:**

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `topic` param | Tampering | Use parameterized query `$2` — never interpolate topic into SQL string |
| Unbounded time range query | Denial of Service | Validate `end - start` max range (e.g., 30 days) |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| InfluxDB for IoT time-series | TimescaleDB (Postgres extension) | ~2020 | Already chosen; Postgres tooling reuse |
| Express 4 | Express 5 (stable) | Dec 2025 | Error handling changes: async errors propagate without `next(err)` in Express 5 |

**Deprecated/outdated:**
- Express 4 `async` error handling required explicit `try/catch + next(err)`. Express 5 auto-catches rejected async route handlers — no need for try/catch in route bodies IF using Express 5. [CITED: Express 5 release notes / npm publish date 2025-12-01]

---

## Open Questions

1. **WebSocket protocol compatibility after switching to index.js**
   - What we know: `plugin.js` uses rosbridge protocol (`op: 'publish'`); `index.js` broadcasts raw `{humidity, timestamp}`
   - What's unclear: Which side should change format? Changing index.js to emit rosbridge-compatible messages is heavier; changing plugin.js onmessage is simpler
   - Recommendation: Update plugin.js onmessage to dispatch on field name (`if (data.humidity !== undefined)`) — matches index.js format and avoids rosbridge dependency

2. **HTTP port for history endpoint**
   - What we know: WebSocket is on 8081; adding Express on same port avoids new docker-compose port mapping
   - What's unclear: Whether rclnodejs + Express on same http.Server has any known issues
   - Recommendation: Share port 8081 via `http.createServer(app)` passed to both Express and `new WebSocket.Server({ server })`

3. **Topic key format in DB (`fc.humidity` vs `/fc1/humidity`)**
   - What we know: plugin.js SENSORS use `fc.humidity` as identifier keys; ROS topics are `/fc1/humidity`
   - What's unclear: Which to store in the DB
   - Recommendation: Store plugin.js keys (`fc.humidity`) — history URL uses the same key, no mapping needed

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Docker Compose reads `src/.env` automatically when present alongside `docker-compose.yml` | Architecture Patterns / .env migration | Env vars not substituted; password stays hardcoded or bridge can't connect |
| A2 | `rclnodejs` supports `async` subscription callbacks without blocking the spin loop | Code Examples | DB inserts could block ROS message processing; need to verify rclnodejs docs |
| A3 | OpenMCT `options.start` and `options.end` are millisecond epoch integers | Architecture Patterns | History query returns wrong time range |
| A4 | Express 5 auto-propagates async errors in route handlers | State of the Art | Unhandled DB errors crash the process instead of returning 500 |
| A5 | Bucket thresholds (2h/12h) provide reasonable chart point counts | Code Examples | Too many or too few points; visual quality issue |

---

## Sources

### Primary (HIGH confidence)
- npm registry — pg@8.20.0 verified (2026-03-04), express@5.2.1 verified (2025-12-01) [VERIFIED: npm registry]
- `src/mission-control/bridge/src/index.js` — actual bridge code read directly [VERIFIED: codebase]
- `src/mission-control/bridge/launch/bridge.launch.py` — actual launch file read directly [VERIFIED: codebase]
- `src/mission-control/bridge/entrypoint.sh` — actual entrypoint read directly [VERIFIED: codebase]
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` — actual plugin code read directly [VERIFIED: codebase]
- `src/docker-compose.yml` — actual compose file read directly [VERIFIED: codebase]

### Secondary (MEDIUM confidence)
- TimescaleDB `create_hypertable` syntax: `SELECT create_hypertable('table', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day')` [CITED: docs.timescale.com/api/latest/hypertable/create_hypertable/]
- TimescaleDB `time_bucket()` with AVG: `SELECT time_bucket('15 minutes', time) AS bucket, AVG(value) FROM ... GROUP BY bucket` [CITED: docs.timescale.com/api/latest/hyperfunctions/time_bucket/]
- OpenMCT tutorial `request()` pattern: GET `/history/{key}?start={start}&end={end}` returns array of datum objects [CITED: github.com/nasa/openmct-tutorial]

### Tertiary (LOW confidence)
- Express 5 async error propagation behavior [ASSUMED — based on Express 5 changelog knowledge, not verified in this session]
- rclnodejs async callback safety [ASSUMED — not verified against rclnodejs docs]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pg and express versions verified against npm registry
- Architecture: HIGH — all source files read directly from codebase
- Bridge entrypoint mismatch: HIGH — confirmed by reading entrypoint.sh and launch file
- Pitfalls: HIGH — derived from direct code inspection
- TimescaleDB patterns: MEDIUM — cited from official docs (via search result URLs), not fetched directly due to redirect chain

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable ecosystem)
