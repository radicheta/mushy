# Phase 58: Capture + Transcription - Research

**Researched:** 2026-06-21
**Domain:** Python port of the Node capture pipeline into `farm_agent/capture/`, wired to Phase 57's `dispatch(envelope)` seam; discriminated-result transcription client (httpx); ULID-keyed attachment storage; `signal_capture` persistence mirroring `outbound_repo` pattern.
**Confidence:** HIGH (all Node source files read directly; all Python target files read directly; all locked decisions verified against CONTEXT.md D-01..D-08)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Transcription is a faithful HTTP port. Build a Python `transcribe_client` (httpx) that POSTs `{audio_path}` to the existing `whisper-transcribe` FastAPI container's `/transcribe`, mirroring `transcribe-client.js` (factory shape, timeout, never-throws `{ok, text, duration_ms, language}` / `{ok:false, reason}` discriminated result). The container stays a sibling service -- it is NOT re-implemented in-process.
- **D-02:** "Off-loop" is satisfied natively by async I/O. An `await transcribe_client.transcribe(path)` is a non-blocking network call; the receive loop continues processing other envelopes during a long transcription. No `ProcessPoolExecutor` is used or needed.
- **D-03 (SUPERSEDES ROADMAP SC#2 wording):** ROADMAP Phase-58 SC#2 literally says "Whisper transcription runs in a `ProcessPoolExecutor` (off-loop)." That wording is superseded. The authoritative SC#2 for this phase is: "audio is transcribed off-loop via an async HTTP call to the `whisper-transcribe` sibling; the receive loop is not blocked during a long transcription." The verifier MUST use this interpretation.
- **D-04:** Fail-open on transcription failure. When `transcribe_client` returns `{ok:false}`, the `signal_capture` row is still persisted with a NULL transcript and the pipeline proceeds. A WARNING is logged. Transcription failure never drops a capture.
- **D-05:** Attachment-download race (SC#3) is fail-safe, not fail-open-blind. A downloaded attachment path MUST be verified to exist on disk before it is passed to the extractor. If a download fails or the file is absent, that modality is dropped and a WARNING logged. The extractor never receives a path to a missing file. The capture row still persists with the modalities that did land.
- **D-06:** Capture is PRE-confirmation, so the no-silent-failure-after-farmer-confirm rule does NOT bind here. Fail-open + WARNING is the correct posture.
- **D-07:** `mushy-whisper-transcribe-1` is currently `unhealthy` (CUDA forward-compat hang, cuInit err 804 on GeForce). Getting it healthy is a prerequisite ops fix, NOT Phase 58 implementation scope. The phase's live-fire gate (SC#1's non-null transcript) cannot pass until the container is healthy. **Flagged blocker:** resolve container health before Phase 58 live-fire/parity verification.
- **D-08:** Keep `transcribe_client`, the capture persistence repo (`capture_repo`), and the farmer-slug/people-directory resolver as separable units (Foray seam goal). Exact internal structure is the planner's call.

### Claude's Discretion

- Santi said "you decide" -- all decisions above (D-01..D-08) were Claude-recommended and Santi-delegated. The planner has latitude on internal module structure, file/dir layout for downloaded attachments (port the Node ULID-based `baseDir/day/time-id.ext` scheme), and the capture/transcribe error taxonomy, provided D-01..D-06 hold.

### Deferred Ideas (OUT OF SCOPE)

- In-process Whisper for Foray self-containment (ProcessPoolExecutor re-architecture).
- Whisper CUDA-compat permanent fix (ops/infra concern).
- Alerter timezone fix (pre-accepted v1.12 delta, tracked separately).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CAP-01 | Inbound envelopes captured to `signal_capture` (ULID id) with attachments downloaded to disk; farmer slug resolved from Signal number via farmOS people directory / farmer-map. | `insertCapture` row shape fully documented; `resolve_farmer` already in `signal_io/router.py`; ULID path scheme ported from `capture.js:buildPath`; psycopg3 `capture_repo` mirrors `outbound_repo` pattern exactly. |
| CAP-02 | Audio attachments transcribed via the local Whisper client without blocking the event loop (off-loop execution); transcript feeds extraction alongside text + image. | `transcribe_client` is a thin httpx POST to `/transcribe`; `await` is non-blocking by asyncio semantics (D-02/D-03); D-04 fail-open on NULL transcript documented; Whisper FastAPI contract read directly. |
</phase_requirements>

---

## Summary

Phase 58 is a near-mechanical port of `capture.js` and its siblings into `farm_agent/capture/`. The Node source has been read in full; every behavior has a clear Python translation using patterns already established in Phases 56 and 57. There are no open design questions -- D-01 through D-08 are all locked.

The three main deliverables are: (1) `capture/pipeline.py` -- the `handle(envelope)` orchestrator that sequences attachment download, transcription, and `signal_capture` insert; (2) `capture/transcribe_client.py` -- a never-throws httpx client to the `whisper-transcribe` container; and (3) `capture/capture_repo.py` -- a `insert_capture` function that mirrors `outbound_repo.py` exactly.

The critical non-code concern is D-07: `mushy-whisper-transcribe-1` is currently unhealthy due to the CUDA forward-compat hang (cuInit err 804 on GeForce). The SC#1 live-fire (non-null transcript) is blocked on resolving that container. All unit tests (including fake-Whisper stubs) can land without the container being healthy, but the final live-fire gate cannot pass until the ops fix is applied.

A second important implementation note: `capture-retention.js` uses `node-cron` which is NOT ported in this phase. The Python equivalent is an `asyncio` periodic task (using `asyncio.sleep` loop). However, given the retention job's role is a simple periodic soft-flag operation (`UPDATE expired=true`), the planner should confirm whether retention belongs in Phase 58 or as a separate later task.

**Primary recommendation:** Port `pipeline.py` as a factory function `create_capture_pipeline(...)` taking injected pool, signal_client, transcribe_client, config, and an optional `dispatch_result` seam for Phase 59. Wire it to `receive_loop.dispatch` in `boot.py`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Envelope parsing + farmer-slug resolution | `capture/pipeline.py` | `signal_io/router.py` (resolve_farmer already there) | pipeline consumes the primitive; doesn't re-derive it |
| Attachment download | `capture/pipeline.py` | `signal_io/client.py` (fetch_attachment) | pipeline orchestrates; client owns the wire call |
| ULID path building + mkdir | `capture/pipeline.py` | `pathlib.Path` (stdlib) | server-controlled path only; never trust attachment filename |
| Disk-existence verification (D-05) | `capture/pipeline.py` | -- | explicit `Path(p).exists()` check after write before adding to list |
| Transcription HTTP client | `capture/transcribe_client.py` | `httpx.AsyncClient` | Foray seam (D-08); separable unit; never-throws discriminated result |
| `signal_capture` persistence | `capture/capture_repo.py` | `persistence/pool.py` (injected pool) | mirrors outbound_repo.py exactly; fail-open; never-throws |
| Retention cron (soft-flag expired rows) | `capture/retention.py` (or `boot.py` task) | `capture/capture_repo.py` (mark_expired_older_than) | asyncio periodic task; not node-cron |
| Capture history (24h recent context) | `capture/capture_history.py` | `persistence/pool.py` | mirrors createCaptureHistory; consumed by Phase 59+ gate/extraction |
| Dispatch seam to Phase 59+ | `capture/pipeline.py` (out-param) | -- | pipeline returns a capture result dict; boot.py or Phase 59 wires it forward |

---

## Standard Stack

### Core (all already in pyproject.toml -- no new installs for this phase)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python asyncio (stdlib) | built-in | async I/O, no ProcessPoolExecutor needed | D-02: `await transcribe_client.transcribe(path)` is already off-loop |
| httpx | >=0.28 (pinned Phase 56) | `transcribe_client` HTTP POST to whisper-transcribe | Same client used by SignalClient; consistency |
| python-ulid or ulid-py | see below | ULID generation for capture IDs | Mirrors `ulid()` from the `ulid` npm package |
| pathlib (stdlib) | built-in | ULID path building, mkdir, exists check | Replaces `path.join` + `fs.mkdir` + `fs.writeFile` |
| psycopg3 (pinned Phase 56) | >=3.3 | `capture_repo` INSERT to `signal_capture` | Same pool+repo pattern as `outbound_repo.py` |
| asyncio.sleep loop | built-in | Retention cron | Replaces `node-cron`; no new dependency needed |

### ULID Package Decision

The Node source uses `const { ulid } = require('ulid')`. Python has two candidates: [VERIFIED: PyPI registry existence checked below in Package Legitimacy Audit]

- `python-ulid` -- pure-Python, well-maintained, provides `ULID.from_datetime()` and `str(ULID())` [ASSUMED: package details from training; verified via registry below]
- `ulid-py` -- older package by Mccartney; lower maintenance [ASSUMED]

**Recommendation:** `python-ulid` (package name on PyPI: `python-ulid`). The ULID must be generated with the captured-at timestamp as the monotonic component, mirroring `ulid(capturedAtMs)`. `python-ulid` exposes `ULID.from_datetime(dt)` for this.

### No New Installs Required

Phase 58 requires zero new runtime packages -- `httpx` and `psycopg3` are already declared in `pyproject.toml`. Only `python-ulid` is new.

**Installation (one new package):**
```bash
cd src/farm-agent && uv add python-ulid
```

**Version verification:**
```bash
pip index versions python-ulid
```

---

## Package Legitimacy Audit

Only one new package is introduced in this phase.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| python-ulid | PyPI | ~5 yrs | Medium-high | github.com/mdomke/python-ulid | [ASSUMED] | Approved -- established ULID implementation, active maintenance |

**Note:** slopcheck was unavailable in this session. `python-ulid` is a well-known package in the Python ULID ecosystem. The planner should run `pip index versions python-ulid` and verify the GitHub repo before `uv add`. If preferred, the planner may implement a minimal ULID generator in-process (a ULID is 48-bit ms + 80-bit random, base32-encoded) as a zero-dependency alternative -- the CONTEXT.md does not mandate using an external package for this.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*All packages above are tagged `[ASSUMED]` -- slopcheck unavailable at research time.*

---

## Architecture Patterns

### System Architecture Diagram

```
  receive_loop.py
       │
       ▼ dispatch(envelope)   [Phase-57 seam -- entry point for Phase 58]
  capture/pipeline.py
  create_capture_pipeline(pool, signal_client, transcribe_client, config)
       │
       ├─ Step 1: envelope parsing
       │    source, dm, text, attachments, groupId, farmosPerson, replyTargetKind
       │    farmosPerson = router.resolve_farmer(source, config)  [Phase 57 primitive]
       │    id = ULID(captured_at_ms)
       │    message_type = classify(text, attachments)
       │
       ├─ Step 2: download attachments  [per-attachment try/except, partial success ok]
       │    for att in attachments:
       │      buf = await signal_client.fetch_attachment(att["id"])
       │      path = build_path(baseDir, captured_at_ms, f"{id}-{att_id}", ext)
       │      Path(path).parent.mkdir(parents=True, exist_ok=True)
       │      Path(path).write_bytes(buf)
       │      if Path(path).exists():          ← D-05 disk-existence gate
       │        attachment_paths.append(path)
       │      else: WARNING, degraded=True
       │
       ├─ Step 3: transcribe first audio attachment [D-02 off-loop; D-04 fail-open]
       │    audio_path = first path matching audio extensions
       │    if audio_path:
       │      r = await transcribe_client.transcribe(audio_path)
       │      if r["ok"]: transcript = r["text"]
       │      else: WARNING, degraded=True, transcript=NULL
       │
       ├─ Step 4: persist signal_capture row [fail-open; capture survives LLM absence]
       │    await capture_repo.insert_capture(pool, {...})
       │    ← continues even on DB failure (mirrors capture.js:167-170)
       │
       ├─ Step 5: return CaptureResult to Phase 59+ gate [or fire-and-forget enqueue]
       │    {capture_id, sender, farmos_person, text, transcript, attachment_paths,
       │     reply_target_kind, group_id, captured_at_ms, signal_msg_ts}
       │
       └─ (Step 6: LLM convo reply -- Phase 59/60 territory; NOT in Phase 58)

  capture/transcribe_client.py
  create_transcribe_client(api_url, timeout_ms=200000)
       POST {audio_path} → /transcribe
       Returns: {ok:True, text, duration_ms, language}
              | {ok:False, reason: "timeout"|"whisper 4xx/5xx: ..."|<error msg>}
       NEVER raises.

  capture/capture_repo.py
  insert_capture(pool, row) → {ok:True} | {ok:False, reason}
       NEVER raises (mirrors outbound_repo.py exactly).

  capture/capture_history.py
  CaptureHistory(pool).select_recent_by_sender(sender, since_ms) → rows
  CaptureHistory(pool).select_recent_outbound_by_recipient(recipient, since_ms) → rows
       [Port of createCaptureHistory; consumed by Phase 59+ gate/extractor]

  capture/retention.py
  async retention_loop(pool, config):
       while True:
         await mark_expired_older_than(pool, config.capture_retention_days * 86400)
         await asyncio.sleep(86400)   # daily
```

### Recommended Project Structure

```
src/farm-agent/farm_agent/
├── capture/                    # FORAY island (no chamber imports)
│   ├── __init__.py
│   ├── pipeline.py             # create_capture_pipeline factory; handle(envelope)
│   ├── transcribe_client.py    # create_transcribe_client; never-throws httpx POST
│   ├── capture_repo.py         # insert_capture, mark_expired_older_than (psycopg3)
│   ├── capture_history.py      # select_recent_by_sender, select_recent_outbound_by_recipient
│   └── retention.py            # asyncio periodic task; async retention_loop()
│
tests/
├── test_capture_pipeline.py    # unit: classify, buildPath, handle fail-open behavior
├── test_capture_repo.py        # unit: insert_capture fail-open; respx or fake pool
├── test_transcribe_client.py   # unit: ok path, timeout, 5xx, missing audio_path
└── test_capture_history.py     # unit: select_recent_by_sender shape
```

### Pattern 1: `insert_capture` -- mirror `outbound_repo.py` exactly

Every pattern established in `outbound_repo.py` carries over verbatim:

```python
# Source: capture-db.js:79-108 + outbound_repo.py pattern [VERIFIED: both read this session]

_INSERT_SQL = """
INSERT INTO signal_capture
  (id, captured_at, sender, message_type, raw_text, attachment_paths,
   transcript, llm_session_tag, llm_reply, degraded,
   group_id, farmos_person, reply_target_kind,
   signal_msg_ts, quote_msg_ts, quote_author_e164, corpus_context)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

async def insert_capture(pool: AsyncConnectionPool, row: dict) -> dict:
    """Insert one row into signal_capture. NEVER raises. Returns {ok:True} or {ok:False, reason}."""
    try:
        async with pool.connection() as conn:
            await conn.execute(_INSERT_SQL, (
                row["id"],
                row["captured_at"],           # datetime(timezone.utc)
                row["sender"],
                row["message_type"],
                row.get("raw_text"),
                row.get("attachment_paths", []),   # text[] -- psycopg3 sends list[str] as text[]
                row.get("transcript"),
                None,                          # llm_session_tag (Phase 59+)
                None,                          # llm_reply (Phase 59+)
                row.get("degraded", False),
                row.get("group_id"),
                row.get("farmos_person"),
                row.get("reply_target_kind"),
                row.get("signal_msg_ts"),      # bigint or None
                row.get("quote_msg_ts"),       # bigint or None
                row.get("quote_author_e164"),
                None,                          # corpus_context (backfill only)
            ))
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.warning("[capture_repo] insert_capture failed: %s", e)
        return {"ok": False, "reason": str(e)}
```

**psycopg3 array handling:** psycopg3 automatically adapts Python `list[str]` to Postgres `text[]`. Do NOT cast with `Jsonb` -- `attachment_paths` is `text[]`, not jsonb. The `corpus_context jsonb` column uses `Jsonb(value)` if non-null. [VERIFIED: outbound_repo.py uses `Jsonb` for jsonb columns; attachment_paths is text[] in capture-db.js DDL]

### Pattern 2: `transcribe_client` -- never-throws discriminated result

```python
# Source: transcribe-client.js:20-58 [VERIFIED: read this session]

def create_transcribe_client(
    api_url: str,
    timeout_ms: int = 200_000,
    logger=None,
) -> dict:
    """Factory returning {transcribe} callable. Port of createTranscribeClient."""
    _log = logger or logging.getLogger(__name__)
    _timeout_s = timeout_ms / 1000

    async def transcribe(arg) -> dict:
        """Accept str path OR {audio_path} dict (harness symmetry).
        Returns {ok:True, text, duration_ms, language} | {ok:False, reason}.
        NEVER raises.
        """
        audio_path = arg if isinstance(arg, str) else (arg or {}).get("audio_path")
        if not audio_path:
            return {"ok": False, "reason": "missing audio_path"}
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{api_url}/transcribe",
                    json={"audio_path": audio_path},
                    timeout=_timeout_s,
                )
                if r.status_code >= 400:
                    text = r.text[:200] if r.content else ""
                    return {"ok": False, "reason": f"whisper {r.status_code}: {text}"}
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

    return {"transcribe": transcribe}
```

**Implementation note:** The Node `createTranscribeClient` creates an `AbortController` + `setTimeout`. Python's `httpx.AsyncClient` handles this natively via `timeout=`. The `httpx.TimeoutException` catches both connect and read timeouts. [VERIFIED: transcribe-client.js:30-35 read this session]

**Reuse vs. create per-call:** The Node client creates a new `fetch()` per call (no persistent connection). To match, the Python version either (a) creates a new `httpx.AsyncClient()` per call as shown above, or (b) holds a persistent client as an injected dependency. Option (b) is cleaner for testing (inject a mocked client). Recommend option (b) as the factory pattern with an injected `http: httpx.AsyncClient` -- mirrors `SignalClient.__init__`.

### Pattern 3: ULID path building

```python
# Source: capture.js:38-44 [VERIFIED: read this session]

import re
from pathlib import Path
from datetime import datetime, timezone

def build_path(base_dir: str, captured_at_ms: int, file_id: str, ext: str) -> str:
    """Build server-controlled attachment path. Never trusts client filename.
    Pattern: base_dir/<YYYY-MM-DD>/<HH-MM-SS>-<file_id>.<sanitized_ext>
    Mirrors capture.js:buildPath (V12 file/resource hardening).
    """
    dt = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
    day = dt.strftime("%Y-%m-%d")
    time_part = dt.strftime("%H-%M-%S")
    safe_ext = re.sub(r"[^a-z0-9]", "", ext, flags=re.IGNORECASE)
    return str(Path(base_dir) / day / f"{time_part}-{file_id}.{safe_ext}")
```

The `file_id` in the Node source is `${id}-${att.id}` where `id` is the capture ULID and `att.id` is the signal-cli attachment ID. Mirror this exactly.

### Pattern 4: ULID generation with timestamp

```python
# Source: capture.js:6,94 -- ulid(capturedAtMs) [VERIFIED: read this session]

from python_ulid import ULID
from datetime import datetime, timezone

def generate_capture_id(captured_at_ms: int) -> str:
    """Generate a ULID string with the given ms-timestamp as the time component.
    Mirrors ulid(capturedAtMs) from the ulid npm package.
    """
    dt = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
    return str(ULID.from_datetime(dt))
```

**Verify `python-ulid` API:** The `ULID.from_datetime(dt)` API is the primary interface for timestamp-seeded generation. Confirm this is the correct call before the planner uses it (see Assumptions Log A1).

### Pattern 5: `classify(text, attachments)` -- message type

```python
# Source: capture.js:12-26 [VERIFIED: read this session]

AUDIO_TYPES = frozenset([
    "audio/aac", "audio/mp4", "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm",
])
IMAGE_TYPES = frozenset([
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "image/gif",
])
SAFE_EXT = {
    "audio/aac": "aac", "audio/mp4": "m4a", "audio/mpeg": "mp3",
    "audio/ogg": "ogg", "audio/wav": "wav", "audio/webm": "webm",
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/heic": "heic", "image/heif": "heif", "image/gif": "gif",
}

def classify(text: str | None, attachments: list[dict]) -> str:
    has_audio = any(a.get("contentType") in AUDIO_TYPES or a.get("voiceNote") is True
                    for a in attachments)
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

### Pattern 6: Signal timestamp extraction (Phase 50 carry-through)

```python
# Source: capture.js:134-144 [VERIFIED: read this session]
# Both sigMsgTs and quoteMsgTs use Number.isFinite(Number(x)) in Node.
# Python equivalent: math.isfinite(float(str(x))) with exception guard.

import math

def _coerce_ts(v) -> int | None:
    """Coerce a numeric or numeric-string timestamp to int. Returns None if invalid."""
    if v is None:
        return None
    try:
        f = float(str(v))
        return int(f) if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None

# In handle():
sig_msg_ts = _coerce_ts(dm.get("timestamp"))
q = dm.get("quote") or {}
quote_msg_ts_raw = q.get("id") if q.get("id") is not None else q.get("timestamp")
quote_msg_ts = _coerce_ts(quote_msg_ts_raw)
quote_author = (
    q.get("author") if isinstance(q.get("author"), str) and q.get("author")
    else q.get("authorNumber") if isinstance(q.get("authorNumber"), str) and q.get("authorNumber")
    else None
)
```

### Pattern 7: `recordReplyCapture` -- persist-only for confirm-thread replies

Node's `capture.js` also exposes `recordReplyCapture(envWrapper, ctx)` -- a stripped-down persist that skips attachment download, transcription, event-gate, and extraction enqueue. It exists so that YES/NO/EDIT replies from the confirm-thread also land in `signal_capture` (for Phase 50 quote-routing and the farmer paper trail). Port this alongside `handle()` -- it is the same pipeline minus Steps 2/3/5 and all convo/LLM branching.

### Anti-Patterns to Avoid

- **Trusting client attachment filename:** Never use `att.get("filename")` in the file path. The path MUST be derived from the server-controlled ULID + sanitized content-type extension only (V12 hardening in `capture.js:43`).
- **Passing a non-existent path to the extractor (D-05 violation):** After writing a file, always call `Path(p).exists()` before appending to `attachment_paths`. The download may succeed but the write may fail silently.
- **Raising from `handle()`:** `handle()` must never propagate exceptions to the caller (mirrors `capture.js` D-03 "errors never escape handle()"). Every step has its own try/except.
- **Importing `os.environ` in `capture/`:** Config comes from injected `TenantConfig` only (FND-02). `whisper_url` and `capture_base_dir` are already on `TenantConfig` (verified in `tenant.py`).
- **Using `datetime.now()` without timezone:** Always `datetime.now(timezone.utc)` for the `captured_at` column (UTC enforcement, mirrors Phase 56 pool's `timezone=UTC` pattern).
- **Holding the capture pipeline across `asyncio.gather`:** Dispatch remains sequential (enforced by `receive_loop.py`). The capture pipeline is invoked once per envelope in a for-loop. No concurrent capture.
- **`corpus_context` field in live captures:** The `corpus_context` column is set ONLY by the Phase 53/54 backfill harness -- live captures always pass `None`. Do not wire it in Phase 58.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP transcription timeout | Manual asyncio timeout wrapper | `httpx` `timeout=` parameter | httpx has first-class timeout; catches both connect and read |
| ULID generation | Custom base32 + random bytes | `python-ulid` | Correct monotonic-timestamp seeding; matching npm `ulid` package behavior |
| Text[] Postgres parameter | JSON-encode and cast | Pass Python `list[str]` directly to psycopg3 | psycopg3 auto-adapts list to text[] for `text[]` columns |
| Discriminated result type | Exception-based | `{ok:True, ...}` / `{ok:False, reason}` dict | Mirrors the Node pattern established in `transcribe-client.js` and `outbound_repo.py` |
| Path sanitization | Regex hand-roll | `re.sub(r"[^a-z0-9]", "", ext, flags=re.IGNORECASE)` | Direct port of `ext.replace(/[^a-z0-9]/gi, '')` from `buildPath` |

**Key insight:** Every part of this phase is a 1:1 translation of `capture.js` and siblings using patterns already proven in Phases 56 and 57. There is no new design territory.

---

## Node Source → Python Translation Map

| Node | Python | Notes |
|------|--------|-------|
| `const { ulid } = require('ulid')` | `from python_ulid import ULID` | `str(ULID.from_datetime(dt))` for timestamp-seeded |
| `path.join(baseDir, day, ...)` | `str(Path(base_dir) / day / ...)` | `pathlib.Path` |
| `fs.mkdir(dir, { recursive: true })` | `Path(dir).mkdir(parents=True, exist_ok=True)` | |
| `fs.writeFile(filePath, buf)` | `Path(file_path).write_bytes(buf)` | `buf` is `bytes` from `fetch_attachment()` |
| `pool.query(INSERT ...)` | `conn.execute(INSERT ..., params)` via `pool.connection()` | psycopg3 pattern (outbound_repo.py) |
| `signalFarmerMap.get(source) ?? '(unassigned)'` | `router.resolve_farmer(source, config)` | Already in `signal_io/router.py` [VERIFIED] |
| `ulid(capturedAtMs)` | `str(ULID.from_datetime(dt))` | |
| `new Date(capturedAtMs)` | `datetime.fromtimestamp(capturedAtMs/1000, tz=timezone.utc)` | Always UTC |
| `Number.isFinite(Number(x))` | `math.isfinite(float(str(x)))` guarded by try/except | `_coerce_ts()` helper |
| `cron.schedule(...)` | `asyncio.sleep` loop in `retention.py` | No node-cron equivalent needed |
| `signalClient.fetchAttachment(att.id)` | `await signal_client.fetch_attachment(att["id"])` | Already in `client.py` [VERIFIED] |
| `createCapturePipeline({...})` | `create_capture_pipeline(...)` factory | Returns `{"handle": handle, "record_reply_capture": record_reply_capture}` |

---

## Scope Boundary: What Phase 58 Does NOT Port

The Node `capture.js` `handle()` contains sections Phase 58 deliberately does not implement:

| Node section | Reason to defer |
|---|---|
| `if (eventGate) { ... gateDecision ... }` (lines 177-202) | Phase 59 (GATE-01) owns the event gate |
| `if (extractionPipeline) { extractionPipeline.enqueue(...) }` (lines 207-223) | Phase 60 (XTR-01) owns extraction |
| `llmClient.compose({...})` (lines 230-259) | Phase 60 |
| Degraded fallback reply + `signalClient.send(replyText)` (lines 265-282) | Phase 59+ owns the reply path |
| LLM field UPDATE (lines 287-313) | Phase 60 |

Phase 58's `handle()` terminates after Step 4 (`insert_capture`) and returns a structured `CaptureResult` that Phases 59+ consume. The planner should design the `handle()` return signature with Phase 59's needs in mind.

**`recordReplyCapture` IS in Phase 58 scope** -- it is a persist-only stub with no gate/extraction/LLM and is required for Phase 50 quote-threading correctness.

---

## Retention Job: Port Decision

`capture-retention.js` uses `node-cron` to run daily. Python equivalent is a simple `asyncio` periodic task:

```python
# capture/retention.py
async def retention_loop(pool, config):
    """Daily soft-expiry of old signal_capture rows. Mirrors createRetentionJob.run()."""
    while True:
        try:
            age_seconds = config.capture_retention_days * 86400
            count = await mark_expired_older_than(pool, age_seconds)
            logger.info("[retention] flagged %d rows expired (>%dd)", count, config.capture_retention_days)
        except Exception as e:
            logger.warning("[retention] failed: %s", e)
        await asyncio.sleep(86400)  # daily; first run after one day
```

This is launched as an `asyncio.create_task(retention_loop(...))` in `boot.py` alongside the receive loop.

---

## Common Pitfalls

### Pitfall 1: `attachment_paths` column is `text[]`, not jsonb

**What goes wrong:** Using `Jsonb(attachment_paths)` (as for the `corpus_context` jsonb column) or passing a JSON-encoded list causes a type mismatch. `attachment_paths text[] NOT NULL DEFAULT ARRAY[]::text[]` expects a Postgres array.

**How to avoid:** Pass `list[str]` directly to psycopg3. psycopg3 auto-adapts Python `list[str]` to `text[]`. Verify with a unit test that a row with `attachment_paths=["a.mp3"]` round-trips to `["a.mp3"]`. [VERIFIED: capture-db.js DDL shows text[]; outbound_repo.py uses Jsonb only for jsonb columns]

**Warning signs:** psycopg3 `invalid input syntax for type text[]` or unexpected stringification.

### Pitfall 2: File written but not readable -- D-05 race

**What goes wrong:** `Path(file_path).write_bytes(buf)` returns without error even when the filesystem is full or the path is on a volume with permission issues. The path is added to `attachment_paths`, the extractor receives it, but the file is absent.

**How to avoid:** After every `write_bytes()`, call `if not Path(file_path).exists(): logger.warning(...); continue`. The cost is negligible (one stat per attachment). [VERIFIED: D-05 CONTEXT.md]

**Warning signs:** Extractor receiving paths to missing files; Phase 59 image modality silently missing.

### Pitfall 3: Whisper container unhealthy -- SC#1 live-fire blocked

**What goes wrong:** `mushy-whisper-transcribe-1` is currently `unhealthy` (CUDA err 804, `[[project_whisper_cuda_compat_geforce_804]]`). Unit tests with fake-Whisper stub pass, but the live-fire SC#1 (non-null transcript for a real voice note) cannot complete.

**How to avoid:** Ops fix BEFORE Phase 58 live-fire. The fix is removing `cuda-compat` from the container or pinning a compatible driver. This is D-07 and explicitly out of Phase 58 implementation scope. The planner should create a Wave 0 blocker note and gate the live-fire plan on container health.

**Warning signs:** `GET /health` returns 503; `docker logs mushy-whisper-transcribe-1` shows `cuInit 804`.

### Pitfall 4: ULID's timestamp component

**What goes wrong:** `ULID()` without a timestamp generates a ULID with `now()`. `ulid(capturedAtMs)` in Node generates with the provided millisecond timestamp as the time component, which is the capture time (not necessarily identical to `time.time()*1000` if the clock is slightly off). The ULID time component affects ordering in the `signal_capture` primary key index.

**How to avoid:** Always pass `captured_at_ms` to the ULID generator. Use `str(ULID.from_datetime(datetime.fromtimestamp(captured_at_ms/1000, tz=timezone.utc)))`.

### Pitfall 5: Envelope shape dual-read

**What goes wrong:** The Node `handle()` handles both `envWrapper.envelope` and `envWrapper` (bare envelope) shapes (`const env = envWrapper.envelope || envWrapper`). The Python receive loop delivers the full raw JSON from signal-cli, which wraps the content under an `envelope` key.

**How to avoid:** Mirror the dual-read: `env = envelope.get("envelope") or envelope`. Extract `dm = env.get("dataMessage") or {}`. This is identical to `router._read_dm()` already in Phase 57 -- the pipeline can reuse that function or inline it. [VERIFIED: receive_loop.py delivers the raw JSON from /v1/receive; router.py already has _read_dm]

### Pitfall 6: `corpus_context` must be NULL for live captures

**What goes wrong:** The `corpus_context jsonb` column is used ONLY by the Phase 53/54 backfill harness to inject `{default_year:2025, source:'paper_log'}`. Live capture rows must always pass `None`. Passing any value here would corrupt the distinction between live and backfill rows.

**How to avoid:** Hard-code `corpus_context=None` in Phase 58's `insert_capture` call. The column is in the INSERT for completeness (and to keep the SQL parameterized in one place), but its value is always `None`.

---

## Runtime State Inventory

This phase adds new Python code to an existing live system. The `signal_capture` table already exists in production (used by the live Node alerter). No migration changes are needed -- all `signal_capture` columns were already added by Phase 56 migrations.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `signal_capture` table in shared TimescaleDB -- already contains live rows from the Node alerter; all columns Phase 58 writes already exist (verified in Phase 56 RESEARCH.md full column inventory). | Code edit only. Python writes new rows; does NOT modify existing Node rows. |
| Live service config | `mushy-whisper-transcribe-1` container -- currently unhealthy (D-07). `WHISPER_URL` env var already in `TenantConfig.whisper_url` (defaults to `http://host.docker.internal:8090`). `CAPTURE_BASE_PATH` already in `TenantConfig.capture_base_dir` (defaults to `/data/signal-capture`). | Ops fix for container health (D-07). Verify `CAPTURE_BASE_PATH` is mounted in `alerter-py` compose block before live-fire. |
| OS-registered state | None -- no task scheduler or systemd entries reference capture paths. | None -- verified. |
| Secrets/env vars | `WHISPER_URL` and `CAPTURE_BASE_PATH` are already wired into `TenantConfig` (tenant.py lines 355-358) and into the `alerter-py` compose env block. No new env vars needed. | None. |
| Build artifacts | None -- Python source changes only. | None. |

**Canonical question:** After every file is updated, what runtime systems still carry state relevant to Phase 58? Answer: the `whisper-transcribe` container's health state (blocked until D-07 ops fix), and the `CAPTURE_BASE_PATH` volume mount on `alerter-py` (must be confirmed in compose before live-fire).

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| `whisper-transcribe` container | SC#1 live-fire (non-null transcript) | UNHEALTHY (D-07 blocker) | `mushy-whisper-transcribe-1` -- cuInit err 804 | Unit tests use fake HTTP stub (respx or httpx_mock); live-fire blocked until fixed |
| TimescaleDB (shared) | `capture_repo.insert_capture` | YES (live) | same as Phase 56/57 | -- |
| httpx | transcribe_client HTTP POST | YES (Phase 56 dep, pinned) | >=0.28 | -- |
| psycopg3 | capture_repo | YES (Phase 56 dep, pinned) | >=3.3 | -- |
| `CAPTURE_BASE_PATH` volume | attachment download + disk write | VERIFY | defaults to `/data/signal-capture`; must be bind-mounted in alerter-py | -- |
| python-ulid | ULID generation | NOT YET INSTALLED | -- | Implement minimal inline ULID or add via `uv add python-ulid` |
| signal-cli container | attachment download (fetch_attachment) | YES (live, MODE=normal) | 0.200-dev | -- |

**Missing dependencies with no fallback:**
- `whisper-transcribe` container health -- blocks SC#1 live-fire only; unit tests proceed without it.

**Missing dependencies with fallback:**
- `python-ulid` -- not yet installed; add via `uv add python-ulid`, or implement inline.
- `CAPTURE_BASE_PATH` mount -- defaults are configured; verify compose override before live-fire.

---

## Validation Architecture

> `workflow.nyquist_validation` is absent from config -- treated as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.0 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `src/farm-agent/pyproject.toml` (Phase 56, unchanged) |
| Quick run command | `cd src/farm-agent && uv run pytest tests/test_capture_*.py -x` |
| Full suite command | `cd src/farm-agent && uv run pytest` |
| Estimated runtime | ~10 seconds (unit, all HTTP mocked) |

**Test layout: FLAT** -- `tests/test_capture_*.py`, consistent with Phase 57's flat convention (not nested subdirs). [VERIFIED: 57-VALIDATION.md confirmed flat layout; ls of tests/ confirms all existing tests are flat]

### Phase Requirements → Test Map

| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| CAP-01 | `handle(envelope)` with text-only message inserts `signal_capture` row; farmer slug resolved via `resolve_farmer`; capture id is a valid ULID string | unit | `uv run pytest tests/test_capture_pipeline.py::test_handle_text_only -x` | ❌ Wave 0 |
| CAP-01 | `handle(envelope)` with one audio attachment: file written to `baseDir/day/time-id.ext`; path in `attachment_paths` | unit | `uv run pytest tests/test_capture_pipeline.py::test_handle_audio_attachment -x` | ❌ Wave 0 |
| CAP-01 (D-05) | Disk-existence gate: if `Path(p).exists()` is False after write, path NOT added to `attachment_paths`; `degraded=True` | unit | `uv run pytest tests/test_capture_pipeline.py::test_d05_missing_file_dropped -x` | ❌ Wave 0 |
| CAP-01 | `insert_capture` fail-open: DB failure does NOT raise from `handle()`; pipeline continues | unit | `uv run pytest tests/test_capture_repo.py::test_insert_fail_open -x` | ❌ Wave 0 |
| CAP-01 | `(unassigned)` farmer slug for unknown sender in `signal_capture.farmos_person` | unit | `uv run pytest tests/test_capture_pipeline.py::test_unassigned_farmer -x` | ❌ Wave 0 |
| CAP-01/SC#1 | Live-fire: send real voice note; `SELECT transcript FROM signal_capture WHERE ...` is non-null | live-fire (manual, autonomous:false) | `docker exec timescale psql -c "SELECT transcript FROM signal_capture ORDER BY captured_at DESC LIMIT 1"` | ❌ BLOCKED D-07 |
| CAP-02 | `transcribe_client.transcribe(path)` returns `{ok:True, text, duration_ms, language}` when Whisper 200 | unit (respx mock) | `uv run pytest tests/test_transcribe_client.py::test_ok -x` | ❌ Wave 0 |
| CAP-02 (D-04) | `transcribe_client` returns `{ok:False, reason}` on timeout; `handle()` sets `transcript=None`, `degraded=True`, does NOT drop capture | unit | `uv run pytest tests/test_transcribe_client.py::test_timeout_fail_open && uv run pytest tests/test_capture_pipeline.py::test_d04_transcription_failure -x` | ❌ Wave 0 |
| CAP-02 (D-02/D-03) | SC#2: receive loop is NOT blocked during transcription -- verified by checking that `transcribe_client.transcribe()` is an `async def` that yields the event loop (not a blocking call) | unit (asyncio event-loop tick assertion) | `uv run pytest tests/test_capture_pipeline.py::test_sc2_transcription_offloop -x` | ❌ Wave 0 |
| CAP-02/SC#1 | SC#1 non-null transcript live-fire path (Whisper healthy) | live-fire (manual) | above SELECT query | ❌ BLOCKED D-07 |

### SC#2 Off-Loop Test Strategy (D-02/D-03)

SC#2's claim is "the receive loop is not blocked during a long transcription." Testing this rigorously requires verifying that `await transcribe_client.transcribe(path)` yields the asyncio event loop, allowing other coroutines to run.

**Practical test approach:**
1. In the unit test, inject a `transcribe_client` whose `transcribe()` coroutine calls `await asyncio.sleep(0.1)` before returning (simulating a slow Whisper call).
2. Verify that while `handle(envelope)` is awaiting transcription, another coroutine can run (insert a `asyncio.create_task` that sets a flag; assert the flag is set after `handle()` completes).
3. Alternatively: verify at code-review level that `transcribe_client.transcribe()` is an `async def` calling `await client.post(...)` -- this is sufficient to confirm the event loop is not blocked.

The key invariant from D-03: `transcribe_client.transcribe()` MUST be `async def` and MUST use `await` on the HTTP call. If it were synchronous (`requests.post()`), it would block. Inspection of the code pattern is sufficient for this assertion in addition to a unit test.

### Whisper Fake/Stub Strategy

Since the live Whisper container is unhealthy (D-07), all unit tests use a fake. Two options:

**Option A: respx mock (consistent with Phase 57 approach)**
```python
# In conftest.py (extend existing signal_http fixture pattern)
@pytest.fixture
def whisper_http():
    import respx, httpx
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://host.docker.internal:8090/transcribe").mock(
            return_value=httpx.Response(200, json={
                "text": "Test transcript", "duration_ms": 1500, "language": "es"
            })
        )
        yield mock
```

**Option B: inject a fake transcribe_client dict**
```python
async def _fake_transcribe(arg):
    return {"ok": True, "text": "fake transcript", "duration_ms": 100, "language": "es"}

fake_transcribe_client = {"transcribe": _fake_transcribe}
```

Option B is simpler and more portable (no respx needed for transcribe_client tests). Recommend Option B for `test_capture_pipeline.py` (inject the fake) and Option A for `test_transcribe_client.py` (test the real HTTP client against a mock server).

### Sampling Rate

- **Per task commit:** `cd src/farm-agent && uv run pytest tests/test_capture_*.py -x`
- **Per wave merge:** `cd src/farm-agent && uv run pytest` (full suite, ~10s)
- **Phase gate:** Full unit suite green + SC#1 live-fire (non-null transcript in prod DB, requires D-07 resolved) before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_capture_pipeline.py` -- handle text/audio/image/mixed; D-04 fail-open transcription; D-05 disk-exists gate; unassigned farmer; SC#2 off-loop assertion
- [ ] `tests/test_capture_repo.py` -- insert_capture ok and fail-open; mark_expired_older_than
- [ ] `tests/test_transcribe_client.py` -- ok response, timeout, 5xx, missing audio_path
- [ ] `tests/test_capture_history.py` -- select_recent_by_sender and select_recent_outbound_by_recipient shapes
- [ ] Add `fake_transcribe_client` fixture to `tests/conftest.py` (Option B above)
- [ ] Ops prerequisite (D-07): `docker logs mushy-whisper-transcribe-1` -- resolve CUDA err 804 before live-fire plan executes
- [ ] Verify `CAPTURE_BASE_PATH` bind-mount in `docker-compose.override.yml` alerter-py block

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Signal identity delegated to signal-cli; sender whitelist enforced in Phase 57 receive_loop before capture is reached |
| V4 Access Control | partial | Sender whitelist gate (Phase 57) fires before `handle()`; `handle()` itself trusts that the envelope was whitelisted |
| V5 Input Validation | yes | `safe_ext()` sanitizes content-type to a known extension; `build_path()` derives the filename from server-controlled ULID + sanitized ext only (V12 file/resource hardening) |
| V6 Cryptography | no | No keys or hashes in this phase |
| V7 Logging | yes | `mask_number()` must be used on any log line referencing the sender e164 (inherited from Phase 57 requirement; `mask_number` is in `signal_io/router.py`) |
| V12 File / Resources | yes | Attachment filename NEVER comes from client; server-controlled path only. whisper-transcribe's `_resolve_safe()` enforces `ALLOWED_ROOT` on its side (verified in `main.py`). |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via attachment filename | Tampering | `build_path()` ignores `att.filename`; only ULID + `safe_ext(contentType)` used |
| Disk exhaustion via large attachments | DoS | `capture_retention_days` soft-expires old rows; disk limit is an ops/infra concern |
| Whisper server-side injection via `audio_path` | Tampering | `whisper-transcribe` enforces `ALLOWED_ROOT` check (verified in `main.py:_resolve_safe`); the path is server-generated, not user-supplied |
| PII leak in logs (e164 in attachment path or log) | Info Disclosure | Attachment path contains ULID only; log lines use `mask_number(source)` |
| `corpus_context` injection from live caller | Tampering | Hard-code `None` in Phase 58 insert call; only the backfill harness ever sets it |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `python-ulid` exposes `ULID.from_datetime(dt)` for timestamp-seeded generation | Standard Stack / Code Examples | MEDIUM -- if the API differs, use `ULID.from_timestamp(ms/1000)` or similar; verify with `python -c "from python_ulid import ULID; help(ULID)"` before using in implementation |
| A2 | `python-ulid` is the correct PyPI package name for the ULID library | Package Legitimacy Audit | LOW -- if the name is wrong, check `pip search ulid` or use PyPI search for "ulid python"; `ulid-py` is the alternative |
| A3 | psycopg3 automatically adapts `list[str]` to Postgres `text[]` in parameterized queries | Pattern 1 / Pitfall 1 | LOW -- psycopg3 documentation confirms built-in array adaptation for Python lists; the Phase 56 migration already uses text[] columns without issues |
| A4 | `whisper-transcribe/main.py`'s `/transcribe` response always includes `duration_ms` and `language` fields (not just `text`) | Standard Stack | LOW -- verified by reading `main.py` directly this session; the return dict is `{"text", "duration_ms", "language", "language_probability"}` [VERIFIED] |
| A5 | The `alerter-py` compose block already has the `WHISPER_URL` and `CAPTURE_BASE_PATH` env vars wired | Runtime State Inventory | MEDIUM -- `TenantConfig` has defaults (`http://host.docker.internal:8090` and `/data/signal-capture`); if the actual container uses a different network alias, live-fire will fail. Planner should verify the compose override file before live-fire. |

---

## Open Questions (RESOLVED — dispositions assigned to plan tasks 2026-06-21)

1. **`python-ulid` API for timestamp-seeded generation**
   - What we know: The npm `ulid` package accepts `ulid(capturedAtMs)` to seed the time component.
   - What's unclear: Whether `python-ulid`'s API is `ULID.from_datetime(dt)`, `ULID.from_timestamp(ms)`, or another name.
   - Recommendation: The planner should verify in Wave 0: `python -c "from python_ulid import ULID; print(dir(ULID))"`. If `from_datetime` is absent, use `ULID(datetime=dt)` or the appropriate alternative.

2. **`capture_retention_days` cron: first-run timing**
   - What we know: The Node retention job uses `cron.schedule(config.captureRetentionCron, run)`. The `captureRetentionCron` field defaults to `'0 3 * * *'` (3 AM daily). The Python implementation as an `asyncio.sleep(86400)` loop fires the FIRST run after 24 hours.
   - What's unclear: Whether firing the first run on startup (before sleeping) is preferred.
   - Recommendation: Planner's call; either is correct. Firing on startup is safer (catches up after a long outage). Use `await run_once(); await asyncio.sleep(86400)` loop.

3. **`ALLOWED_ROOT` path alignment between `alerter-py` and `whisper-transcribe`**
   - What we know: `whisper-transcribe/main.py` enforces `ALLOWED_ROOT = Path(os.getenv("ALLOWED_ROOT", "/data/signal-capture"))`. The `transcribe_client` sends an `audio_path` that must be under this root.
   - What's unclear: Whether the `alerter-py` container mounts the same `/data/signal-capture` path as the `whisper-transcribe` container.
   - Recommendation: Verify in compose that both services share the same bind-mount for `/data/signal-capture` before the live-fire. If not, the Whisper service will 400 every transcription request regardless of container health.

**Resolution dispositions (assigned during planning):**
- Q1 (python-ulid timestamp API, A1): RESOLVED-IN-EXECUTION — Plan 58-01 Task 2 is a gated Wave-0 probe that confirms the exact call form (`from ulid import ULID`; `ULID.from_datetime` vs `from_timestamp`) and records it as "A1 RESOLVED" in 58-01-SUMMARY before any implementation task (58-03) uses it. No code guesses the API.
- Q2 (retention first-run timing): RESOLVED — Plan 58-03 Task 2 uses the run-once-then-`asyncio.sleep(86400)` loop (fires on startup to catch up after an outage), per the recommendation.
- Q3 (ALLOWED_ROOT mount alignment, A5): RESOLVED-AT-PREFLIGHT — Plan 58-04 Task 1 preflights `config.capture_base_dir == "/data/signal-capture"` and the operator runbook (58-04 Task 2, prereq 2) verifies the cross-container bind-mount before the live-fire.

---

## Sources

### Primary (HIGH confidence)

- `src/agents/alerter/src/capture.js` -- port target; all orchestration logic, `classify`, `buildPath`, `safeExt`, `handle`, `recordReplyCapture` [VERIFIED: read this session]
- `src/agents/alerter/src/capture-db.js` -- `insertCapture` row shape + all DDL + `markExpiredOlderThan` + `getAttachmentPathsForIds` [VERIFIED: read this session]
- `src/agents/alerter/src/transcribe-client.js` -- `createTranscribeClient` factory shape, never-throws, dual-arg calling convention [VERIFIED: read this session]
- `src/agents/alerter/src/capture-history.js` -- `selectRecentBySender`, `selectRecentOutboundByRecipient` [VERIFIED: read this session]
- `src/agents/alerter/src/capture-retention.js` -- `createRetentionJob`, `markExpiredOlderThan` usage [VERIFIED: read this session]
- `src/whisper-transcribe/main.py` -- `/transcribe` response shape `{text, duration_ms, language, language_probability}`, `/health` contract, `_resolve_safe` ALLOWED_ROOT check [VERIFIED: read this session]
- `src/farm-agent/farm_agent/signal_io/receive_loop.py` -- `dispatch(envelope)` seam, sequential for-loop [VERIFIED: read this session]
- `src/farm-agent/farm_agent/signal_io/client.py` -- `SignalClient.fetch_attachment(id) -> bytes`, `mask_number` [VERIFIED: read this session]
- `src/farm-agent/farm_agent/signal_io/router.py` -- `resolve_farmer(source, config)` primitive [VERIFIED: read this session]
- `src/farm-agent/farm_agent/persistence/pool.py` -- `build_pool` pattern [VERIFIED: read this session]
- `src/farm-agent/farm_agent/persistence/outbound_repo.py` -- never-throws repo pattern, psycopg3 parameterized INSERT [VERIFIED: read this session]
- `src/farm-agent/farm_agent/tenancy/tenant.py` -- `TenantConfig.whisper_url`, `capture_base_dir`, `capture_retention_days` [VERIFIED: read this session]
- `src/farm-agent/tests/conftest.py` -- `FakeOutboundRepo`, `signal_http` (respx) fixture shape [VERIFIED: read this session]
- `src/farm-agent/pyproject.toml` -- current deps (httpx, psycopg, respx); flat test layout [VERIFIED: read this session]
- `.planning/phases/58-capture-transcription/58-CONTEXT.md` -- D-01..D-08 locked decisions [VERIFIED: read this session]
- `.planning/REQUIREMENTS.md` -- CAP-01, CAP-02 verbatim [VERIFIED: read this session]
- `.planning/phases/56-foundation/56-RESEARCH.md` -- `signal_capture` full column inventory [VERIFIED: read this session]
- `.planning/phases/57-signal-i-o/57-RESEARCH.md` + `57-VALIDATION.md` -- Phase 57 patterns, flat test layout, respx approach [VERIFIED: read this session]

### Secondary (MEDIUM confidence)

- `[[project_whisper_cuda_compat_geforce_804]]` memory -- CUDA forward-compat hang root cause (D-07 background) [CITED: project memory]
- `.planning/STATE.md` -- Phase 57 closeout confirmed; current focus Phase 58 [VERIFIED: read this session]

### Tertiary (LOW confidence)

- None -- all claims in this research are backed by verified source files.

---

## Metadata

**Confidence breakdown:**
- Node source behavior: HIGH -- all five files read directly this session
- Python target patterns: HIGH -- all six Python files read directly this session
- ULID package API: MEDIUM -- package existence assumed; API details require Wave 0 probe (A1)
- Whisper container state: HIGH -- D-07 blocker confirmed in CONTEXT.md and STATE.md
- compose environment alignment: MEDIUM -- defaults verified in tenant.py; actual mount config not re-read this session (A5)

**Research date:** 2026-06-21
**Valid until:** 2026-07-21 (stable; all dependencies pinned; only time-sensitive item is the D-07 container health fix)
