# Stack Research

**Domain:** Python port of live Node.js Signal-bot / LLM-extraction / farmOS-commit agent (v1.12 Farm-Agent Python Port)
**Researched:** 2026-06-14
**Confidence:** HIGH (all versions verified from PyPI live; signal-cli interop verified from upstream docs and discussion threads; Anthropic SDK and pydantic verified via Context7)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12 | Runtime | `python:3.12-slim-bookworm` Docker base. Structural `match/case` useful for state machines. `asyncio` native. No ROS dependency -- do not use the ROS image. |
| asyncio (stdlib) | built-in | Async runtime | All I/O is I/O-bound (signal-cli socket, Postgres, LLM, WebSocket). Single event loop, no threads. Direct port of the Node event loop model. |
| anthropic | 0.109.1 | Anthropic Claude API | Official SDK. `AsyncAnthropic` is asyncio-native. `output_format=PydanticModel` enables direct structured output; tool-use passes `Model.model_json_schema()` as `input_schema`. Replaces `@anthropic-ai/sdk`. |
| pydantic | 2.13.4 | Schema validation + JSON-schema export for LLM | Replaces `zod` + `zod-to-json-schema`. `Model.model_json_schema()` emits OpenAPI-compatible JSON Schema; `Model.model_validate(data)` replaces `schema.parse(data)`. Rust core, fast. |
| psycopg (with [binary] extra) | 3.3.4 | PostgreSQL / TimescaleDB driver | See rationale below. Replaces `pg` (Node). Use `AsyncConnection` + `AsyncConnectionPool`. |
| psycopg-pool | 3.3.1 | Connection pooling for psycopg3 | Separate package; required for `AsyncConnectionPool`. |
| websockets | 16.0 | WebSocket client to ROS bridge | Replaces `ws` npm package in bridge-client.js. Pure asyncio; `connect()` is an async context manager. |
| python-ulid | 3.1.0 | ULID generation | Replaces `ulid` npm package. `ULID()` generates; sortable, stores as TEXT or UUID in Postgres. |
| Pillow | 12.2.0 | Image prep for LLM vision | Replaces `jimp`. Resize + JPEG re-encode before base64 encoding for Claude. |
| ruamel.yaml | 0.19.1 | Tenant config parsing | Replaces `yaml` npm package. Preserves YAML comments on round-trip (useful if config is ever written back). |
| httpx | 0.28.1 | farmOS HTTP client (async) | Replaces the implicit `node-fetch` / axios patterns in farmos/client.js. `httpx.AsyncClient` works inside asyncio. Do NOT use `requests` (blocking -- will stall the event loop). |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| APScheduler | 3.11.2 | Watchdog / cron schedulers | Replaces `node-cron`. Use `AsyncIOScheduler` for the commit-watchdog and draft-expiry watchdog. Pin `<4` -- v4 is a breaking API rewrite not yet production-stable. For simple interval watchdogs, a bare `asyncio.create_task` + `asyncio.sleep` loop is fine and avoids the APScheduler dependency entirely. |
| pytest | 9.1.0 | Test runner | Standard. |
| pytest-asyncio | 1.4.0 | Async test support | Required for testing asyncio coroutines. Set `asyncio_mode = "auto"` in `pyproject.toml`. |
| ruff | 0.15.17 | Linter + formatter | Replaces flake8 + isort + black as a single tool. Millisecond feedback. Replaces `ament_flake8`. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| uv | Dependency management + venv | Deterministic lockfile (`uv.lock`), fast installs, pyproject.toml-native. Use `uv sync` in Dockerfile. Replaces pip + venv + requirements.txt. |
| pyproject.toml | Single config file | All tool config (ruff, pytest, mypy if desired) goes here. No setup.py. |
| python:3.12-slim-bookworm | Docker base image | Alerter has zero ROS dependency -- use slim Python base, not `ros:jazzy-ros-core`. Smaller, cleaner. |

---

## The signal-cli Interop Decision

This is the most consequential architecture choice in the port. Four options exist:

### Option A: Raw JSON-RPC over UNIX socket -- RECOMMENDED

signal-cli runs in `daemon` mode exposing a UNIX socket (path: `$XDG_RUNTIME_DIR/signal-cli/socket`, or a fixed compose volume path). The Python process opens an asyncio `StreamReader`/`StreamWriter` to this socket and exchanges newline-terminated JSON-RPC 2.0 messages.

Receive: signal-cli in `--receive-mode=on-start` (default) pushes unsolicited `{"jsonrpc":"2.0","method":"receive","params":{...}}` notifications on the persistent connection. A background `asyncio.Task` reads these in a `async for line in reader` loop and dispatches envelopes to the receive-loop handler.

Send: `{"jsonrpc":"2.0","method":"send","params":{"recipient":["+NNN"],"message":"..."},"id":"<ulid>"}` + newline.

**Why this is correct:**
- The existing Node alerter already uses the JSON-RPC socket. This preserves the deployment topology (signal-cli as a sidecar in compose) exactly.
- Zero new runtime dependencies -- stdlib `asyncio` streams only.
- Full control over envelope parsing, quote-threading (Phase-50 bugs), and attachment (audio/image) enumeration at the wire level.
- Implementation is ~150-200 lines of straightforward async I/O.

### Option B: signalbot 1.2.2

An async Python bot framework that communicates with signal-cli via an intermediate `signal-cli-rest-api` HTTP/WebSocket sidecar.

**Why not:** Requires an additional `signal-cli-rest-api` container. Adds a framework abstraction over the envelope format. The alerter needs envelope-level control (quote threading, multi-farmer routing, attachment enumeration) that signalbot's `Command` model fights. Signalbot is designed for simple command-response bots.

### Option C: DBus (pydbus)

signal-cli exposes a DBus interface (`org.asamk.Signal`). pydbus can subscribe to `MessageReceived` signals.

**Why not:** DBus is session IPC designed for desktop environments. Making it work inside Docker requires a dbus-daemon and session management -- non-trivial and not the existing stack's approach. Ruled out.

### Option D: subprocess stdin/stdout (jsonRpc command)

Run `signal-cli jsonRpc` as a subprocess; communicate via stdin/stdout.

**Why not:** More fragile than a socket. Subprocess restart semantics, signal propagation, and EOF handling need manual plumbing. The `daemon` + socket model is strictly superior.

**Decision: Option A (raw JSON-RPC UNIX socket).** No new deps. Same topology. Full control.

---

## Postgres Driver: psycopg3 over asyncpg

Both are production async Postgres drivers. The choice is **psycopg3**.

**Rationale:**

1. **farmos-agent precedent.** The existing Python service uses `psycopg2`. psycopg3 is its direct successor -- same `%s` param syntax, same connection string format, same `cursor.fetchone()` / `fetchall()` API. Port effort is minimal.

2. **SQL param syntax continuity.** asyncpg uses PostgreSQL-native `$1`-style positional params. The existing Node `pg` package uses `$1` syntax too, but the mental overhead of writing Python with asyncpg's record types and then context-switching to psycopg3 in `farmos-agent` (when both touch the same Timescale DB) is not worth the performance gain.

3. **Performance gap is irrelevant for this workload.** asyncpg benchmarks 25-35% faster than psycopg3 at high concurrency. The alerter's DB workload is single-row inserts and point lookups (one row per envelope, one per draft state change). asyncpg's throughput advantage does not materialize.

4. **psycopg3 is actively maintained** (3.3.4 as of June 2026).

Install: `psycopg[binary]>=3.3` + `psycopg-pool>=3.3`. The `[binary]` extra bundles its own libpq -- no system package needed in Docker.

---

## Async Runtime Model

**Pure asyncio. No threads. No trio.**

The alerter runs three concurrent I/O streams:
1. signal-cli UNIX socket reader (envelope receive loop)
2. Anthropic LLM calls (extraction, gating, confirm parsing) -- `AsyncAnthropic`
3. Postgres writes (draft state, outbound queue) -- `psycopg.AsyncConnection`
4. WebSocket to ROS bridge (if telemetry queries needed) -- `websockets`

All are I/O-bound. asyncio handles them correctly. The JS state machines (confirm/, event-gate/) translate directly to Python `async def` + `await` with identical structure.

**Watchdogs:** For simple interval watchdogs (commit-watchdog, draft-expiry), use a bare `asyncio.create_task` wrapping a `while True: await asyncio.sleep(N)` loop. This is simpler than APScheduler for periodic tasks with no cron expression requirement. Use APScheduler only if you need a time-of-day cron trigger or job persistence.

---

## Schema Validation + LLM Structured Extraction

pydantic v2 replaces both `zod` and `zod-to-json-schema`:

```python
from pydantic import BaseModel, Field
import json

class InocolationDraft(BaseModel):
    session_id: str = Field(description="ULID of the inoculation session")
    parent_block_names: list[str] = Field(description="Source substrate block names")
    # ...

# For tool-use extraction -- replaces zodToJsonSchema(schema)
tool_schema = InocolationDraft.model_json_schema()

# For validating LLM response -- replaces schema.parse(data)
draft = InocolationDraft.model_validate(llm_json_response)
```

The Anthropic SDK also supports `output_format=InocolationDraft` in `messages.stream()` for direct structured output without tool-use. Either pattern works; tool-use is more explicit and matches the existing pipeline's approach.

---

## farmOS HTTP Client

Use `httpx.AsyncClient` with a persistent session (reuse across requests). Session-cookie auth pattern is identical to `farmos-agent`'s `requests.Session`, just async:

```python
async with httpx.AsyncClient() as client:
    resp = await client.post(f"{farmos_url}/user/login", ...)
    csrf = resp.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf
```

Do NOT use `requests` -- it blocks the event loop on every call.

---

## Installation

```toml
# pyproject.toml
[project]
name = "mushy-alerter"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.109",
    "pydantic>=2.13",
    "psycopg[binary]>=3.3",
    "psycopg-pool>=3.3",
    "websockets>=16.0",
    "python-ulid>=3.1",
    "Pillow>=12.2",
    "ruamel.yaml>=0.19",
    "httpx>=0.28",
    "APScheduler>=3.10,<4",    # v4 is a breaking rewrite; stay on v3.x
]

[project.optional-dependencies]
dev = [
    "pytest>=9.1",
    "pytest-asyncio>=1.4",
    "ruff>=0.15",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
```

```dockerfile
# Dockerfile (alerter)
FROM python:3.12-slim-bookworm
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev
COPY src/ ./src/
CMD ["uv", "run", "python", "-m", "alerter"]
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| psycopg3 | asyncpg | If throughput on bulk inserts (>1k rows/s) is a concern; not the case for the alerter's envelope-per-message workload. |
| raw JSON-RPC socket | signalbot | If building a simple command-response bot with no multimodal pipeline and happy to run signal-cli-rest-api as an extra sidecar. |
| httpx.AsyncClient | aiohttp | Either works; httpx has a more requests-compatible API that eases the port from farmos-agent. |
| APScheduler 3.x | asyncio.create_task loop | For simple interval watchdogs a bare while-loop task is simpler. Use APScheduler if you need cron expressions or job persistence. |
| ruamel.yaml | PyYAML 6.0.3 | PyYAML is fine if configs are strictly read-only. Prefer ruamel.yaml if configs are written back. |
| python:3.12-slim-bookworm | ros:jazzy-ros-core | farmos-agent uses the ROS base because it is a ROS2 lifecycle node. The alerter has zero ROS dependency; use the slim Python base -- smaller, faster builds. |

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| SQLAlchemy / Tortoise ORM | Heavy ORM for direct SQL with known schemas; adds a mapping layer with no benefit | Raw psycopg3 with typed row factories |
| FastAPI / Starlette / Flask | The alerter is not an HTTP server; it is a long-running daemon with socket I/O | Plain asyncio entry point (`asyncio.run(main())`) |
| Celery + Redis | Task queue overkill for a single-process sequential pipeline | `asyncio.Queue` for internal fan-out between receive-loop and extraction workers |
| dbus-python / pydbus | DBus signal-cli interface is Docker-hostile; existing stack does not use it | JSON-RPC UNIX socket (Option A) |
| tenacity / retry library | Simple exponential backoff for LLM + farmOS is ~10 lines | Inline retry loop |
| signalbot / pysignalclijsonrpc | Both add abstraction layers over the JSON-RPC socket with no gain for envelope-level pipeline control | Raw asyncio stream reads (Option A) |
| APScheduler 4.x | API is a complete rewrite (different scheduler class hierarchy, different import paths); not yet production-stable | APScheduler 3.x pinned `<4` |
| PydanticAI | Agent framework that abstracts the LLM call; the alerter's state machine IS the agent -- adding another agent framework creates two competing control flows | anthropic SDK directly |
| requests (blocking) | Blocks the asyncio event loop on every HTTP call | httpx.AsyncClient |
| node-cron Python equivalents (schedule, crontab) | Thread-based; fight asyncio | APScheduler AsyncIOScheduler or bare asyncio.sleep loops |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| anthropic 0.109.x | pydantic 2.x | SDK uses pydantic internally; no conflict. |
| psycopg 3.3 | psycopg-pool 3.3 | Major versions must match. Install both. |
| psycopg[binary] | Python 3.11/3.12, TimescaleDB | Bundles libpq; no system package needed in Docker. If using psycopg[c] instead, add `libpq-dev` to apt. |
| APScheduler 3.11.x | Python 3.11/3.12, asyncio | Do NOT upgrade to 4.x without reading migration guide. |
| websockets 16.0 | Python 3.11/3.12 | API stable; `websockets.connect()` is the async context manager. |
| pytest-asyncio 1.4.0 | pytest 9.x | Set `asyncio_mode = "auto"` in pyproject.toml to avoid per-test decorator. |
| Pillow 12.2.0 | Python 3.11/3.12 | Install `libjpeg-dev` in Docker apt if building from source; `[binary]` wheels include it. Standard slim image works with the pre-built wheel. |

---

## Existing Python Precedent: farmos-agent

`src/farmos-agent/` is a ROS2 Python lifecycle node that:
- Uses `requests` (sync, acceptable because it runs in a ROS2 executor thread, not asyncio)
- Uses `python3-psycopg2` (via apt, not pip)
- Uses `python3-apscheduler` (via apt)
- Has no `pyproject.toml`; uses `setup.py` (ROS2 convention)

The new alerter diverges from this on purpose: it uses async equivalents (`httpx`, `psycopg3`) because it runs in a pure asyncio loop, and `pyproject.toml` + `uv` because it is not a ROS2 package. Do not inherit the farmos-agent's sync patterns into the alerter.

---

## Sources

- `/anthropics/anthropic-sdk-python` (Context7) -- async client, structured output with pydantic, tool-use input_schema pattern
- `/pydantic/pydantic` (Context7) -- `model_json_schema()` export, v2 validation API
- `/psycopg/psycopg` (Context7) -- `AsyncConnectionPool`, async connection patterns, pool with FastAPI lifespan (analogous pattern)
- PyPI live versions verified 2026-06-14: anthropic 0.109.1, pydantic 2.13.4, psycopg 3.3.4, psycopg-pool 3.3.1, asyncpg 0.31.0, websockets 16.0, python-ulid 3.1.0, Pillow 12.2.0, APScheduler 3.11.2, ruamel.yaml 0.19.1, httpx 0.28.1, ruff 0.15.17, pytest 9.1.0, pytest-asyncio 1.4.0, PyYAML 6.0.3
- https://github.com/AsamK/signal-cli/wiki/JSON-RPC-service -- JSON-RPC transport options, receive-mode semantics
- https://github.com/AsamK/signal-cli/discussions/799 -- socket path, newline-terminated protocol, subscribeReceive for manual mode
- https://github.com/AsamK/signal-cli/blob/master/man/signal-cli-jsonrpc.5.adoc -- full JSON-RPC method list and notification format
- https://pypi.org/project/signalbot/ -- signalbot 1.2.2; confirmed signal-cli-rest-api dependency (extra sidecar required)
- https://fernandoarteaga.dev/blog/psycopg-vs-asyncpg/ -- psycopg3 vs asyncpg benchmark; 25-35% asyncpg advantage at scale; MEDIUM confidence
- `src/farmos-agent/Dockerfile` + `farmos_client.py` -- existing Python precedent (psycopg2, requests, APScheduler in apt)

---
*Stack research for: v1.12 Farm-Agent Python Port (mushy alerter)*
*Researched: 2026-06-14*
