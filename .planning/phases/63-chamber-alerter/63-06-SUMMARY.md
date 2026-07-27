# Phase 63 — Plan 06 Summary

**Status:** COMPLETE
**Date:** 2026-07-25
**Branch:** `feat/phase-63-chamber-alerter`

---

## What shipped

### Task 1 — Pure backoff schedule + health parsing
**Commit:** `9aac5c4` — `feat(63): add bridge backoff schedule and health parsing`

- `farm_agent/chamber/ws_client.py`: `MIN_BACKOFF_MS` (1_000), `MAX_BACKOFF_MS`
  (30_000), `next_backoff_ms`, `_dig`, `parse_health`.
- `tests/chamber/test_ws_client.py`: 14 socket-free tests.

**RED observed:**
```
ImportError while importing test module '.../tests/chamber/test_ws_client.py'.
E   ImportError: cannot import name 'ws_client' from 'farm_agent.chamber'
```

### Task 2 — WsClient reconnect loop
**Commit:** `468e350` — `feat(63): add the WsClient reconnect loop over the pure backoff logic`

- `WsClient` with `poll_health`, `_health_loop`, `run`, and the
  `ws_connected` / `ws_last_connected_ms` properties. `connect`, `sleep` and
  `clock` are all injectable.
- 7 further tests appended (21 total in the file).

**RED observed:**
```
E   AttributeError: module 'farm_agent.chamber.ws_client' has no attribute 'WsClient'
tests/chamber/test_ws_client.py:178: AttributeError
```
Task 1's 14 pure tests stayed green throughout.

---

## ⚙ Step 0 — websockets API pinned against the INSTALLED package

RESEARCH Q2 / assumption A1 was unverified. Interrogated the real package rather
than trusting memory. **Plan 08 and Phase 64 depend on these findings:**

| Question | Answer (verified 2026-07-25) |
|----------|------------------------------|
| Version | **16.1.1** |
| Import path | `websockets.connect` exists and is a re-export of **`websockets.asyncio.client.connect`** (`connect.__module__` == `websockets.asyncio.client`) |
| `connect` is | a **class**, not a function |
| `await connect(url)` | ✅ supported (`connect.__await__` exists) → returns `ClientConnection` |
| `async with connect(url)` | ✅ supported (`connect.__aenter__` exists) |
| `ClientConnection` as async CM | ✅ (`__aenter__` / `__aexit__` both present) |
| Iteration | `ClientConnection.__aiter__` yields via `recv()` in an infinite loop; **exits cleanly on `ConnectionClosedOK`**, raises `ConnectionClosedError` on protocol/network failure |
| `ConnectionClosed` | `websockets.exceptions.ConnectionClosed` |

**Idiom chosen:** `sock = await self._connect(url)` then
`async with sock:` / `async for raw in sock:`. This is the one shape that works
identically for the real `connect` class **and** for a plain injected async
callable in tests — the async-context-manager-only form would have forced the
fakes to imitate the `connect` class instead of just returning a socket.

---

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest tests/chamber/test_ws_client.py -v` | **21 passed in 1.80s** (well under the <5s bar) |
| backoff sequence | exactly `[1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]` |
| `parse_health(None, now)` → `ws_connected=True` | ✅ |
| `parse_health(payload, now, ws_connected=False)` preserves `fc1_last_msg_ts` | ✅ |
| malformed-payload parametrization | 6 shapes, none raising |
| `grep -c "httpx.AsyncClient()" ws_client.py` | **0** (no self-constructed client) |
| `grep -c "import websockets" ws_client.py` | **1** |
| `uv run pytest tests/chamber/ -q` | **133 passed** |
| `uv run lint-imports --config .lint-imports` | **1 kept, 0 broken** |
| `uv run pytest tests/ -q` | **782 passed, 36 skipped** (was 761 + 36) |

No skips added; the 36 remain the pre-existing baseline.

---

## Parity verification against the Node source

Read `bridge-client.js` (101 lines) in full. Every plan claim held:

- `backoffMs` starts at `minBackoffMs`; on close Node schedules
  `setTimeout(open, backoffMs)` and only **then** does
  `backoffMs = Math.min(backoffMs * 2, maxBackoffMs)` — wait-then-advance, exactly
  as the plan insisted. The implementation mirrors that ordering.
- `backoffMs = minBackoffMs` on `ws.on('open')` (line 49) — reset on success.
- A failed `/health` poll emits `wsConnected: true` (line 38) — the socket is fine,
  only the data is unknown.
- `ws.on('close')` sources `rosConnected` / `humidifierLastMsgTs` / `fc1LastMsgTs`
  from the cached `lastHealth`, not from null.
- The 10s health cadence starts on open and is cleared on close.

Nothing the plan asserted turned out false.

---

## Deviations

1. **`_health_loop` uses `asyncio.sleep`, not the injected `sleep`.** The injected
   sleep carries the parity-critical **backoff** schedule, and the tests assert on
   the exact contents of the recorded `slept` list. Routing the fixed 10s health
   cadence through the same injection point would have interleaved `10.0` entries
   into that list and corrupted the backoff assertions (and tripped the fakes'
   10-entry loop guard). The health task is cancelled on every close, so it never
   actually elapses in tests — the suite runs in 1.8s. Documented in the method's
   docstring.

2. **Task 1 test count is 14, not 13.** The plan's Step 4 says "13 passed" while
   its own acceptance criteria say 14; 14 is correct (3 backoff + 5 health + a
   6-way parametrization).

3. **`poll_health` re-raises `CancelledError` before the fail-open catch.** Not in
   the plan's text, but required: a bare `except Exception` would not catch
   `CancelledError` (it derives from `BaseException`), and the explicit re-raise
   documents that shutdown is not a "health poll failure". Same guard added around
   the per-frame `json.loads` handler.

---

## Produced for later plans

```python
MIN_BACKOFF_MS: int   # 1_000
MAX_BACKOFF_MS: int   # 30_000
HEALTH_POLL_INTERVAL_S: float  # 10.0

next_backoff_ms(current_ms) -> int
parse_health(payload, now_ms, ws_connected=True) -> dict

class WsClient:
    __init__(*, config, http, on_message, on_liveness, log=None,
             connect=None, sleep=None, clock=None)
    async run() -> None          # reconnect loop; cancel to stop
    async poll_health() -> None
    ws_connected -> bool
    ws_last_connected_ms -> int | None
```

**Plan 08 wiring notes:**
- `http` MUST be boot.py's shared `httpx.AsyncClient` — `WsClient` never builds one.
- `run()` propagates `asyncio.CancelledError`, so boot's
  `except asyncio.CancelledError: pass` shutdown path works unchanged.
- The liveness dict keys (`ws_connected`, `ros_connected`, `humidifier_last_msg_ts`,
  `fc1_last_msg_ts`, `now_ms`) feed Plan 07's `is_pi_offline` / `is_humidifier_stuck`
  arguments directly.
