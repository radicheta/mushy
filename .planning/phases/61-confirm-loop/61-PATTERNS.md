# Phase 61: Confirm Loop - Pattern Map

**Mapped:** 2026-06-28
**Files analyzed:** 10 (6 new, 2 modified, 2 reference anchors)
**Analogs found:** 10 / 10

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `farm_agent/confirm/state_machine.py` | pure function / FSM | event-driven | `src/agents/alerter/src/confirm/state-machine.js` | exact (port) |
| `farm_agent/confirm/confirm_repo.py` | DAO / service | CRUD + conditional UPDATE | `farm_agent/capture/capture_repo.py` | role-match; also `src/agents/alerter/src/confirm/confirm-db.js` for SQL |
| `farm_agent/confirm/watchdog.py` | async task | event-driven / batch | `farm_agent/capture/retention.py` | exact (same loop shape) |
| `farm_agent/confirm/strain_ask_back.py` | utility | transform / request-response | `src/agents/alerter/src/confirm/strain-ask-back.js` + `farmos/strain-resolver.js` | exact (port) |
| `farm_agent/tenancy/tenant.py` | config | -- | existing `tenant.py` | self-analog (add two fields) |
| `farm_agent/boot.py` | entrypoint | -- | existing `boot.py` | self-analog (add one `create_task` call) |
| `farm_agent/signal_io/` (send + dispatch) | I/O | request-response | `farm_agent/signal_io/client.py` + `receive_loop.py` | reference only (no change) |
| `farm_agent/persistence/migrations.py` (schema reference) | migration | -- | existing migrations.py | reference only (no change) |
| `tests/confirm/test_*.py` (4 new files) | test | -- | `tests/test_capture_repo.py` | exact pattern match |
| `tests/conftest.py` (modified) | test fixture | -- | existing `FakeCaptureRepo` pattern | self-analog |

---

## Pattern Assignments

### `farm_agent/confirm/state_machine.py` (pure FSM, no I/O)

**Analog:** `src/agents/alerter/src/confirm/state-machine.js` (verbatim port)

**Node imports/constants** (state-machine.js lines 9-24):
```javascript
const CONFIRM_STATUS = Object.freeze({
  AWAITING_FARMER: 'awaiting_farmer',
  CONFIRMED: 'confirmed',
  DISCARDED: 'discarded',
  EXPIRED: 'expired',
  NEEDS_REVIEW: 'needs_review',
});

const CONFIRM_EVENTS = Object.freeze({
  FARMER_YES: 'farmer_yes',
  FARMER_NO: 'farmer_no',
  FARMER_EDIT: 'farmer_edit',
  NUDGE_DUE: 'nudge_due',
  EXPIRE_DUE: 'expire_due',
  SUPERSEDED: 'superseded',
});
```

Python equivalent (dataclasses + StrEnum, as sketched in RESEARCH.md):
```python
from dataclasses import dataclass
from enum import Enum

class ConfirmStatus(str, Enum):
    AWAITING_FARMER = "awaiting_farmer"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    EXPIRED = "expired"
    NEEDS_REVIEW = "needs_review"

class ConfirmEvent(str, Enum):
    FARMER_YES = "farmer_yes"
    FARMER_NO = "farmer_no"
    FARMER_EDIT = "farmer_edit"
    NUDGE_DUE = "nudge_due"
    EXPIRE_DUE = "expire_due"
    SUPERSEDED = "superseded"
```

**Ordering rule** (state-machine.js lines 52-65 — CRITICAL):
```javascript
// Dup-YES check BEFORE the inactive guard -- port this ordering exactly.
if (event.type === CONFIRM_EVENTS.FARMER_YES && status === CONFIRM_STATUS.CONFIRMED) {
  return { nextStatus: CONFIRM_STATUS.CONFIRMED, ..., side_effects: ['send_confirm_idempotent_ack'], reason: 'already_confirmed' };
}
if (status !== CONFIRM_STATUS.AWAITING_FARMER) {
  return _noop(state, 'inactive');
}
```

**Edit cap pattern** (state-machine.js lines 84-100):
```javascript
case CONFIRM_EVENTS.FARMER_EDIT: {
  const cap = (event.maxEditTurns != null) ? event.maxEditTurns : 3;
  if (editCount >= cap) {
    return { nextStatus: CONFIRM_STATUS.NEEDS_REVIEW, ..., side_effects: ['send_edit_cap_msg'], reason: 'edit_cap_exceeded' };
  }
  return { nextStatus: CONFIRM_STATUS.AWAITING_FARMER, nextEditTurnCount: editCount + 1, side_effects: ['run_edit_reextraction'], reason: 'edit_loop' };
}
```

**isTerminal** (state-machine.js lines 26-33):
```javascript
function isTerminal(status) {
  return status === CONFIRM_STATUS.CONFIRMED || status === CONFIRM_STATUS.DISCARDED ||
         status === CONFIRM_STATUS.EXPIRED    || status === CONFIRM_STATUS.NEEDS_REVIEW;
}
```

**Critical constraint:** `transition()` MUST be pure -- no DB, no I/O, no logging. Side effects are `list[str]`; callers dispatch them. This is what makes the table-parity test possible without any mocks.

---

### `farm_agent/confirm/confirm_repo.py` (never-throws DAO)

**Primary analog:** `src/farm-agent/farm_agent/capture/capture_repo.py` (never-throws pattern)
**SQL analog:** `src/agents/alerter/src/confirm/confirm-db.js` (verbatim SQL, $1 -> %s)

**Never-throws pattern** (capture_repo.py lines 110-116):
```python
try:
    async with pool.connection() as conn:
        await conn.execute(_INSERT_SQL, params)
    return {"ok": True}
except Exception as e:  # noqa: BLE001 -- fail-open per D-04
    logger.warning("[capture_repo] insert_capture failed: %s", e)
    return {"ok": False, "reason": str(e)}
```

**rowcount read** (capture_repo.py lines 129-135):
```python
async with pool.connection() as conn:
    result = await conn.execute(_EXPIRE_SQL, (str(age_seconds),))
    return result.rowcount or 0
```

**Interval predicate** (capture_repo.py lines 45-50, `_EXPIRE_SQL`):
```python
_EXPIRE_SQL = """
UPDATE signal_capture
   SET expired = true
 WHERE captured_at < NOW() - (%s || ' seconds')::interval
   AND expired IS DISTINCT FROM true
"""
```
For `confirm_repo.py` use `' minutes'` instead of `' seconds'`. Always pass the integer as `str(nudge_min)`.

**Transaction + event append pattern** (confirm-db.js lines 97-114):
```javascript
async function _runTransition(pool, sql, params, eventName, eventPayload) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const r = await client.query(sql, params);
    if (r.rowCount === 1) {
      await appendEvent(client, draftId, eventName, eventPayload || null);
    }
    await client.query('COMMIT');
    return { ok: true, rowCount: r.rowCount };
  } catch (e) {
    try { await client.query('ROLLBACK'); } catch (_) {}
    return { ok: false, reason: e.message };
  } finally { client.release(); }
}
```
Python equivalent:
```python
async with pool.connection() as conn:
    async with conn.transaction():
        result = await conn.execute(update_sql, params)
        if result.rowcount == 1:
            await _append_event(conn, draft_id, event_name, payload)
return {"ok": True, "rowcount": result.rowcount}
```

**confirmDraft SQL** (confirm-db.js lines 117-130, $1 -> %s):
```sql
UPDATE signal_draft
   SET status='confirmed',
       confirmed_at=NOW(),
       terminal_reason='farmer_yes',
       updated_at=NOW()
 WHERE id=%s AND status='awaiting_farmer'
 RETURNING id
```

**markNudgeSent SQL** (confirm-db.js lines 185-199, no transaction):
```sql
UPDATE signal_draft
   SET nudge_sent_at=NOW(),
       updated_at=NOW()
 WHERE id=%s AND nudge_sent_at IS NULL
 RETURNING id
```
Note: `markNudgeSent` does NOT use a transaction (pool-level query only; no event append inside a txn).

**appendEvent SQL** (confirm-db.js lines 60-75):
```sql
INSERT INTO signal_draft_event (draft_id, seq, event, payload, created_at)
VALUES (%s,
        (SELECT COALESCE(MAX(seq), 0) + 1 FROM signal_draft_event WHERE draft_id = %s),
        %s, %s::jsonb, NOW())
RETURNING seq
```

**findNudgeCandidates SQL** (confirm-db.js lines 292-306):
```sql
SELECT id, sender_e164, reply_target_kind, group_id, farmer_facing_preview, updated_at
  FROM signal_draft
 WHERE status='awaiting_farmer'
   AND nudge_sent_at IS NULL
   AND updated_at < NOW() - (%s || ' minutes')::interval
```

**findExpireCandidates SQL** (confirm-db.js lines 308-321):
```sql
SELECT id, sender_e164, reply_target_kind, group_id, farmer_facing_preview
  FROM signal_draft
 WHERE status='awaiting_farmer'
   AND updated_at < NOW() - (%s || ' minutes')::interval
```

---

### `farm_agent/confirm/watchdog.py` (async task, immediate-then-interval)

**Analog:** `src/farm-agent/farm_agent/capture/retention.py` (exact loop shape)

**Loop pattern** (retention.py lines 36-60):
```python
async def retention_loop(pool: AsyncConnectionPool, config: TenantConfig) -> None:
    while True:
        try:
            age_seconds = config.capture_retention_days * 86_400
            count = await mark_expired_older_than(pool, age_seconds)
            logger.info("[retention] flagged %d rows expired (>%dd)", count, config.capture_retention_days)
        except Exception as e:  # noqa: BLE001
            logger.warning("[retention] mark_expired_older_than failed: %s", e)
        await asyncio.sleep(86_400)
```

Key differences for `confirm_watchdog_loop`:
- Tick IMMEDIATELY on first entry (before the sleep), then loop -- the retention loop also runs immediately before its first sleep, so the pattern is identical
- Interval from `config.draft_watchdog_interval_ms / 1000` (not 86400)
- Wrap `tick_once` in an `asyncio.Lock` created once per loop invocation (belt-and-suspenders for tick overlap)
- `asyncio.CancelledError` must re-raise (same implicit behavior as retention_loop -- the while True exits on cancel)

**Lock pattern** (from RESEARCH.md, no existing codebase instance yet):
```python
_tick_lock = asyncio.Lock()  # one lock per watchdog task instance

async def confirm_watchdog_loop(pool, signal_client, config) -> None:
    lock = asyncio.Lock()
    # immediate tick on boot (restart-safe)
    try:
        await tick_once(pool, signal_client, config, lock)
    except Exception as e:
        log.warning("[watchdog] initial tick failed: %s", e)
    while True:
        try:
            await asyncio.sleep(config.draft_watchdog_interval_ms / 1000)
            await tick_once(pool, signal_client, config, lock)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("[watchdog] tick error: %s", e)
```

**Node timing** (watchdog.js lines 15-17):
```javascript
const timeoutMin = config.draftPendingTimeoutMin;
const nudgeMin = Math.round(config.draftPendingTimeoutMin * config.draftNudgeFraction);
// -> nudgeMin = round(30 * 0.8) = 24 min (default)
```

**minutesRemaining computation** (watchdog.js lines 22-24):
```javascript
const updatedAtMs = new Date(row.updated_at).getTime();
const elapsedMin = (clock.now() - updatedAtMs) / 60000;
const minutesRemaining = Math.max(0, timeoutMin - Math.round(elapsedMin));
```
Python: `max(0, round(config.draft_pending_timeout_min - (datetime.now(timezone.utc) - row['updated_at']).total_seconds() / 60))`

---

### `farm_agent/confirm/strain_ask_back.py` (template + reply parser + strain resolver)

**Analog:** `src/agents/alerter/src/confirm/strain-ask-back.js` + `src/agents/alerter/src/farmos/strain-resolver.js` (verbatim ports)

**renderStrainAskBack** (strain-ask-back.js lines 16-30):
```javascript
function renderStrainAskBack(seenCode, nearest) {
  const code = String(seenCode || '').toUpperCase().trim();
  if (nearest) {
    const n = String(nearest).toUpperCase().trim();
    return [
      `Saw strain '${code}' -- not in the active list.`,
      `New strain, or did you mean ${n}?`,
      `Reply YES to add '${code}' as a new strain, or reply ${n} (or "no, ${n}") to use the existing one.`,
    ].join('\n');
  }
  return [
    `Saw strain '${code}' -- not in the active list.`,
    `New strain? Reply YES to add it, or reply the correct strain code to remap.`,
  ].join('\n');
}
```
Style locks: ASCII-only, no em-dashes (use `--`), no emoji.

**CONFIRM_SET + CODE_RE** (strain-ask-back.js lines 33-39):
```javascript
const CONFIRM_SET = new Set(['yes', 'y', 'ok', 'si', 'si', 'confirm', 'new']);
// Note: 'si' appears twice in Node; Python set deduplicates automatically
const CODE_RE = /^[A-Za-z][A-Za-z0-9]{1,3}$/;
```
Python: `CONFIRM_SET = {'yes', 'y', 'ok', 'si', 'confirm', 'new'}` and `CODE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9]{1,3}$')`

**parseStrainAskBackReply reply paths** (strain-ask-back.js lines 47-75):
- `firstToken in CONFIRM_SET` -> `{'kind': 'confirm_new'}`
- `firstToken == 'no'` + rest matches CODE_RE -> `{'kind': 'correction', 'code': rest.upper()}`
- bare token matches CODE_RE -> `{'kind': 'correction', 'code': token.upper()}`
- anything else -> `{'kind': 'unknown'}`

**resolveStrain** (strain-resolver.js lines 71-87):
```javascript
function resolveStrain(code, curatedSet) {
  if (code === null || code === undefined || typeof code !== 'string') return { known: false, code: null };
  const norm = code.toUpperCase().trim();
  if (!norm) return { known: false, code: null };
  if (curatedSet && curatedSet.includes(norm)) return { known: true, code: norm };
  const result = { known: false, code: norm };
  if (curatedSet && curatedSet.length > 0) result.nearest = nearestKnown(norm, curatedSet);
  return result;
}
```

**nearestKnown Levenshtein DP** (strain-resolver.js lines 24-39 -- port verbatim, no external dep):
```javascript
function levenshtein(a, b) {
  const m = a.length, n = b.length;
  const dp = [];
  for (let i = 0; i <= m; i++) {
    dp[i] = [i];
    for (let j = 1; j <= n; j++) {
      dp[i][j] = i === 0 ? j : j === 0 ? i
        : a[i-1] === b[j-1] ? dp[i-1][j-1]
        : 1 + Math.min(dp[i-1][j-1], dp[i-1][j], dp[i][j-1]);
    }
  }
  return dp[m][n];
}
```
Tie-break: first element in curatedSet wins (loop order, take first minimum).
`nearest_known()` is DISPLAY ONLY -- never used for auto-remap.

---

### `farm_agent/tenancy/tenant.py` (MODIFIED -- add two fields)

**Analog:** existing `tenant.py` (self-analog, add to existing pattern)

**Existing `_parse_float_env` and `_parse_int_env` helpers** (tenant.py lines 98-128):
```python
def _parse_float_env(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"[config] {key}={raw!r} is not a valid float") from None

def _parse_int_env(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"[config] {key}={raw!r} is not a valid integer") from None
```

**TenantConfig dataclass location** (tenant.py lines 214-282): Add two new fields in the `# --- Draft confirm loop ---` section (lines 272-275):
```python
# --- Draft confirm loop ---
draft_pending_timeout_min: int
draft_watchdog_interval_ms: int
draft_nudge_fraction: float    # ADD: default 0.8 (DRAFT_NUDGE_FRACTION env)
max_edit_turns: int            # ADD: default 3    (MAX_EDIT_TURNS env)
```

**load() wiring location** (tenant.py lines 373-374), add alongside existing confirm-loop fields:
```python
# --- Draft confirm loop ---
draft_pending_timeout_min = _parse_int_env(env, "DRAFT_PENDING_TIMEOUT_MIN", 30)
draft_watchdog_interval_ms = _parse_int_env(env, "DRAFT_WATCHDOG_INTERVAL_MS", 60000)
draft_nudge_fraction = _parse_float_env(env, "DRAFT_NUDGE_FRACTION", 0.8)   # ADD
max_edit_turns = _parse_int_env(env, "MAX_EDIT_TURNS", 3)                    # ADD
```
Also add both fields to the `TenantConfig(...)` constructor call at the bottom.

---

### `farm_agent/boot.py` (MODIFIED -- add confirm watchdog task)

**Analog:** existing `boot.py` (self-analog; mirrors `retention_task` wiring exactly)

**Existing retention_task pattern** (boot.py lines 101-103):
```python
# Start daily retention task.
retention_task = asyncio.create_task(retention_loop(pool, config))
```

**Existing shutdown pattern** (boot.py lines 118-123):
```python
await receive_loop.stop()
retention_task.cancel()
try:
    await retention_task
except asyncio.CancelledError:
    pass
```

**New confirm_task wiring** -- add immediately after `retention_task` line:
```python
from farm_agent.confirm.watchdog import confirm_watchdog_loop
confirm_task = asyncio.create_task(confirm_watchdog_loop(pool, signal_client, config))
```
Add to shutdown block alongside `retention_task.cancel()`:
```python
confirm_task.cancel()
try:
    await confirm_task
except asyncio.CancelledError:
    pass
```

---

### `farm_agent/signal_io/` (send + dispatch -- reference, no change)

**SignalClient.send() signature** (signal_io/client.py lines 178-189):
```python
async def send(
    self,
    body: str,
    *,
    bypass_cap: bool = False,
    to: str | dict | None = None,
    intent: str | None = None,
    related_capture_id: str | None = None,
    related_draft_id: str | None = None,
    source_module: str = "signal_io",
    quote: dict | None = None,
) -> dict:
    # Returns {"ok": True, "timestamp": int} on success
    # Returns {"ok": False, "reason": "rate-cap"} when capped
    # Raises ValueError on invalid target, RuntimeError on HTTP error
```
For watchdog nudge/ack sends: pass `to=row['sender_e164']` for DM or `to={"groupId": row['group_id']}` for group (mirror `reply_target_kind` field logic). Pass `related_draft_id=draft_id`.

**ReceiveLoop dispatch seam** (receive_loop.py lines 10-13):
> "The dispatch seam is the Phase-58+ capture-pipeline entry point. This file does NOT implement capture/confirm -- it exposes only the gated dispatch(envelope) call."
Phase 61 adds the strain intercept + YES/NO/EDIT routing inside the pipeline's `handle` callable (not inside ReceiveLoop directly). The ReceiveLoop calls `dispatch(envelope)` which routes through the capture pipeline.

---

### `farm_agent/persistence/migrations.py` (schema reference -- no change)

**signal_draft columns written by confirm_repo** (migrations.py lines 157-216):

| Column | Type | Migration source |
|--------|------|-----------------|
| `id` | text PK | base CREATE TABLE (line 158) |
| `status` | text NOT NULL | base CREATE TABLE (line 164) |
| `sender_e164` | text NOT NULL | base CREATE TABLE (line 161) |
| `edit_turn_count` | integer DEFAULT 0 | ADD COLUMN (line 203) |
| `nudge_sent_at` | timestamptz NULL | ADD COLUMN (line 206) |
| `confirmed_at` | timestamptz NULL | ADD COLUMN (line 209) |
| `discarded_at` | timestamptz NULL | ADD COLUMN (line 198) |
| `expired_at` | timestamptz NULL | ADD COLUMN (line 212) |
| `terminal_reason` | text NULL | ADD COLUMN (line 215) |
| `needs_review_reason` | text | base CREATE TABLE (line 168) |
| `draft_json` | jsonb | base CREATE TABLE (line 165) |
| `per_field_confidence` | jsonb | base CREATE TABLE (line 166) |
| `farmer_facing_preview` | text | base CREATE TABLE (line 169) |
| `updated_at` | timestamptz | base CREATE TABLE (line 160) |
| `reply_target_kind` | text | base CREATE TABLE (line 171) |
| `group_id` | text | base CREATE TABLE (line 172) |

**signal_draft_event columns** (migrations.py lines 238-246):
```sql
CREATE TABLE IF NOT EXISTS signal_draft_event (
  draft_id   text NOT NULL,
  seq        integer NOT NULL,
  event      text NOT NULL,
  payload    jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (draft_id, seq)
)
```

---

### `tests/confirm/test_state_machine.py` (pure FSM parity, no DB)

**Analog:** `tests/test_capture_repo.py` (DB-independent section, lines 100-133)

**Pattern: local import inside test function** (test_capture_repo.py line 102):
```python
async def test_insert_capture_fail_open_never_raises():
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415
```

**Parametrize pattern** (from RESEARCH.md):
```python
@pytest.mark.parametrize("status,event_type,condition,expected_next,expected_effects,expected_reason", [
    ("confirmed",        "farmer_yes", {},                              "confirmed",        ["send_confirm_idempotent_ack"], "already_confirmed"),
    ("discarded",        "farmer_no",  {},                              "discarded",        ["noop"],                        "inactive"),
    ("awaiting_farmer",  "farmer_yes", {},                              "confirmed",        ["send_confirm_ack"],            "farmer_yes"),
    ("awaiting_farmer",  "farmer_no",  {},                              "discarded",        ["send_discard_ack"],            "farmer_no"),
    ("awaiting_farmer",  "farmer_edit",{"edit_turn_count": 0},          "awaiting_farmer",  ["run_edit_reextraction"],       "edit_loop"),
    ("awaiting_farmer",  "farmer_edit",{"edit_turn_count": 3},          "needs_review",     ["send_edit_cap_msg"],           "edit_cap_exceeded"),
    ("awaiting_farmer",  "nudge_due",  {"nudge_sent_at": None},         "awaiting_farmer",  ["send_nudge","mark_nudge_sent"],"nudge"),
    ("awaiting_farmer",  "nudge_due",  {"nudge_sent_at": "2026-01-01"}, "awaiting_farmer",  ["noop"],                        "already_nudged"),
    ("awaiting_farmer",  "expire_due", {},                              "expired",          ["send_expired_note"],           "timeout_expired"),
    ("awaiting_farmer",  "superseded", {},                              "expired",          ["noop"],                        "superseded_by_newer_draft"),
    ("awaiting_farmer",  None,         {},                              "awaiting_farmer",  ["noop"],                        "unknown_event"),
])
def test_transition_parity(status, event_type, condition, ...):
    ...
```
No DB, no mocks, no asyncio -- pure function.

---

### `tests/confirm/test_confirm_repo.py` (DB-gated)

**Analog:** `tests/test_capture_repo.py` (DB-gated section, lines 141-283)

**_requires_db marker** (test_capture_repo.py lines 32-43):
```python
def _db_reachable() -> bool:
    host = os.environ.get("TEST_TIMESCALE_HOST", "localhost")
    port_str = os.environ.get("TEST_TIMESCALE_PORT", "5434")
    try:
        with socket.create_connection((host, int(port_str)), timeout=2):
            return True
    except OSError:
        return False

_NO_DB_REASON = "no test DB reachable -- start postgres:14 on :5434"
_requires_db = pytest.mark.skipif(not _db_reachable(), reason=_NO_DB_REASON)
```

**DB-gated test structure** (test_capture_repo.py lines 141-165):
```python
@_requires_db
async def test_attachment_paths_roundtrip_as_text_array(pool):
    from farm_agent.capture.capture_repo import insert_capture  # noqa: PLC0415

    sentinel_id = str(uuid.uuid4())
    row = _capture_row(id=sentinel_id, ...)
    result = await insert_capture(pool, row)
    assert result == {"ok": True}, f"insert_capture failed: {result}"

    async with pool.connection() as conn:
        cur = await conn.execute("SELECT ... FROM signal_capture WHERE id = %s", (sentinel_id,))
        fetched = await cur.fetchone()
    assert fetched is not None
    assert fetched[0] == expected_value
```

**Concurrent nudge race test** (from RESEARCH.md SC-3 design):
```python
@_requires_db
@pytest.mark.asyncio
async def test_concurrent_nudge_race(pool):
    # Call mark_nudge_sent concurrently to test the SQL guard (bypass Lock)
    r1, r2 = await asyncio.gather(
        confirm_repo.mark_nudge_sent(pool, draft_id),
        confirm_repo.mark_nudge_sent(pool, draft_id),
    )
    rowcounts = sorted([r1["rowcount"], r2["rowcount"]])
    assert rowcounts == [0, 1]  # exactly one won the race
```

---

### `tests/conftest.py` (MODIFIED -- add FakeConfirmRepo + TEST_ENV fields)

**Analog:** existing `FakeCaptureRepo` pattern (conftest.py lines 155-180):
```python
class FakeCaptureRepo:
    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[dict] = []

    async def insert_capture(self, pool: object, row: dict) -> dict:
        self.calls.append(row)
        if self.should_raise:
            raise RuntimeError("FakeCaptureRepo: simulated insert failure")
        return {"ok": True}

@pytest.fixture
def fake_capture_repo():
    return FakeCaptureRepo()
```

**FakeConfirmRepo** should mirror this exactly, with methods matching the `confirm_repo` public API (`confirm_draft`, `discard_draft`, `expire_draft`, `mark_nudge_sent`, `find_awaiting_for_sender`, `find_nudge_candidates`, `find_expire_candidates`). Each records calls and returns `{"ok": True, "rowcount": 1}` by default.

**TEST_ENV additions** (conftest.py lines 36-52): Add two new keys to the `TEST_ENV` dict:
```python
TEST_ENV = {
    ...existing keys...
    "DRAFT_NUDGE_FRACTION": "0.8",    # ADD
    "MAX_EDIT_TURNS": "3",            # ADD
}
```

---

## Shared Patterns

### Never-throws discriminated result
**Source:** `src/farm-agent/farm_agent/capture/capture_repo.py` lines 110-116
**Apply to:** All `confirm_repo.py` public functions
```python
try:
    async with pool.connection() as conn:
        result = await conn.execute(sql, params)
    return {"ok": True, "rowcount": result.rowcount}
except Exception as e:  # noqa: BLE001
    logger.warning("[confirm_repo] %s failed: %s", op_name, e)
    return {"ok": False, "reason": str(e)}
```

### Interval arithmetic (string cast, NOT timedelta binding)
**Source:** `src/farm-agent/farm_agent/capture/capture_repo.py` line 47 (`_EXPIRE_SQL`)
**Apply to:** `find_nudge_candidates`, `find_expire_candidates` in `confirm_repo.py`
```python
# CORRECT: pass integer as str, use string cast in SQL
result = await conn.execute(
    "... AND updated_at < NOW() - (%s || ' minutes')::interval",
    (str(nudge_min),)
)
# WRONG: psycopg3 cannot bind timedelta to this expression
```

### PII masking on logs (phone numbers)
**Source:** `src/farm-agent/farm_agent/tenancy/tenant.py` lines 195-206 (`mask_number`)
**Apply to:** All logging in `confirm_repo.py`, `watchdog.py`, `strain_ask_back.py` that touches `sender_e164`
```python
from farm_agent.tenancy.tenant import mask_number
logger.info("[confirm_repo] sender=%s", mask_number(sender_e164))
```

### asyncio.CancelledError re-raise
**Source:** `src/farm-agent/farm_agent/boot.py` lines 118-123 (shutdown pattern)
**Apply to:** `confirm_watchdog_loop` inner exception handler
```python
except asyncio.CancelledError:
    raise   # always re-raise; do NOT swallow
except Exception as e:
    log.warning("[watchdog] tick error: %s", e)
```

### DB-gated skip
**Source:** `src/farm-agent/tests/test_capture_repo.py` lines 32-43
**Apply to:** `tests/confirm/test_confirm_repo.py` (dup-YES idempotency + nudge race)
```python
_requires_db = pytest.mark.skipif(not _db_reachable(), reason=_NO_DB_REASON)
```

---

## No Analog Found

All files have analogs. No entries.

---

## Metadata

**Analog search scope:** `src/farm-agent/farm_agent/`, `src/farm-agent/tests/`, `src/agents/alerter/src/confirm/`, `src/agents/alerter/src/farmos/`
**Files scanned:** 18
**Pattern extraction date:** 2026-06-28
