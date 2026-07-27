# Phase 57: Signal I/O - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 14 (7 source modules + 7 unit tests)
**Analogs found:** 14 / 14 (every file has BOTH a Node port-target and a Phase-56 Python idiom analog)

> This is a **1:1 behavior-preserving Node→Python port** gated by the Phase-64 parity check. Two analog axes apply to every file:
> 1. **Node port-target** — the structure/behavior source of truth (what to translate).
> 2. **Phase-56 Python analog** — the established idiom on disk (package layout, psycopg3 repo shape, TenantConfig injection, conftest/test layout) the new file must MIRROR, not just the JS.
>
> The Python package on disk is `farm_agent/` (under `src/farm-agent/`), package dir `signal_io/` does NOT yet exist (Wave 0). Tests live in `tests/` (flat), NOT `tests/unit/` — RESEARCH proposed `tests/unit/signal_io/` but the Phase-56 layout on disk is flat `tests/test_*.py`. **Planner: reconcile — either nest under `tests/unit/signal_io/` (RESEARCH/Validation-Architecture preference) or keep flat `tests/test_signal_*.py` (matches Phase-56 on-disk). Flat matches what exists; nested matches the research test-map commands. Recommend flat for Phase-56 consistency unless the planner wants the suite folder split.**

## File Classification

| New File | Role | Data Flow | Node Port-Target | Python Idiom Analog | Match |
|----------|------|-----------|------------------|---------------------|-------|
| `farm_agent/signal_io/client.py` | service (SignalClient) | request-response + rate-cap | `signal.js` (whole `createSignalClient`) | `persistence/pool.py` (async/httpx-style ctor + injection), `tenancy/tenant.py` (frozen-config consumption) | exact |
| `farm_agent/signal_io/quote.py` | utility | transform/validate | `signal.js:71-131` (`isValidQuote` + payload build) | `tenancy/tenant.py` `_parse_*`/`_resolve_*` pure-helper module shape | role-match |
| `farm_agent/signal_io/groups.py` | utility | request-response (lazy cache) | `signal.js:22-39, 98-112` (`ensureGroupsLoaded` + translate) | `persistence/pool.py` (httpx/psycopg async helper shape) | role-match |
| `farm_agent/signal_io/ratecap.py` | utility/state | event-driven (in-mem state + Lock) | `signal.js:13, 41-56, 82-89, 147, 226-229` (`sendHistory`, `pruneHistory`, `currentCap`) | (NEW: `asyncio.Lock` — no Node or Py analog; only genuinely new mechanism) | partial |
| `farm_agent/signal_io/router.py` | service | event-driven (envelope routing) | `receive-loop.js:14-29, 124-156` (whitelist, DM-vs-group, `collectGroupTriggers`) + `capture.js:86` (`(unassigned)`) + `config.js:258` (`maskNumber`) | `tenancy/tenant.py` (pure-function module + frozen-config reads) | role-match |
| `farm_agent/signal_io/receive_loop.py` | service | event-driven (poll loop) | `receive-loop.js:47-70, 130-156` (`createReceiveLoop` skeleton: poll → sequential dispatch) | `persistence/pool.py` (async lifecycle: build/open/close ↔ start/stop) | role-match |
| `farm_agent/persistence/outbound_repo.py` | repository | CRUD (single INSERT) | `outbound-db.js:54-82` (`insertOutbound` never-throw) | `persistence/migrations.py` + `persistence/pool.py` (psycopg3 `async with pool.connection()`, parameterized SQL) | exact |
| `tests/test_signal_client.py` | test | — | (no Node test analog) | `tests/test_persistence.py` (skipif gate, async tests) + `tests/conftest.py` (TEST_ENV) | role-match |
| `tests/test_signal_quote.py` | test | — | — | `tests/test_persistence.py` (pure DB-independent unit shape, e.g. `test_make_conninfo_*`) | role-match |
| `tests/test_signal_groups.py` | test | — | — | `tests/test_persistence.py` | role-match |
| `tests/test_signal_ratecap.py` | test | — | — | `tests/test_persistence.py` (async) | role-match |
| `tests/test_signal_router.py` | test | — | — | `tests/test_persistence.py` (DB-independent pure unit) | role-match |
| `tests/test_signal_receive_loop.py` | test | — | — | `tests/test_persistence.py` | role-match |
| `tests/test_signal_persist.py` | test | — | — | `tests/test_persistence.py` (fail-open via fake repo) | role-match |

> **Module-split note:** RESEARCH's structure lists only `client.py` / `router.py` / `receive_loop.py` (3 files) and folds quote/groups/ratecap INTO `client.py`. The table above splits them for clarity/testability. **Planner decision:** either keep the RESEARCH 3-file layout (quote/groups/ratecap as private methods/functions inside `client.py` — matches `signal.js`'s single-factory shape most faithfully, lowest parity-diff) OR split into helper modules (more Pythonic, easier unit isolation). **Recommend: keep it close to `signal.js` — one `client.py` SignalClient with `is_valid_quote`/`ensure_groups_loaded`/`_prune_history`/`_current_cap` as methods/module-funcs, and a separate `router.py` + `receive_loop.py`.** The per-capability test files still map cleanly either way.

## Pattern Assignments

### `farm_agent/signal_io/client.py` (service, SignalClient)

**Node port-target:** `src/agents/alerter/src/signal.js` (entire `createSignalClient`, lines 5-232)
**Python idiom analog:** `farm_agent/persistence/pool.py` (constructor-injection + httpx/psycopg async client style), `farm_agent/tenancy/tenant.py` (reads frozen `TenantConfig`, never `os.environ`)

**Constructor / injection pattern** — port `signal.js:5-13`. Node passes a loose opts-bag (`apiUrl, sender, recipient, defaultTarget, maxSendsPerHour, getMaxSendsPerHour, outboundDb, pool, tenantId`). In Python, inject `TenantConfig` + `httpx.AsyncClient` + the `outbound_repo` + `pool`. Mirror `pool.py`'s injection idiom (config in, opened resource out):
```python
# pool.py:19-21 — the established injection shape to mirror
async def build_pool(config: TenantConfig) -> AsyncConnectionPool:
    ...
# client.py ctor should take: config: TenantConfig, http: httpx.AsyncClient,
#   outbound_repo, pool, get_max_sends_per_hour: Callable[[], int] | None, logger
# effectiveDefault resolution (signal.js:8-11): defaultTarget ?? recipient; raise if empty
```

**Send choke-point + target resolution** — port `signal.js:82-112` verbatim (RESEARCH Pattern 1, Code Examples §Send):
```javascript
// signal.js:91-112 — target resolution (str phone | {groupId})
const target = to !== undefined ? to : effectiveDefault;
const isStringTarget = typeof target === 'string' && target.length > 0;
const isGroupTarget = target && typeof target === 'object' && typeof target.groupId === 'string' && target.groupId.length > 0;
if (!isStringTarget && !isGroupTarget) throw new Error('invalid send target');
// group → ensureGroupsLoaded(false), translate internal_id→id-b64, recipients = [`group.${resolvedGroupId}`]
```
Python: `target = to if to is not None else effective_default`; `isinstance(target, str)` vs `isinstance(target, dict) and target.get("groupId")`; `raise ValueError("invalid send target")`.

**Send POST (fetch → httpx)** — port `signal.js:133-203` (RESEARCH Code Examples §Send). `AbortController + setTimeout` → `httpx` `timeout=`; `res.ok` check → `if r.status_code >= 400: raise RuntimeError(...)`; `json.timestamp || now` → `data.get("timestamp") or now`. Return `{"ok": True, "timestamp": ...}` / `{"ok": False, "reason": "rate-cap"}`.

**Receive + fetch_attachment + accounts** — port `signal.js:205-224` (RESEARCH Code Examples §Receive / §Fetch attachment). `arrayBuffer()`+`Buffer.from` → `r.content` (bytes). `encodeURIComponent` → `urllib.parse.quote_plus`.

**Log masking** — every send/route log line must mask the e164 via the ported `mask_number` (see router.py; `config.js:258`). `signal.js:148-151` builds the log label with `maskNumber(target)` / `group:<id[:8]>…`.

---

### `farm_agent/signal_io/quote.py` (utility, validate/transform — SIG-04)

**Node port-target:** `src/agents/alerter/src/signal.js:71-80` (`isValidQuote`) + `:119-131` (payload build)
**Python idiom analog:** `farm_agent/tenancy/tenant.py:98-128` (`_parse_int_env` / `_parse_float_env` — pure tolerant-coercion helpers with try/except + module-level functions)

**`is_valid_quote` shape check** — port `signal.js:71-80` (RESEARCH Pitfall 3 gives the exact Python):
```python
# Source: signal.js:71-80 — Number.isFinite(Number(ts)) → math.isfinite(float(str(ts)))
def is_valid_quote(q) -> bool:
    if not isinstance(q, dict):
        return False
    try:
        ts_ok = math.isfinite(float(str(q.get("timestamp"))))
    except (TypeError, ValueError):
        return False
    return (ts_ok and isinstance(q.get("author"), str) and len(q["author"]) > 0
            and isinstance(q.get("message"), str))  # empty message allowed
```

**Payload coercion + fail-open** — port `signal.js:119-131`. Valid → `payload["quote"] = {"timestamp": int(str(quote["timestamp"])), "author": ..., "message": ...}` (RESEARCH: `int(str(ts))` NOT `float()`, NOT bare `int()`). Invalid → `logger.warning(...)` and send WITHOUT the quote field — NEVER raise (D-05 fail-open, `[[feedback_no_silent_failure_after_farmer_confirm]]`).

**Anti-pattern (RESEARCH):** `int(q['timestamp'])` without `str()` raises on a numeric-string. Always `int(str(ts))`.

---

### `farm_agent/signal_io/groups.py` (utility, lazy cache — SIG-03/SC#2)

**Node port-target:** `src/agents/alerter/src/signal.js:20-39` (`groupIdMap` + `ensureGroupsLoaded`) + `:98-112` (translate-on-send)
**Python idiom analog:** `farm_agent/persistence/pool.py` (async resource helper, try/except-warn degradation)

**Lazy-load + translate** — port `signal.js:22-39` (RESEARCH Pattern 3 gives exact Python). `Map` → `dict`; `g.id.slice('group.'.length)` → `g["id"][len("group."):]`; fail → `logger.warning(...)`, do NOT throw (send may still pass through as-is). Force-refresh-once-on-miss semantics from `signal.js:101-108`.

---

### `farm_agent/signal_io/ratecap.py` (state, in-mem + asyncio.Lock — SIG-02/SC#4)

**Node port-target:** `src/agents/alerter/src/signal.js:13` (`sendHistory = []`), `:41-44` (`pruneHistory`), `:46-56` (`currentCap`/`getMaxSendsPerHour`), `:82-89` (cap check), `:147` (`sendHistory.push`), `:226-229` (`sendsThisHour`)
**Python idiom analog:** **NONE on disk** — `asyncio.Lock` is the single genuinely new mechanism (RESEARCH "Key insight"). No Phase-56 file uses it.

**Prune + dynamic cap** — port `signal.js:41-56`:
```javascript
// signal.js:41-44  cutoff = now - 3600000; shift entries older than cutoff
// signal.js:48-56  currentCap(): try getMaxSendsPerHour() finite number, else maxSendsPerHour
```
Python: `cutoff = now - 3_600_000`; `self._send_history = [t for t in self._send_history if t >= cutoff]`.

**Lock-guarded check+reserve** — RESEARCH Pattern 2 (the ONE deviation from "copy the logic"):
```python
# Source: signal.js:82-89, 147 + asyncio.Lock (PITFALLS #6 / D-04)
async with self._lock:
    self._prune_history(now)
    cap = self._current_cap()
    if not bypass_cap and len(self._send_history) >= cap:
        self._logger.warning(f"[signal] cap reached ({len(self._send_history)}/{cap}/h) — dropping")
        return {"ok": False, "reason": "rate-cap"}
    self._send_history.append(now)   # reserve BEFORE await (RESEARCH option (a))
# POST /v2/send OUTSIDE the lock
```
**RESEARCH design note (flag for Phase-64 parity):** Node appends only on POST success (`signal.js:147`); option (a) reserve-before-await counts attempts. Micro-delta, never matters at 20/h. **Do NOT hold the lock across `await client.post(...)`** (would serialize all sends).

---

### `farm_agent/signal_io/router.py` (service, envelope routing — SIG-03/SC#5)

**Node port-target:** `src/agents/alerter/src/receive-loop.js:14-29` (`collectGroupTriggers`), `:124-128` (`allowedSenders` whitelist), `:134-156` (source extract, whitelist gate, DM-vs-group, triggers) + `src/agents/alerter/src/capture.js:86` (`(unassigned)` resolution) + `src/agents/alerter/src/config.js:258-261` (`maskNumber`)
**Python idiom analog:** `farm_agent/tenancy/tenant.py` (pure module functions + frozen-config reads; `_resolve_farmer_map` already builds the `signal_farmer_map` dict this router consumes)

> **SCOPE BOUNDARY (RESEARCH "Scope Boundary Note" — load-bearing):** CONTEXT lists `message.js` as the routing source. **That is WRONG — `message.js` is the alert FORMATTER (`formatProblem`/`fmtNum`), belongs to Phase 63 `chamber/message.py`, NOT signal_io.** Routing actually lives in `receive-loop.js`. Port ONLY the attribution-sensitive skeleton: source extract + whitelist + DM-vs-group + group-trigger + `(unassigned)` resolution + a `dispatch(envelope)` seam. The confirm/snooze/experiment/capture dispatch branches (`receive-loop.js:184+`) are LATER phases — do NOT port them here.

**Whitelist gate** — port `receive-loop.js:124-128, 139-142`:
```javascript
// receive-loop.js:126-128
const allowedSenders = new Set([config.signalSender, config.signalRecipient, ...(config.signalAdditionalSenders||[])].filter(Boolean));
// receive-loop.js:139 — gate BEFORE any branch (V4 access control, T-17-02/R7)
if (!allowedSenders.has(source)) { logger.warn('[receive] rejected sender (not in whitelist)'); continue; }
```
Python: build a `set` from `config.signal_sender`, `config.signal_recipient`, additional senders. Read via `TenantConfig`, never env (mirror `tenant.py`).

**DM-vs-group + triggers** — port `receive-loop.js:14-29, 149-156`. Defensive dual-shape read `env?.envelope?.dataMessage || env?.dataMessage` → `env.get("envelope", {}).get("dataMessage") or env.get("dataMessage") or {}` (V5 input validation). `isGroup = bool(groupId) and groupType not in ("UPDATE","QUIT")`.

**`(unassigned)` resolution primitive (SC#5)** — port `capture.js:86`. This is the primitive RESEARCH says MUST land here (Pitfall 6), not wait for Phase-58:
```javascript
// capture.js:86
const farmosPerson = signalFarmerMap.get(source) ?? '(unassigned)';
```
Python: `def resolve_farmer(source: str) -> str: return config.signal_farmer_map.get(source) or "(unassigned)"`. The `signal_farmer_map` dict is already produced by `tenant.py:_resolve_farmer_map`. Unknown-but-whitelisted sender must NOT be dropped → tagged `(unassigned)`.

**maskNumber** — port `config.js:258-261` (V7 logging):
```javascript
// config.js:258-261
function maskNumber(n) {
  if (typeof n !== 'string' || n.length < 6) return 'XXXX';
  return n.slice(0,2) + 'X'.repeat(n.length-6) + n.slice(-4);
}
```
Python: `n[:2] + "X"*(len(n)-6) + n[-4:]` with the `< 6` guard → `"XXXX"`.

---

### `farm_agent/signal_io/receive_loop.py` (service, poll loop)

**Node port-target:** `src/agents/alerter/src/receive-loop.js:47-70` (`createReceiveLoop` ctor: `signalClient, dispatch, config, logger, clock`), `:130-156` (`tick()` poll → **sequential** envelope iteration)
**Python idiom analog:** `farm_agent/persistence/pool.py` (async lifecycle: `open=False` then `await open()` ↔ `start()/stop()` start/stop seam)

**Sequential dispatch (attribution-critical)** — port `receive-loop.js:132-133` `for (const env of envelopes)` as a Python `for env in envelopes:` with one `await` per envelope. **RESEARCH anti-pattern + memory `[[feedback_verify_signal_send_attribution]]`: NEVER `asyncio.gather()` over envelopes — it breaks send-attribution ordering (PITFALLS #5/#6).** Read `env["envelope"]["source"]` directly; never infer from arrival order/length.

**Loop-never-dies** — port `receive-loop.js:131` try/except: log warning, next tick proceeds (Pitfall 4). Use `asyncio` task + cancel for start/stop (Node uses `setInterval`/`clearInterval` via `timer`).

> RESEARCH Open Question A3: the live Node alerter polls the SAME `/v1/receive` (destructive drain) on the shared `signal-cli` account. Two pollers race. Flag for the planner: SC#1 live round-trip needs the Node alerter receive loop stopped OR a bot→bot self-send (`+59891840205`), per the Phase-50 spike.

---

### `farm_agent/persistence/outbound_repo.py` (repository, CRUD — SIG-02)

**Node port-target:** `src/agents/alerter/src/outbound-db.js:54-82` (`insertOutbound`, never-throw `{ok, reason}`)
**Python idiom analog:** `farm_agent/persistence/migrations.py:32-38` + `farm_agent/persistence/pool.py:44-52` (psycopg3 `async with pool.connection()`, parameterized SQL, `AsyncConnectionPool` type)

> **DDL is already done.** `migrations.py:263-327` (`_run_outbound_migrations`) already creates `signal_outbound` + `signal_msg_ts bigint` + indexes. This repo file ONLY writes rows — no DDL, no `initDb`. (Node's `outbound-db.js` mixed DDL+writes; the Python split puts DDL in migrations.py per Phase-56 D-02.)

**Never-throw INSERT** — port `outbound-db.js:54-82`. Node uses `$1..$11` placeholders + returns `{ok:false, reason}` on exception. Python psycopg3 uses `%s` placeholders inside `async with pool.connection() as conn: await conn.execute(sql, params)`:
```javascript
// outbound-db.js:57-77 — column order is the contract (match it exactly)
INSERT INTO signal_outbound
  (tenant_id, sent_at, recipient_e164, intent, body, attachments,
   source_module, source_line, related_capture_id, related_draft_id, signal_msg_ts)
VALUES ($1..$10, $11)
// attachments: JSON.stringify(...) or null  → psycopg Jsonb(...) or None
// signal_msg_ts: row.signal_msg_ts ?? null  (insertOutbound does NOT coerce; caller already int()'d)
```
psycopg3 SQL: `VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)`. Mirror `migrations.py`'s `async with pool.connection()` acquisition (NOT a raw cursor). Return `{"ok": True}` / `{"ok": False, "reason": str(e)}` — **never raise** (D-02 fail-open; the `signal.js:171-196` caller ALSO wraps in try/except — defense in depth, keep both).

**Coercion happens in client.py, not here** — `signal_msg_ts = int(data["timestamp"]) if data.get("timestamp") else None` is built by the CALLER (`signal.js:187` does `Number(json.timestamp)`); the repo stores as-is (`outbound-db.js:75`). RESEARCH Pitfall 1: `int(str(ts))`, NEVER `float()`; bigint-safe.

---

## Shared Patterns

### Constructor injection of TenantConfig (no direct env reads)
**Source:** `farm_agent/persistence/pool.py:19` + `farm_agent/tenancy/tenant.py` (sole `os.environ` reader)
**Apply to:** `client.py`, `router.py`, `receive_loop.py`
Every signal_io module receives `TenantConfig` (and the httpx client / pool / repo) by injection. NONE reads `os.environ`. `SIGNAL_SENDER` is env-only (already enforced by `tenant.py:294 _must_env`).

### psycopg3 connection acquisition
**Source:** `farm_agent/persistence/migrations.py:32` + `pool.py:44-51`
**Apply to:** `outbound_repo.py`
```python
async with pool.connection() as conn:
    await conn.execute(sql, params)   # %s placeholders, NOT $1
```
`AsyncConnectionPool` type hint (psycopg-pool), NOT asyncpg (Phase-56 D-01 lock).

### Fail-open on the send path (never throw, warn + proceed)
**Source:** `signal.js:119-131` (quote), `:171-196` (persist), `outbound-db.js:79-81` (repo)
**Apply to:** `quote.py`, `groups.py`, `outbound_repo.py`, `client.py` persist hook
Invalid quote shape, group-list fetch failure, and outbound-insert failure ALL degrade to warn-log + continue. Load-bearing for `[[feedback_no_silent_failure_after_farmer_confirm]]` (vague ack beats no ack).

### Test layout (skipif DB gate + pure unit + TEST_ENV)
**Source:** `tests/conftest.py` (TEST_ENV dict, session `pool` fixture, socket-reachability skip) + `tests/test_persistence.py` (`@_requires_db` skipif, DB-independent pure tests that ALWAYS run)
**Apply to:** all `tests/test_signal_*.py`
- HTTP-mocked unit tests (httpx) need NO DB → no `pool` fixture, always run. **RESEARCH: decide `respx` (declarative, recommended) vs monkeypatched `AsyncClient`; `respx` is NOT in Phase-56 deps — add to dev deps + slopcheck before pinning.**
- The fail-open persist test (`test_signal_persist.py`) uses a FAKE repo that raises, asserts `send()` still returns `{"ok": True}` — no real DB (mirror `test_persistence.py`'s DB-independent style).
- The SC#4 concurrency test runs two `send()` coroutines (async test; `asyncio_mode = "auto"` already set in `pyproject.toml`).
- `pytest-asyncio` is already configured; async test functions need no decorator (auto mode, as in `test_persistence.py:99`).

### Logging masks PII (maskNumber on every number)
**Source:** `config.js:258-261`
**Apply to:** `client.py`, `router.py`, `receive_loop.py`
Never log a full e164. Group labels truncated to 8 chars (`signal.js:150`).

## No Analog Found

| File | Gap | Planner action |
|------|-----|----------------|
| `signal_io/ratecap.py` `asyncio.Lock` | No Node analog (Node's event loop made it unnecessary) and no Phase-56 Python analog (no concurrency primitives on disk yet) | This is the ONE genuinely new mechanism (RESEARCH Pattern 2 / "Key insight"). Use RESEARCH Pattern 2 verbatim; flag append-timing micro-delta for Phase-64 parity. |
| httpx mocking in tests | No httpx-mock fixture exists in Phase-56 `conftest.py` (only the DB `pool` fixture) | Add an httpx mock fixture (respx or monkeypatched `AsyncClient`) to `conftest.py`. respx is a NEW dev dep — slopcheck + pin before use. |

## Metadata

**Analog search scope:** `src/agents/alerter/src/` (Node port targets), `src/farm-agent/farm_agent/` + `src/farm-agent/tests/` (Phase-56 Python idioms)
**Files scanned:** signal.js, outbound-db.js, receive-loop.js (head + routing tail), config.js (maskNumber tail), capture.js (`(unassigned)` line); pool.py, migrations.py, tenant.py, conftest.py, test_persistence.py
**Key corrections folded in:** (1) `message.js` is the alert formatter (Phase 63), NOT routing — routing is in `receive-loop.js`; (2) transport is REST→httpx against `signal-cli-rest-api`, NOT a JSON-RPC socket; (3) DDL already shipped in `migrations.py` (Phase 56) — `outbound_repo.py` is write-only; (4) on-disk tests are flat `tests/test_*.py`, not `tests/unit/signal_io/`.
**Pattern extraction date:** 2026-06-15
