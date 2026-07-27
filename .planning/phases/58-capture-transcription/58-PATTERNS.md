# Phase 58: Capture + Transcription - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 9 (5 capture module files + 4 test files)
**Analogs found:** 9 / 9 (every file has a Node port-target AND a Python idiom analog)

> This is a **Node→Python port phase** under v1.12. Two analog axes apply to every file:
> 1. **Node port-target** — the behavioral spec (what to translate).
> 2. **Python idiom analog** — the established idiom on disk (the shape to mirror exactly).
>
> Tests live in `tests/` (flat `tests/test_capture_*.py`), consistent with Phase 57's
> on-disk layout (`tests/test_signal_*.py`). Inject fake capture pipeline via a fake dict
> (`{"handle": ..., "record_reply_capture": ...}`) mirroring the `FakeOutboundRepo` pattern
> in `conftest.py`.

---

## File Classification

| New File | Role | Data Flow | Node Port-Target | Python Idiom Analog | Match |
|----------|------|-----------|------------------|---------------------|-------|
| `farm_agent/capture/__init__.py` | config | — | — | `farm_agent/signal_io/__init__.py` | role-match |
| `farm_agent/capture/pipeline.py` | service (factory) | event-driven (envelope→capture row) | `capture.js` (`createCapturePipeline`, `handle`, `recordReplyCapture`) | `signal_io/receive_loop.py` (factory + injected deps + sequential await) | exact |
| `farm_agent/capture/transcribe_client.py` | service (HTTP client) | request-response (never-throws) | `transcribe-client.js` (`createTranscribeClient`) | `signal_io/client.py` (httpx + constructor injection + discriminated result) | exact |
| `farm_agent/capture/capture_repo.py` | repository | CRUD (INSERT, UPDATE) | `capture-db.js` (`insertCapture`, `markExpiredOlderThan`) | `persistence/outbound_repo.py` (psycopg3 fail-open INSERT, `%s` params, `Jsonb` for jsonb only) | exact |
| `farm_agent/capture/capture_history.py` | repository | CRUD (SELECT) | `capture-history.js` (`createCaptureHistory`, `selectRecentBySender`, `selectRecentOutboundByRecipient`) | `persistence/outbound_repo.py` (psycopg3 `async with pool.connection()`, typed result) | role-match |
| `farm_agent/capture/retention.py` | utility (periodic task) | event-driven (asyncio loop) | `capture-retention.js` (`createRetentionJob`, daily cron) | `signal_io/receive_loop.py` (`start()`/`stop()` asyncio.Task lifecycle) | role-match |
| `tests/test_capture_pipeline.py` | test | — | (no Node test) | `tests/test_signal_receive_loop.py` (fake injected deps, async, dispatch seam) | role-match |
| `tests/test_capture_repo.py` | test | — | (no Node test) | `tests/test_signal_persist.py` (FakeRepo, fail-open assertion) | role-match |
| `tests/test_transcribe_client.py` | test | — | (no Node test) | `tests/test_signal_client.py` (respx httpx mock, async, discriminated result) | role-match |
| `tests/test_capture_history.py` | test | — | (no Node test) | `tests/test_persistence.py` (async, DB-gated, skipif socket) | role-match |

---

## Pattern Assignments

### `farm_agent/capture/pipeline.py` (service, event-driven)

**Node port-target:** `src/agents/alerter/src/capture.js` — `createCapturePipeline`, `handle`, `recordReplyCapture`
**Python idiom analog:** `farm_agent/signal_io/receive_loop.py` (factory function returning a class/dict with async methods; injected deps; sequential await; loop-never-dies per-step try/except)

**Factory + injection shape** — mirror `receive_loop.py:30-63` and `capture.js:70-92`:
```python
# receive_loop.py:50-63 — the injection shape to mirror
class ReceiveLoop:
    def __init__(
        self,
        signal_client: Any,
        dispatch: Callable[[dict], Awaitable[None]],
        config: TenantConfig,
        logger: logging.Logger | None = None,
        poll_sec: int | float | None = None,
    ) -> None:
        self._client = signal_client
        self._dispatch = dispatch
        self._config = config
        self._logger = logger or _LOG
        ...

# capture/pipeline.py should mirror this shape:
def create_capture_pipeline(
    pool: AsyncConnectionPool,
    signal_client: Any,          # duck-typed; needs fetch_attachment()
    transcribe_client: dict,     # {"transcribe": async_fn}
    config: TenantConfig,
    dispatch_result: Callable | None = None,  # Phase 59+ seam
    logger: logging.Logger | None = None,
) -> dict:
    """Factory returning {"handle": handle, "record_reply_capture": record_reply_capture}."""
```

**Sequential dispatch seam** — `handle()` is the Phase-58 entry point wired to `receive_loop.dispatch`. Never raises (mirrors `capture.js` D-03):
```python
# receive_loop.py:86-108 — per-envelope try/except pattern (loop-never-dies)
try:
    await self._dispatch(env)
except Exception as exc:  # noqa: BLE001
    self._logger.warning(
        "[receive] dispatch error for %s: %s",
        _router.mask_number(source),
        exc,
    )

# pipeline.py handle() must wrap EVERY step in its own try/except:
async def handle(envelope: dict) -> dict | None:
    try:
        # Step 1: parse
        # Step 2: download attachments
        # Step 3: transcribe
        # Step 4: insert_capture
        # Step 5: return CaptureResult
        ...
    except Exception as exc:  # noqa: BLE001 -- errors never escape handle()
        _log.warning("[capture] unhandled error in handle(): %s", exc)
        return None
```

**Farmer-slug resolution** — reuse `router.resolve_farmer` (already on disk, Phase 57):
```python
# router.py:178-187 — reuse this primitive directly
def resolve_farmer(source: str, config: TenantConfig) -> str:
    return config.signal_farmer_map.get(source) or "(unassigned)"

# In pipeline.handle():
from farm_agent.signal_io.router import resolve_farmer, _read_dm
farmos_person = resolve_farmer(source, config)
dm = _read_dm(envelope)
```

**Attachment download + D-05 disk-existence gate** — mirror `capture.js:116-142` (the V12 path-hardening + write-verify loop):
```python
# After write_bytes, always check existence before appending (D-05):
path = build_path(config.capture_base_dir, captured_at_ms, f"{capture_id}-{att_id}", ext)
Path(path).parent.mkdir(parents=True, exist_ok=True)
buf = await signal_client.fetch_attachment(att["id"])
Path(path).write_bytes(buf)
if not Path(path).exists():
    _log.warning("[capture] attachment missing after write: %s", path)
    degraded = True
    continue
attachment_paths.append(path)
```

**D-04 fail-open on transcription failure:**
```python
# mirrors capture.js:163-170
if audio_path:
    r = await transcribe_client["transcribe"](audio_path)
    if r.get("ok"):
        transcript = r.get("text")
    else:
        _log.warning("[capture] transcription failed (fail-open): %s", r.get("reason"))
        degraded = True
        transcript = None
```

**Timestamp coercion helper** — port `capture.js:134-144`, mirrors `quote.py`'s `math.isfinite(float(str(ts)))` pattern:
```python
import math

def _coerce_ts(v) -> int | None:
    if v is None:
        return None
    try:
        f = float(str(v))
        return int(f) if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None
```

**ULID + path builder** — port `capture.js:6,38-44,94`:
```python
from python_ulid import ULID
from datetime import datetime, timezone
import re
from pathlib import Path

def _generate_capture_id(captured_at_ms: int) -> str:
    dt = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
    return str(ULID.from_datetime(dt))

def build_path(base_dir: str, captured_at_ms: int, file_id: str, ext: str) -> str:
    dt = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
    day = dt.strftime("%Y-%m-%d")
    time_part = dt.strftime("%H-%M-%S")
    safe_ext = re.sub(r"[^a-z0-9]", "", ext, flags=re.IGNORECASE)
    return str(Path(base_dir) / day / f"{time_part}-{file_id}.{safe_ext}")
```

**Classify helper** — port `capture.js:12-26`:
```python
AUDIO_TYPES = frozenset(["audio/aac","audio/mp4","audio/mpeg","audio/ogg","audio/wav","audio/webm"])
IMAGE_TYPES = frozenset(["image/jpeg","image/png","image/webp","image/heic","image/heif","image/gif"])
SAFE_EXT = {
    "audio/aac":"aac","audio/mp4":"m4a","audio/mpeg":"mp3","audio/ogg":"ogg",
    "audio/wav":"wav","audio/webm":"webm","image/jpeg":"jpg","image/png":"png",
    "image/webp":"webp","image/heic":"heic","image/heif":"heif","image/gif":"gif",
}

def classify(text: str | None, attachments: list[dict]) -> str:
    has_audio = any(
        a.get("contentType") in AUDIO_TYPES or a.get("voiceNote") is True
        for a in attachments
    )
    has_image = any(a.get("contentType") in IMAGE_TYPES for a in attachments)
    if has_audio and (has_image or text):
        return "mixed"
    if has_audio:
        return "audio"
    if has_image:
        return "image"
    return "text"

def safe_ext(content_type: str) -> str:
    return SAFE_EXT.get(content_type, "bin")
```

**Imports block** (mirror `receive_loop.py:1-27` and `router.py:1-25`):
```python
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from psycopg_pool import AsyncConnectionPool
from python_ulid import ULID

from farm_agent.signal_io.router import resolve_farmer, _read_dm, mask_number
from farm_agent.tenancy.tenant import TenantConfig
```

---

### `farm_agent/capture/transcribe_client.py` (service, request-response)

**Node port-target:** `src/agents/alerter/src/transcribe-client.js` — `createTranscribeClient` factory, never-throws, dual-arg (`str | {audio_path}`)
**Python idiom analog:** `signal_io/client.py:46-90` (httpx, injected config, discriminated `{ok, ...}` / `{ok:False, reason}` result, never raises)

**Constructor injection shape** — mirror `SignalClient.__init__` (client.py:52-90). Hold the `httpx.AsyncClient` as an injected dependency (not created per-call) for testability:
```python
# client.py:52-62 — constructor injection pattern to mirror
class SignalClient:
    def __init__(
        self,
        *,
        config: TenantConfig,
        http: httpx.AsyncClient,
        ...
    ) -> None:
        self._config = config
        self.http = http
        ...
        self._api_url = config.signal_api_url

# transcribe_client.py factory mirrors this with a closure:
def create_transcribe_client(
    api_url: str,
    http: httpx.AsyncClient,
    timeout_ms: int = 200_000,
    logger: logging.Logger | None = None,
) -> dict:
    """Factory returning {"transcribe": transcribe}. Port of createTranscribeClient."""
```

**Never-throws discriminated result** — mirror `outbound_repo.py:79-85` (try/except → `{ok:False, reason}`), applied to the httpx call:
```python
# outbound_repo.py:79-85 — fail-open pattern to mirror in transcribe_client
try:
    async with pool.connection() as conn:
        await conn.execute(_INSERT_SQL, params)
    return {"ok": True}
except Exception as e:  # noqa: BLE001
    logger.warning("[outbound_repo] insert_outbound failed: %s", e)
    return {"ok": False, "reason": str(e)}

# transcribe_client wraps httpx the same way:
async def transcribe(arg) -> dict:
    audio_path = arg if isinstance(arg, str) else (arg or {}).get("audio_path")
    if not audio_path:
        return {"ok": False, "reason": "missing audio_path"}
    try:
        r = await _http.post(
            f"{_api_url}/transcribe",
            json={"audio_path": audio_path},
            timeout=_timeout_s,
        )
        if r.status_code >= 400:
            return {"ok": False, "reason": f"whisper {r.status_code}: {r.text[:200]}"}
        data = r.json()
        return {
            "ok": True,
            "text": data.get("text") or "",
            "duration_ms": data.get("duration_ms", 0),
            "language": data.get("language") or "unknown",
        }
    except httpx.TimeoutException:
        _log.warning("[transcribe] timeout after %.0fs", _timeout_s)
        return {"ok": False, "reason": "timeout"}
    except Exception as e:  # noqa: BLE001
        _log.warning("[transcribe] error: %s", e)
        return {"ok": False, "reason": str(e)}
```

**Timeout handling** — mirror `client.py:257-262` (httpx `timeout=` param; no manual AbortController needed):
```python
# client.py:256-262 — httpx timeout and status check pattern
r = await self.http.post(
    f"{self._api_url}/v2/send",
    json=payload,
    timeout=self._timeout_s,
)
if r.status_code >= 400:
    raise RuntimeError(f"signal-cli {r.status_code}: {r.text[:200]}")
```

**Imports block:**
```python
from __future__ import annotations

import logging

import httpx

from farm_agent.tenancy.tenant import TenantConfig
```

---

### `farm_agent/capture/capture_repo.py` (repository, CRUD)

**Node port-target:** `src/agents/alerter/src/capture-db.js` — `insertCapture` row shape, `markExpiredOlderThan`
**Python idiom analog:** `persistence/outbound_repo.py` — mirror exactly (SQL constant, `%s` placeholders, `async with pool.connection()`, fail-open try/except, `Jsonb` for jsonb columns only)

**Never-throws INSERT** — copy `outbound_repo.py:28-85` structure verbatim, substituting the `signal_capture` columns:
```python
# outbound_repo.py:28-85 — the exact structure to mirror
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

_INSERT_SQL = """
INSERT INTO signal_capture
  (id, captured_at, sender, message_type, raw_text, attachment_paths,
   transcript, llm_session_tag, llm_reply, degraded,
   group_id, farmos_person, reply_target_kind,
   signal_msg_ts, quote_msg_ts, quote_author_e164, corpus_context)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

async def insert_capture(pool: AsyncConnectionPool, row: dict) -> dict:
    """Insert one row into signal_capture. NEVER raises."""
    params = (
        row["id"],
        row["captured_at"],           # datetime(timezone.utc) -- never naive
        row["sender"],
        row["message_type"],
        row.get("raw_text"),
        row.get("attachment_paths", []),  # list[str] -- psycopg3 auto-adapts to text[]
        row.get("transcript"),            # str | None (None = fail-open D-04)
        None,                             # llm_session_tag (Phase 59+)
        None,                             # llm_reply (Phase 59+)
        row.get("degraded", False),
        row.get("group_id"),
        row.get("farmos_person"),
        row.get("reply_target_kind"),
        row.get("signal_msg_ts"),         # bigint | None
        row.get("quote_msg_ts"),          # bigint | None
        row.get("quote_author_e164"),
        None,                             # corpus_context -- always None for live captures
    )
    try:
        async with pool.connection() as conn:
            await conn.execute(_INSERT_SQL, params)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.warning("[capture_repo] insert_capture failed: %s", e)
        return {"ok": False, "reason": str(e)}
```

**CRITICAL pitfall:** `attachment_paths` is `text[]` (NOT jsonb). Pass `list[str]` directly — psycopg3 auto-adapts. Do NOT wrap in `Jsonb(...)`. Only `corpus_context jsonb` uses `Jsonb` (and it is always `None` in Phase 58). See RESEARCH Pitfall 1.

**`mark_expired_older_than`** — mirrors the same fail-open pattern; returns count of affected rows:
```python
_EXPIRE_SQL = """
UPDATE signal_capture
   SET expired = true
 WHERE captured_at < NOW() - (%s || ' seconds')::interval
   AND expired IS DISTINCT FROM true
"""

async def mark_expired_older_than(pool: AsyncConnectionPool, age_seconds: int) -> int:
    """Soft-expire capture rows older than age_seconds. NEVER raises. Returns row count."""
    try:
        async with pool.connection() as conn:
            result = await conn.execute(_EXPIRE_SQL, (str(age_seconds),))
            return result.rowcount or 0
    except Exception as e:  # noqa: BLE001
        logger.warning("[capture_repo] mark_expired_older_than failed: %s", e)
        return 0
```

**Imports block** (copy `outbound_repo.py:19-26`):
```python
from __future__ import annotations

import logging

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
```

---

### `farm_agent/capture/capture_history.py` (repository, SELECT)

**Node port-target:** `src/agents/alerter/src/capture-history.js` — `createCaptureHistory`, `selectRecentBySender`, `selectRecentOutboundByRecipient`
**Python idiom analog:** `persistence/outbound_repo.py` (psycopg3 `async with pool.connection()`, fail-open, returns typed result); `persistence/pool.py` (pool injected, not read from env)

**Shape to mirror:**
```python
# outbound_repo.py:79-85 pattern applied to SELECT:
async def select_recent_by_sender(
    pool: AsyncConnectionPool,
    sender: str,
    since_ms: int,
) -> list[dict]:
    """Return recent signal_capture rows for sender since since_ms. NEVER raises."""
    since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
    try:
        async with pool.connection() as conn:
            rows = await conn.execute(
                "SELECT * FROM signal_capture WHERE sender = %s AND captured_at >= %s"
                " ORDER BY captured_at DESC",
                (sender, since_dt),
            )
            return [dict(r) for r in await rows.fetchall()]
    except Exception as e:  # noqa: BLE001
        logger.warning("[capture_history] select_recent_by_sender failed: %s", e)
        return []
```

Note: `selectRecentOutboundByRecipient` joins or queries `signal_outbound` for the outbound context window used by Phase 59+ gate/extractor. Mirror the same fail-open SELECT shape.

---

### `farm_agent/capture/retention.py` (utility, asyncio periodic task)

**Node port-target:** `src/agents/alerter/src/capture-retention.js` — `createRetentionJob`, daily `cron.schedule`, `markExpiredOlderThan`
**Python idiom analog:** `signal_io/receive_loop.py:114-143` (asyncio.Task lifecycle: `start()`/`stop()`, `asyncio.create_task`, `asyncio.CancelledError` swallowed)

**Task lifecycle** — copy `receive_loop.py:114-143` shape:
```python
# receive_loop.py:114-143 — start/stop asyncio.Task lifecycle to mirror
async def start(self) -> None:
    if self._task is not None:
        return
    async def _loop() -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self._poll_sec)
    self._task = asyncio.create_task(_loop())

async def stop(self) -> None:
    if self._task is None:
        return
    self._task.cancel()
    try:
        await self._task
    except asyncio.CancelledError:
        pass
    finally:
        self._task = None

# retention.py mirrors this as a module-level function (simpler than class):
async def retention_loop(pool: AsyncConnectionPool, config: TenantConfig) -> None:
    """Daily soft-expiry of old signal_capture rows. Port of createRetentionJob."""
    while True:
        try:
            age_seconds = config.capture_retention_days * 86_400
            count = await mark_expired_older_than(pool, age_seconds)
            logger.info("[retention] flagged %d rows expired (>%dd)", count, config.capture_retention_days)
        except Exception as e:  # noqa: BLE001
            logger.warning("[retention] failed: %s", e)
        await asyncio.sleep(86_400)  # daily
```

Launched from `boot.py` as `asyncio.create_task(retention_loop(pool, config))` alongside the receive loop task.

---

## Test Pattern Assignments

### `tests/test_capture_pipeline.py`

**Analog:** `tests/conftest.py:117-143` (`FakeOutboundRepo` pattern) + async test shape from `test_signal_receive_loop.py`

**Fake pipeline deps pattern** — mirror `FakeOutboundRepo` for capture:
```python
# conftest.py:117-143 — FakeOutboundRepo shape to mirror for FakeCaptureRepo
class FakeOutboundRepo:
    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[dict] = []

    async def insert_outbound(self, pool: object, row: dict) -> dict:
        self.calls.append(row)
        if self.should_raise:
            raise RuntimeError("FakeOutboundRepo: simulated insert failure")
        return {"ok": True}

# In conftest.py, add analogous:
class FakeCaptureRepo:
    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[dict] = []
    async def insert_capture(self, pool: object, row: dict) -> dict:
        self.calls.append(row)
        if self.should_raise:
            raise RuntimeError("FakeCaptureRepo: simulated DB failure")
        return {"ok": True}
```

**Fake transcribe_client** (Option B from RESEARCH — inject a dict, no respx needed):
```python
# Add to conftest.py:
async def _fake_transcribe(arg):
    return {"ok": True, "text": "fake transcript", "duration_ms": 100, "language": "es"}

fake_transcribe_client = {"transcribe": _fake_transcribe}
```

**Async test shape** — mirror `conftest.py:50` (`asyncio_mode = "auto"` already set; no decorator needed):
```python
# tests already use asyncio_mode=auto from pyproject.toml:
# [tool.pytest.ini_options] asyncio_mode = "auto"
# Just write async def test_*():

async def test_handle_text_only(fake_capture_repo):
    pipeline = create_capture_pipeline(
        pool=None,
        signal_client=FakeSignalClient(),
        transcribe_client={"transcribe": _fake_transcribe},
        config=_test_config(),
        dispatch_result=None,
    )
    result = await pipeline["handle"](TEXT_ENVELOPE)
    assert result is not None
    assert fake_capture_repo.calls[0]["message_type"] == "text"
```

---

### `tests/test_transcribe_client.py`

**Analog:** `tests/conftest.py:97-114` (`signal_http` respx fixture) for the real HTTP client tests

**respx mock fixture** — extend or reuse the existing `signal_http` fixture pattern for a `whisper_http` variant:
```python
# conftest.py:97-114 — signal_http fixture shape to mirror
@pytest.fixture
def signal_http():
    import respx, httpx
    with respx.mock(assert_all_called=False) as mock_transport:
        yield mock_transport

# Add to conftest.py:
@pytest.fixture
def whisper_http():
    import respx, httpx
    with respx.mock(assert_all_called=False) as mock_transport:
        yield mock_transport

# In test_transcribe_client.py:
async def test_ok(whisper_http):
    whisper_http.post("http://host.docker.internal:8090/transcribe").mock(
        return_value=httpx.Response(200, json={
            "text": "hola", "duration_ms": 1500, "language": "es"
        })
    )
    async with httpx.AsyncClient(transport=whisper_http) as http:
        client = create_transcribe_client("http://host.docker.internal:8090", http)
    result = await client["transcribe"]("/data/signal-capture/test.ogg")
    assert result["ok"] is True
    assert result["text"] == "hola"
```

---

### `tests/test_capture_repo.py`

**Analog:** `tests/test_signal_persist.py` (fail-open via `FakeOutboundRepo`, no real DB required for the fail-open test; DB-gated `pool` fixture for the round-trip test)

**DB-skip gate** — copy `conftest.py:50-89` (`pool` fixture with socket-reachability skip):
```python
# The existing pool fixture in conftest.py already does this:
# pytest.skip(f"no test DB reachable at {host}:{port} ...")
# DB-independent fail-open tests do NOT request the pool fixture and always run.
```

---

## Shared Patterns

### 1. Fail-open: never raise, return `{ok:False, reason}`
**Source:** `persistence/outbound_repo.py:79-85`
**Apply to:** `capture_repo.insert_capture`, `capture_repo.mark_expired_older_than`, `capture_history.select_recent_by_sender`, `capture_history.select_recent_outbound_by_recipient`
```python
# outbound_repo.py:79-85
try:
    async with pool.connection() as conn:
        await conn.execute(_INSERT_SQL, params)
    return {"ok": True}
except Exception as e:  # noqa: BLE001
    logger.warning("[outbound_repo] insert_outbound failed: %s", e)
    return {"ok": False, "reason": str(e)}
```

### 2. psycopg3 connection acquisition (`%s` placeholders, UTC pool)
**Source:** `persistence/pool.py:45-51`, `persistence/outbound_repo.py:79-81`
**Apply to:** `capture_repo.py`, `capture_history.py`
```python
# pool.py:45-51
pool = AsyncConnectionPool(
    conninfo=conninfo,
    min_size=1,
    max_size=5,
    open=False,  # defer open() until event loop is running
)
await pool.open()

# outbound_repo.py:80-81
async with pool.connection() as conn:
    await conn.execute(sql, params)   # %s placeholders, NOT $1
```
The pool sets `options="-c timezone=UTC"` — `datetime.now(timezone.utc)` for all `timestamptz` values.

### 3. TenantConfig injection — no direct `os.environ` reads
**Source:** `signal_io/receive_loop.py:42-46`, `signal_io/client.py:55-56`
**Apply to:** `pipeline.py`, `transcribe_client.py`, `retention.py`
```python
# receive_loop.py:42-46 — TenantConfig is the sole env-reader
config: TenantConfig,
...
self._config = config
# Whisper URL and capture_base_dir come from:
config.whisper_url          # WHISPER_URL env (default: http://host.docker.internal:8090)
config.capture_base_dir     # CAPTURE_BASE_PATH env (default: /data/signal-capture)
config.capture_retention_days  # CAPTURE_RETENTION_DAYS env (default: 30)
```

### 4. PII masking in log lines
**Source:** `signal_io/router.py:25` (re-exports `mask_number`), `signal_io/client.py:267-271`
**Apply to:** `pipeline.py` (all log lines referencing `sender`/`source`)
```python
# client.py:267-271 — mask before logging
from farm_agent.signal_io.router import mask_number
self._logger.info("[signal] sent -> %s (%d chars)", mask_number(str(target)), len(body))
# pipeline.py mirrors: _log.warning("[capture] error for %s: ...", mask_number(source))
```

### 5. Discriminated result type `{ok:True,...}` / `{ok:False, reason}`
**Source:** `persistence/outbound_repo.py:82-85`, `signal_io/client.py:204-206`
**Apply to:** `transcribe_client.transcribe()`, `capture_repo.insert_capture()`
```python
# client.py:204-206 — early-return discriminated result
if not bypass_cap and len(self._send_history) >= cap:
    ...
    return {"ok": False, "reason": "rate-cap"}
# Never raise from these functions; caller checks result["ok"].
```

### 6. Test fixture layout (flat, `conftest.py` extension)
**Source:** `tests/conftest.py:31-143`
**Apply to:** all `tests/test_capture_*.py`

Two new fixtures to add to `tests/conftest.py` (no new file needed):
- `FakeCaptureRepo` class (mirrors `FakeOutboundRepo:117-143`)
- `fake_transcribe_client` fixture (dict `{"transcribe": async_fn}`)
- `whisper_http` fixture (mirrors `signal_http:97-114`)

TEST_ENV already has `SIGNAL_SENDER`, `FARMOS_URL` etc. No new keys needed for Phase 58 (whisper URL and capture_base_dir have working defaults in `TenantConfig`).

---

## New Dependency Flag

| Package | Install | Why | Risk |
|---------|---------|-----|------|
| `python-ulid` | `cd src/farm-agent && uv add python-ulid` | ULID generation with timestamp-seeding: `str(ULID.from_datetime(dt))` mirrors `ulid(capturedAtMs)` | MEDIUM: verify `ULID.from_datetime` exists before use: `python -c "from python_ulid import ULID; print(dir(ULID))"`. Fallback: `ULID.from_timestamp(ms/1000)` or inline 26-char base32 impl. |

---

## Critical Subtleties (planner must read)

| # | Subtlety | Location | Consequence if missed |
|---|----------|----------|-----------------------|
| 1 | `attachment_paths` is `text[]` NOT jsonb — pass `list[str]` directly, no `Jsonb()` | `capture_repo.py` INSERT params | psycopg3 type error at INSERT time |
| 2 | `corpus_context` is always `None` for live captures — hard-code `None` in params tuple | `capture_repo.py` INSERT params | Corrupts distinction between live and backfill rows |
| 3 | `ULID.from_datetime(dt)` must receive the `captured_at_ms` timestamp, not `time.time()` | `pipeline.py` ULID generation | ULID time component wrong; ordering in PK index drifts |
| 4 | D-05: call `Path(p).exists()` AFTER `write_bytes()` before appending to `attachment_paths` | `pipeline.py` attachment loop | Extractor (Phase 59) receives paths to missing files |
| 5 | D-04: `insert_capture` is called even when `transcript=None` (fail-open) — never skip the row | `pipeline.py` Step 4 | Voice note captures silently lost on Whisper outage |
| 6 | `handle()` must NEVER propagate exceptions to the caller (D-03) | `pipeline.py` outer try/except | Kills the receive loop for subsequent envelopes |
| 7 | `CAPTURE_BASE_PATH` bind-mount must exist in `docker-compose.override.yml` for the `alerter-py` service before live-fire | ops prereq | `write_bytes()` fails silently or `Path.mkdir` raises |
| 8 | D-07: `mushy-whisper-transcribe-1` is currently `unhealthy` (CUDA err 804) — SC#1 live-fire is blocked until container is fixed | live-fire gate | Unit tests pass, SC#1 live-fire cannot complete |

---

## No Analog Found

No files in this phase are without any analog. All five module files have both a Node behavioral spec and a direct Python idiom analog from Phases 56/57. The only genuinely new mechanism is `asyncio.create_task(retention_loop(...))` in `boot.py`, but the `asyncio.Task` lifecycle shape is already established in `receive_loop.py:start()/stop()`.

---

## Metadata

**Analog search scope:** `src/agents/alerter/src/` (Node port-targets), `src/farm-agent/farm_agent/` + `src/farm-agent/tests/` (Phase-56/57 Python idioms)
**Files read:** `outbound_repo.py`, `client.py`, `router.py`, `receive_loop.py`, `pool.py`, `tenant.py` (lines 1-60 + grep for capture fields), `tests/conftest.py`
**Pattern extraction date:** 2026-06-21
