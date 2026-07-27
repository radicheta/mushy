# Phase 61: Confirm Loop - Research

**Researched:** 2026-06-28
**Domain:** Python asyncio FSM port -- confirm loop state machine, psycopg3 conditional UPDATEs, asyncio serialization, strain-confirm intercept
**Confidence:** HIGH (all findings from live source files in this repo)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Area 1: FSM, module structure & guards**
- FSM: a PURE `transition(status, event, ctx) -> {next_status, side_effects, guard}` function mirroring Node `confirm/state-machine.js` table verbatim.
- States (5): `awaiting_farmer`, `confirmed`, `discarded`, `expired`, `needs_review`.
- Module layout: new `farm_agent/confirm/` package: `state_machine.py`, `watchdog.py`, `confirm_repo.py`, `strain_ask_back.py`.
- DAO: never-throws `{ok, reason}` (mirrors `capture_repo.py`).
- Idempotency + race guards = pure SQL conditional UPDATEs with `WHERE ... RETURNING id`; rowcount 0 = race lost.

**Area 2: Watchdog wiring, timing & serialization**
- `asyncio.create_task(confirm_watchdog_loop(...))` at boot alongside `retention_loop`.
- `tick_once()` runs immediately on boot (restart-safe), then interval-sleep.
- Never-throws (swallow + WARNING + continue), mirroring `retention.py:retention_loop`.
- Nudge at `timeout_min * nudge_fraction`, expire at `timeout_min`. Thresholds from config/env.
- Wrap `tick_once` in `asyncio.Lock` (belt-and-suspenders) + SQL `RETURNING id` guard (correctness).

**Area 3: Strain-confirm source-of-truth, commit boundary & testing**
- Curated-14-set: SHI SH2 KOY MAI MALI KOS DT CAS CAZ WIN ALM MOR BP LIMA.
- Detection = EXACT-MATCH only; Levenshtein `nearest_known()` for display suggestion ONLY.
- Phase 61 stops at `confirmed` + commit-trigger/strain-approval MARKER. No farmOS HTTP call.
- Testing: (1) pure FSM table-parity test (no DB/network); (2) DB-gated dup-YES idempotency; (3) DB-gated concurrent-tick nudge race.

### Claude's Discretion
- Internal helper names, exact event/side-effect enum spelling, file splits within `confirm/`, and test parametrization -- provided locked transition table, SQL guards, and module/commit boundaries hold.

### Deferred Ideas (OUT OF SCOPE)
- Phase-54.2 live-farmOS-taxonomy strain source-of-truth -- Phase 62 / stranded-branch triage.
- Real farmOS commit + createMissingFungiType mint -- Phase 62 (Write Path).
- Reconciling stranded `fix/inoc-starting-seq-dispatch` strain-detection commits.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CNF-01 | YES/NO/EDIT/expiry confirm state machine as pure function with table-driven 100% parity tests; duplicate YES does not double-commit. | Node `state-machine.js` + `confirm-db.js` SQL guards fully read and documented below. |
| CNF-02 | Strain-confirm-before-mint, compact session-preview rendering, edit handler, nudge/expire watchdog; watchdog ticks serialized; no asyncio race producing duplicate nudges/expires. | `watchdog.js`, `strain-ask-back.js`, `strain-resolver.js`, `receive-loop.js` lines 314-411 fully read. |
</phase_requirements>

---

## Summary

Phase 61 ports the Node confirm loop (`src/agents/alerter/src/confirm/`) to Python. The work is a
faithful translation -- there is no new design. Every interesting decision already exists in Node
and is verified by reading the live source files. The crux is: (1) the pure FSM function must match
the Node transition table case-for-case so the parity test can assert Python == Node on every
(status, event, condition) triple; (2) the three SQL conditional-UPDATE guards are the correctness
mechanism for dup-YES, nudge-race, and double-expire -- the Python port must reproduce the exact
WHERE predicates and read rowcount from psycopg3's `execute()` return; (3) the asyncio.Lock around
`tick_once` is belt-and-suspenders only -- the SQL guard is the race correctness mechanism; and (4)
the strain-confirm intercept route has three distinct reply paths (confirm_new / correction /
unknown) each with exact behavior specified in Node receive-loop.js.

Two TenantConfig fields are missing and must be added as part of this phase:
`draft_nudge_fraction` (Node default 0.8 -- the CONTEXT.md description of "~50%" was
approximate) and `max_edit_turns` (Node default 3). Both already exist in Node `config.js` and
both are consumed by watchdog and the FSM respectively.

**Primary recommendation:** Port the Node files 1:1 with minimal abstraction. The Python files are
thin wrappers over the verified Node logic. Do not over-engineer -- each file maps directly to its
Node equivalent.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| FSM pure function (transition) | Python process -- farm_agent | -- | Pure function, no I/O; called by ReceiveLoop and watchdog |
| Inbound YES/NO/EDIT routing | Python process -- ReceiveLoop | -- | ReceiveLoop owns inbound parse; calls confirm_repo + signal_client for acks |
| Nudge / expire scheduling | Python process -- watchdog task | DB (SQL guards) | Watchdog polls DB; SQL WHERE guard is the correctness mechanism |
| Strain-ask-back intercept | Python process -- ReceiveLoop | -- | Intercept happens in ReceiveLoop before standard confirmParser path |
| Idempotency guards | DB (psycopg3 conditional UPDATE) | asyncio.Lock | SQL WHERE is correctness; Lock prevents overlap of slow tick with next interval |
| Commit-trigger marker | Python process -- confirm_repo | DB signal_draft | Phase 61 emits marker on `confirmed`; Phase 62 reads it |
| Audit log (signal_draft_event) | DB | -- | Append-only; existing schema from Phase 56 migrations |

---

## Node Source of Truth: Verbatim Transition Table

[VERIFIED: live source at `src/agents/alerter/src/confirm/state-machine.js`]

The Node FSM is a pure `transition(state, event)` function. `state` carries `{status, edit_turn_count, nudge_sent_at}`. `event` carries `{type, maxEditTurns?}`.

### Complete Transition Table (golden reference for parity test)

| Current Status | Event Type | Condition | Next Status | Side Effects | Reason |
|---------------|-----------|-----------|-------------|--------------|--------|
| `confirmed` | `farmer_yes` | (any -- dup YES) | `confirmed` | `['send_confirm_idempotent_ack']` | `already_confirmed` |
| (any non-`awaiting_farmer`) | (any) | status != `awaiting_farmer` AND not dup-YES case | same | `['noop']` | `inactive` |
| `awaiting_farmer` | `farmer_yes` | -- | `confirmed` | `['send_confirm_ack']` | `farmer_yes` |
| `awaiting_farmer` | `farmer_no` | -- | `discarded` | `['send_discard_ack']` | `farmer_no` |
| `awaiting_farmer` | `farmer_edit` | `edit_turn_count < cap` | `awaiting_farmer` | `['run_edit_reextraction']` | `edit_loop` |
| `awaiting_farmer` | `farmer_edit` | `edit_turn_count >= cap` | `needs_review` | `['send_edit_cap_msg']` | `edit_cap_exceeded` |
| `awaiting_farmer` | `nudge_due` | `nudge_sent_at IS NULL` | `awaiting_farmer` | `['send_nudge', 'mark_nudge_sent']` | `nudge` |
| `awaiting_farmer` | `nudge_due` | `nudge_sent_at IS NOT NULL` | `awaiting_farmer` | `['noop']` | `already_nudged` |
| `awaiting_farmer` | `expire_due` | -- | `expired` | `['send_expired_note']` | `timeout_expired` |
| `awaiting_farmer` | `superseded` | -- | `expired` | `['noop']` | `superseded_by_newer_draft` |
| (any) | None / missing type | -- | same | `['noop']` | `unknown_event` |

**Cap default:** `cap = event.maxEditTurns if event.maxEditTurns is not None else 3`

**Return shape:** `{next_status, next_edit_turn_count, side_effects: list[str], reason: str}`

**isTerminal:** status in {`confirmed`, `discarded`, `expired`, `needs_review`}

**Key ordering rule:** The dup-YES check (`confirmed + farmer_yes`) runs BEFORE the inactive guard
(`status != awaiting_farmer`). This is explicit in the Node code (lines 53-60 before line 63).
The Python port must preserve this ordering or the parity test will catch the difference.

---

## Node Source of Truth: SQL Guards (verbatim)

[VERIFIED: live source at `src/agents/alerter/src/confirm/confirm-db.js`]

### Guard 1: confirmDraft (dup-YES idempotency)
```sql
UPDATE signal_draft
   SET status='confirmed',
       confirmed_at=NOW(),
       terminal_reason='farmer_yes',
       updated_at=NOW()
 WHERE id=$1 AND status='awaiting_farmer'
 RETURNING id
```
- `rowcount == 1`: transition happened; send ack + emit commit-trigger marker.
- `rowcount == 0`: already confirmed (race lost); send idempotent ack, NO second trigger.
- Also wraps in a BEGIN/COMMIT transaction that appends `signal_draft_event` row if rowcount==1.

### Guard 2: markNudgeSent (nudge race)
```sql
UPDATE signal_draft
   SET nudge_sent_at=NOW(),
       updated_at=NOW()
 WHERE id=$1 AND nudge_sent_at IS NULL
 RETURNING id
```
- `rowcount == 0`: another tick already set `nudge_sent_at`; return without sending nudge.
- NOTE: `markNudgeSent` does NOT use a transaction or append a draft event (it's a pool-level query, not `_runTransition`). The event is appended separately via `appendEventViaPool` AFTER the send.

### Guard 3: expireDraft (double-expire / needs_review)
```sql
-- For timeout_expired and superseded_by_newer_draft:
UPDATE signal_draft
   SET status='expired',
       expired_at=NOW(),
       terminal_reason=$2,
       updated_at=NOW()
 WHERE id=$1 AND status='awaiting_farmer'
 RETURNING id

-- For edit_cap_exceeded (-> needs_review, no expired_at):
UPDATE signal_draft
   SET status='needs_review',
       terminal_reason=$2,
       updated_at=NOW()
 WHERE id=$1 AND status='awaiting_farmer'
 RETURNING id
```
- `rowcount == 0`: already expired/transitioned; return early.

### Guard 4: discardDraft
```sql
UPDATE signal_draft
   SET status='discarded',
       discarded_at=NOW(),
       terminal_reason='farmer_no',
       updated_at=NOW()
 WHERE id=$1 AND status='awaiting_farmer'
 RETURNING id
```

### Additional DB helpers needed
- `bumpEditTurn(pool, draft_id)` -- `UPDATE ... SET edit_turn_count = edit_turn_count + 1 WHERE id=$1 AND status='awaiting_farmer' RETURNING edit_turn_count`
- `updateDraftAfterEdit(pool, draft_id, fields)` -- updates `draft_json`, `per_field_confidence`, `farmer_facing_preview`
- `findAwaitingForSender(pool, sender_e164)` -- finds most recent `awaiting_farmer` or recent `commit_failed` (Phase 61 only needs `awaiting_farmer`; include `commit_failed` for completeness)
- `findNudgeCandidates(pool, nudge_min)` -- select from `signal_draft` WHERE `status='awaiting_farmer' AND nudge_sent_at IS NULL AND updated_at < NOW() - ($1 || ' minutes')::interval`
- `findExpireCandidates(pool, timeout_min)` -- same WHERE but without `nudge_sent_at IS NULL`
- `appendEvent(conn, draft_id, event, payload)` -- INSERT into `signal_draft_event` with MAX(seq)+1

### Interval predicate (verbatim from Node + capture_repo.py precedent)
```sql
updated_at < NOW() - ($1 || ' minutes')::interval
```
Pass the integer as a STRING (str(nudge_min)). This pattern is already established in
`capture_repo.py`'s `_EXPIRE_SQL` which uses `(%s || ' seconds')::interval`. [VERIFIED: local source]

---

## psycopg3 Framework Quick Reference

[VERIFIED: local source `src/farm-agent/farm_agent/capture/capture_repo.py`,
`src/farm-agent/farm_agent/persistence/pool.py`]

### Running UPDATE...RETURNING and reading rowcount

The pool exposes `AsyncConnectionPool` (psycopg3 / psycopg_pool).

**Pattern A -- pool.connection() context manager (for simple non-transactional queries):**
```python
async with pool.connection() as conn:
    result = await conn.execute(sql, params)
    # result is a psycopg3 cursor
    rowcount = result.rowcount   # int: rows affected; -1 if not applicable
    row = await result.fetchone()  # None if no RETURNING rows
```

**Pattern B -- transaction with explicit connection (mirrors Node _runTransition):**
```python
async with pool.connection() as conn:
    async with conn.transaction():
        result = await conn.execute(sql, params)
        if result.rowcount == 1:
            await conn.execute(event_sql, event_params)
        # transaction commits on __aexit__
```

**rowcount semantics in psycopg3:** `cursor.rowcount` is set correctly after `execute()` for
UPDATE/INSERT/DELETE. For `UPDATE...RETURNING id`, if no row matched the WHERE predicate,
`rowcount == 0`. If one row matched, `rowcount == 1`. This is the correct gate.

**PITFALL -- `conn.execute()` vs `conn.cursor().execute()`:** The shorthand
`await conn.execute(sql, params)` returns the cursor directly in psycopg3. You do NOT need to
call `cursor()` first. This matches the pattern in `capture_repo.py`.

**Parameter placeholder:** psycopg3 uses `%s` (not `$1`). The Node SQL uses `$1` positional style;
Python must translate to `%s` style. [VERIFIED: local source uses `%s` throughout]

**Interval predicate -- pass as str:**
```python
result = await conn.execute(
    "... AND updated_at < NOW() - (%s || ' minutes')::interval",
    (str(nudge_min),)   # pass integer as string
)
```
This matches the exact pattern in `capture_repo.py`'s `_EXPIRE_SQL`.

### asyncio.Lock pattern for watchdog serialization
```python
import asyncio

_tick_lock = asyncio.Lock()

async def tick_once(pool, signal_client, config):
    async with _tick_lock:
        # ... process nudge and expire candidates
```

For the watchdog loop, the lock prevents a slow tick from overlapping with the next scheduled
tick. The lock is instantiated once per watchdog task, not globally.

### Testing concurrent ticks with asyncio.gather

```python
# Prove the nudge-race guard: two concurrent tick_once calls on the same row
results = await asyncio.gather(
    tick_once(pool, signal_client, config),
    tick_once(pool, signal_client, config),
    return_exceptions=True,
)
# Assert: signal sends happened exactly once
assert len(sent_nudges) == 1
```

For this to be a REAL race test (not serialized by the Lock), the test must call the inner SQL
function directly (bypassing the Lock) or must spawn two event loop tasks against separate lock
instances. See Pitfall section for the race-test determinism detail.

---

## Node Source of Truth: Watchdog Behavior

[VERIFIED: live source at `src/agents/alerter/src/confirm/watchdog.js`]

### Timing
```javascript
const timeoutMin = config.draftPendingTimeoutMin;    // default: 30 min
const nudgeMin = Math.round(
    config.draftPendingTimeoutMin * config.draftNudgeFraction  // default: 0.8
);
// -> nudgeMin = round(30 * 0.8) = 24 min (NOT ~50%)
```

**IMPORTANT:** The CONTEXT.md says "~50%" for nudge timing. The actual Node default is
`draftNudgeFraction=0.8`, so nudge fires at 80% of timeout (e.g. 24 min when timeout=30).
The fraction is configurable via `DRAFT_NUDGE_FRACTION` env. Port this faithfully: add
`draft_nudge_fraction: float` to `TenantConfig` with default `0.8`.

### Loop shape
```
start():
  await tickOnce()          # immediate on boot (restart-safe)
  setInterval(tickOnce, intervalMs)  # then every intervalMs (default 60000ms)
```

Python equivalent (`retention_loop` model):
```python
async def confirm_watchdog_loop(pool, signal_client, config):
    await tick_once(pool, signal_client, config)   # immediate
    while True:
        await asyncio.sleep(config.draft_watchdog_interval_ms / 1000)
        await tick_once(pool, signal_client, config)
```

### Per-row processing order
1. Find nudge candidates (`WHERE status='awaiting_farmer' AND nudge_sent_at IS NULL AND updated_at < NOW() - nudge_min`)
2. For each: `markNudgeSent` (SQL guard) -- if rowcount==0, skip; otherwise send nudge + append event.
3. Find expire candidates (`WHERE status='awaiting_farmer' AND updated_at < NOW() - timeout_min`)
4. For each: `expireDraft('timeout_expired')` (SQL guard) -- if rowcount==0, skip; otherwise send expired note.

**minutesRemaining** is computed from `updated_at` of the row, not the current tick time.

---

## Node Source of Truth: Strain Ask-Back

[VERIFIED: live source at `src/agents/alerter/src/confirm/strain-ask-back.js`]

### renderStrainAskBack(seen_code, nearest)
- `nearest` not None: "Saw strain '{CODE}' -- not in the active list.\nNew strain, or did you mean {NEAREST}?\nReply YES to add '{CODE}' as a new strain, or reply {NEAREST} (or \"no, {NEAREST}\") to use the existing one."
- `nearest` is None: "Saw strain '{CODE}' -- not in the active list.\nNew strain? Reply YES to add it, or reply the correct strain code to remap."
- ASCII-only, no em-dashes, no emoji (repo style lock).

### parseStrainAskBackReply(text) -> kind
- `CONFIRM_SET = {'yes', 'y', 'ok', 'si', 'confirm', 'new'}` (first token, lowercased)
  -> `{'kind': 'confirm_new'}`
- `firstToken == 'no'` + rest matches `CODE_RE = /^[A-Za-z][A-Za-z0-9]{1,3}$/`
  -> `{'kind': 'correction', 'code': rest.upper()}`
- bare token matching `CODE_RE`
  -> `{'kind': 'correction', 'code': token.upper()}`
- anything else -> `{'kind': 'unknown'}`

**CODE_RE in Python:** `r'^[A-Za-z][A-Za-z0-9]{1,3}$'`

---

## Node Source of Truth: Strain Resolver

[VERIFIED: live source at `src/agents/alerter/src/farmos/strain-resolver.js`]

### resolveStrain(code, curated_set) -> {known, code, nearest?}
- Normalize: `code.upper().strip()`
- `norm in curated_set` -> `{'known': True, 'code': norm}`
- otherwise -> `{'known': False, 'code': norm, 'nearest': nearest_known(norm, curated_set)}`
- null/non-string input -> `{'known': False, 'code': None}`

### nearestKnown(code, curated_set)
- Levenshtein edit distance; tie-break by list order (first element wins).
- Returns string or None. Display-only -- NEVER used for auto-remap.

**Python Levenshtein:** No external dependency needed; port the Node DP function verbatim.

---

## Node Source of Truth: Strain Intercept in ReceiveLoop

[VERIFIED: live source at `src/agents/alerter/src/receive-loop.js` lines 314-411]

When `draftRow.needs_review_reason == 'strain_unknown_pending_confirm'`:

1. `parseStrainAskBackReply(text)` routes to one of three paths:
   - `confirm_new`: `updateDraftStatus(..., needs_review_reason='strain_confirm_approved')` then `confirmDraft()`; send ack (dup-YES guard applies).
   - `correction` with `resolveStrain(code, curated_set).known == True`: rewrite `draft_json.species_code` inline (`Object.assign({}, draftRow.draft_json, {species_code: resolved.code})`), then `confirmDraft()` WITHOUT approval marker; send ack.
   - `correction` with `resolved.known == False`: re-ask (`send_strain_ask_back` with `seenCode=draft_json.species_code`, `nearest=resolved.nearest`).
   - `unknown` (bare `no`, unrecognized): fall through to NOOP -- does NOT confirm, does NOT re-ask. The receive loop returns to the capture pipeline.

2. Outside the strain intercept block, the standard `confirmParser.parseReply(text)` handles YES/NO/EDIT.

**Python ReceiveLoop wiring for Phase 61:** Phase 61 adds the strain intercept + yes/no handling to the existing `ReceiveLoop`. The edit handler (`run_edit_reextraction`) is a side effect the FSM emits; the actual re-extraction is Phase 60 work -- Phase 61 should stub it (noop + log) or call through to Phase 60's extractor if it exists.

---

## signal_draft Schema: Columns Touched by confirm_repo

[VERIFIED: live source at `src/farm-agent/farm_agent/persistence/migrations.py`]

The schema already exists (Phase 56 migrations). Columns relevant to Phase 61:

| Column | Type | Purpose |
|--------|------|---------|
| `id` | text PK | hex SHA-256 draft identity |
| `status` | text | `awaiting_farmer` / `confirmed` / `discarded` / `expired` / `needs_review` |
| `sender_e164` | text | farmer phone; used by `findAwaitingForSender` |
| `edit_turn_count` | integer DEFAULT 0 | bumped by `bumpEditTurn` |
| `nudge_sent_at` | timestamptz NULL | set by `markNudgeSent`; NULL = not yet nudged |
| `confirmed_at` | timestamptz NULL | set by `confirmDraft` |
| `discarded_at` | timestamptz NULL | set by `discardDraft` |
| `expired_at` | timestamptz NULL | set by `expireDraft` (NOT set for needs_review path) |
| `terminal_reason` | text NULL | e.g. `farmer_yes`, `farmer_no`, `timeout_expired`, `edit_cap_exceeded`, `superseded_by_newer_draft` |
| `needs_review_reason` | text | `strain_unknown_pending_confirm` / `strain_confirm_approved` |
| `draft_json` | jsonb | holds `species_code` rewritten by correction path |
| `per_field_confidence` | jsonb | updated by `updateDraftAfterEdit` |
| `farmer_facing_preview` | text | updated by `updateDraftAfterEdit` |
| `updated_at` | timestamptz | used by watchdog interval predicate |
| `reply_target_kind` | text | `dm` or `group`; returned by watchdog candidate queries |
| `group_id` | text | group routing; returned by watchdog candidate queries |

`signal_draft_event` columns: `(draft_id text, seq integer, event text, payload jsonb, created_at timestamptz)`, PK `(draft_id, seq)`.

---

## File-by-File Implementation Map

### `farm_agent/confirm/__init__.py`
Empty package marker. No exports (callers import submodules directly).

### `farm_agent/confirm/state_machine.py`
**Port of:** `src/agents/alerter/src/confirm/state-machine.js`

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

@dataclass
class Event:
    type: ConfirmEvent
    max_edit_turns: int | None = None

@dataclass
class State:
    status: str
    edit_turn_count: int = 0
    nudge_sent_at: object = None  # datetime | None

@dataclass
class TransitionResult:
    next_status: str
    next_edit_turn_count: int
    side_effects: list[str]
    reason: str

def is_terminal(status: str) -> bool: ...
def transition(state: State, event: Event) -> TransitionResult: ...
```

**Critical:** `transition()` is PURE -- no logging, no DB, no I/O. Side effects are strings; callers dispatch them.

### `farm_agent/confirm/confirm_repo.py`
**Port of:** `src/agents/alerter/src/confirm/confirm-db.js`

Never-throws DAO following `capture_repo.py` pattern. All public functions return `{ok: bool, ...}` or `int`, never raise.

Functions to implement:
- `confirm_draft(pool, draft_id) -> dict` -- `{ok, rowcount}`
- `discard_draft(pool, draft_id) -> dict` -- `{ok, rowcount}`
- `expire_draft(pool, draft_id, reason) -> dict` -- `{ok, rowcount}`; three SQL variants by reason
- `mark_nudge_sent(pool, draft_id) -> dict` -- `{ok, rowcount}`; no transaction
- `bump_edit_turn(pool, draft_id) -> dict` -- `{ok, edit_turn_count, rowcount}`
- `update_draft_after_edit(pool, draft_id, fields) -> dict` -- `{ok, rowcount}`
- `find_awaiting_for_sender(pool, sender_e164) -> dict | None`
- `find_nudge_candidates(pool, nudge_min) -> list[dict]`
- `find_expire_candidates(pool, timeout_min) -> list[dict]`
- `append_event(conn, draft_id, event, payload) -> dict` -- `{ok, seq}`; used inside transactions
- `append_event_via_pool(pool, draft_id, event, payload) -> dict` -- pool-level overload

**Transaction pattern** for `confirm_draft`, `discard_draft`, `expire_draft`:
```python
async with pool.connection() as conn:
    async with conn.transaction():
        result = await conn.execute(update_sql, params)
        if result.rowcount == 1:
            await append_event(conn, draft_id, event_name, payload)
return {"ok": True, "rowcount": result.rowcount}
```

### `farm_agent/confirm/watchdog.py`
**Port of:** `src/agents/alerter/src/confirm/watchdog.js`

```python
import asyncio
import logging

async def tick_once(pool, signal_client, config, lock: asyncio.Lock | None = None): ...

async def confirm_watchdog_loop(pool, signal_client, config) -> None:
    lock = asyncio.Lock()
    # immediate tick on boot
    try:
        await tick_once(pool, signal_client, config, lock)
    except Exception as e:
        log.warning("[watchdog] initial tick failed: %s", e)
    # then interval loop
    while True:
        try:
            await asyncio.sleep(config.draft_watchdog_interval_ms / 1000)
            await tick_once(pool, signal_client, config, lock)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("[watchdog] tick error: %s", e)
```

**minutesRemaining** computation: `max(0, round(config.draft_pending_timeout_min - elapsed_min))` where `elapsed_min = (now - row['updated_at']).total_seconds() / 60`.

**CancelledError must re-raise** (as in retention_loop implicitly -- the while True exits on cancel from boot.py `retention_task.cancel()`).

### `farm_agent/confirm/strain_ask_back.py`
**Port of:** `src/agents/alerter/src/confirm/strain-ask-back.js`
**Port of:** `src/agents/alerter/src/farmos/strain-resolver.js`

Functions:
- `render_strain_ask_back(seen_code: str, nearest: str | None) -> str`
- `parse_strain_ask_back_reply(text) -> dict` -- `{kind: 'confirm_new'|'correction'|'unknown', code?: str}`
- `resolve_strain(code, curated_set) -> dict` -- `{known: bool, code: str|None, nearest?: str}`
- `nearest_known(code: str, curated_set: list[str]) -> str | None`

**CONFIRM_SET** (Python): `{'yes', 'y', 'ok', 'si', 'confirm', 'new'}` -- note Node has `'si'` twice; Python set deduplicates.

### Boot wiring (`farm_agent/boot.py`)
Add alongside `retention_task`:
```python
from farm_agent.confirm.watchdog import confirm_watchdog_loop
confirm_task = asyncio.create_task(confirm_watchdog_loop(pool, signal_client, config))
```
Shutdown:
```python
confirm_task.cancel()
try:
    await confirm_task
except asyncio.CancelledError:
    pass
```

### TenantConfig additions (`farm_agent/tenancy/tenant.py`)
Add two new fields (currently missing):
```python
draft_nudge_fraction: float    # default 0.8  (DRAFT_NUDGE_FRACTION env)
max_edit_turns: int            # default 3    (MAX_EDIT_TURNS env)
```
Parse with `_parse_float_env(env, "DRAFT_NUDGE_FRACTION", 0.8)` and
`_parse_int_env(env, "MAX_EDIT_TURNS", 3)`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Race-safe nudge/expire deduplication | app-level in-memory seen-set | SQL `WHERE nudge_sent_at IS NULL RETURNING id` | survives restart; works across processes; already verified in Node |
| Dup-YES protection | app-level boolean flag | SQL `WHERE status='awaiting_farmer' RETURNING id` | same row can be re-confirmed after restart without flag |
| Event sequence numbers | UUID or timestamp | `SELECT COALESCE(MAX(seq),0)+1` subquery in INSERT | ensures monotonic per-draft seq without a sequence object |
| Levenshtein distance | external library | port Node DP function verbatim | 30 lines; no dependency; well-tested in production |
| Interval arithmetic | Python timedelta binding | `(%s || ' minutes')::interval` string cast | psycopg3 cannot bind timedelta to interval-arithmetic expression; established pattern in codebase |

---

## Common Pitfalls

### Pitfall 1: rowcount semantics -- -1 vs 0
**What goes wrong:** After `conn.execute("UPDATE ... RETURNING id", params)`, checking `result.rowcount == 0` when psycopg3 returns `-1` for statements that do not provide a count.
**Why it happens:** psycopg3 `rowcount` is `-1` when the backend does not report a count (e.g. for some DDL). For `UPDATE...RETURNING`, the backend DOES report a count. But `execute()` returns a cursor where `rowcount` reflects rows matched by WHERE, not rows returned by RETURNING. For `UPDATE...WHERE id=$1 AND status='awaiting_farmer' RETURNING id`, if the WHERE fails, rowcount=0; if it succeeds, rowcount=1.
**How to avoid:** Test against the real DB with the exact SQL to confirm rowcount behavior. The existing `test_capture_repo.py` DB-gated tests provide the pattern.
**Warning signs:** `rowcount == -1` in a test is a strong signal the wrong SQL variant or method was used.

### Pitfall 2: asyncio.Lock does NOT prevent the SQL race -- it prevents tick overlap
**What goes wrong:** Wrapping `tick_once` in `asyncio.Lock` and assuming this prevents duplicate nudges. If two processes run (e.g. during a deploy) or if the Lock is bypassed in a test, the SQL guard is the only protection.
**Why it happens:** The Lock is intra-process only; the SQL WHERE guard is cross-process and cross-restart.
**How to avoid:** The race SC (SC-3) must test the SQL guard directly -- call the underlying DAO function concurrently (bypassing the Lock) via `asyncio.gather`. The Lock is belt-and-suspenders for the slow-tick overlap case only.
**Warning signs:** SC-3 test uses `tick_once` with the Lock in place -- it will serialize the calls and prove nothing. The test must call `confirm_repo.mark_nudge_sent` concurrently.

### Pitfall 3: dup-YES race test is not deterministic without real Postgres
**What goes wrong:** Writing the dup-YES race test against a fake/in-memory repo: the test passes regardless because there is no actual concurrent transaction isolation.
**Why it happens:** Race correctness requires real Postgres transaction semantics (the WHERE predicate runs atomically within the row lock).
**How to avoid:** SC-2 and SC-3 tests must be DB-gated (skip without :5434), matching the existing `_requires_db` pattern. The `conftest.py` `pool` fixture provides the session-scoped real pool.

### Pitfall 4: no-silent-failure after YES
**What goes wrong:** `confirmDraft` succeeds (rowcount==1) but the `send_confirm_ack` call fails (signal-cli timeout). The farmer sees no response and doesn't know the YES registered.
**Why it happens:** Signal sends can fail transiently. If the ack send is fire-and-forget with no fallback, the farmer is left hanging.
**How to avoid:** Per `[[feedback_no_silent_failure_after_farmer_confirm]]`, every terminal post-YES state must ack the farmer. The ack send must be tried; failure logged at WARNING; a degraded response ("your answer was recorded") is better than silence. For f1=Santi the rule is relaxed but acks should still fire.

### Pitfall 5: restart-safe nudge -- NUDGE_DUE + nudge_sent_at NOT NULL is a noop, not an error
**What goes wrong:** Treating a row with `nudge_sent_at IS NOT NULL` as an error or re-nudging it on restart.
**Why it happens:** On restart, the watchdog ticks immediately. Any row that was already nudged before the restart will have `nudge_sent_at` set. The SQL guard (`WHERE nudge_sent_at IS NULL`) catches this. The FSM also handles it (`NUDGE_DUE + nudge_sent_at NOT NULL -> noop`).
**How to avoid:** Confirm the FSM noop path is tested (table-parity test case: `awaiting_farmer + nudge_due + nudge_sent_at=datetime -> side_effects=['noop']`).

### Pitfall 6: side_effects as data, not I/O
**What goes wrong:** The `transition()` function directly calls `signal_client.send()` instead of returning effect names.
**Why it happens:** It's tempting to co-locate the effect trigger with the decision.
**How to avoid:** `transition()` MUST be pure (no I/O, no logging). It returns `side_effects: list[str]`. The caller (`ReceiveLoop` or `watchdog`) dispatches each side effect. This is what makes the table-parity test possible (pure function, no mocks needed).

### Pitfall 7: curated-set exact-match vs fuzzy -- no auto-remap
**What goes wrong:** Using `nearest_known()` to auto-remap an unknown code to the nearest curated code.
**Why it happens:** `nearest_known()` is available; it's tempting to use it for auto-resolution.
**How to avoid:** `nearest_known()` is for DISPLAY ONLY in the ask-back message. Unknown codes ALWAYS go through the farmer ask-back loop. The POY-as-KOY silent-misattribution bug was caused by exactly this class of silent fuzzy remapping -- `[[project_backfill_extraction_fidelity_38pct_silent_misattribution]]`.

### Pitfall 8: `%s` vs `$1` in SQL
**What goes wrong:** Copying Node SQL verbatim with `$1, $2` placeholders into Python psycopg3.
**Why it happens:** Node pg uses `$1` positional parameters; psycopg3 uses `%s`.
**How to avoid:** All Python SQL must use `%s` placeholders. Check every SQL string in the port.

### Pitfall 9: draft_nudge_fraction missing from TenantConfig
**What goes wrong:** `confirm_watchdog_loop` tries to access `config.draft_nudge_fraction` and gets `AttributeError`.
**Why it happens:** `draft_nudge_fraction` (and `max_edit_turns`) do not currently exist in `TenantConfig` (verified by grep). They must be added in this phase.
**How to avoid:** Wave 0 task: add `draft_nudge_fraction: float` and `max_edit_turns: int` to `TenantConfig` with `_parse_float_env` / `_parse_int_env` loaders. Add to `TEST_ENV` in `conftest.py`.

### Pitfall 10: signal_draft_event seq race under concurrent inserts
**What goes wrong:** Two concurrent `appendEvent` calls for the same `draft_id` compute the same `COALESCE(MAX(seq),0)+1` and collide on the composite PK.
**Why it happens:** Without a transaction wrapping the select-max + insert, two concurrent connections can both read the same max(seq).
**How to avoid:** `appendEvent` (the transactional variant) is always called INSIDE an open transaction that already holds a row lock on the `signal_draft` row (because the enclosing UPDATE will have locked it). `appendEventViaPool` (pool-level, no outer transaction) is fine for single events (watchdog nudge_sent event). The composite PK ensures a collision raises and can be caught.

---

## Architecture Patterns

### System Architecture Diagram

```
Inbound Signal message (farmer YES/NO/EDIT/strain reply)
        |
        v
ReceiveLoop.dispatch()
        |
        +-- strain_intercept? (needs_review_reason == 'strain_unknown_pending_confirm')
        |       |
        |       +-- parse_strain_ask_back_reply()
        |       |       |
        |       |       +-- confirm_new -> updateDraftStatus(strain_confirm_approved)
        |       |       |                  -> confirm_repo.confirm_draft() [SQL guard]
        |       |       |                  -> signal_client.send(ack)
        |       |       |
        |       |       +-- correction+known -> rewrite draft_json.species_code
        |       |       |                       -> confirm_repo.confirm_draft() [SQL guard]
        |       |       |                       -> signal_client.send(ack)
        |       |       |
        |       |       +-- correction+unknown -> signal_client.send(re-ask)
        |       |       |
        |       |       +-- unknown -> fall through to capture pipeline
        |       |
        +-- standard confirm path
                |
                +-- YES -> confirm_repo.confirm_draft() [SQL guard rowcount]
                |           rowcount=1 -> signal_client.send(confirm_ack)
                |                         emit COMMIT_TRIGGER_MARKER
                |           rowcount=0 -> signal_client.send(idempotent_ack)
                |
                +-- NO  -> confirm_repo.discard_draft() [SQL guard]
                |           -> signal_client.send(discard_ack)
                |
                +-- EDIT -> bump_edit_turn() + stub run_edit_reextraction
                            or expireDraft(edit_cap_exceeded) if cap hit

asyncio.create_task(confirm_watchdog_loop)  [boot.py, alongside retention_task]
        |
        +-- tick_once() [immediately on boot, then every interval_ms]
                |
                +-- confirm_repo.find_nudge_candidates() [SQL interval predicate]
                |       for each row:
                |         confirm_repo.mark_nudge_sent() [SQL guard rowcount]
                |         rowcount=1 -> signal_client.send(nudge) + append_event
                |
                +-- confirm_repo.find_expire_candidates() [SQL interval predicate]
                        for each row:
                          confirm_repo.expire_draft('timeout_expired') [SQL guard]
                          rowcount=1 -> signal_client.send(expired_note)
```

### Recommended Project Structure
```
src/farm-agent/farm_agent/confirm/
├── __init__.py           # empty package marker
├── state_machine.py      # pure FSM (no I/O)
├── confirm_repo.py       # never-throws DAO
├── watchdog.py           # asyncio loop (immediate-then-interval)
└── strain_ask_back.py    # template + reply parser + strain resolver

src/farm-agent/tests/
├── test_confirm_state_machine.py   # pure FSM table-parity (no DB)
├── test_confirm_repo.py            # DB-gated: dup-YES + nudge race
└── test_confirm_watchdog.py        # watchdog loop (mock signal_client)
```

---

## Validation Architecture

> nyquist_validation = true (confirmed in .planning/config.json)

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (already in use) |
| Config file | `src/farm-agent/pytest.ini` or `pyproject.toml` [ASSUMED -- verify] |
| Quick run command | `pytest src/farm-agent/tests/test_confirm_state_machine.py -x` |
| Full suite command | `pytest src/farm-agent/tests/ -x` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CNF-01 (SC-1) | Python FSM table == Node table for every (status, event, condition) case | unit (pure function) | `pytest tests/test_confirm_state_machine.py -x` | Wave 0 |
| CNF-01 (SC-2) | Dup YES -> exactly one confirmed transition; rowcount=0 on second attempt | DB-gated integration | `pytest tests/test_confirm_repo.py::test_dup_yes_idempotency -x` | Wave 0 |
| CNF-02 (SC-3) | Two concurrent tick_once (bypassing Lock) -> exactly one nudge sent | DB-gated integration | `pytest tests/test_confirm_repo.py::test_concurrent_nudge_race -x` | Wave 0 |
| CNF-02 (SC-4) | strain_confirm intercept: unknown code held; known curated-14 code passes through without ask-back | unit (no DB) | `pytest tests/test_confirm_state_machine.py::test_strain_intercept -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest src/farm-agent/tests/test_confirm_state_machine.py -x`
- **Per wave merge:** `pytest src/farm-agent/tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_confirm_state_machine.py` -- covers SC-1 (FSM parity) and SC-4 (strain intercept pure logic)
- [ ] `tests/test_confirm_repo.py` -- covers SC-2 (dup-YES) and SC-3 (nudge race); DB-gated
- [ ] `tests/test_confirm_watchdog.py` -- covers watchdog loop shape (mock signal_client, no DB)
- [ ] Add `DRAFT_NUDGE_FRACTION` and `MAX_EDIT_TURNS` to `TEST_ENV` in `conftest.py`

### SC-1: FSM Parity Test Design

The parity test enumerates ALL rows from the Node transition table (as a fixture) and asserts
`transition(state, event) == expected` for each. Every case in the table above must be a test
case. Parametrize with `@pytest.mark.parametrize`.

```python
@pytest.mark.parametrize("status,event_type,condition,expected_next,expected_effects,expected_reason", [
    # Row 1: dup YES on confirmed
    ("confirmed", "farmer_yes", {}, "confirmed", ["send_confirm_idempotent_ack"], "already_confirmed"),
    # Row 2: inactive (discarded + farmer_no)
    ("discarded", "farmer_no", {}, "discarded", ["noop"], "inactive"),
    # ... all 11 rows
])
def test_transition_parity(status, event_type, condition, ...):
    state = State(status=status, **condition)
    result = transition(state, Event(type=event_type))
    assert result.next_status == expected_next
    assert result.side_effects == expected_effects
    assert result.reason == expected_reason
```

### SC-3: Concurrent Nudge Race Test Design

To prove the SQL guard (not the Lock), the test must bypass the Lock and call the DAO function directly:

```python
@_requires_db
@pytest.mark.asyncio
async def test_concurrent_nudge_race(pool):
    # Insert an awaiting_farmer row with nudge_sent_at=NULL
    # ...
    # Call mark_nudge_sent concurrently from two tasks
    r1, r2 = await asyncio.gather(
        confirm_repo.mark_nudge_sent(pool, draft_id),
        confirm_repo.mark_nudge_sent(pool, draft_id),
    )
    # Exactly one rowcount=1, one rowcount=0
    rowcounts = sorted([r1["rowcount"], r2["rowcount"]])
    assert rowcounts == [0, 1]
```

---

## Security Domain

> security_enforcement absent from config = enabled.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | partial | farmers are authenticated at Signal level (phone E164); `findAwaitingForSender` is scoped to `sender_e164` |
| V5 Input Validation | yes | `parseStrainAskBackReply` regex gate; `resolveStrain` normalizes via `.upper().strip()` |
| V6 Cryptography | no | -- |

| Threat Pattern | STRIDE | Mitigation |
|----------------|--------|-----------|
| Farmer B replies YES to Farmer A's draft | Spoofing | `findAwaitingForSender(pool, sender_e164)` scopes lookup by sender -- only the original sender's drafts are returned |
| Re-confirming an already-committed draft | Tampering | SQL `WHERE status='awaiting_farmer'` guard prevents state transitions on terminal rows |
| PII leak in logs (e164 phone numbers) | Information Disclosure | Use `mask_number()` from tenancy for any phone logged; established codebase pattern |
| SQL injection via strain code input | Tampering | All SQL uses parameterized queries (`%s` placeholders); strain code passed as parameter never interpolated |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-----------------|--------------|--------|
| Node.js confirm loop (pg pool, setInterval) | Python asyncio (psycopg3, asyncio.sleep) | Phase 61 | No behavior change; same SQL guards and timing |
| curated-14 set | curated-14 set (unchanged) | -- | Phase 54.2 live-farmOS supersession deferred to Phase 62 |

**Deprecated/outdated:**
- `src/agents/alerter/src/confirm/` (Node): replaced by `farm_agent/confirm/` (Python) after Phase 65 cutover. Do NOT modify Node source during Phase 61 -- Node is still the live stack.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| psycopg3 / psycopg_pool | confirm_repo.py | Already in project | -- | -- |
| asyncio | watchdog.py | stdlib | -- | -- |
| pytest / pytest-asyncio | tests | Already in project | -- | -- |
| PostgreSQL :5434 | DB-gated tests | Conditional | -- | Skip via `_requires_db` mark |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | pytest.ini / pyproject.toml already configures pytest-asyncio mode | Validation Architecture | Tests need asyncio mode set; add `asyncio_mode = "auto"` to config if missing |
| A2 | The edit handler side effect (`run_edit_reextraction`) can be stubbed in Phase 61 (noop + log) since Phase 60 extractor exists but integration is Phase 62 scope | Implementation Map | If Phase 60 extractor must be called here, the stub will leave EDIT replies unprocessed; acceptable for Phase 61 since SC only covers the FSM and watchdog, not full edit-reextraction |

**If this table is empty:** All claims in this research were verified or cited -- no user confirmation needed.

---

## Open Questions (RESOLVED inline — A1: add asyncio_mode if missing; A2: stub edit re-extraction in Plan 03)

1. **pytest-asyncio mode configuration**
   - What we know: tests use `pytest_asyncio.fixture` (conftest.py uses it).
   - What's unclear: whether `asyncio_mode = "auto"` is already set; some test files may need `@pytest.mark.asyncio` explicitly.
   - Recommendation: check `pyproject.toml` in Wave 0; add mode config if missing.

2. **Edit handler stub vs full integration**
   - What we know: Phase 61 SC does not require full edit-reextraction; SC-1 only tests the FSM pure function; receive-loop dispatches `run_edit_reextraction` side effect.
   - What's unclear: whether the planner wants a full wire-up to Phase 60's extractor or a logged stub.
   - Recommendation: stub with `log.info("[confirm] edit reextraction stub -- Phase 62")` and return to capture pipeline; the FSM and SQL work is Phase 61 scope.

---

## Sources

### Primary (HIGH confidence)
- `src/agents/alerter/src/confirm/state-machine.js` -- full transition table, states, events
- `src/agents/alerter/src/confirm/watchdog.js` -- tick loop, timing, nudge/expire processing
- `src/agents/alerter/src/confirm/confirm-db.js` -- all SQL guards verbatim, transaction pattern, appendEvent shape
- `src/agents/alerter/src/confirm/strain-ask-back.js` -- render template, parseReply, CONFIRM_SET, CODE_RE
- `src/agents/alerter/src/farmos/strain-resolver.js` -- resolveStrain, nearestKnown, Levenshtein
- `src/agents/alerter/src/receive-loop.js` lines 314-411 -- strain intercept + YES/NO/EDIT routing
- `src/agents/alerter/src/config.js` -- draftNudgeFraction=0.8, maxEditTurns=3, draftPendingTimeoutMin=30
- `src/farm-agent/farm_agent/capture/capture_repo.py` -- never-throws DAO pattern
- `src/farm-agent/farm_agent/capture/retention.py` -- immediate-then-sleep watchdog loop pattern
- `src/farm-agent/farm_agent/boot.py` -- asyncio.create_task wiring pattern
- `src/farm-agent/farm_agent/persistence/pool.py` -- AsyncConnectionPool, rowcount semantics
- `src/farm-agent/farm_agent/persistence/migrations.py` -- signal_draft schema (all columns)
- `src/farm-agent/farm_agent/tenancy/tenant.py` -- TenantConfig fields (missing: draft_nudge_fraction, max_edit_turns)
- `src/farm-agent/tests/conftest.py` -- DB-gated skip pattern, pool fixture, TEST_ENV

### Secondary (MEDIUM confidence)
- psycopg3 docs: `cursor.rowcount` for UPDATE statements returns the number of rows matched by WHERE predicate.

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH -- all libraries already in the project
- Architecture: HIGH -- direct read of Node source files; no inference
- Node behavior (transition table, SQL guards): HIGH -- read from live source
- Pitfalls: HIGH -- derived from Node source + established Python codebase patterns
- rowcount semantics: MEDIUM -- verified by existing project usage + psycopg3 documented behavior; not run a live test

**Research date:** 2026-06-28
**Valid until:** stable (source files in this repo; re-read if Node confirm-db.js or receive-loop.js changes)
