# Extraction Write Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Python farm-agent the ability to create a `signal_draft`, so intake reaches the confirm loop instead of dead-ending after capture.

**Architecture:** Faithful port of Node's extraction write path (`src/agents/alerter/src/extraction/`) plus the two confirm-side modules that depend on it. Node on `main` is the source of truth; every module below names the exact Node file and line range it ports. The layer is inserted between the already-ported extractor and the already-ported confirm loop, wired at the seam Node uses (`capture.js:207`).

**Tech Stack:** Python 3.12, psycopg3 + psycopg-pool (async), Pydantic v2, anthropic SDK, pytest + pytest-asyncio (`asyncio_mode = "auto"`), ruff (line-length 100), import-linter.

**Spec:** `.planning/phases/64-extraction-write-path/64-DESIGN.md`

**Ticket:** MUSHY-76

## Global Constraints

- **Node is the source of truth.** Where this plan and the Node source disagree, the Node source wins — flag the discrepancy in the task's commit message rather than silently choosing.
- **Never-throw DAOs.** Every DB function returns `{"ok": True, ...}` or `{"ok": False, "reason": str}` and never raises. Mirror `farm_agent/capture/capture_repo.py` exactly for structure and psycopg3 usage.
- **`enqueue` never raises.** Outer `try/except` returns `{"ok": False, "reason": str(e)}`.
- **PII:** `mask_number(sender)` on every log line that references an e164. Never log farmer text, transcripts, or draft contents.
- **Secrets:** never log the config object or any field of it.
- **No em-dashes in farmer-facing strings.** `sanitize_farmer_text` sweeps them; use `?`, `--`, or `n/a`.
- **All farmer-facing numbers via `fmt_num`** (1 decimal, rounded).
- **`origin='python'`** on every `insert_draft`. Non-negotiable: the default `'node'` would hand the draft to the live Node commit watchdog, which writes to production farmOS.
- **Import-linter:** nothing under `farm_agent/extraction/` or `farm_agent/confirm/` may import `farm_agent.chamber`. Contract in `src/farm-agent/.lint-imports`; no config change needed.
- **Line length 100** (ruff), `from __future__ import annotations` at the top of every new module.
- **All paths below are relative to `src/farm-agent/`** unless stated otherwise.
- **Run tests with:** `cd src/farm-agent && uv run pytest <path> -v`

## File Structure

| File | Responsibility |
|---|---|
| `farm_agent/extraction/extraction_db.py` | `signal_draft` DAO. Deterministic draft ids, never-throw writes, in-flight lookup. |
| `farm_agent/extraction/state_machine.py` | Pure extraction FSM: extraction result -> next status + side-effect tags. No I/O. |
| `farm_agent/extraction/preview_builder.py` | All farmer-facing draft rendering. Pure string functions. |
| `farm_agent/extraction/outbound.py` | Side-effect tag -> Signal send. Owns the trinity-skip and operator-channel routing. |
| `farm_agent/extraction/pipeline.py` | `enqueue` orchestrator: in-flight, idle guard, extract, continuity, persist, dispatch. |
| `farm_agent/extraction/batch_mode.py` | Multi-draft paper-log page handling (batch review + small-N fan-out). |
| `farm_agent/extraction/starting_seq.py` | The `needs_input='starting_seq'` ask-back and its reply handler. |
| `farm_agent/confirm/preview.py` | Confirm-loop farmer copy (acks, nudge, expired note, preview+suffix). |
| `farm_agent/confirm/edit_handler.py` | EDIT re-extraction, replacing the Phase 61 stub. |

Tasks 1-4 are leaves with no dependencies on each other and can be executed in parallel. Tasks 5-7 depend on 1-4. Tasks 8-10 depend on 5-7.

---

### Task 1: `extraction_db.py` — the signal_draft DAO

Ports `src/agents/alerter/src/extraction/extraction-db.js` lines 18-24 and 76-250. `initDb` (lines 26-74) is NOT ported: `farm_agent/persistence/migrations.py:157` already creates the table and the D-02c partial unique index.

**Files:**
- Create: `farm_agent/extraction/extraction_db.py`
- Test: `tests/extraction/test_extraction_db.py`
- Create if absent: `tests/extraction/__init__.py` (empty)

**Interfaces:**
- Consumes: nothing.
- Produces:
```python
IN_FLIGHT_STATUSES: tuple[str, ...] = ("pending", "awaiting_farmer")

def compute_draft_id(capture_ids: list[str], draft_index: int | None = None) -> str
async def insert_draft(pool, row: dict) -> dict          # {ok:True,id} | {ok:False,reason}
async def get_in_flight_for_sender(pool, sender_e164: str) -> dict | None
async def update_draft_status(pool, draft_id: str, new_status: str,
                              extras: dict | None = None) -> dict  # {ok,rowcount}|{ok,reason}
async def advance_askback_turn(pool, draft_id: str) -> dict         # {ok,askback_turns}|{ok,reason}
async def expire_idle(pool, gap_minutes: int) -> dict               # {ok,rowcount}|{ok,reason}
async def get_drafts_for_capture(pool, capture_id: str) -> list[dict]   # [] on error
async def get_draft_by_id(pool, draft_id: str) -> dict | None           # None on error
```

`insert_draft` row keys: `id`, `sender_e164`, `farmos_person`, `source_capture_ids`, `status`, `log_type`, `draft_json`, `per_field_confidence`, `askback_turns`, `farmer_facing_preview`, `needs_review_reason`, `reply_target_kind`, `group_id`.

- [ ] **Step 1: Write the failing tests**

`compute_draft_id` must stay byte-identical to Node for the single-draft case — existing rows in the shared database were keyed by it.

```python
"""DAO tests for signal_draft. Port parity: extraction-db.js."""

import hashlib

import pytest

from farm_agent.extraction import extraction_db as db


def test_compute_draft_id_matches_node_single():
    # Node: sha256(sorted(ids).join('|')); index 0 and None are NOT suffixed.
    ids = ["01JB", "01JA"]
    expected = hashlib.sha256("01JA|01JB".encode()).hexdigest()
    assert db.compute_draft_id(ids) == expected
    assert db.compute_draft_id(ids, 0) == expected


def test_compute_draft_id_indexed_is_suffixed():
    ids = ["01JA"]
    expected = hashlib.sha256("01JA#2".encode()).hexdigest()
    assert db.compute_draft_id(ids, 2) == expected


def test_compute_draft_id_does_not_mutate_input():
    ids = ["c", "a", "b"]
    db.compute_draft_id(ids)
    assert ids == ["c", "a", "b"]


class FakePool:
    """Minimal async pool double: records executed SQL, optionally raises."""

    def __init__(self, raises=None, rowcount=1, rows=None):
        self.raises = raises
        self.rowcount = rowcount
        self.rows = rows if rows is not None else []
        self.calls = []

    def connection(self):
        return _FakeConnCtx(self)


class _FakeConnCtx:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return _FakeConn(self.pool)

    async def __aexit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, pool):
        self.pool = pool

    async def execute(self, sql, params=None):
        self.pool.calls.append((sql, params))
        if self.pool.raises is not None:
            raise self.pool.raises
        return _FakeCursor(self.pool)


class _FakeCursor:
    def __init__(self, pool):
        self.rowcount = pool.rowcount
        self._rows = pool.rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows


class FakeUniqueViolation(Exception):
    sqlstate = "23505"


async def test_insert_draft_stamps_origin_python():
    pool = FakePool()
    res = await db.insert_draft(pool, {
        "id": "d1", "sender_e164": "+100", "source_capture_ids": ["c1"],
        "status": "pending", "draft_json": {"type": "harvest"},
    })
    assert res["ok"] is True
    sql, params = pool.calls[0]
    assert "origin" in sql
    assert "python" in params


async def test_insert_draft_in_flight_conflict_on_23505():
    pool = FakePool(raises=FakeUniqueViolation())
    res = await db.insert_draft(pool, {
        "id": "d1", "sender_e164": "+100", "source_capture_ids": ["c1"], "status": "pending",
    })
    assert res == {"ok": False, "reason": "in_flight_conflict"}


async def test_insert_draft_other_error_returns_reason():
    pool = FakePool(raises=RuntimeError("boom"))
    res = await db.insert_draft(pool, {
        "id": "d1", "sender_e164": "+100", "source_capture_ids": ["c1"], "status": "pending",
    })
    assert res["ok"] is False
    assert res["reason"] == "boom"


async def test_update_draft_status_ignores_unwhitelisted_keys():
    pool = FakePool()
    res = await db.update_draft_status(pool, "d1", "needs_review", {
        "needs_review_reason": "askback_cap_exceeded",
        "status; DROP TABLE signal_draft": "evil",
        "origin": "node",
    })
    assert res["ok"] is True
    sql, params = pool.calls[0]
    assert "needs_review_reason" in sql
    assert "DROP TABLE" not in sql
    assert "origin" not in sql.split("SET", 1)[1].split("WHERE", 1)[0]
    assert "node" not in params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'farm_agent.extraction.extraction_db'`

- [ ] **Step 3: Write the implementation**

Translate `extraction-db.js` function-for-function. The three things to get exactly right:

```python
"""
extraction/extraction_db.py -- never-throws signal_draft DAO.

Port of src/agents/alerter/src/extraction/extraction-db.js (initDb excluded --
persistence/migrations.py:157 already owns the DDL and the D-02c partial
unique index).

MUSHY-76 deviation from Node: insert_draft stamps origin='python'. Node relies
on the column default 'node'. The Node commit watchdog selects
`WHERE status='confirmed' AND origin != 'python'`, so a Python-created draft
left at the default is committed to PRODUCTION farmOS by the Node agent.
"""

from __future__ import annotations

import hashlib
import logging

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

IN_FLIGHT_STATUSES: tuple[str, ...] = ("pending", "awaiting_farmer")

# Whitelisted so a caller-supplied key can never reach the SET clause.
# Verbatim from extraction-db.js UPDATE_EXTRAS_WHITELIST (8 keys).
_UPDATE_EXTRAS_WHITELIST = frozenset({
    "needs_review_reason",
    "farmer_facing_preview",
    "draft_json",
    "per_field_confidence",
    "log_type",
    "farmos_person",
    "reply_target_kind",
    "group_id",
})

_INSERT_SQL = """
INSERT INTO signal_draft
  (id, sender_e164, farmos_person, source_capture_ids, status, log_type,
   draft_json, per_field_confidence, askback_turns, farmer_facing_preview,
   needs_review_reason, reply_target_kind, group_id, origin)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def compute_draft_id(capture_ids: list[str], draft_index: int | None = None) -> str:
    """Deterministic, replay-safe draft id (D-02a).

    SHA-256 over sorted capture ids joined by '|'. Index 0 and None are NOT
    suffixed, so single-draft ids stay byte-identical to every pre-Plan-08 row
    already in the shared database. Port of extraction-db.js:18-24.
    """
    sorted_ids = "|".join(sorted(capture_ids))
    keyed = sorted_ids if draft_index in (None, 0) else f"{sorted_ids}#{draft_index}"
    return hashlib.sha256(keyed.encode()).hexdigest()
```

For `insert_draft`, detect the unique violation by SQLSTATE, not by message text:

```python
async def insert_draft(pool: AsyncConnectionPool, row: dict) -> dict:
    params = (
        row["id"],
        row["sender_e164"],
        row.get("farmos_person"),
        row.get("source_capture_ids", []),   # text[] -- pass the list directly
        row["status"],
        row.get("log_type"),
        Jsonb(row["draft_json"]) if row.get("draft_json") is not None else None,
        Jsonb(row["per_field_confidence"]) if row.get("per_field_confidence") is not None else None,
        row.get("askback_turns", 0),
        row.get("farmer_facing_preview"),
        row.get("needs_review_reason"),
        row.get("reply_target_kind"),
        row.get("group_id"),
        "python",                            # MUSHY-76: origin guard
    )
    try:
        async with pool.connection() as conn:
            await conn.execute(_INSERT_SQL, params)
        return {"ok": True, "id": row["id"]}
    except Exception as e:  # noqa: BLE001 -- never-throw DAO
        if getattr(e, "sqlstate", None) == "23505":
            return {"ok": False, "reason": "in_flight_conflict"}
        logger.warning("[extraction_db] insert_draft failed: %s", e)
        return {"ok": False, "reason": str(e)}
```

Note `draft_json` and `per_field_confidence` are `jsonb` and must be wrapped in `psycopg.types.json.Jsonb`; `source_capture_ids` is `text[]` and must NOT be wrapped (same rule as `attachment_paths` in `capture_repo.py`).

`update_draft_status` builds its SET clause from the whitelist only:

```python
async def update_draft_status(
    pool: AsyncConnectionPool, draft_id: str, new_status: str, extras: dict | None = None
) -> dict:
    set_parts = ["status = %s", "updated_at = now()"]
    params: list = [new_status]
    for k, v in (extras or {}).items():
        if k not in _UPDATE_EXTRAS_WHITELIST:
            continue
        set_parts.append(f"{k} = %s")
        params.append(Jsonb(v) if k in ("draft_json", "per_field_confidence") and v is not None else v)
    params.append(draft_id)
    sql = f"UPDATE signal_draft SET {', '.join(set_parts)} WHERE id = %s"
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(sql, tuple(params))
            return {"ok": True, "rowcount": cur.rowcount or 0}
    except Exception as e:  # noqa: BLE001
        logger.warning("[extraction_db] update_draft_status failed: %s", e)
        return {"ok": False, "reason": str(e)}
```

Remaining functions port directly: `get_in_flight_for_sender` (extraction-db.js:113-122, `LIMIT 1`, returns the row dict or `None`), `advance_askback_turn` (169-188, `RETURNING askback_turns`), `expire_idle` (190-210, `updated_at < now() - (%s || ' minutes')::interval` — the string-cast interval, same reason as `capture_repo._EXPIRE_SQL`), `get_drafts_for_capture` (212-230, `source_capture_ids @> ARRAY[%s]::text[]`, `ORDER BY created_at ASC`, `[]` on error), `get_draft_by_id` (232-250, `None` on error).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_db.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Lint**

Run: `cd src/farm-agent && uv run ruff check farm_agent/extraction/extraction_db.py`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add src/farm-agent/farm_agent/extraction/extraction_db.py src/farm-agent/tests/extraction/
git commit -m "feat(port): signal_draft DAO with origin='python' guard [MUSHY-76]"
```

---

### Task 2: `extraction/state_machine.py` — the pure extraction FSM

Ports `src/agents/alerter/src/extraction/state-machine.js` in full (223 lines). This is a different FSM from the already-ported `farm_agent/confirm/state_machine.py`; both may be imported in the same module, so keep the names distinct.

**Files:**
- Create: `farm_agent/extraction/state_machine.py`
- Test: `tests/extraction/test_extraction_state_machine.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
```python
class DraftStatus(str, Enum):
    PENDING = "pending"
    AWAITING_FARMER = "awaiting_farmer"
    NEEDS_REVIEW = "needs_review"
    EXPIRED = "expired"

REQUIRED_FIELDS: dict[str, list[str]]

@dataclass
class AskBackInfo:
    ask_back: bool
    missing_fields: list[str]
    low_conf_fields: list[str]

@dataclass
class ExtractionTransition:
    next_status: str
    next_askback_turns: int
    side_effects: list[str]
    reason: str | None
    ask_back_info: AskBackInfo | None = None

def should_ask_back(draft: dict | None, per_field_confidence: dict | None,
                    threshold: float) -> AskBackInfo
def force_start_new_if_idle(prev_draft: dict | None, now_ms: int,
                            idle_gap_min: int) -> str | None   # 'start_new' | None
def transition(state: dict, event: dict) -> ExtractionTransition
```

`REQUIRED_FIELDS` verbatim from state-machine.js:23-33:
```python
REQUIRED_FIELDS = {
    "seeding":         ["species", "block_name", "qty", "event_timestamp"],
    "activity":        ["name", "asset_ref", "event_timestamp"],
    "input":           ["recipe_lot", "asset_ref", "event_timestamp"],
    "observation":     ["asset_ref", "event_timestamp"],
    "harvest":         ["harvest_batch_id", "source_block_refs", "qty_g", "event_timestamp"],
    "seeding_session": ["event_date", "groups"],
}
```

Side-effect tags emitted: `handoff_to_phase_39`, `send_ask_back`, `send_needs_review_ping`, `mark_expired`, `noop`.

- [ ] **Step 1: Write the failing tests**

The cap arithmetic is the subtle part: with `max_askback_turns=3`, `askback_turns=2` plus a still-asking extraction goes to `needs_review` — the last turn is not burned.

```python
"""100% transition-table parity for the extraction FSM. Pure: no DB, no mocks."""

import pytest

from farm_agent.extraction.state_machine import (
    REQUIRED_FIELDS,
    AskBackInfo,
    DraftStatus,
    force_start_new_if_idle,
    should_ask_back,
    transition,
)

CLEAN_HARVEST = {
    "type": "harvest",
    "harvest_batch_id": "H1",
    "source_block_refs": ["b1"],
    "qty_g": 500,
    "event_timestamp": "2026-05-22T10:00:00Z",
}


def test_should_ask_back_clean_draft():
    r = should_ask_back(CLEAN_HARVEST, {}, 0.7)
    assert r.ask_back is False
    assert r.missing_fields == []
    assert r.low_conf_fields == []


def test_should_ask_back_missing_required():
    draft = dict(CLEAN_HARVEST)
    del draft["qty_g"]
    r = should_ask_back(draft, {}, 0.7)
    assert r.ask_back is True
    assert "qty_g" in r.missing_fields


@pytest.mark.parametrize("value", [None, [], "", "   "])
def test_field_presence_rules(value):
    draft = dict(CLEAN_HARVEST, source_block_refs=value)
    r = should_ask_back(draft, {}, 0.7)
    assert "source_block_refs" in r.missing_fields


def test_low_confidence_required_field_is_flagged_not_missing():
    r = should_ask_back(CLEAN_HARVEST, {"qty_g": 0.4}, 0.7)
    assert r.ask_back is True
    assert r.low_conf_fields == ["qty_g"]
    assert r.missing_fields == []


def test_low_confidence_optional_present_field_is_flagged():
    # Optional fields the LLM emitted below threshold surface too, so the
    # preview-builder can mark them [?]. state-machine.js:90-95.
    draft = dict(CLEAN_HARVEST, notes="maybe")
    r = should_ask_back(draft, {"notes": 0.2}, 0.7)
    assert "notes" in r.low_conf_fields


def test_low_confidence_absent_field_is_not_flagged():
    r = should_ask_back(CLEAN_HARVEST, {"notes": 0.2}, 0.7)
    assert "notes" not in r.low_conf_fields


def test_observation_state_or_notes_marker():
    draft = {"type": "observation", "asset_ref": "a1", "event_timestamp": "t"}
    r = should_ask_back(draft, {}, 0.7)
    assert "state_or_notes" in r.missing_fields


def test_observation_notes_alone_satisfies():
    draft = {"type": "observation", "asset_ref": "a1", "event_timestamp": "t", "notes": "n"}
    r = should_ask_back(draft, {}, 0.7)
    assert r.ask_back is False


def test_unknown_type_has_no_required_fields():
    r = should_ask_back({"type": "nonsense"}, {}, 0.7)
    assert r.ask_back is False


# --- force_start_new_if_idle -------------------------------------------------

def test_force_start_new_none_when_no_prior():
    assert force_start_new_if_idle(None, 1_000_000, 30) is None


def test_force_start_new_none_when_no_timestamp():
    assert force_start_new_if_idle({"last_updated_at_ms": None}, 1_000_000, 30) is None


def test_force_start_new_at_exactly_the_gap():
    now = 30 * 60 * 1000
    assert force_start_new_if_idle({"last_updated_at_ms": 0}, now, 30) == "start_new"


def test_force_start_new_none_just_under_the_gap():
    now = 30 * 60 * 1000 - 1
    assert force_start_new_if_idle({"last_updated_at_ms": 0}, now, 30) is None


# --- transition --------------------------------------------------------------

def _extraction_event(draft, conf=None, threshold=0.7, cap=3, now_ms=0):
    return {
        "type": "extraction_result", "draft": draft,
        "per_field_confidence": conf or {}, "threshold": threshold,
        "max_askback_turns": cap, "now_ms": now_ms,
    }


def test_clean_extraction_goes_awaiting_farmer_with_handoff():
    t = transition({"status": "pending", "askback_turns": 0}, _extraction_event(CLEAN_HARVEST))
    assert t.next_status == DraftStatus.AWAITING_FARMER
    assert t.side_effects == ["handoff_to_phase_39"]
    assert t.reason == "ready_for_confirm"
    assert t.next_askback_turns == 0


def test_dirty_extraction_asks_back_and_increments():
    draft = dict(CLEAN_HARVEST)
    del draft["qty_g"]
    t = transition({"status": "pending", "askback_turns": 0}, _extraction_event(draft))
    assert t.next_status == DraftStatus.AWAITING_FARMER
    assert t.side_effects == ["send_ask_back"]
    assert t.reason == "ask_back"
    assert t.next_askback_turns == 1


def test_askback_cap_reached_goes_needs_review_without_burning_last_turn():
    draft = dict(CLEAN_HARVEST)
    del draft["qty_g"]
    t = transition({"status": "pending", "askback_turns": 2}, _extraction_event(draft, cap=3))
    assert t.next_status == DraftStatus.NEEDS_REVIEW
    assert t.side_effects == ["send_needs_review_ping"]
    assert t.reason == "askback_cap"
    assert t.next_askback_turns == 2


def test_farmer_replied_counts_the_turn_only():
    t = transition({"status": "awaiting_farmer", "askback_turns": 1},
                   {"type": "farmer_replied", "now_ms": 0})
    assert t.next_status == DraftStatus.AWAITING_FARMER
    assert t.next_askback_turns == 2
    assert t.side_effects == ["noop"]


def test_idle_check_expires_active_draft():
    t = transition({"status": "pending", "askback_turns": 0, "last_updated_at_ms": 0},
                   {"type": "idle_check", "now_ms": 30 * 60 * 1000, "idle_gap_min": 30})
    assert t.next_status == DraftStatus.EXPIRED
    assert t.side_effects == ["mark_expired"]
    assert t.reason == "idle_gap"


def test_idle_check_noop_within_cap():
    t = transition({"status": "pending", "askback_turns": 0, "last_updated_at_ms": 0},
                   {"type": "idle_check", "now_ms": 60_000, "idle_gap_min": 30})
    assert t.side_effects == ["noop"]
    assert t.reason == "within_idle_cap"


def test_idle_check_noop_on_inactive_status():
    t = transition({"status": "expired", "askback_turns": 0, "last_updated_at_ms": 0},
                   {"type": "idle_check", "now_ms": 10**12, "idle_gap_min": 30})
    assert t.next_status == "expired"
    assert t.reason == "not_active"


@pytest.mark.parametrize("event", [None, {}, {"type": "bogus"}])
def test_unknown_event_is_noop_preserving_state(event):
    t = transition({"status": "pending", "askback_turns": 4}, event)
    assert t.next_status == "pending"
    assert t.next_askback_turns == 4
    assert t.side_effects == ["noop"]
    assert t.reason == "unknown_event"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_state_machine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Translate state-machine.js:44-214 directly. Field-presence rule (js:44-50):

```python
def _is_field_present(draft: dict, field: str) -> bool:
    v = draft.get(field)
    if v is None:
        return False
    if isinstance(v, (list, tuple)) and len(v) == 0:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    return True
```

Cap arithmetic (js:155-164), the one line most likely to be got wrong:

```python
current_turns = state.get("askback_turns") or 0
if current_turns + 1 >= max_askback_turns:
    return ExtractionTransition(
        next_status=DraftStatus.NEEDS_REVIEW,
        next_askback_turns=current_turns,
        side_effects=["send_needs_review_ping"],
        reason="askback_cap",
        ask_back_info=ask,
    )
```

Node's camelCase event keys become snake_case in Python: `perFieldConfidence` -> `per_field_confidence`, `maxAskbackTurns` -> `max_askback_turns`, `idleGapMin` -> `idle_gap_min`. Keep `now_ms` as-is (already snake in Node).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_state_machine.py -v`
Expected: PASS (24 tests)

- [ ] **Step 5: Commit**

```bash
git add src/farm-agent/farm_agent/extraction/state_machine.py src/farm-agent/tests/extraction/test_extraction_state_machine.py
git commit -m "feat(port): pure extraction FSM with full transition-table parity [MUSHY-76]"
```

---

### Task 3: `preview_builder.py` — farmer-facing draft rendering

Ports `src/agents/alerter/src/extraction/preview-builder.js` in full (374 lines). Pure string functions, no I/O.

**Files:**
- Create: `farm_agent/extraction/preview_builder.py`
- Test: `tests/extraction/test_preview_builder.py`

**Interfaces:**
- Consumes: `farm_agent.extraction.state_machine.REQUIRED_FIELDS` (Task 2) for the caller's `required_fields` argument; this module does not import it itself.
- Produces:
```python
def sanitize_farmer_text(s: str) -> str
def build_top_question(missing_fields: list[str], low_conf_fields: list[str],
                       draft_type: str | None) -> str
def render_value(v) -> str
def render_scalar(v) -> str
def classify_field(field: str, draft: dict, per_field_confidence: dict,
                   threshold: float) -> str
def build_preview(draft: dict | None, per_field_confidence: dict | None,
                  threshold: float, required_fields: list[str]) -> str
def render_seeding_session(draft: dict) -> str
def render_starting_seq_ask_back(draft: dict) -> str
```

`build_preview` takes keyword arguments in Node (`{draft, perFieldConfidence, threshold, requiredFields}`); in Python it takes those four as keyword-only parameters so call sites stay readable.

- [ ] **Step 1: Write the failing tests**

Style locks are farm rules, not cosmetics: em-dashes are an LLM tell in farmer-facing text, and numbers go through `fmt_num`.

```python
"""Rendering parity for the extraction preview builder. Pure strings."""

import pytest

from farm_agent.extraction.preview_builder import (
    build_preview,
    build_top_question,
    classify_field,
    render_seeding_session,
    render_value,
    sanitize_farmer_text,
)


def test_sanitize_strips_em_dashes():
    out = sanitize_farmer_text("harvest — 500 g")
    assert "—" not in out


def test_sanitize_is_idempotent():
    once = sanitize_farmer_text("a — b")
    assert sanitize_farmer_text(once) == once


def test_preview_marks_low_confidence_fields():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_preview(draft=draft, per_field_confidence={"qty_g": 0.3},
                        threshold=0.7, required_fields=["qty_g"])
    assert "[?]" in out


def test_preview_omits_marker_when_confident():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_preview(draft=draft, per_field_confidence={"qty_g": 0.95},
                        threshold=0.7, required_fields=["qty_g"])
    assert "[?]" not in out


def test_preview_never_contains_em_dash():
    draft = {"type": "harvest", "harvest_batch_id": "H — 1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "t"}
    out = build_preview(draft=draft, per_field_confidence={},
                        threshold=0.7, required_fields=[])
    assert "—" not in out


def test_preview_on_none_draft_does_not_raise():
    out = build_preview(draft=None, per_field_confidence=None,
                        threshold=0.7, required_fields=[])
    assert isinstance(out, str)


def test_top_question_prefers_missing_over_low_conf():
    q = build_top_question(missing_fields=["qty_g"], low_conf_fields=["notes"],
                           draft_type="harvest")
    assert "qty" in q.lower()


def test_seeding_session_table_columns_align():
    draft = {
        "type": "seeding_session",
        "event_date": "20260522",
        "groups": [
            {"parent": {"value": "KOY"}, "species": {"value": "KOY"},
             "qty": {"value": 3}, "child_block_names": {"value": ["a", "b", "c"]}},
            {"parent": {"value": "SHIITAKE-LONG"}, "species": {"value": "SHI"},
             "qty": {"value": 11}, "child_block_names": {"value": []}},
        ],
    }
    out = render_seeding_session(draft)
    lines = [ln for ln in out.splitlines() if "|" in ln]
    widths = {len(ln) for ln in lines}
    assert len(widths) == 1, f"table rows are ragged: {widths}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_preview_builder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Port function-for-function from preview-builder.js. Map of Node line ranges to Python functions:

| Node lines | Python function |
|---|---|
| 45-59 | `sanitize_farmer_text` |
| 61-82 | `build_top_question` (keep `TOP_Q_TEMPLATES` verbatim) |
| 84-102 | `render_value`, `render_scalar` |
| 104-131 | `classify_field` |
| 133-240 | `build_preview` |
| 242-287 | `render_seeding_session` |
| 289-308 | `render_starting_seq_ask_back` |
| 310-322 | `_format_session_row` |
| 324-346 | `_render_children` |
| 348-367 | `_compute_column_widths`, `_pad_row` |

`fmt_num` already exists in the Python port — locate it (`grep -rn "def fmt_num" farm_agent/`) and import it rather than re-implementing. If it does not exist, port it from `src/agents/alerter/src/message.js` into the same module the Node one lives in and note that in the commit.

`sanitize_farmer_text` must be idempotent and must strip em-dashes; everything farmer-facing in this phase goes through it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_preview_builder.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/farm-agent/farm_agent/extraction/preview_builder.py src/farm-agent/tests/extraction/test_preview_builder.py
git commit -m "feat(port): extraction preview builder [MUSHY-76]"
```

---

### Task 4: `extraction/outbound.py` — side-effect dispatcher

Ports `src/agents/alerter/src/extraction/outbound.js` in full (189 lines).

**Files:**
- Create: `farm_agent/extraction/outbound.py`
- Test: `tests/extraction/test_extraction_outbound.py`

**Interfaces:**
- Consumes: `preview_builder.sanitize_farmer_text` (Task 3); a duck-typed `signal_client` with `async send(body, *, to, intent, related_capture_id, related_draft_id, source_module)`.
- Produces:
```python
def create_outbound_dispatcher(
    signal_client, config, preview_builder, operator_recipient: str | None,
    log: logging.Logger | None = None,
) -> dict   # {"dispatch": async (side_effect: str, draft_row: dict | None) -> dict}
```

Handled tags: `send_ask_back`, `send_needs_review_ping`, `send_batch_review_summary`. No-send tags returning `{"ok": True, "noop": True}`: `mark_expired`, `handoff_to_phase_39`, `noop`. Anything else returns `{"ok": False, "reason": "unknown_side_effect"}` with a warning.

Before writing this task, check the actual keyword names on `farm_agent/signal_io/client.py`'s `send` — the Python client may name them differently from Node's options object. Match the Python client.

- [ ] **Step 1: Write the failing tests**

The trinity-skip matters: when the operator recipient is the same number as the sender, operator-channel pings interrupt Santi's own farmer conversation with internal-looking chatter.

```python
"""Extraction outbound dispatcher: routing, trinity-skip, unknown tags."""

import pytest

from farm_agent.extraction import preview_builder
from farm_agent.extraction.outbound import create_outbound_dispatcher


class FakeSignalClient:
    def __init__(self):
        self.sent = []

    async def send(self, body, **kwargs):
        self.sent.append((body, kwargs))
        return {"ok": True}


def _dispatcher(client, operator="+59890000000"):
    return create_outbound_dispatcher(
        signal_client=client, config=object(), preview_builder=preview_builder,
        operator_recipient=operator,
    )["dispatch"]


async def test_ask_back_sends_preview_to_dm():
    c = FakeSignalClient()
    await _dispatcher(c)("send_ask_back", {
        "id": "abc123", "sender_e164": "+59891111111",
        "farmer_facing_preview": "How many grams?",
        "reply_target_kind": "dm", "source_capture_ids": ["cap1"],
    })
    body, kw = c.sent[0]
    assert body == "How many grams?"
    assert kw["to"] == "+59891111111"
    assert kw["related_draft_id"] == "abc123"
    assert kw["related_capture_id"] == "cap1"


async def test_ask_back_routes_to_group_when_group_kind():
    c = FakeSignalClient()
    await _dispatcher(c)("send_ask_back", {
        "id": "abc123", "sender_e164": "+59891111111", "farmer_facing_preview": "q",
        "reply_target_kind": "group", "group_id": "g1", "source_capture_ids": [],
    })
    _, kw = c.sent[0]
    assert kw["to"] == {"group_id": "g1"} or kw.get("group_id") == "g1"


async def test_ask_back_group_kind_without_group_id_has_no_target():
    c = FakeSignalClient()
    res = await _dispatcher(c)("send_ask_back", {
        "id": "abc", "sender_e164": "+5989", "farmer_facing_preview": "q",
        "reply_target_kind": "group", "group_id": None, "source_capture_ids": [],
    })
    assert res == {"ok": False, "reason": "no_target"}
    assert c.sent == []


async def test_needs_review_ping_skipped_when_operator_is_sender():
    c = FakeSignalClient()
    res = await _dispatcher(c, operator="+59891111111")("send_needs_review_ping", {
        "id": "abc", "sender_e164": "+59891111111", "needs_review_reason": "askback_cap",
    })
    assert res["ok"] is True
    assert res["skipped"] == "trinity"
    assert c.sent == []


async def test_needs_review_ping_no_target_when_operator_unset():
    c = FakeSignalClient()
    res = await _dispatcher(c, operator=None)("send_needs_review_ping", {"id": "a", "sender_e164": "+1"})
    assert res == {"ok": False, "reason": "no_target"}


async def test_batch_summary_counts_clean_and_needs_review():
    c = FakeSignalClient()
    await _dispatcher(c)("send_batch_review_summary", {
        "sender_e164": "+59891111111",
        "draftIds": [
            {"id": "a" * 20, "status": "needs_review"},
            {"id": "b" * 20, "status": "needs_review"},
            {"id": "c" * 20, "status": "awaiting_farmer"},
        ],
    })
    body, _ = c.sent[0]
    assert "3 drafts" in body
    assert "1 clean" in body
    assert "2 need review" in body
    assert "Don Santiago" in body


@pytest.mark.parametrize("tag", ["mark_expired", "handoff_to_phase_39", "noop"])
async def test_no_send_tags(tag):
    c = FakeSignalClient()
    res = await _dispatcher(c)(tag, {})
    assert res == {"ok": True, "noop": True}
    assert c.sent == []


async def test_unknown_tag():
    c = FakeSignalClient()
    res = await _dispatcher(c)("send_nukes", {})
    assert res == {"ok": False, "reason": "unknown_side_effect"}


async def test_dispatch_never_raises_when_send_throws():
    class Boom:
        async def send(self, body, **kw):
            raise RuntimeError("signal down")

    res = await _dispatcher(Boom())("send_ask_back", {
        "id": "a", "sender_e164": "+1", "farmer_facing_preview": "q",
        "reply_target_kind": "dm", "source_capture_ids": [],
    })
    assert res["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_outbound.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Port outbound.js:19-186. Structure: closure factory holding `signal_client`, `operator_recipient`, `sanitize`; inner `_resolve_ask_back_target`, `_safe_send`, `_first_capture_id`, `_is_operator_equals_sender`, `_send_ask_back`, `_send_batch_review_summary`, `_send_needs_review_ping`, and the `dispatch` match statement.

`_safe_send` sends with `intent="extraction_preview"` and `source_module="extraction/outbound.py"`. Per-draft sends pass `related_draft_id`; batch summaries span many drafts and pass `None`.

Copy the two operator-channel message bodies verbatim from outbound.js:129 and :151, including the "Hey Don Santiago" address — project rule is never to refer to Santi as "the operator".

`truncId` is `id[:10]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_outbound.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/farm-agent/farm_agent/extraction/outbound.py src/farm-agent/tests/extraction/test_extraction_outbound.py
git commit -m "feat(port): extraction outbound dispatcher with trinity-skip [MUSHY-76]"
```

---

### Task 5: `pipeline.py` — the `enqueue` orchestrator

Ports `src/agents/alerter/src/extraction/pipeline.js` lines 38-159 (module helpers) and 289-791 (`enqueue`), excluding the two multi-draft branches (Task 6) and the starting-seq branch (Task 7), which are stubbed here and filled in by those tasks.

**Files:**
- Create: `farm_agent/extraction/pipeline.py`
- Test: `tests/extraction/test_extraction_pipeline.py`

**Interfaces:**
- Consumes: `extraction_db` (Task 1), `state_machine` (Task 2), `preview_builder` (Task 3), the dispatcher from `outbound.create_outbound_dispatcher` (Task 4), and the existing `farm_agent.extraction.extractor.create_extractor` result dict.
- Produces:
```python
def create_extraction_pipeline(
    pool, extractor: dict, config, *,
    extraction_db=None, state_machine=None, preview_builder=None,
    outbound_dispatcher=None, clock=None, log=None,
) -> dict   # {"enqueue": async fn, "handle_starting_seq_reply": async fn}

async def enqueue(capture_ctx: dict) -> dict
```

`capture_ctx` keys (from `capture.js:208-221`): `capture_id`, `sender`, `farmos_person`, `text`, `transcripts` (list[str]), `attachment_paths`, `reply_target_kind`, `group_id`, `captured_at_ms`, `corpus_context`, `sender_name`.

`enqueue` returns `{"ok": True, "draft_id", "status", "continuity", "side_effects"}` on the single-draft path, or `{"ok": False, "reason"}`. Never raises.

Module-level helpers to port from pipeline.js:38-159: `_load_image_blocks` (38-51), `_format_event_date_human` (60-67), `_sum_group_qtys` (115-123), `_min_leaf_confidence` (129-145), `_should_batch_review` (151-159).

- [ ] **Step 1: Write the failing tests**

```python
"""enqueue orchestration: continuity, idle guard, image loading, fail-soft."""

import pytest

from farm_agent.extraction.pipeline import create_extraction_pipeline


class FakeDb:
    def __init__(self, in_flight=None):
        self.in_flight = in_flight
        self.inserted = []
        self.updates = []
        self.bumps = []

    def compute_draft_id(self, ids, index=None):
        return "draft-" + "|".join(sorted(ids)) + ("" if index in (None, 0) else f"#{index}")

    async def get_in_flight_for_sender(self, pool, sender):
        return self.in_flight

    async def insert_draft(self, pool, row):
        self.inserted.append(row)
        return {"ok": True, "id": row["id"]}

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        self.updates.append((draft_id, status, extras or {}))
        return {"ok": True, "rowcount": 1}

    async def advance_askback_turn(self, pool, draft_id):
        self.bumps.append(draft_id)
        return {"ok": True, "askback_turns": 1}


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, effect, row):
        self.calls.append((effect, row))
        return {"ok": True}


CLEAN = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
         "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}


def _extractor(result):
    async def extract(captures, in_flight_draft=None, corpus_context=None,
                      farmer_correction=None):
        return result
    return {"extract": extract}


def _config(**over):
    class C:
        extraction_confidence_threshold = 0.7
        draft_idle_gap_min = 30
        max_askback_turns = 3
    c = C()
    for k, v in over.items():
        setattr(c, k, v)
    return c


def _pipeline(db, extractor, dispatcher=None, config=None):
    return create_extraction_pipeline(
        pool=None, extractor=extractor, config=config or _config(),
        extraction_db=db, outbound_dispatcher=dispatcher or FakeDispatcher(),
        clock=lambda: 1_000_000,
    )


CTX = {"capture_id": "cap1", "sender": "+59891111111", "farmos_person": "santi",
       "text": "harvested 500g", "transcripts": [], "attachment_paths": [],
       "reply_target_kind": "dm", "group_id": None, "captured_at_ms": 1_000_000}


async def test_missing_sender_returns_reason():
    p = _pipeline(FakeDb(), _extractor({"ok": True}))
    res = await p["enqueue"]({"capture_id": "c"})
    assert res == {"ok": False, "reason": "missing_sender_or_capture_id"}


async def test_clean_draft_inserts_and_lands_awaiting_farmer():
    db = FakeDb()
    d = FakeDispatcher()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), d)
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
    assert res["status"] == "awaiting_farmer"
    assert res["continuity"] == "start_new"
    assert db.inserted[0]["status"] == "pending"
    assert db.inserted[0]["source_capture_ids"] == ["cap1"]
    assert ("handoff_to_phase_39", pytest.approx) or d.calls[0][0] == "handoff_to_phase_39"


async def test_extractor_failure_returns_reason_and_writes_nothing():
    db = FakeDb()
    p = _pipeline(db, _extractor({"ok": False, "reason": "schema_invalid"}))
    res = await p["enqueue"](CTX)
    assert res == {"ok": False, "reason": "schema_invalid"}
    assert db.inserted == []


async def test_extractor_raising_is_caught():
    db = FakeDb()

    async def boom(**kw):
        raise RuntimeError("anthropic down")

    p = _pipeline(db, {"extract": boom})
    res = await p["enqueue"](CTX)
    assert res["ok"] is False
    assert db.inserted == []


async def test_append_continuity_updates_existing_draft():
    db = FakeDb(in_flight={"id": "existing", "source_capture_ids": ["cap0"],
                           "askback_turns": 1, "updated_at": None})
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "append",
        "usage": None,
    }))
    res = await p["enqueue"](CTX)
    assert res["draft_id"] == "existing"
    assert res["continuity"] == "append"
    assert db.inserted == []


async def test_idle_gap_forces_start_new_over_llm_append():
    # in-flight last updated 31 minutes before now -> LLM 'append' is overridden.
    now = 1_000_000
    db = FakeDb(in_flight={"id": "old", "source_capture_ids": ["cap0"],
                           "askback_turns": 0,
                           "updated_at_ms": now - 31 * 60 * 1000})
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "append",
        "usage": None,
    }))
    res = await p["enqueue"](CTX)
    assert res["continuity"] == "start_new"
    assert db.inserted != []
    assert ("old", "expired", {}) in [(a, b, c) for a, b, c in db.updates]


async def test_ask_back_path_builds_preview_and_bumps_turn():
    db = FakeDb()
    d = FakeDispatcher()
    dirty = dict(CLEAN)
    del dirty["qty_g"]
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": dirty, "per_field_confidence": {}}],
        "draft": dirty, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), d)
    res = await p["enqueue"](CTX)
    assert res["side_effects"] == ["send_ask_back"]
    _, _, extras = db.updates[-1]
    assert extras["farmer_facing_preview"]
    assert db.bumps == [res["draft_id"]]
    assert d.calls[0][0] == "send_ask_back"


async def test_insert_conflict_returns_reason():
    db = FakeDb()

    async def conflict(pool, row):
        return {"ok": False, "reason": "in_flight_conflict"}

    db.insert_draft = conflict
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }))
    res = await p["enqueue"](CTX)
    assert res == {"ok": False, "reason": "in_flight_conflict"}


async def test_dispatch_failure_does_not_fail_enqueue():
    class BadDispatcher:
        async def dispatch(self, effect, row):
            raise RuntimeError("signal down")

    db = FakeDb()
    p = _pipeline(db, _extractor({
        "ok": True, "drafts": [{"draft": CLEAN, "per_field_confidence": {}}],
        "draft": CLEAN, "per_field_confidence": {}, "continuity_decision": "start_new",
        "usage": None,
    }), BadDispatcher())
    res = await p["enqueue"](CTX)
    assert res["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Follow pipeline.js:289-791 step by step. The ordered sequence, with the Node line range for each:

1. Guard `sender` and `capture_id` (293-296).
2. In-flight lookup; on exception return `{"ok": False, "reason": str(e)}` (298-306).
3. Normalize `updated_at` to `last_updated_at_ms` for the FSM helpers (308-316). Accept `datetime`, ISO string, or `None`.
4. `force_start_new_if_idle`; `treat_in_flight = None` when forced (318-324).
5. **Load image blocks before calling the extractor** (326-333). This is the 2026-05-12 Node bug fix: `attachment_paths` are filesystem paths, but the multimodal layer expects `{data, media_type}` base64 blocks. Pass raw paths and every image is silently skipped, Claude sees an empty prompt, and extraction returns `schema_invalid`. Reuse `farm_agent/extraction/multimodal.py` rather than re-implementing.
6. Call `extractor["extract"]`; catch exceptions; return early on `ok: False` (334-352).
7. Usage stamp onto `signal_capture` (354-380): best-effort `UPDATE signal_capture SET input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, model WHERE id = %s`. Skipped when `usage` is falsy. Failure is logged and swallowed.
8. Multi-draft routing (382-393) — **stub in this task**: `if len(drafts) > 1: return await self._route_multi(...)` where `_route_multi` raises `NotImplementedError`. Task 6 replaces it. Add a test asserting the single-draft path is unaffected.
9. Resolve continuity (494-520): `append`/`replace` reuse the in-flight id and its `askback_turns`; `start_new` computes a fresh id from `[capture_id]`.
10. Expire the prior in-flight when starting new and the id differs (515-525).
11. Persist: update on `append`/`replace` (530-560, including the separate `source_capture_ids` UPDATE — the extras whitelist excludes arrays), insert on `start_new` (562-580).
12. Starting-seq short-circuit (582-672) — **stub in this task**, filled by Task 7.
13. FSM transition (674-690).
14. Status update with extras; build the preview when the transition includes `send_ask_back` or `send_needs_review_ping`; set `needs_review_reason='askback_cap_exceeded'` when `reason == 'askback_cap'` (692-725).
15. Bump `askback_turns` when `send_ask_back` fired (727-733).
16. Build `draft_row` and dispatch each side effect in its own try/except (735-760).

Everything after the extractor call is fail-soft: a failed dispatch or a failed usage stamp logs a warning and the function still returns `{"ok": True, ...}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_extraction_pipeline.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/farm-agent/farm_agent/extraction/pipeline.py src/farm-agent/tests/extraction/test_extraction_pipeline.py
git commit -m "feat(port): extraction enqueue orchestrator [MUSHY-76]"
```

---

### Task 6: `batch_mode.py` — multi-draft pages

Ports `pipeline.js` lines 182-288 (`runBatchMode`) and 393-493 (the small-N `multi_confirm` fan-out), replacing the Task 5 stub.

**Files:**
- Create: `farm_agent/extraction/batch_mode.py`
- Modify: `farm_agent/extraction/pipeline.py` (replace the `_route_multi` stub)
- Test: `tests/extraction/test_batch_mode.py`

**Interfaces:**
- Consumes: `extraction_db`, `state_machine`, `preview_builder`, the dispatcher, and `pipeline._should_batch_review` / `_min_leaf_confidence` (Task 5).
- Produces:
```python
async def run_batch_mode(*, drafts_arr, capture_ctx, sender, capture_id,
                         source_capture_ids_base, now_ms, in_flight,
                         pool, extraction_db, state_machine, preview_builder,
                         outbound_dispatcher, config, log) -> dict
# -> {"ok": True, "mode": "batch", "count": int, "draft_ids": [...]}

async def run_multi_confirm(*, drafts_arr, capture_ctx, sender, capture_id,
                            now_ms, in_flight, pool, extraction_db, state_machine,
                            preview_builder, outbound_dispatcher, config, log) -> dict
# -> {"ok": True, "mode": "multi_confirm", "count": int, "draft_ids": [...], "side_effects": [...]}
```

Routing rule (pipeline.js:395-407): with more than one draft, go to `run_batch_mode` when `_should_batch_review(drafts_arr)` is true **or** any draft has `type == 'seeding_session'`; otherwise `run_multi_confirm`. `_should_batch_review` is `len(drafts) > 5 or _min_leaf_confidence(drafts) < 0.7`.

- [ ] **Step 1: Write the failing tests**

The regression to protect is subtle and cost a real page of data in Node: a clean batch draft routed to `awaiting_farmer` occupies the per-sender in-flight slot, so every sibling insert on the same page fails with `in_flight_conflict` and all but the first entry is silently dropped.

```python
"""Batch mode and small-N fan-out. Guards the 2026-05-25 in-flight-slot regression."""

import pytest

from farm_agent.extraction.batch_mode import run_batch_mode, run_multi_confirm
from farm_agent.extraction import preview_builder, state_machine


class RealisticDb:
    """Enforces the D-02c partial unique index: one in-flight draft per sender."""

    def __init__(self):
        self.rows = {}

    def compute_draft_id(self, ids, index=None):
        return "d-" + "|".join(sorted(ids)) + ("" if index in (None, 0) else f"#{index}")

    async def insert_draft(self, pool, row):
        in_flight = [r for r in self.rows.values()
                     if r["sender_e164"] == row["sender_e164"]
                     and r["status"] in ("pending", "awaiting_farmer")]
        if in_flight:
            return {"ok": False, "reason": "in_flight_conflict"}
        self.rows[row["id"]] = dict(row)
        return {"ok": True, "id": row["id"]}

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        if draft_id not in self.rows:
            return {"ok": False, "reason": "not_found"}
        self.rows[draft_id]["status"] = status
        self.rows[draft_id].update(extras or {})
        return {"ok": True, "rowcount": 1}

    async def advance_askback_turn(self, pool, draft_id):
        return {"ok": True, "askback_turns": 1}


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, effect, row):
        self.calls.append((effect, row))
        return {"ok": True}


def _config():
    class C:
        extraction_confidence_threshold = 0.7
        draft_idle_gap_min = 30
        max_askback_turns = 3
    return C()


def _clean(i):
    return {"draft": {"type": "harvest", "harvest_batch_id": f"H{i}", "qty_g": 100,
                      "source_block_refs": [f"b{i}"], "event_timestamp": "t"},
            "per_field_confidence": {}}


CTX = {"farmos_person": "santi", "reply_target_kind": "dm", "group_id": None}


def _kwargs(db, dispatcher, drafts):
    return dict(drafts_arr=drafts, capture_ctx=CTX, sender="+5989", capture_id="cap1",
                now_ms=0, in_flight=None, pool=None, extraction_db=db,
                state_machine=state_machine, preview_builder=preview_builder,
                outbound_dispatcher=dispatcher, config=_config(), log=None)


async def test_batch_mode_persists_every_draft_on_the_page():
    """The regression: all 7 entries must land, not just the first."""
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(i) for i in range(7)]
    res = await run_batch_mode(source_capture_ids_base=["cap1"],
                               **_kwargs(db, d, drafts))
    assert res["count"] == 7
    assert len(db.rows) == 7


async def test_batch_mode_routes_clean_drafts_to_needs_review():
    db, d = RealisticDb(), FakeDispatcher()
    await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, [_clean(0)]))
    row = next(iter(db.rows.values()))
    assert row["status"] == "needs_review"
    assert row["needs_review_reason"] == "batch_mode_clean"


async def test_batch_mode_flags_low_conf_drafts_distinctly():
    db, d = RealisticDb(), FakeDispatcher()
    dirty = {"draft": {"type": "harvest", "harvest_batch_id": "H", "event_timestamp": "t"},
             "per_field_confidence": {}}
    await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, [dirty]))
    row = next(iter(db.rows.values()))
    assert row["status"] == "needs_review"
    assert row["needs_review_reason"] == "batch_mode_low_conf"


async def test_batch_mode_never_asks_the_farmer_back():
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(i) for i in range(3)]
    await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, drafts))
    assert all(effect != "send_ask_back" for effect, _ in d.calls)


async def test_batch_mode_expires_prior_in_flight():
    db, d = RealisticDb(), FakeDispatcher()
    db.rows["old"] = {"id": "old", "sender_e164": "+5989", "status": "awaiting_farmer"}
    kw = _kwargs(db, d, [_clean(0)])
    kw["in_flight"] = {"id": "old"}
    await run_batch_mode(source_capture_ids_base=["cap1"], **kw)
    assert db.rows["old"]["status"] == "expired"


async def test_draft_ids_are_unique_per_index():
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(i) for i in range(3)]
    res = await run_batch_mode(source_capture_ids_base=["cap1"], **_kwargs(db, d, drafts))
    assert len(set(res["draft_ids"])) == 3


async def test_multi_confirm_sends_one_prompt_per_draft():
    db, d = RealisticDb(), FakeDispatcher()
    drafts = [_clean(0), _clean(1)]
    res = await run_multi_confirm(**_kwargs(db, d, drafts))
    assert res["mode"] == "multi_confirm"
    assert res["count"] == 2
```

Note: `test_multi_confirm_sends_one_prompt_per_draft` will expose the Node quirk described below. Run it and see what it does before asserting on dispatch calls; assert on `count` and persisted rows, and record the observed behaviour in the commit message.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_batch_mode.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`run_batch_mode` ports pipeline.js:182-288. Per draft: `compute_draft_id(base, i)`, insert as `pending`, run the FSM with `max_askback_turns=0` to force the needs-review path, then map the result:

```python
next_status = transition.next_status
extras = {}
if transition.reason == "askback_cap":
    extras["needs_review_reason"] = "batch_mode_low_conf"
elif next_status == DraftStatus.AWAITING_FARMER:
    # 2026-05-25: a clean batch draft must NOT sit in awaiting_farmer. It would
    # (1) wait forever for a per-draft YES that batch mode never solicits, and
    # (2) hold the per-sender in-flight slot, so every sibling insert on the
    # same page fails with in_flight_conflict and all but the first entry of a
    # multi-entry page is silently dropped.
    next_status = DraftStatus.NEEDS_REVIEW
    extras["needs_review_reason"] = "batch_mode_clean"
```

Then one `send_batch_review_summary` dispatch for the whole page.

`run_multi_confirm` ports pipeline.js:393-493: expire prior in-flight once, then per draft insert as `pending`, run the FSM with the real `max_askback_turns`, build a preview when needed, update status, dispatch each side effect.

**Known Node quirk — port it, do not fix it.** The `needs_preview` test at pipeline.js:466-468 checks for `send_confirm_prompt`, but the FSM never emits that tag; the clean path emits `handoff_to_phase_39`. So a clean draft in the small-N path gets no preview built and no message sent. Reproduce this faithfully and note it in the commit message; it is part of the wider gap recorded in Task 10's follow-up.

Finally, in `pipeline.py`, replace the `_route_multi` stub with the real routing rule.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/extraction/ -v`
Expected: PASS (whole extraction directory, including Task 5's tests still green)

- [ ] **Step 5: Commit**

```bash
git add src/farm-agent/farm_agent/extraction/batch_mode.py src/farm-agent/farm_agent/extraction/pipeline.py src/farm-agent/tests/extraction/test_batch_mode.py
git commit -m "feat(port): batch mode and small-N confirm fan-out [MUSHY-76]"
```

---

### Task 7: `starting_seq.py` — the SEQ ask-back

Ports `pipeline.js` lines 80-113 (`buildStartingSeqAskBackText`, `parseStartingSeqReply`) and 582-672 (the enqueue short-circuit) and 792-916 (`handleStartingSeqReply`), replacing the Task 5 stub.

**Files:**
- Create: `farm_agent/extraction/starting_seq.py`
- Modify: `farm_agent/extraction/pipeline.py` (replace the starting-seq stub)
- Test: `tests/extraction/test_starting_seq.py`

**Interfaces:**
- Consumes: `farm_agent.extraction.seq_helper.lookup_last_seq_for_date`, `.mint_child_block_names`, `.yyyymmdd_to_yymmdd` (all already ported); `extraction_db.get_draft_by_id` / `.update_draft_status`.
- Produces:
```python
def build_starting_seq_ask_back_text(*, total_children: int, event_date: str,
                                     last_seq: int | None, last_block_name: str | None,
                                     sender_name: str | None) -> str
def parse_starting_seq_reply(reply_text: str) -> dict
    # {"kind": "yes"} | {"kind": "number", "value": int} | {"kind": "unclear"}
async def handle_starting_seq_ask_back(*, draft, draft_id, sender, capture_ctx,
                                       source_capture_ids, prior_askback_turns,
                                       pool, extraction_db, outbound_dispatcher,
                                       log) -> dict
async def handle_starting_seq_reply(*, draft_id, reply_text, capture_ctx,
                                    pool, extraction_db, outbound_dispatcher,
                                    log) -> dict
```

The short-circuit fires only when `draft["type"] == "seeding_session"` and `draft.get("needs_input") == "starting_seq"`.

**B5 SEQ is per-session, not per-strain** — the counter runs across all groups in the session in order, so group 2's first child continues from where group 1 stopped. `mint_child_block_names` already implements this; do not re-derive it.

- [ ] **Step 1: Write the failing tests**

```python
"""starting_seq ask-back: prompt text, reply parsing, per-session SEQ minting."""

import pytest

from farm_agent.extraction.starting_seq import (
    build_starting_seq_ask_back_text,
    handle_starting_seq_reply,
    parse_starting_seq_reply,
)


@pytest.mark.parametrize("text,expected", [
    ("YES", {"kind": "yes"}),
    ("yes", {"kind": "yes"}),
    ("  Yes  ", {"kind": "yes"}),
    ("4", {"kind": "number", "value": 4}),
    ("  12 ", {"kind": "number", "value": 12}),
    ("maybe tomorrow", {"kind": "unclear"}),
    ("", {"kind": "unclear"}),
])
def test_parse_reply(text, expected):
    assert parse_starting_seq_reply(text) == expected


def test_ask_back_text_has_no_em_dash():
    out = build_starting_seq_ask_back_text(
        total_children=11, event_date="20260522", last_seq=3,
        last_block_name="260522_KOY_3", sender_name="Santi")
    assert "—" not in out


def test_ask_back_text_includes_the_hint_when_last_seq_known():
    out = build_starting_seq_ask_back_text(
        total_children=11, event_date="20260522", last_seq=3,
        last_block_name="260522_KOY_3", sender_name=None)
    assert "260522_KOY_3" in out


def test_ask_back_text_survives_unknown_last_seq():
    out = build_starting_seq_ask_back_text(
        total_children=11, event_date="20260522", last_seq=None,
        last_block_name=None, sender_name=None)
    assert isinstance(out, str) and out.strip() != ""


class FakeDb:
    def __init__(self, row):
        self.row = row
        self.updates = []

    async def get_draft_by_id(self, pool, draft_id):
        return self.row

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        self.updates.append((draft_id, status, extras or {}))
        self.row["draft_json"] = (extras or {}).get("draft_json", self.row.get("draft_json"))
        return {"ok": True, "rowcount": 1}


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, effect, row):
        self.calls.append((effect, row))
        return {"ok": True}


def _session_row():
    return {
        "id": "d1", "sender_e164": "+5989", "status": "awaiting_farmer",
        "source_capture_ids": ["cap1"], "reply_target_kind": "dm", "group_id": None,
        "draft_json": {
            "type": "seeding_session", "event_date": "20260522",
            "needs_input": "starting_seq",
            "groups": [
                {"parent": {"value": "P1"}, "species": {"value": "KOY"},
                 "qty": {"value": 2}, "child_block_names": {"value": []}},
                {"parent": {"value": "P2"}, "species": {"value": "KOY"},
                 "qty": {"value": 3}, "child_block_names": {"value": []}},
            ],
        },
    }


async def test_numeric_reply_mints_seq_across_groups():
    """B5: SEQ is per-session. Group 2 continues from group 1, it does not restart."""
    db, d = FakeDb(_session_row()), FakeDispatcher()
    res = await handle_starting_seq_reply(
        draft_id="d1", reply_text="4", capture_ctx={},
        pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert res["ok"] is True
    groups = db.row["draft_json"]["groups"]
    assert [n[-1] for n in groups[0]["child_block_names"]["value"]] == ["4", "5"]
    assert [n[-1] for n in groups[1]["child_block_names"]["value"]] == ["6", "7", "8"]


async def test_reply_clears_needs_input():
    db, d = FakeDb(_session_row()), FakeDispatcher()
    await handle_starting_seq_reply(draft_id="d1", reply_text="4", capture_ctx={},
                                    pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert not db.row["draft_json"].get("needs_input")


async def test_second_reply_is_idempotent_noop():
    row = _session_row()
    row["draft_json"].pop("needs_input")
    db, d = FakeDb(row), FakeDispatcher()
    res = await handle_starting_seq_reply(draft_id="d1", reply_text="YES", capture_ctx={},
                                          pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert res == {"ok": True, "noop": True}
    assert db.updates == []


async def test_unclear_reply_redispatches_askback_without_minting():
    db, d = FakeDb(_session_row()), FakeDispatcher()
    res = await handle_starting_seq_reply(draft_id="d1", reply_text="dunno", capture_ctx={},
                                          pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert db.row["draft_json"]["groups"][0]["child_block_names"]["value"] == []
    assert any("askback" in effect for effect, _ in d.calls)


async def test_missing_draft_returns_reason():
    db, d = FakeDb(None), FakeDispatcher()
    res = await handle_starting_seq_reply(draft_id="nope", reply_text="4", capture_ctx={},
                                          pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert res["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/extraction/test_starting_seq.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`handle_starting_seq_ask_back` ports pipeline.js:591-671: look up the last SEQ for the date (wrapped in try/except — a lookup failure degrades to `last_seq=None`, it does not fail the ask-back), sum the group quantities, build the `last_block_name` hint as `f"{yyyymmdd_to_yymmdd(event_date)}_{first_species}_{last_seq}"` when both are available, render the prompt, persist `awaiting_farmer` with `farmer_facing_preview`, dispatch `send_starting_seq_askback`, and return early.

`handle_starting_seq_reply` ports pipeline.js:792-916: parse the reply; on `unclear` re-dispatch a clarifying ask-back and mint nothing; on `yes` use the default; on `number` use that value. Walk `groups` in order consuming one running counter, set `child_block_names.value` per group, leave `.confidence` untouched, set `.sources` to `["model_inference", "text"]`, clear `needs_input`, persist `draft_json`, and dispatch `send_seeding_session_filled_preview`.

Idempotency: a second reply on a draft whose `needs_input` is already cleared returns `{"ok": True, "noop": True}` without re-minting.

Then wire the short-circuit into `pipeline.py` at the point where Task 5 left the stub (after persist, before the FSM transition).

Add these two tags to the Task 4 dispatcher's match statement: `send_starting_seq_askback` and `send_seeding_session_filled_preview`, both sending `draft_row["farmer_facing_preview"]` to the ask-back target, same as `send_ask_back`. Extend `tests/extraction/test_extraction_outbound.py` with a case for each.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/extraction/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/farm-agent/farm_agent/extraction/starting_seq.py src/farm-agent/farm_agent/extraction/pipeline.py src/farm-agent/farm_agent/extraction/outbound.py src/farm-agent/tests/extraction/
git commit -m "feat(port): starting_seq ask-back and per-session SEQ minting [MUSHY-76]"
```

---

### Task 8: `confirm/preview.py` + `confirm/edit_handler.py`

Ports `src/agents/alerter/src/confirm/preview.js` (68 lines) and `src/agents/alerter/src/confirm/edit-handler.js` (165 lines), and replaces the Phase 61 stub at `farm_agent/confirm/dispatch.py:401`.

**Heads-up for the implementer:** the Python confirm loop currently invents its own farmer copy inline instead of using the ported renderers. `dispatch.py:139` sends `"Got it! Your answer was recorded."` where Node sends `"Locked in. Writing now. (draft abc123)"`; `watchdog.py:108` sends `"Reminder: you have a pending entry waiting for confirmation."` where Node sends `"Still want to lock in this draft? Reply YES / NO / EDIT or it auto-expires in N min."`. This task replaces those inline strings with the ported functions, which means existing tests asserting the invented copy will fail and must be updated to the Node text. That is the point of the task, not a regression.

**Files:**
- Create: `farm_agent/confirm/preview.py`
- Create: `farm_agent/confirm/edit_handler.py`
- Modify: `farm_agent/confirm/dispatch.py` (remove `_run_edit_reextraction_stub`, use the real handler and the ported copy)
- Modify: `farm_agent/confirm/watchdog.py:108-111` (use `build_nudge`), `:160-ish` (use `build_expired_note`)
- Test: `tests/confirm/test_confirm_preview.py`, `tests/confirm/test_edit_handler.py`
- Update: existing tests in `tests/confirm/` that assert the invented copy

**Interfaces:**
- Consumes: `extraction.preview_builder.sanitize_farmer_text` / `.build_preview` (Task 3); `extraction.state_machine.REQUIRED_FIELDS` (Task 2); `extraction_db` (Task 1); the extractor dict.
- Produces:
```python
# confirm/preview.py
def build_preview_with_suffix(*, draft, per_field_confidence, required_fields, threshold) -> str
def build_confirm_ack(draft_id: str) -> str
def build_idempotent_ack() -> str
def build_discard_ack() -> str
def build_edit_cap_msg(max_edit_turns: int) -> str
def build_nudge(*, minutes_remaining=None, preview_summary=None) -> str
def build_expired_note() -> str

# confirm/edit_handler.py
def create_edit_handler(*, pool, extractor, confirm_repo, extraction_db,
                        config, log=None) -> dict
async def handle_edit(draft_row: dict, edit_text: str) -> dict
    # {"ok": True, "side_effect": "send_preview_resend", "new_preview": str}
    # | {"ok": False, "reason": str}
```

Exact Node copy, to be reproduced character for character:

| Function | String |
|---|---|
| `build_confirm_ack` | `Locked in. Writing now. (draft {id[:10]})` |
| `build_idempotent_ack` | `Already locked in. Check the previous message.` |
| `build_discard_ack` | `Discarded. Nothing written.` |
| `build_edit_cap_msg` | `I cannot get this right after {fmt_num(n)} tries. Try splitting the message into smaller updates, or send NO to discard.` |
| `build_nudge` | `Still want to lock in this draft? Reply YES / NO / EDIT or it auto-expires in {fmt_num(mins)} min.` (plus `\n{preview_summary}` when non-empty) |
| `build_expired_note` | `Draft expired. Nothing was written. Send a fresh message if you still want to log this.` |
| `REPLY_SUFFIX` | `\n\nReply YES to commit, NO to discard, EDIT <text> to amend.` |

- [ ] **Step 1: Write the failing tests**

```python
"""Confirm-loop farmer copy. Exact strings; these are what the farmer reads."""

import pytest

from farm_agent.confirm.preview import (
    build_confirm_ack,
    build_discard_ack,
    build_edit_cap_msg,
    build_expired_note,
    build_idempotent_ack,
    build_nudge,
    build_preview_with_suffix,
)


def test_confirm_ack_truncates_draft_id_to_10():
    assert build_confirm_ack("a" * 64) == "Locked in. Writing now. (draft " + "a" * 10 + ")"


def test_idempotent_ack():
    assert build_idempotent_ack() == "Already locked in. Check the previous message."


def test_discard_ack():
    assert build_discard_ack() == "Discarded. Nothing written."


def test_nudge_rounds_minutes():
    out = build_nudge(minutes_remaining=6.4)
    assert "6 min" in out


def test_nudge_clamps_negative_to_zero():
    assert "0 min" in build_nudge(minutes_remaining=-5)


def test_nudge_handles_missing_minutes():
    assert "0 min" in build_nudge()


def test_nudge_appends_preview_summary():
    out = build_nudge(minutes_remaining=6, preview_summary="harvest 500 g")
    assert out.endswith("harvest 500 g")


def test_nudge_ignores_blank_preview_summary():
    out = build_nudge(minutes_remaining=6, preview_summary="   ")
    assert out.rstrip().endswith("min.")


def test_expired_note():
    assert build_expired_note() == (
        "Draft expired. Nothing was written. Send a fresh message if you still want to log this."
    )


def test_preview_with_suffix_strips_question_markers():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "t"}
    out = build_preview_with_suffix(draft=draft, per_field_confidence={"qty_g": 0.1},
                                    required_fields=["qty_g"], threshold=0.7)
    assert "[?]" not in out
    assert out.endswith("Reply YES to commit, NO to discard, EDIT <text> to amend.")


@pytest.mark.parametrize("fn,args", [
    (build_confirm_ack, ("x" * 12,)),
    (build_idempotent_ack, ()),
    (build_discard_ack, ()),
    (build_expired_note, ()),
])
def test_no_em_dashes_anywhere(fn, args):
    assert "—" not in fn(*args)
```

And for the edit handler:

```python
"""EDIT re-extraction. Replaces the Phase 61 stub -- a farmer correction must land."""

import pytest

from farm_agent.confirm.edit_handler import create_edit_handler


class FakeConfirmRepo:
    def __init__(self, bump_ok=True):
        self.bumped = []
        self.bump_ok = bump_ok

    async def bump_edit_turn(self, pool, draft_id):
        self.bumped.append(draft_id)
        return {"ok": self.bump_ok, "edit_turn_count": 1}


class FakeExtractionDb:
    def __init__(self):
        self.updates = []

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        self.updates.append((draft_id, status, extras or {}))
        return {"ok": True, "rowcount": 1}


CORRECTED = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 750,
             "source_block_refs": ["b1"], "event_timestamp": "t"}


def _extractor(result):
    calls = []

    async def extract(captures, in_flight_draft=None, corpus_context=None,
                      farmer_correction=None):
        calls.append(farmer_correction)
        return result

    return {"extract": extract}, calls


def _config():
    class C:
        extraction_confidence_threshold = 0.7
        max_edit_turns = 3
    return C()


ROW = {"id": "d1", "sender_e164": "+5989", "status": "awaiting_farmer",
       "source_capture_ids": ["cap1"], "draft_json": {"type": "harvest", "qty_g": 500},
       "edit_turn_count": 0, "reply_target_kind": "dm", "group_id": None}


async def test_edit_passes_the_correction_to_the_extractor():
    ex, calls = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                            "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "no it was 750 grams")
    assert res["ok"] is True
    assert calls[0] == "no it was 750 grams"


async def test_edit_updates_draft_in_place_same_id():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    db = FakeExtractionDb()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=db, config=_config())
    await h["handle_edit"](ROW, "750 grams")
    draft_id, status, extras = db.updates[-1]
    assert draft_id == "d1"
    assert extras["draft_json"]["qty_g"] == 750


async def test_edit_returns_preview_resend_with_new_preview():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["side_effect"] == "send_preview_resend"
    assert "750" in res["new_preview"]


async def test_edit_bumps_the_turn_counter():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {},
                        "drafts": [{"draft": CORRECTED, "per_field_confidence": {}}]})
    repo = FakeConfirmRepo()
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=repo,
                            extraction_db=FakeExtractionDb(), config=_config())
    await h["handle_edit"](ROW, "750 grams")
    assert repo.bumped == ["d1"]


async def test_edit_extractor_failure_returns_reason_not_silence():
    ex, _ = _extractor({"ok": False, "reason": "schema_invalid"})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "750 grams")
    assert res["ok"] is False
    assert res["reason"] == "schema_invalid"


async def test_edit_no_draft_row():
    ex, _ = _extractor({"ok": True, "draft": CORRECTED, "per_field_confidence": {}})
    h = create_edit_handler(pool=None, extractor=ex, confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](None, "text")
    assert res == {"ok": False, "reason": "no_draft_row"}


async def test_edit_never_raises():
    async def boom(**kw):
        raise RuntimeError("down")

    h = create_edit_handler(pool=None, extractor={"extract": boom},
                            confirm_repo=FakeConfirmRepo(),
                            extraction_db=FakeExtractionDb(), config=_config())
    res = await h["handle_edit"](ROW, "text")
    assert res["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/confirm/test_confirm_preview.py tests/confirm/test_edit_handler.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`confirm/preview.py` ports preview.js:10-58. `build_preview_with_suffix` calls the extraction `build_preview`, strips `[?]` markers with `re.sub(r"\s*\[\?\]", "", body)` (by `awaiting_farmer` time every field has cleared the threshold), appends `REPLY_SUFFIX`, and sanitizes.

`confirm/edit_handler.py` ports edit-handler.js:12-165: bump `edit_turn_count`, re-extract with the farmer's correction as `farmer_correction`, update the draft in place (same id, same `source_capture_ids`), re-render the preview via `build_preview_with_suffix`, return `{"ok": True, "side_effect": "send_preview_resend", "new_preview": ...}`. Note edit-handler.js:55-67 accepts a `commit_failed` draft and transitions it back to `awaiting_farmer` — port that branch, including the lost-race log at line 66.

Then in `dispatch.py`: delete `_run_edit_reextraction_stub`, call the real handler where the FSM emits `run_edit_reextraction`, and replace the four inline ack strings with `build_confirm_ack` / `build_idempotent_ack` / `build_discard_ack` / `build_edit_cap_msg`. In `watchdog.py` replace the inline nudge and expired bodies with `build_nudge` / `build_expired_note`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/farm-agent && uv run pytest tests/confirm/ -v`
Expected: PASS. Existing tests asserting the invented copy will fail first — update them to the Node strings, and treat any failure that is NOT about copy as a real regression.

- [ ] **Step 5: Commit**

```bash
git add src/farm-agent/farm_agent/confirm/ src/farm-agent/tests/confirm/
git commit -m "feat(port): confirm preview copy and real EDIT re-extraction [MUSHY-76]

Replaces the Phase 61 edit-reextraction stub, which logged a line and
dropped the farmer's correction. Also replaces invented ack copy with the
ported Node strings so the farmer reads the same text after cutover."
```

---

### Task 9: Config, boot wiring, and the capture seam

This is the task that makes the previous eight reachable from production.

**Files:**
- Modify: `farm_agent/tenancy/tenant.py` (three new fields)
- Modify: `farm_agent/capture/pipeline.py:130-140` (parameter), `:269-296` (gate + last_bot), `:326-350` (enqueue seam)
- Modify: `farm_agent/boot.py:105-110`
- Modify: `/docker-compose.override.yml` (alerter-py env block, repo root)
- Test: `tests/test_capture_extraction_seam.py`, plus additions to `tests/test_tenancy.py` and `tests/test_boot.py`

**Interfaces:**
- Consumes: `create_extraction_pipeline` (Task 5).
- Produces: `TenantConfig.extraction_confidence_threshold: float`, `.draft_idle_gap_min: int`, `.max_askback_turns: int`; `create_capture_pipeline(..., extraction_pipeline=None)` replacing the unused `extractor` parameter.

- [ ] **Step 1: Write the failing tests**

```python
"""The seam: capture -> gate -> enqueue. This is what was missing (MUSHY-76)."""

import pytest

from farm_agent.capture.pipeline import create_capture_pipeline
from farm_agent.tenancy.tenant import load as load_config
from tests.conftest import TEST_ENV


class FakeExtractionPipeline:
    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    async def enqueue(self, ctx):
        self.calls.append(ctx)
        if self.raises:
            raise self.raises
        return {"ok": True, "draft_id": "d1"}


class FakeSignalClient:
    async def fetch_attachment(self, att_id):
        return b""


def _gate(allow_extract=True):
    seen = []

    async def classify(env_ctx, last_bot_outbound, now_ms):
        seen.append((env_ctx, last_bot_outbound, now_ms))
        return {"gate": "event", "allow_extract": allow_extract, "allow_convo": True}

    return {"classify": classify}, seen


class FakeRepo:
    async def insert_capture(self, pool, row):
        return {"ok": True}


def _envelope(sender="+59891111111", text="harvested 500g"):
    return {"envelope": {"source": sender, "dataMessage": {
        "message": text, "timestamp": 1_700_000_000_000, "attachments": []}}}


def _config():
    return load_config(dict(TEST_ENV, SIGNAL_SENDER="+10000000000"))


async def test_config_defaults():
    c = _config()
    assert c.extraction_confidence_threshold == 0.7
    assert c.draft_idle_gap_min == 30
    assert c.max_askback_turns == 3


async def test_config_clamps_out_of_range_threshold():
    c = load_config(dict(TEST_ENV, EXTRACTION_CONFIDENCE_THRESHOLD="4.2"))
    assert c.extraction_confidence_threshold == 0.7


async def test_known_farmer_reaches_enqueue():
    xp = FakeExtractionPipeline()
    gate, _ = _gate(allow_extract=True)
    p = create_capture_pipeline(
        None, FakeSignalClient(), {"transcribe": None}, _config(),
        capture_repo=FakeRepo(), gate=gate, extraction_pipeline=xp)
    await p["handle"](_envelope())
    assert len(xp.calls) == 1
    ctx = xp.calls[0]
    assert ctx["capture_id"]
    assert ctx["sender"] == "+59891111111"
    assert ctx["text"] == "harvested 500g"


async def test_gate_denial_blocks_enqueue():
    xp = FakeExtractionPipeline()
    gate, _ = _gate(allow_extract=False)
    p = create_capture_pipeline(
        None, FakeSignalClient(), {"transcribe": None}, _config(),
        capture_repo=FakeRepo(), gate=gate, extraction_pipeline=xp)
    await p["handle"](_envelope())
    assert xp.calls == []


async def test_unknown_farmer_blocks_enqueue():
    xp = FakeExtractionPipeline()
    gate, _ = _gate(allow_extract=True)
    p = create_capture_pipeline(
        None, FakeSignalClient(), {"transcribe": None}, _config(),
        capture_repo=FakeRepo(), gate=gate, extraction_pipeline=xp)
    await p["handle"](_envelope(sender="+19999999999"))   # not in the farmer map
    assert xp.calls == []


async def test_enqueue_failure_never_breaks_capture():
    xp = FakeExtractionPipeline(raises=RuntimeError("extraction down"))
    gate, _ = _gate()
    p = create_capture_pipeline(
        None, FakeSignalClient(), {"transcribe": None}, _config(),
        capture_repo=FakeRepo(), gate=gate, extraction_pipeline=xp)
    result = await p["handle"](_envelope())
    assert result is not None
    assert result["capture_id"]


async def test_last_bot_outbound_is_passed_to_the_gate():
    """Closes TODO(Phase 60) at capture/pipeline.py:280."""
    gate, seen = _gate()
    p = create_capture_pipeline(
        None, FakeSignalClient(), {"transcribe": None}, _config(),
        capture_repo=FakeRepo(), gate=gate, extraction_pipeline=FakeExtractionPipeline())
    await p["handle"](_envelope())
    _, last_bot, _ = seen[0]
    # None is acceptable (no recent outbound in this fixture); the point is that
    # the argument is now sourced, not hard-coded.
    assert len(seen) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/farm-agent && uv run pytest tests/test_capture_extraction_seam.py -v`
Expected: FAIL — `TypeError: create_capture_pipeline() got an unexpected keyword argument 'extraction_pipeline'`

- [ ] **Step 3: Write the implementation**

**Config** (`tenancy/tenant.py`): add the three fields to the dataclass and to `load()`. Node clamps the threshold and warns on an out-of-range override (config.js:194-196); mirror that. Follow the existing `_parse_int_env` / `_pick` patterns in the file.

```python
extraction_confidence_threshold: float   # EXTRACTION_CONFIDENCE_THRESHOLD, 0.7, clamped [0,1]
draft_idle_gap_min: int                  # DRAFT_IDLE_GAP_MIN, 30
max_askback_turns: int                   # MAX_ASKBACK_TURNS, 3
```

**Capture pipeline** (`capture/pipeline.py`): replace the unused `extractor: dict | None = None` parameter with `extraction_pipeline=None`, and update the docstring. In the gate block, source `last_bot_outbound` before calling the gate, closing the `TODO(Phase 60)` at line 280:

```python
neg_since_ms = captured_at_ms - 30 * 60 * 1000
try:
    recent_out = await capture_history.select_recent_outbound_by_recipient(
        pool, source, neg_since_ms
    )
except Exception:  # noqa: BLE001 -- gate input is best-effort
    recent_out = []
last_bot = recent_out[-1] if recent_out else None
```

Check the real signature of `select_recent_outbound_by_recipient` in `farm_agent/capture/capture_history.py` and match it. Exactly one call per capture.

After the `insert_capture` block, add the enqueue seam, porting capture.js:205-222:

```python
# MUSHY-76: fire-and-forget extraction enqueue. Gated on the event-gate's
# allow_extract AND on a resolved farmer slug -- '(unassigned)' means we do not
# know who sent it, and an unattributed draft cannot be confirmed by anyone.
if (
    gate_allow_extract
    and extraction_pipeline is not None
    and farmos_person
    and farmos_person != "(unassigned)"
):
    try:
        await extraction_pipeline.enqueue({
            "capture_id": capture_id,
            "sender": source,
            "farmos_person": farmos_person,
            "text": text,
            "transcripts": [transcript] if transcript else [],
            "attachment_paths": attachment_paths,
            "reply_target_kind": reply_target_kind,
            "group_id": group_id,
            "captured_at_ms": captured_at_ms,
            "corpus_context": None,   # live captures never set this (T-58-03-04)
        })
    except Exception as exc:  # noqa: BLE001 -- extraction never breaks capture
        _log.warning(
            "[capture] extraction enqueue failed: sender=%s err=%s",
            mask_number(source), exc,
        )
```

`gate_allow_extract` defaults to `True` when the gate is absent or errors — the gate is fail-open, matching capture.js:186-190.

**Boot** (`boot.py`): after `create_extractor`, build the dispatcher and the pipeline, then pass the pipeline down.

```python
extractor = create_extractor(client=anthropic_client)
extraction_outbound = create_outbound_dispatcher(
    signal_client=signal_client,
    config=config,
    preview_builder=preview_builder,
    operator_recipient=config.signal_recipient,
)
extraction_pipeline = create_extraction_pipeline(
    pool=pool, extractor=extractor, config=config,
    outbound_dispatcher=extraction_outbound,
)
pipeline = create_capture_pipeline(
    pool, signal_client, transcribe_client, config,
    gate=gate, extraction_pipeline=extraction_pipeline,
)
```

Add `log.info("extraction pipeline live")` alongside the existing lifecycle lines. Never log config fields.

**Compose** (`/docker-compose.override.yml`, repo root): add to the `alerter-py` environment block, using the same `${VAR:-default}` form as the Node `alerter` block so one `.env` value moves both agents:

```yaml
      - EXTRACTION_CONFIDENCE_THRESHOLD=${EXTRACTION_CONFIDENCE_THRESHOLD:-0.7}
      - DRAFT_IDLE_GAP_MIN=${DRAFT_IDLE_GAP_MIN:-30}
      - MAX_ASKBACK_TURNS=${MAX_ASKBACK_TURNS:-3}
```

Use the `- KEY=${VAR:-default}` list form, not the object form: compose v2.40 silently drops `env_file` object form, and this repo standardises on the list form.

- [ ] **Step 4: Run the full suite**

Run: `cd src/farm-agent && uv run pytest -v`
Expected: PASS. Baseline before this phase was 842 passed / 36 skipped / 0 failed; the count is now higher. Zero failures is the gate.

- [ ] **Step 5: Verify the import contract**

Run: `cd src/farm-agent && uv run lint-imports`
Expected: `1 kept, 0 broken`

- [ ] **Step 6: Commit**

```bash
git add src/farm-agent/farm_agent/tenancy/tenant.py src/farm-agent/farm_agent/capture/pipeline.py src/farm-agent/farm_agent/boot.py src/farm-agent/tests/ docker-compose.override.yml
git commit -m "feat(port): wire the extraction pipeline into capture and boot [MUSHY-76]

Replaces the unused extractor parameter on create_capture_pipeline with
the extraction pipeline, and closes TODO(Phase 60) by sourcing
last_bot_outbound for the gate. The Python agent can now create a draft."
```

---

### Task 10: Live-fire ship-gate

Hermetic tests prove the wiring; this proves the whole path against the real model and a real database. Mirrors the existing `tests/test_gate_live_fire.py` pattern.

**Files:**
- Create: `tests/test_extraction_write_path_live_fire.py`
- Modify: `pyproject.toml` (marker documentation)
- Create: `.planning/phases/64-extraction-write-path/64-VERIFICATION.md`

**Interfaces:**
- Consumes: everything from Tasks 1-9.
- Produces: nothing importable.

- [ ] **Step 1: Confirm the throwaway database**

The suite already uses a throwaway postgres on port **5434** via `TEST_TIMESCALE_PORT` in `tests/conftest.py` — use it. Do not point this test at the shared TimescaleDB: any draft that reaches `confirmed` there is picked up by the live Node commit watchdog and written to production farmOS.

Run: `cd src/farm-agent && uv run pytest tests/test_persistence.py -v`
Expected: PASS, confirming the throwaway database is up and migrated. If it is not running, start it before continuing.

- [ ] **Step 2: Write the live-fire test**

```python
"""
Real-Sonnet, real-DB ship-gate for the extraction write path (MUSHY-76).

Skipped by default. NEVER runs in CI. Requires:
    ANTHROPIC_API_KEY=...  EXTRACTION_LIVE_FIRE=1

Runs the real 2026-05-22 session (audio transcript + downscaled photo + text
follow-up) end-to-end and asserts a real signal_draft row lands.

Writes to the throwaway postgres on :5434 ONLY. Against the shared
TimescaleDB, a confirmed draft is picked up by the live Node commit watchdog
and written to production farmOS.
"""

import os

import anthropic
import pytest

from farm_agent.extraction.extractor import create_extractor
from farm_agent.extraction.outbound import create_outbound_dispatcher
from farm_agent.extraction.pipeline import create_extraction_pipeline
from farm_agent.extraction import preview_builder

pytestmark = [
    pytest.mark.live_fire,
    pytest.mark.skipif(
        not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("EXTRACTION_LIVE_FIRE") == "1"),
        reason="live-fire: set ANTHROPIC_API_KEY and EXTRACTION_LIVE_FIRE=1",
    ),
]

FIXTURE_DIR = "tests/fixtures/may22"


class RecordingSignalClient:
    def __init__(self):
        self.sent = []

    async def send(self, body, **kwargs):
        self.sent.append((body, kwargs))
        return {"ok": True}


async def test_may22_session_lands_a_real_draft(pool, tenant_config):
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=2)
    signal_client = RecordingSignalClient()
    try:
        pipeline = create_extraction_pipeline(
            pool=pool,
            extractor=create_extractor(client=client),
            config=tenant_config,
            outbound_dispatcher=create_outbound_dispatcher(
                signal_client=signal_client, config=tenant_config,
                preview_builder=preview_builder, operator_recipient=None,
            ),
        )
        res = await pipeline["enqueue"]({
            "capture_id": "live-fire-may22",
            "sender": tenant_config.signal_recipient,
            "farmos_person": "santi",
            "text": None,
            "transcripts": [open(f"{FIXTURE_DIR}/transcript.txt").read()],
            "attachment_paths": [f"{FIXTURE_DIR}/page.jpg"],
            "reply_target_kind": "dm",
            "group_id": None,
            "captured_at_ms": 1_747_900_000_000,
            "corpus_context": None,
        })

        assert res["ok"] is True, res

        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, status, log_type, origin, farmer_facing_preview, draft_json "
                "FROM signal_draft WHERE %s = ANY(source_capture_ids)",
                ("live-fire-may22",),
            )
            rows = await cur.fetchall()

        assert len(rows) >= 1, "no signal_draft row was created -- MUSHY-76 is not fixed"
        row = rows[0]
        assert row[3] == "python", "origin must be 'python' or the Node watchdog commits it"
        assert row[2] == "seeding_session"
        assert row[1] in ("awaiting_farmer", "pending", "needs_review")
        print(f"\nstatus={row[1]} log_type={row[2]} origin={row[3]}")
        print(f"preview:\n{row[4]}")
    finally:
        await client.close()
```

Add a `tenant_config` fixture to `tests/conftest.py` if one does not already exist (`load(TEST_ENV)`).

- [ ] **Step 3: Source the fixture**

The real 2026-05-22 session already exists in the repo — Phase 60's `test_extraction_live_fire.py` uses it. Find its path (`grep -rn "may22\|05-22\|2026-05-22" tests/`) and reuse it rather than copying files. Update `FIXTURE_DIR` to match.

- [ ] **Step 4: Verify it skips cleanly by default**

Run: `cd src/farm-agent && uv run pytest tests/test_extraction_write_path_live_fire.py -v`
Expected: SKIPPED (1), reason `live-fire: set ANTHROPIC_API_KEY and EXTRACTION_LIVE_FIRE=1`

- [ ] **Step 5: Run it for real**

This costs real Sonnet tokens. Run once, deliberately:

```bash
cd src/farm-agent && EXTRACTION_LIVE_FIRE=1 uv run pytest tests/test_extraction_write_path_live_fire.py -v -s
```

Expected: PASS, with the preview printed. **Save the full output** to `.planning/phases/64-extraction-write-path/64-VERIFICATION.md` — never overwrite paid-API results, and the preview text is the artifact worth keeping.

If it fails, do not weaken the assertions. A failure here is the phase failing, which is exactly what the gate is for.

- [ ] **Step 6: Update the marker documentation**

In `pyproject.toml`, the `live_fire` marker description already names `EXTRACTION_LIVE_FIRE`. Confirm it still reads correctly with this second consumer and adjust the wording if not.

- [ ] **Step 7: Full suite + lint**

```bash
cd src/farm-agent && uv run pytest -v && uv run ruff check farm_agent/ && uv run lint-imports
```
Expected: 0 failures, 0 ruff findings, `1 kept, 0 broken`

- [ ] **Step 8: Commit**

```bash
git add src/farm-agent/tests/test_extraction_write_path_live_fire.py src/farm-agent/pyproject.toml .planning/phases/64-extraction-write-path/64-VERIFICATION.md
git commit -m "test(port): real-session live-fire ship-gate for the write path [MUSHY-76]"
```

- [ ] **Step 9: File the follow-up tickets**

Three things this phase deliberately did not fix. File each in Plane against the MUSHY project, referencing MUSHY-76:

1. **A cleanly-extracted draft is never announced to the farmer.** The FSM emits `handoff_to_phase_39` for a clean draft and the dispatcher treats it as a no-send, so the farmer's first and only contact is the confirm watchdog's nudge: "Still want to lock in this draft? Reply YES / NO / EDIT or it auto-expires in N min." — with no preview of what "this draft" is, because `watchdog.js:31` passes only `minutesRemaining` and never `previewSummary`. This affects prod Node today, not just the port. Likely a contributing cause of the draft-expiry rate that has been attributed to Signal breakage.
2. **`handle_starting_seq_reply` has no caller** in either agent. Node's `receive-loop.js` never routes to it, so a farmer's answer to the SEQ ask-back goes nowhere.
3. **Cutover prerequisites:** the 12 existing `commit_failed` drafts are all `origin='node'` and after a swap would be picked up by neither watchdog. They need draining or re-origining, and the swap itself needs a runbook.

---

## Self-Review

**Spec coverage.** Every module in the spec's inventory table has a task: `extraction_db` (1), `state_machine` (2), `preview_builder` (3), `outbound` (4), `pipeline` (5), `batch_mode` (6), `starting_seq` (7), `confirm/preview` + `confirm/edit_handler` (8). All four deliberate deviations are covered: `origin='python'` (Task 1, asserted again in Task 10), the three config fields (Task 9), the `extractor` -> `extraction_pipeline` parameter swap (Task 9), the edit-reextraction stub (Task 8). Both parity deltas are covered: `handle_starting_seq_reply` ported-but-unrouted (Task 7, ticketed in Task 10 Step 9), and the `TODO(Phase 60)` `last_bot_outbound` (Task 9). Every verification item in the spec maps to a step: FSM parity (Task 2), preview parity (Task 3), `in_flight_conflict` (Tasks 1 and 6), the continuity matrix (Task 5), the live-fire (Task 10).

**Two corrections to the spec, made here:**
- The spec said the throwaway postgres is on port 5433. The repo's existing test container is on **5434** (`tests/conftest.py:_test_host`). Task 10 uses 5434.
- The spec's inventory implied `confirm/preview.py` was needed only by the edit handler. It is also needed to correct the invented ack copy already shipped in `dispatch.py` and `watchdog.py` (Task 8), which is farmer-visible and would otherwise change the farmer's experience at cutover in exactly the way this phase exists to prevent.

**Placeholder scan.** No TBDs. Three places instruct the implementer to read the codebase before writing rather than trusting this document — the `send` keyword names in Task 4, `select_recent_outbound_by_recipient`'s signature in Task 9, and the May-22 fixture path in Task 10. These are deliberate: this plan was written from the Node source, and those three are Python-side details where guessing would produce a confidently wrong call site.

**Type consistency.** `compute_draft_id(capture_ids, draft_index)` is used with that name and argument order in Tasks 1, 5, and 6. `update_draft_status(pool, draft_id, new_status, extras)` likewise in 1, 5, 6, 7, 8. The dispatcher is `{"dispatch": async (side_effect, draft_row)}` in Tasks 4, 5, 6, 7. `ExtractionTransition` fields (`next_status`, `next_askback_turns`, `side_effects`, `reason`, `ask_back_info`) are used consistently in Tasks 2, 5, 6. Side-effect tags are one closed set across Tasks 2, 4, 6, 7: `handoff_to_phase_39`, `send_ask_back`, `send_needs_review_ping`, `send_batch_review_summary`, `send_starting_seq_askback`, `send_seeding_session_filled_preview`, `mark_expired`, `noop`.
