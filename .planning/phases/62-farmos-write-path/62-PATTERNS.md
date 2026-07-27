# Phase 62: farmOS Write Path - Pattern Map

**Mapped:** 2026-06-28
**Files analyzed:** 12 (10 new Python, 1 Python modify, 1 Node modify)
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `farm_agent/farmos/client.py` | service | request-response | `capture/transcribe_client.py` | exact |
| `farm_agent/farmos/merge.py` | utility | transform | `farmos/merge.js` | faithful-port (no Python twin yet) |
| `farm_agent/farmos/assets.py` | service | CRUD | `confirm/confirm_repo.py` + `farmos/assets.js` | role-match |
| `farm_agent/farmos/logs.py` | service | CRUD | `confirm/confirm_repo.py` + `farmos/logs.js` | role-match |
| `farm_agent/farmos/files.py` | service | file-I/O | `capture/transcribe_client.py` + `farmos/files.js` | role-match |
| `farm_agent/farmos/commits/normalize.py` | utility | transform | `farmos/commits/normalize.js` | faithful-port |
| `farm_agent/farmos/commits/commit_router.py` | controller | request-response | `farmos/commits/commit-router.js` + `gate/event_gate.py` | role-match |
| `farm_agent/farmos/commits/commit_seeding.py` | service | CRUD | `farmos/commits/commit-seeding.js` | faithful-port |
| `farm_agent/farmos/commit_watchdog.py` | service | event-driven | `confirm/watchdog.py` | exact |
| `farm_agent/farmos/fidelity_gate.py` | utility | transform | `confirm/strain_ask_back.py` | role-match |
| `farm_agent/persistence/migrations.py` (MODIFY) | migration | batch | `persistence/migrations.py` (self) | exact |
| `src/agents/alerter/src/farmos/commit-db.js` (MODIFY) | service | CRUD | `farmos/commit-db.js` (self) | exact |

---

## Pattern Assignments

### `farm_agent/farmos/client.py` (service, request-response)

**Analog:** `src/farm-agent/farm_agent/capture/transcribe_client.py`
**Node source:** `src/agents/alerter/src/farmos/client.js`

**Imports pattern** (`transcribe_client.py` lines 18-26):
```python
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)
```

**Never-throws factory pattern** (`transcribe_client.py` lines 28-50):
```python
def create_transcribe_client(
    api_url: str,
    http: httpx.AsyncClient,
    timeout_ms: int = 200_000,
    log: logging.Logger | None = None,
) -> dict:
    """Factory returning {"transcribe": transcribe}. ..."""
    _log = log or logger
    _timeout_s = timeout_ms / 1000

    async def transcribe(arg) -> dict:
        ...
        try:
            r = await http.post(...)
            if r.status_code >= 400:
                return {"ok": False, "reason": f"..."}
            ...
            return {"ok": True, ...}
        except httpx.TimeoutException:
            return {"ok": False, "reason": "timeout"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": str(e)}

    return {"transcribe": transcribe}
```

**Node auth + retry pattern to port** (`client.js` lines 36-64, 110-168):
- `_authenticate()`: POST `/user/login?_format=json` -> extract `Set-Cookie` header + `csrf_token` body field
- `_session = {"cookie": None, "csrf": None}` stored in closure
- Retry loop: `backoff_ms = [1000, 4000, 16000]`, `timeout_ms = 10000`, `retry_max = 3`
- 401/403 -> one-shot reauth (`did_reauth` flag)
- 5xx -> transient retry with backoff
- Transient check: `AbortError`, `TypeError`, ECONNRESET/ECONNREFUSED/ETIMEDOUT pattern
- Never-throws: return `{"ok": False, "status": None, ..., "error": e.message}` on network failure

**Python adaptation note:** Replace `AbortController` with `httpx.TimeoutException`. Replace Node `fetch` with `httpx.AsyncClient`. Session state is closure dict `_session`. `postBinary` maps to `http.post(content=bytes, headers={"Content-Type": "application/octet-stream", "Content-Disposition": "file; filename=..."}, timeout=30.0)`.

**Return envelope** (`client.js` line 168):
```python
# All methods return this shape:
{"ok": bool, "status": int|None, "body": dict|str|None, "latency_ms": int}
```

---

### `farm_agent/farmos/merge.py` (utility, transform)

**Analog:** `src/agents/alerter/src/farmos/merge.js` (faithful Python port, no existing Python twin)

**Constants to port** (`merge.js` lines 8-12):
```python
STABLE_NOTES_SEPARATOR = "\n---\n"

ARRAY_REF_FIELDS = ["parent", "qr_codes", "farm_id_tag"]
SCALAR_REL_FIELDS = ["fungi_type", "fungi_xing"]
SCALAR_ATTR_FIELDS = ["status"]
```

**Exception class** (`merge.js` lines 14-22):
```python
class IdentityMutationError(Exception):
    def __init__(self, field: str, existing, incoming):
        super().__init__("identity_mutation:" + field)
        self.field = field
        self.existing = existing
        self.incoming = incoming
```

**Core merge function signature** (`merge.js` lines 54-131):
```python
def merge_asset_fields(existing: dict, incoming: dict) -> dict:
    """Returns {"merged": dict, "conflicts": list}.

    Rules (byte-identical to merge.js):
      - identity: name + type throw IdentityMutationError on mutation
      - array-ref (parent/qr_codes/farm_id_tag): set-union by id
      - scalar rels (fungi_type/fungi_xing): null=take, equal=noop, differ=conflict-keep-existing
      - scalar attrs (status): same scalar rule
      - notes: split on STABLE_NOTES_SEPARATOR, dedup, rejoin
    """
```

**Notes merge rule** (`merge.js` lines 41-52):
```python
def _merge_notes(existing_notes: dict | None, incoming_notes: dict | None) -> dict:
    existing_value = (existing_notes or {}).get("value", "")
    incoming_value = (incoming_notes or {}).get("value", "")
    sep = STABLE_NOTES_SEPARATOR
    entries = [s.strip() for s in existing_value.split(sep) if s.strip()]
    for entry in (s.strip() for s in incoming_value.split(sep) if s.strip()):
        if entry not in entries:
            entries.append(entry)
    return {"value": sep.join(entries), "format": "plain_text"}
```

**Deep clone:** Use `import copy; copy.deepcopy(existing)` (equivalent to `JSON.parse(JSON.stringify(...))` in JS).

---

### `farm_agent/farmos/assets.py` (service, CRUD)

**Analog:** `confirm/confirm_repo.py` (never-throws DAO shape) + `src/agents/alerter/src/farmos/assets.js` (faithful port)

**LRU name cache** (`assets.js` lines 22-46):
```python
import functools

# Simple LRU cap-32 dict (mirror Node NAME_CACHE + NAME_CACHE_MAX=32)
_NAME_CACHE: dict[str, str] = {}  # name -> asset_id; OrderedDict w/ max 32
_NAME_CACHE_MAX = 32
```

**findAssetByName** (`assets.js` lines 48-61):
```python
async def find_asset_by_name(client: dict, name: str) -> dict:
    """GET /api/asset/fungi?filter[name][value]=<enc>
    Returns {"found": True, "asset_id": str} | {"found": False} | {"found": False, "error": str}
    """
    cached = _cache_get(name)
    if cached:
        return {"found": True, "asset_id": cached, "cached": True}
    enc = urllib.parse.quote(name)
    r = await client["get"](f"/api/asset/fungi?filter[name][value]={enc}")
    if not r["ok"]:
        return {"found": False, "error": f"http_{r.get('status') or 'network'}"}
    arr = (r.get("body") or {}).get("data")
    if isinstance(arr, list) and arr:
        asset_id = arr[0]["id"]
        _cache_set(name, asset_id)
        return {"found": True, "asset_id": asset_id}
    return {"found": False}
```

**upsertFungiAsset** (`assets.js` lines 189-312): miss -> POST createFungiAsset; hit -> GET existing -> mergeAssetFields -> PATCH if non-noop. Soft revision_id compare + one retry on race. Returns `{"ok": bool, "asset_id": str, "outcome": "created"|"patched"|"noop", "conflicts": list}`.

**Note on `mushy:draft:{draftId}` trailer** (`assets.js` lines 91-95):
```python
note_trailer = (notes + "\n" if notes else "") + f"mushy:draft:{draft_id}"
```

---

### `farm_agent/farmos/logs.py` (service, CRUD)

**Analog:** `confirm/confirm_repo.py` (never-throws DAO shape) + `src/agents/alerter/src/farmos/logs.js` (faithful port)

**Constants to port** (`logs.js` lines 21-53):
```python
NATIVE_LOG_TYPES = ["seeding", "activity", "input", "observation", "harvest"]
LOG_TYPES = [*NATIVE_LOG_TYPES, "seeding_session"]

# LOG_STABLE_KEYS: per-type stable key resolver functions
# seeding: filter by asset.id (B5 invariant: one seeding log per child asset)
# others: None -> POST-only path
LOG_STABLE_KEYS = {
    "seeding": lambda opts: (
        {"path": f"/api/log/seeding?filter[asset.id][value]={urllib.parse.quote(opts['asset_ids'][0])}"}
        if opts.get("asset_ids") else None
    ),
    "activity": None,
    "input": None,
    "observation": None,
    "harvest": None,
}
```

**upsertLog signature** (`logs.js` lines 149-319):
```python
async def upsert_log(client: dict, type: str, opts: dict) -> dict:
    """Lookup-by-stable-key then PATCH-merge-or-POST-create.

    Returns {"ok": bool, "log_id": str, "outcome": str, "conflicts": list, "warnings": list}
    """
```

---

### `farm_agent/farmos/files.py` (service, file-I/O)

**Analog:** `capture/transcribe_client.py` (httpx async + never-throws) + `src/agents/alerter/src/farmos/files.js`

**Field-scoped upload** (`files.js` lines 70-94):
```python
async def upload_field_attachment(
    client: dict,
    collection_path: str,  # e.g. "/api/asset/fungi"
    uuid: str,
    field: str,            # "image" NOT "file"
    abs_path: str,
    filename: str | None = None,
    opts: dict | None = None,
) -> dict:
    """POST /api/asset/{bundle}/{uuid}/{field} with octet-stream body.

    Single call: creates file AND links to entity field. Field must be "image"
    for fungi assets (the "file" field rejects jpg/png with 422).

    Returns {"ok": True, "file_id": str} | {"ok": False, "reason": str, ...}
    """
    # Read file bytes from abs_path; if missing return {"ok": False, "reason": "attachment_missing", "skipped": True}
    # POST via client["post_binary"](url, bytes, filename=fn, timeout_ms=30000)
    # Extract file_id from response: body.data[-1].id if array, else body.data.id
```

**`_extract_file_id` helper** (`files.js` lines 61-68):
```python
def _extract_file_id(body: dict | None) -> str | None:
    d = (body or {}).get("data")
    if not d:
        return None
    if isinstance(d, list):
        return d[-1]["id"] if d else None
    return d.get("id")
```

---

### `farm_agent/farmos/commits/normalize.py` (utility, transform)

**Analog:** `src/agents/alerter/src/farmos/commits/normalize.js` (faithful port)

**Function signature** (`normalize.js` lines 24-128):
```python
def normalize(draft: dict) -> dict:
    """Pure function: returns a NEW draft with draft_json reshaped to commit-shape.
    Idempotent: guards prevent double-application.
    Does NOT mutate input (D-01).
    """
    dj = dict(draft.get("draft_json") or {})
    # Clone arrays (idempotency: each transform is guarded)
    for key in ("qr_codes", "source_block_refs", "source_qr_codes", "bags", "input_ingredients"):
        if isinstance(dj.get(key), list):
            dj[key] = list(dj[key])

    # Common: event_timestamp (ISO str) -> timestamp (unix seconds, floor)
    if not isinstance(dj.get("timestamp"), (int, float)) and isinstance(dj.get("event_timestamp"), str):
        import math, datetime
        ms = datetime.datetime.fromisoformat(dj["event_timestamp"]).timestamp() * 1000
        dj["timestamp"] = math.floor(ms / 1000)

    # Common: asset_ref (str) -> qr_codes (list)
    if not isinstance(dj.get("qr_codes"), list) and isinstance(dj.get("asset_ref"), str):
        dj["qr_codes"] = [] if dj["asset_ref"] == "<UNKNOWN>" else [dj["asset_ref"]]

    # Per-type switch (mirror normalize.js lines 56-125)
    log_type = draft.get("log_type")
    if log_type == "seeding":
        if not dj.get("species_code") and isinstance(dj.get("species"), str):
            dj["species_code"] = dj["species"]
    elif log_type == "harvest":
        ...  # source_block_refs -> source_qr_codes; harvest_batch_id; qty_g -> bags
    elif log_type == "activity":
        if not dj.get("activity_subtype") and isinstance(dj.get("name"), str):
            dj["activity_subtype"] = dj["name"]
    elif log_type == "input":
        if isinstance(dj.get("recipe_lot"), str):
            dj["notes"] = "recipe_lot: " + dj["recipe_lot"] + ("\n" + dj["notes"] if dj.get("notes") else "")
            del dj["recipe_lot"]
    elif log_type == "observation":
        if isinstance(dj.get("state"), str) and dj["state"]:
            dj["notes"] = (dj["notes"] + "\nstate: " + dj["state"]) if dj.get("notes") else ("state: " + dj["state"])
            del dj["state"]

    return {**draft, "draft_json": dj}
```

---

### `farm_agent/farmos/commits/commit_router.py` (controller, request-response)

**Analog:** `src/agents/alerter/src/farmos/commits/commit-router.js` + `gate/event_gate.py` (dispatch pattern)

**Dispatch table + commit function** (`commit-router.js` lines 16-70):
```python
from farm_agent.farmos.commits import (
    commit_seeding,
    commit_activity,
    commit_input,
    commit_observation,
    commit_harvest,
    commit_seeding_session,
)
from farm_agent.farmos.commits.normalize import normalize
from farm_agent.farmos.logs import LOG_TYPES

DISPATCH = {
    "seeding": commit_seeding.commit_seeding,
    "activity": commit_activity.commit_activity,
    "input": commit_input.commit_input,
    "observation": commit_observation.commit_observation,
    "harvest": commit_harvest.commit_harvest,
    "seeding_session": commit_seeding_session.commit_seeding_session,
}

async def commit(client: dict, draft: dict, ctx: dict | None = None) -> dict:
    """Dispatch one signal_draft.log_type to its commit module.

    Returns {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
             "attachments_failed": list, "latency_ms": int, "reason": str|None}
    """
    import time
    t0 = time.monotonic()
    log_type = (draft or {}).get("log_type")
    if not log_type or log_type not in LOG_TYPES:
        return {"ok": False, "reason": "unsupported_log_type", "log_type": log_type,
                "asset_ids": [], "log_ids": [], "file_ids": [],
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    fn = DISPATCH[log_type]
    try:
        r = await fn(client, normalize(draft), ctx)
        return {"ok": bool(r.get("ok")), "asset_ids": r.get("asset_ids") or [],
                "log_ids": r.get("log_ids") or [], "file_ids": r.get("file_ids") or [],
                "attachments_failed": r.get("attachments_failed") or [],
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "reason": r.get("reason")}
    except Exception as e:
        return {"ok": False, "reason": str(e) or "commit_error",
                "asset_ids": [], "log_ids": [], "file_ids": [],
                "latency_ms": int((time.monotonic() - t0) * 1000)}
```

---

### `farm_agent/farmos/commits/commit_seeding.py` (service, CRUD)

**Analog:** `src/agents/alerter/src/farmos/commits/commit-seeding.js` (faithful port)

**Core pattern** (`commit-seeding.js` lines 20-93):
```python
async def commit_seeding(client: dict, draft: dict, ctx: dict | None = None) -> dict:
    dj = draft.get("draft_json") or {}
    draft_id = draft["id"]
    qr_codes = dj.get("qr_codes") or []
    timestamp = dj["timestamp"] if isinstance(dj.get("timestamp"), (int, float)) else (time.time())

    # QR path resolution: path_b_ids (found) vs path_a_qrs (new)
    path_b_ids, path_a_qrs = [], []
    for qr in qr_codes:
        r = await resolve_qr(client, qr)
        if r.get("found") and r.get("asset_id"):
            path_b_ids.append(r["asset_id"])
        else:
            path_a_qrs.append(qr)
    if len(path_b_ids) > 1:
        return {"ok": False, "reason": "ambiguous_qr_seeding"}

    # Path A: create/upsert block
    if not path_b_ids:
        strain = dj.get("species_code") or dj.get("species") or dj.get("strain") or dj.get("fungi_type")
        if not strain:
            return {"ok": False, "reason": "missing_strain"}
        block_name = dj.get("block_name")
        if not block_name:
            return {"ok": False, "reason": "missing_block_name"}
        block_res = await upsert_fungi_asset(client, {
            "name": block_name, "fungi_type_name": strain, "fungi_xing_name": "block",
            "qr_codes": path_a_qrs, "draft_id": draft_id,
        })
        if not block_res.get("ok"):
            return {"ok": False, "reason": block_res.get("reason") or "block_upsert_failed"}
        block_id = block_res["asset_id"]
        created_assets = [block_id] if block_res.get("outcome") == "created" else []
    else:
        block_id = path_b_ids[0]
        created_assets = []

    # Seeding log upsert
    log_res = await upsert_log(client, "seeding", {
        "name": f"Inoc {dj.get('block_name') or block_id}",
        "timestamp": timestamp,
        "asset_ids": [block_id],
        "notes": ...,
        "draft_id": draft_id,
    })
    if not log_res.get("ok"):
        return {"ok": False, "reason": log_res.get("reason") or "log_upsert_failed",
                "asset_ids": created_assets}
    return {"ok": True, "asset_ids": created_assets, "log_ids": [log_res["log_id"]], "file_ids": []}
```

---

### `farm_agent/farmos/commit_watchdog.py` (service, event-driven)

**Analog:** `confirm/watchdog.py` (exact pattern)

**Loop shape** (`watchdog.py` lines 192-232):
```python
async def commit_watchdog_loop(pool, farmos_client: dict, config) -> None:
    """Poll confirmed drafts, acquire lock, commit to farmOS.

    Mirrors confirm_watchdog_loop: immediate-then-sleep, never-throws, CancelledError re-raises.
    Interval: config.commit_watchdog_interval_ms / 1000 (mirror Node COMMIT_WATCHDOG_INTERVAL_MS=30000).
    """
    lock = asyncio.Lock()
    interval = config.commit_watchdog_interval_ms / 1000

    # Immediate tick on boot (restart-safe)
    try:
        await _tick_once(pool, farmos_client, config, lock=lock)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("[commit_watchdog] initial tick failed: %s", e)

    while True:
        try:
            await asyncio.sleep(interval)
            await _tick_once(pool, farmos_client, config, lock=lock)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("[commit_watchdog] tick error: %s", e)
```

**Tick function** (mirrors Node `commit-db.js` watchdog SELECT + acquire/mark/fail cycle):
```python
async def _tick_once(pool, farmos_client, config, *, lock: asyncio.Lock) -> None:
    async with lock:
        rows = await commit_db.find_confirmed_candidates(pool, batch_cap=10)
        for row in rows:
            draft_id = row["id"]
            acq = await commit_db.acquire_commit_lock(pool, draft_id)
            if not acq.get("ok") or acq.get("rowcount", 0) == 0:
                continue  # race lost or already committing
            try:
                result = await commit_router.commit(farmos_client, row)
                if result.get("ok"):
                    await commit_db.mark_committed(pool, draft_id, result)
                else:
                    await commit_db.mark_failed(pool, draft_id, result.get("reason"))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                await commit_db.mark_failed(pool, draft_id, str(e))
```

**Origin guard SELECT** (ported `commit-db.js` `findConfirmedCandidates` with Phase 62 clause):
```python
async def find_confirmed_candidates(pool, batch_cap: int = 10) -> list[dict]:
    """SELECT * FROM signal_draft WHERE status='confirmed' AND origin='python' ORDER BY confirmed_at ASC LIMIT $1"""
```

---

### `farm_agent/farmos/fidelity_gate.py` (utility, transform)

**Analog:** `confirm/strain_ask_back.py` (hold + ask-back pattern, D-06/D-07)

**Gate interface** (new file, pattern from `strain_ask_back.py` and D-06):
```python
def check_fidelity(draft: dict, csv_rows: list[dict]) -> dict:
    """Compare draft block_name strain against CSV source.

    Returns:
      {"pass": True}                                         -- no disagreement
      {"pass": False, "reason": "block_not_in_csv"}          -- block absent from CSV (no-op; pass)
      {"pass": False, "reason": "strain_mismatch",
       "draft_strain": str, "csv_strain": str,
       "hold_status": "fidelity_cross_check_unverified",
       "ask_back_msg": str}                                  -- hold + ask-back
    """
```

**New status string** (D-06): `"fidelity_cross_check_unverified"` -- add to migration's allowed statuses comment + ensure schema migration handles it.

**Ask-back message pattern** (ASCII-only, no em-dash, mirrors `strain_ask_back.py`):
```python
def render_fidelity_ask_back(block_name: str, draft_strain: str, csv_strain: str) -> str:
    return "\n".join([
        f"Block '{block_name}': draft says strain {draft_strain}, CSV says {csv_strain}.",
        "Which is correct? Reply with the correct strain code to resolve, or YES to keep draft value.",
    ])
```

**CSV load** (D-07): load at boot from env-configured prod CSV path; tests use fixture CSV.

---

### `farm_agent/persistence/migrations.py` (MODIFY, migration, batch)

**Analog:** Self. Pattern from `persistence/migrations.py` lines 187-217 (`ADD COLUMN IF NOT EXISTS` block).

**New migration to add** (after existing Phase 39/49/61 blocks):
```python
# Phase 62 D-01: origin guard column.
await conn.execute(
    "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'"
)
# Phase 62 D-06: CSV fidelity hold status (new allowed status string, no CHECK constraint
# per Phase 38/39 precedent -- validated in application code only).
# No column needed: status column already exists; 'fidelity_cross_check_unverified'
# is a new allowed value. Document in the allowed-statuses comment block only.
```

---

### `src/agents/alerter/src/farmos/commit-db.js` (MODIFY, service, CRUD)

**Analog:** Self. Change: `findConfirmedCandidates` lines 47-60 gains `AND origin != 'python'`.

**Before** (`commit-db.js` lines 47-60):
```javascript
async function findConfirmedCandidates(pool, batchCap) {
  try {
    const r = await pool.query(
      `SELECT * FROM signal_draft
        WHERE status='confirmed'
        ORDER BY confirmed_at ASC NULLS LAST
        LIMIT $1`,
      [batchCap]
    );
    return r.rows || [];
  } catch (e) {
    return [];
  }
}
```

**After** (D-01 origin guard):
```javascript
async function findConfirmedCandidates(pool, batchCap) {
  try {
    const r = await pool.query(
      `SELECT * FROM signal_draft
        WHERE status='confirmed'
          AND origin != 'python'
        ORDER BY confirmed_at ASC NULLS LAST
        LIMIT $1`,
      [batchCap]
    );
    return r.rows || [];
  } catch (e) {
    return [];
  }
}
```

---

## Shared Patterns

### Never-throws function shape
**Source:** `src/farm-agent/farm_agent/capture/transcribe_client.py` lines 68-89 + `confirm/confirm_repo.py` lines 157-166
**Apply to:** All `farm_agent/farmos/*.py` service functions (assets, logs, files, commit_watchdog tick)
```python
try:
    ...  # main body
    return {"ok": True, ...}
except asyncio.CancelledError:
    raise  # always re-raise (watchdog loops)
except Exception as e:  # noqa: BLE001
    log.warning("[farmos] <operation> failed: %s", e)
    return {"ok": False, "reason": str(e)}
```

### Atomic CAS status transitions (origin-guard DB writes)
**Source:** `src/farm-agent/farm_agent/confirm/confirm_repo.py` lines 157-166
**Apply to:** `commit_watchdog.py` acquire/mark/fail cycle; `migrations.py` new column
```python
async with pool.connection() as conn:
    async with conn.transaction():
        result = await conn.execute(SQL, (draft_id,))
return {"ok": True, "rowcount": result.rowcount}
```

### asyncio.create_task watchdog wiring
**Source:** `src/farm-agent/farm_agent/boot.py` lines 105-106
**Apply to:** `boot.py` (add commit_watchdog_loop task)
```python
commit_watchdog_task = asyncio.create_task(
    commit_watchdog_loop(pool, farmos_client, config)
)
```
And in shutdown block (boot.py lines 122-130):
```python
commit_watchdog_task.cancel()
try:
    await commit_watchdog_task
except asyncio.CancelledError:
    pass
```

### Immediate-then-sleep loop with CancelledError re-raise
**Source:** `src/farm-agent/farm_agent/confirm/watchdog.py` lines 192-232
**Apply to:** `farm_agent/farmos/commit_watchdog.py`
```python
# Tick immediately on boot, then sleep-repeat
try:
    await tick_once(...)
except asyncio.CancelledError:
    raise
except Exception as e:  # noqa: BLE001
    log.warning("[watchdog] initial tick failed: %s", e)

while True:
    try:
        await asyncio.sleep(interval)
        await tick_once(...)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("[watchdog] tick error: %s", e)
```

### JSON:API content-type headers
**Source:** `client.js` lines 82-98
**Apply to:** All `farm_agent/farmos/client.py` requests
```python
headers = {
    "Accept": "application/vnd.api+json",
    "Cookie": _session["cookie"] or "",
    "X-CSRF-Token": _session["csrf"] or "",
    # For JSON body:
    "Content-Type": "application/vnd.api+json",
    # For binary upload:
    "Content-Type": "application/octet-stream",
    "Content-Disposition": f'file; filename="{filename}"',
}
```

### ADD COLUMN IF NOT EXISTS migration pattern
**Source:** `src/farm-agent/farm_agent/persistence/migrations.py` lines 187-217
**Apply to:** `migrations.py` `origin` column addition
```python
await conn.execute(
    "ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'"
)
```

---

## No Analog Found

None. All files have an analog in the codebase (Node source-of-truth for port semantics; Python files for language/style patterns).

---

## Key Port Discipline Notes

These apply across ALL `farm_agent/farmos/` files:

1. **Byte-identical semantics:** `merge.py` must replicate `merge.js` field rules exactly (set-union, scalar conflict, notes split-dedup). Test with the same inputs as the Node test suite.
2. **Name-based stable identity:** `find_asset_by_name` uses `filter[name][value]=<url_encoded>` query parameter. No hex digest anywhere.
3. **Notes marker:** every created asset/log appends `mushy:draft:{draft_id}` to notes via `_build_note_value()` helper.
4. **`image` field for photos:** `upload_field_attachment` always targets field `"image"`, NOT `"file"` (422 on jpg). URL is `/api/asset/fungi/{uuid}/image`.
5. **Origin guard sequence:** Python commit writes must set `origin='python'` on every `signal_draft` row it touches; the Node watchdog `AND origin != 'python'` clause must be deployed FIRST (D-02).
6. **Dev vs prod farmOS:** `FARMOS_URL` env var selects `:18080` (dev) vs `:8082` (prod). Both API-named "Mossrock". In-phase live-fire runs against dev (D-04).

---

## Metadata

**Analog search scope:** `src/agents/alerter/src/farmos/`, `src/farm-agent/farm_agent/`
**Files scanned:** 15 source files read
**Pattern extraction date:** 2026-06-28
