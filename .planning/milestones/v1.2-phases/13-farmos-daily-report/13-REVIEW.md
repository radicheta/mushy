---
phase: 13-farmos-daily-report
reviewed: 2026-04-13T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - docker-compose.override.yml
  - docker-compose.yml
  - src/farmos-agent/Dockerfile
  - src/farmos-agent/entrypoint.sh
  - src/farmos-agent/farmos_agent/farmos_agent_node.py
  - src/farmos-agent/farmos_agent/farmos_client.py
  - src/farmos-agent/farmos_agent/report_builder.py
  - src/farmos-agent/farmos_agent/telemetry_query.py
  - src/farmos-agent/setup.py
  - src/farmos-agent/tests/conftest.py
  - src/mission-control/bridge/src/index.js
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-04-13
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the new `farmos-agent` service and its integration with the bridge and docker-compose stack. The Python code is well-structured with good separation of concerns across `farmos_client`, `telemetry_query`, and `report_builder`. SQL injection is properly guarded with parameterized queries. Credentials are correctly sourced from environment variables.

Two critical issues were found: the `upload_photo` function bypasses the authenticated session by creating a bare `requests.post` call (losing cookies and CSRF token), and the bridge's `/camera/latest.jpg` endpoint serves stale frames from any prior session with no age check, meaning the farmos-agent can silently post a photo that is days old.

Four warnings cover error-handling gaps: `create_observation` can raise on network failure and the caller does not distinguish partial success (photo uploaded, observation failed), `_db_conn` is not reconnected if the long-running connection goes stale, the `get_asset_uuid` pagination assumption breaks silently if FarmOS returns more than one page of structure assets, and the `observation_exists_for_date` duplicate check uses a CONTAINS filter that could match a substring (e.g., "FC-1 Daily Report 2026-04-1" matches "2026-04-10" and "2026-04-11" through "2026-04-19").

## Critical Issues

### CR-01: `upload_photo` drops session cookies and CSRF token

**File:** `src/farmos-agent/farmos_agent/farmos_client.py:100`
**Issue:** `upload_photo` calls `requests.post(...)` directly instead of `session.post(...)`. The authenticated `requests.Session` object (which holds the session cookie and `X-CSRF-Token` header from `get_session`) is not used. The function manually copies headers from `session.headers` but does not attach the session's cookie jar. FarmOS requires the session cookie for authentication and the CSRF token for write operations (T-13-03). A bare `requests.post` call will send the CSRF token header but not the authenticated session cookie, causing the request to be rejected with a 403 or 401.

**Fix:**
```python
def upload_photo(
    session: requests.Session,
    farmos_url: str,
    jpeg_bytes: bytes,
    filename: str = 'fc1-daily.jpg',
) -> str | None:
    # Use session.post — preserves cookie jar AND allows Content-Type override
    resp = session.post(
        f"{farmos_url}/api/log/observation/image",
        headers={
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': f'file; filename="{filename}"',
        },
        data=jpeg_bytes,
        timeout=30,
    )
    if resp.ok:
        return resp.json()['data']['id']
    return None
```

---

### CR-02: Bridge serves stale camera frames with no age guard

**File:** `src/mission-control/bridge/src/index.js:258-268` and `src/farmos-agent/farmos_agent/farmos_agent_node.py:261-268`
**Issue:** `GET /camera/latest.jpg` returns `latestFrame` with no timestamp check. `lastFrameTime` is tracked but never consulted by the endpoint. If the bridge restarts without a live camera, `latestFrame` remains `null` (returns 503 — OK). However if the bridge stays running but the camera disconnects, `latestFrame` retains the last received frame indefinitely — potentially hours or days old. The farmos-agent log will say "camera snapshot fetched from bridge" and attach a stale image to the FarmOS observation with no warning. This is a correctness issue: the report is supposed to document the current day.

**Fix in `index.js`** — add a staleness guard to the endpoint (e.g., 2 hours):
```javascript
const FRAME_MAX_AGE_MS = 2 * 60 * 60 * 1000; // 2 hours

app.get('/camera/latest.jpg', (req, res) => {
    const stale = !latestFrame
        || !lastFrameTime
        || (Date.now() - lastFrameTime > FRAME_MAX_AGE_MS);
    if (stale) {
        return res.status(503).json({ error: 'No recent camera frame available' });
    }
    res.writeHead(200, {
        'Content-Type': 'image/jpeg',
        'Content-Length': latestFrame.length,
        'Cache-Control': 'no-cache'
    });
    res.end(latestFrame);
});
```

Apply the same guard to `/camera/snapshot` for consistency.

---

## Warnings

### WR-01: `observation_exists_for_date` CONTAINS filter can false-positive on date substrings

**File:** `src/farmos-agent/farmos_agent/farmos_client.py:177-186`
**Issue:** The duplicate-check query uses `filter[name][operator]=CONTAINS` with the value `FC-1 Daily Report YYYY-MM-DD`. A CONTAINS (substring) match for `FC-1 Daily Report 2026-04-1` would match observations for 2026-04-10 through 2026-04-19. For a date like `2026-04-10`, the query value is `FC-1 Daily Report 2026-04-10`, which is specific — but `2026-04-1` (without trailing zero, not applicable here since `strftime('%Y-%m-%d')` always zero-pads) is the edge case. More importantly, CONTAINS means a report named `FC-1 Daily Report 2026-04-10 (amended)` would block the real report. Use an exact match operator instead.

**Fix:**
```python
params={
    'filter[name][value]': f'FC-1 Daily Report {date_str}',
    'filter[name][operator]': '=',
}
```

---

### WR-02: Long-running psycopg2 connection will go stale without reconnect logic

**File:** `src/farmos-agent/farmos_agent/farmos_agent_node.py:71-78` and `telemetry_query.py:70`
**Issue:** `self._db_conn` is opened once during `on_configure` and reused for the lifetime of the container. PostgreSQL will close idle connections after `tcp_keepalives_idle` (default varies, often 2 hours on Linux). After a network hiccup or server-side timeout, `cursor.execute` in `query_daily_summary` will raise `psycopg2.OperationalError: connection closed`. The outer `try/except Exception` in `execute_report` will catch this, log it, and skip the report — silently missing the day with no retry. A reconnect attempt should be added.

**Fix — add a helper method and call it before querying:**
```python
def _ensure_db_conn(self):
    """Reconnect if the connection has gone away."""
    try:
        self._db_conn.cursor().execute('SELECT 1')
    except Exception:
        self.get_logger().warning('[farmos_agent] DB connection lost — reconnecting')
        try:
            self._db_conn.close()
        except Exception:
            pass
        timescale_host = os.environ.get('TIMESCALE_HOST', 'localhost')
        self._db_conn = psycopg2.connect(
            host=timescale_host,
            port=5432,
            dbname='postgres',
            user='postgres',
            password=self._farmos_password,  # already loaded in on_configure
            connect_timeout=10,
        )
```
Note: `_farmos_password` is already stored on `self` for the session re-auth path, so this does not require storing the TimescaleDB password separately — but you would need to store `timescale_password` on `self` during `on_configure` similarly to how `_farmos_password` is stored.

---

### WR-03: `get_asset_uuid` does not handle paginated FarmOS responses

**File:** `src/farmos-agent/farmos_agent/farmos_client.py:69-79`
**Issue:** The function iterates over `resp.json().get('data', [])` from a single GET to `/api/asset/structure`. The FarmOS JSON:API returns paginated results (default page size 50). If the farm has more than 50 structure assets, `FC-1` may not appear on the first page. The function would return `None`, log a warning, and skip the report. This is a latent bug that will surface when the farm grows.

**Fix — follow JSON:API `links.next` pagination:**
```python
url = f"{farmos_url}/api/asset/structure"
while url:
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    for item in body.get('data', []):
        if item['attributes'].get('name') == asset_name:
            uuid = item['id']
            cache[cache_key] = uuid
            return uuid
    url = (body.get('links') or {}).get('next', {}).get('href')
return None
```

---

### WR-04: Partial-success state not handled when photo upload succeeds but observation creation fails

**File:** `src/farmos-agent/farmos_agent/farmos_agent_node.py:202-226`
**Issue:** If `upload_photo` returns a `file_id` but `create_observation` then raises (network error, 5xx from FarmOS), the uploaded file entity is orphaned in FarmOS with no observation attached. On the next scheduled run, `observation_exists_for_date` returns `False` so the agent tries again — but `upload_photo` is called again, creating a second orphaned file. The duplicate check does not prevent double photo uploads. This is not a data-loss issue but leaves orphaned file entities in FarmOS and means the photo always gets re-uploaded on each retry attempt.

**Fix — capture and log the `file_id`, then consider wrapping the record phase in a try that re-uses the already-uploaded `file_id` on retry, or accept orphaned files as an acceptable trade-off and document the behavior in a comment.** At minimum, log the `file_id` before calling `create_observation` so a manual cleanup is possible:
```python
if file_id:
    self.get_logger().info(
        f'[farmos_agent] photo uploaded — file_id: {file_id} — creating observation'
    )
obs_uuid = create_observation(...)  # if this raises, file_id is logged above
```

---

## Info

### IN-01: Humidity telemetry mismatch between bridge and report_builder

**File:** `src/mission-control/bridge/src/index.js:323-327` and `src/farmos-agent/farmos_agent/report_builder.py:17`
**Issue:** The bridge stores `fc.humidity` as `msg.relative_humidity * 100` (i.e., already multiplied by 100, stored as a percentage like 82.3). The `report_builder` then formats humidity as `round(avg * 100, 1)`, which would display 8230% instead of 82.3%. This is a latent display bug if the values in `telemetry` are stored as percentages. However, the `conftest.py` fixture uses `0.823` for humidity avg, which is the fractional form — suggesting the test expectation matches the report_builder's assumption (fractional), not the bridge's storage (percentage). **This needs verification against live data.** If the bridge is storing 82.3 in the DB, the report_builder must change `lambda avg: f'{round(avg * 100, 1)}'` to `lambda avg: f'{round(avg, 1)}'`.

---

### IN-02: `timescale/timescaledb:latest-pg14` image tag is not pinned

**File:** `docker-compose.yml:33`
**Issue:** Using `latest-pg14` means a `docker compose pull` could silently pull a breaking TimescaleDB patch release. For a production system storing persistent telemetry, pin to a specific digest or version tag (e.g., `2.14.2-pg14`).

---

### IN-03: `setup.py` uses placeholder maintainer email

**File:** `src/farmos-agent/setup.py:17`
**Issue:** `maintainer_email='santi@example.com'` is a placeholder. Not a functional issue but worth updating to the real address before the package is distributed.

---

_Reviewed: 2026-04-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
