---
phase: 07-historical-data-storage-and-openmct-time-series-visualization
reviewed: 2026-04-07T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - src/docker-compose.yml
  - src/mission-control/bridge/Dockerfile
  - src/mission-control/bridge/entrypoint.sh
  - src/mission-control/bridge/package.json
  - src/mission-control/bridge/src/index.js
  - src/mission-control/frontend/index.html
  - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-04-07T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the mission-control bridge (Node.js WebSocket + REST history server), OpenMCT frontend plugin, and docker-compose orchestration for the new TimescaleDB historical telemetry feature. The bridge code is well-structured with good security practices (topic allowlist, parameterized queries, range caps). One critical issue: a hardcoded fallback database password in source code. Three warnings around input validation logic, database exposure, and overly broad CORS. Two informational items on dead code and minor shell hardening.

## Critical Issues

### CR-01: Hardcoded fallback database password

**File:** `src/mission-control/bridge/src/index.js:12`
**Issue:** The PostgreSQL pool constructor falls back to `'mysecretpassword'` when `TIMESCALE_PASSWORD` is not set. If the environment variable is ever missing (misconfigured deploy, local dev without `.env`), the bridge connects with this well-known password. Since TimescaleDB is exposed on host port 5432 (docker-compose line 95), an attacker on the network could authenticate with this password.
**Fix:** Remove the fallback and fail fast if the variable is absent:
```javascript
const pool = new Pool({
    host: process.env.TIMESCALE_HOST || 'timescale',
    database: process.env.TIMESCALE_DB || 'postgres',
    user: process.env.TIMESCALE_USER || 'postgres',
    password: process.env.TIMESCALE_PASSWORD,  // required — no fallback
    port: 5432
});

if (!process.env.TIMESCALE_PASSWORD) {
    console.error('[db] TIMESCALE_PASSWORD env var is required');
    process.exit(1);
}
```

## Warnings

### WR-01: parseInt validation rejects valid zero epoch via falsy check

**File:** `src/mission-control/bridge/src/index.js:85`
**Issue:** The check `if (!start || !end || isNaN(start) || isNaN(end))` uses JavaScript truthiness. `parseInt('0', 10)` returns `0`, and `!0` is `true`, so a request with `start=0` would be incorrectly rejected. More practically, if OpenMCT ever sends `start=0` for "beginning of time" queries, the endpoint returns a 400 error. The `isNaN` checks alone are sufficient for validating that the values parsed correctly.
**Fix:**
```javascript
if (isNaN(start) || isNaN(end)) {
    return res.status(400).json({ error: 'start and end query params required (ms epoch)' });
}
```

### WR-02: TimescaleDB port exposed to all host interfaces

**File:** `src/docker-compose.yml:95`
**Issue:** `ports: "5432:5432"` binds TimescaleDB to `0.0.0.0:5432` on the host, making the database accessible from any network interface (including WireGuard tunnel peers or LAN). Combined with CR-01 (hardcoded fallback password), this creates a direct attack surface.
**Fix:** Bind only to localhost if the bridge is the sole consumer (it uses `network_mode: host` so localhost works):
```yaml
ports:
  - "127.0.0.1:5432:5432"
```

### WR-03: Wildcard CORS allows any origin

**File:** `src/mission-control/bridge/src/index.js:53`
**Issue:** `Access-Control-Allow-Origin: *` allows any web page to call the history REST API. While this is common in development, in production any site the user visits could exfiltrate telemetry data from the bridge if they know the IP.
**Fix:** Restrict to the known OpenMCT origin:
```javascript
app.use((req, res, next) => {
    const origin = req.headers.origin;
    const allowed = process.env.CORS_ORIGIN || 'http://localhost:8080';
    if (origin === allowed) {
        res.setHeader('Access-Control-Allow-Origin', origin);
    }
    next();
});
```

## Info

### IN-01: Client sends rosbridge subscribe/unsubscribe ops that server ignores

**File:** `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js:149`
**Issue:** The `sendIfOpen()` calls on lines 149, 220, and 229 send `{ op: 'subscribe', topic: ... }` and `{ op: 'unsubscribe', ... }` messages to the bridge WebSocket server. However, the bridge server (`index.js` lines 128-136) has no message handler for incoming WS messages -- it only broadcasts. These subscribe/unsubscribe ops are dead code inherited from the previous rosbridge protocol. They cause no harm but add confusion about the intended protocol.
**Fix:** Remove the `sendIfOpen` calls related to subscribe/unsubscribe in `plugin.js`, or add a no-op `ws.on('message', ...)` handler in the bridge with a comment explaining that subscription filtering is not implemented (all clients receive all topics).

### IN-02: entrypoint.sh missing pipefail

**File:** `src/mission-control/bridge/entrypoint.sh:2`
**Issue:** The script uses `set -e` but not `set -euo pipefail`. Since the script is simple (source + exec), this is low risk, but `pipefail` is a shell best practice for catching failures in piped commands.
**Fix:**
```bash
#!/bin/bash
set -euo pipefail
```

---

_Reviewed: 2026-04-07T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
