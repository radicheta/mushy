# Phase 63: Chamber Alerter - Pattern Map

**Mapped:** 2026-07-13
**Files analyzed:** 15 (new chamber/ modules + tests + 4 modified Foray files)
**Analogs found:** 15 / 15

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog (farm-agent) | Match Quality |
|---|---|---|---|---|
| `chamber/config.py` (new) | config | request-response (frozen load-at-boot) | `tenancy/tenant.py` (`TenantConfig` + `load()`) | exact |
| `chamber/rules.py` (new) | utility (pure detectors) | transform | none (novel pure-function shape) — mirror `router.py`'s pure-function style | role-match |
| `chamber/state.py` (new) | service (FSM) | event-driven | none exact; `confirm/watchdog.py` for event/tick handler shape | role-match |
| `chamber/message.py` (new) | utility (formatting) | transform | none exact; `tenancy/tenant.py::mask_number` for pure-formatter-with-doc-comment style | partial |
| `chamber/snooze.py` (new) | utility (grammar parser) | transform | `signal_io/router.py` (regex-based classification, `_COMMAND_RE`) | role-match |
| `chamber/heartbeat.py` (new) | service (scheduler) | event-driven / batch | `capture/retention.py` (`retention_loop` daily run-once-then-sleep asyncio task) | exact |
| `chamber/ws_client.py` (new) | service (bridge client) | streaming | `signal_io/client.py` (`SignalClient`, httpx wrapper + reconnect concerns) — closest async I/O client shape available | role-match |
| `chamber/service.py` (new) | service (composer) | event-driven | `signal_io/receive_loop.py` (`ReceiveLoop` start/stop lifecycle) + `boot.py` (composition) | exact |
| `tests/chamber/*.py` (new, multiple) | test | — | `tests/test_tenancy.py`, `tests/test_signal_ratecap.py` | exact |
| `tenancy/tenant.py` (MODIFY — D-03 field removal) | config | request-response | itself (surgical edit) | exact |
| `.lint-imports` (MODIFY — fix source_modules) | config | — | itself (surgical edit) | exact |
| `tests/test_foray_seam.py` (MODIFY — FORAY_PACKAGES list) | test | — | itself (surgical edit) | exact |
| `signal_io/client.py` (MODIFY — D-03/Pitfall-9 rate-cap fallback) | service | request-response | itself (surgical edit) | exact |
| `signal_io/router.py` / `receive_loop.py` (reused, not modified) | route/middleware | event-driven | itself (D-05 wiring point) | exact |
| `boot.py` (MODIFY — wire chamber composite dispatch + service) | config/composer | event-driven | itself (surgical edit) | exact |

## Pattern Assignments

### `chamber/config.py` (config, request-response)

**Analog:** `src/farm-agent/farm_agent/tenancy/tenant.py` (full file read, 435 lines)

**Frozen dataclass + doc-comment-as-spec pattern** (lines 1-13, 214-221):
```python
"""
tenancy/tenant.py — the SOLE reader of os.environ in farm_agent business code.
...
Secrets (SIGNAL_SENDER, TIMESCALE_PASSWORD, ANTHROPIC_API_KEY, FARMOS_PASSWORD)
resolve ONLY from env via _must_env() — never from tenant YAML (FND-02 / W9 policy).
"""
...
@dataclass(frozen=True)
class TenantConfig:
    """Immutable config for a single tenant. ..."""
```
`ChamberConfig` must copy this exact shape: a module docstring naming the Node
source it ports (`config.js`), a `@dataclass(frozen=True)`, and NO tenant-YAML
layer per RESEARCH Open Question 3 recommendation (env-only + hardcoded
defaults) — i.e. `ChamberConfig.load()` should use `_parse_int_env`/
`_parse_float_env`-style helpers directly against `env`, skipping `_pick`/
`_load_tenant_file`.

**Sole-env-reader env-parsing helpers to copy verbatim (lines 45-54, 98-129):**
```python
def _must_env(env: dict[str, str], key: str) -> str:
    v = env.get(key)
    if not v:
        raise RuntimeError(f"[config] Required env var {key} is missing")
    return v

def _parse_int_env(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"[config] {key}={raw!r} is not a valid integer") from None
```
Copy `_parse_int_env`/`_parse_float_env` into `chamber/config.py` (or a shared
`farm_agent/_env.py` if the planner prefers de-duplication — Claude's
Discretion) for the new knobs: `oob_n`, `oob_window_min`, `cooldown_min`,
`critical_cooldown_min`, `humidifier_stuck_min`, `sensor_flap_min_sec`,
`mode_stale_min`, `mode_boot_grace_ms`, `receive_poll_sec`, and the 7 D-03
relocated fields (`rh_target`, `rh_band`, `pi_offline_min`,
`sensor_offline_min`, `heartbeat_hour`, `max_sends_per_hour`, `timezone`).

**Composition pattern for D-02 (secrets from TenantConfig, not re-read from env):**
`ChamberConfig` must NOT call `_must_env` again for `signal_sender`,
`signal_recipient`, `signal_api_url`, `tenant_id`, or timescale creds — it
receives a `TenantConfig` instance (already loaded by `boot.py`) and copies
those fields directly, mirroring how `SignalClient.__init__` (client.py:65-74)
pulls `config.signal_api_url` / `config.signal_sender` off an injected
`TenantConfig` rather than re-deriving them:
```python
# signal_io/client.py:65-74 — composition-by-injection pattern to mirror
self._config = config
...
self._api_url = config.signal_api_url
self._sender = config.signal_sender
```

**Public loader function shape** (lines 297-306, 395-434):
```python
def load(env: dict[str, str] | None = None) -> TenantConfig:
    if env is None:
        env = dict(os.environ)
    tenant_id = env.get("TENANT_ID") or "mossrock"
    ...
    return TenantConfig(tenant_id=tenant_id, ...)
```
`ChamberConfig.load(env, tenant_config)` should take the already-loaded
`TenantConfig` as a second param (composition) plus optional `env` dict for
testability — same signature shape as `tenancy.load`.

**D-04 default (the TZ bug fix, contrast case):**
```python
# tenant.py:392 — the CURRENT (to-be-superseded-for-alerter-purposes) default:
timezone = env.get("TZ") or "America/Toronto"
```
`ChamberConfig` must NOT copy this default — copy the `_pick`/env-read
*mechanism* but flip the literal default string to `"America/Montevideo"`
(D-04). This field is also one of the 7 moving out of `TenantConfig` (D-03).

---

### `chamber/rules.py` (utility, transform — pure detectors)

**Analog:** No close Python analog exists yet; closest available shape is
`signal_io/router.py`'s pure-function-with-injected-config style (no class,
explicit params, no side effects). Node source (`src/agents/alerter/src/rules.js`,
110 lines) is the parity target for behavior — see RESEARCH.md's full
Node→Python mapping table and Pitfalls 1-5 (stale-suspend, fc1-dark hard
3-min constant, offline-blindness order, flap-floor scope).

**Pure-function-injected-config pattern to copy** (`router.py:42-61`):
```python
def allowed_senders(config: TenantConfig) -> set[str]:
    """Build the whitelist set from TenantConfig (T-17-02 / R7). ..."""
    return {...}

def is_whitelisted(source: str, config: TenantConfig) -> bool:
    """Return True iff source is in the sender whitelist (T-57-03-01)."""
    return source in allowed_senders(config)
```
Every `rules.py` detector (`is_rh_oob`, `is_sensor_error`, `is_pi_offline`,
`is_humidifier_stuck`, `is_sensor_silent`) must follow this exact shape:
plain module-level function, explicit params (never a global/module config
read), one-line docstring citing the Node line numbers/dates it ports (mirror
`router.py`'s "Ports X from Y" docstring convention).

**Doc-comment-as-spec citation convention** (`router.py:1-19`, also used
throughout `client.py`):
```python
"""
signal_io/router.py — attribution-sensitive envelope routing primitives (SIG-03 / SC#5).
...
Ports the whitelist gate, DM-vs-group classification, ... from receive-loop.js:14-29, 124-156
"""
```
`rules.py` must cite `rules.js` line ranges and the specific historical bug-fix
dates (2026-05-07, Phase-46 D-09/D-10, 2026-05-12) exactly as RESEARCH.md's
Code Examples section already demonstrates — treat these as load-bearing,
not incidental.

---

### `chamber/state.py` (service/FSM, event-driven)

**Analog:** No direct Python FSM analog exists. Closest event-handler-loop
shape: `confirm/watchdog.py` (231 lines, not fully read this pass — role-match
only, event/tick-driven watchdog pattern) and `signal_io/receive_loop.py`'s
`tick()` method shape (sequential, try/except-wrapped, no `asyncio.gather`).
Node `state.js` (718 lines) is the parity target.

**Sequential-never-gather discipline to carry over** (`receive_loop.py:69-108`):
```python
async def tick(self) -> None:
    ...
    for env in envelopes:  # Sequential for-loop — NEVER asyncio.gather
        ...
        try:
            await self._dispatch(env)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(...)
```
While `state.py`'s `transition()`/`drive_alert_type()` are themselves pure
(no I/O), any code in `service.py` that iterates over the 6 alert types to
call `drive_alert_type` per tick should follow this same sequential,
per-item try/except discipline — no `asyncio.gather` fan-out across alert
types (keeps ordering/log attribution deterministic, matches Node's
synchronous per-tick loop).

**Recommend dataclasses over dict+deepcopy** (per RESEARCH Code Examples,
`transition` row): use `dataclasses.replace()` on a frozen or mutable
dataclass for the FSM entry, not `copy.deepcopy(dict)` — matches the
project's established `TenantConfig`/`EffectiveConfig`-as-dataclass idiom
already used in `tenancy/tenant.py`.

---

### `chamber/message.py` (utility, transform — TZ formatting, CHM-02)

**Analog:** `tenancy/tenant.py::mask_number` (lines 195-207) — closest existing
pure-formatter with a "port of X" doc comment and worked example in the
docstring:
```python
def mask_number(n: object) -> str:
    """Mask a phone number for safe logging.

    Port of config.js maskNumber():
      - Non-string or len < 6 → 'XXXX'
      - Otherwise: first 2 chars + (len-6) Xs + last 4 chars

    Example: '+15551234567' → '+1XXXXXX4567'
    """
    if not isinstance(n, str) or len(n) < 6:
        return "XXXX"
    return n[:2] + "X" * (len(n) - 6) + n[-4:]
```
Copy this exact shape for `fmt_num`/`hhmm`/`fmt_duration`/`fmt_relative`:
one-line summary, "Port of message.js X()" line, bullet-point behavior spec,
worked example in the docstring.

**D-04 TZ fix — exact code to use** (already spec'd in RESEARCH.md Code
Examples, reproduced here as the concrete target):
```python
from datetime import datetime
from zoneinfo import ZoneInfo

def hhmm(ts_ms: int, tz_name: str) -> str:
    """Render a UTC epoch-ms timestamp as zero-padded local HH:MM (D-04 fix).

    Every farmer-facing call site MUST route through this — never format via
    UTC directly.
    """
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=ZoneInfo(tz_name))
    return dt.strftime("%H:%M")
```
`tz_name` must come from `ChamberConfig.timezone` (never hardcoded, never
`timezone.utc`) — see Anti-Patterns in RESEARCH.md.

---

### `chamber/snooze.py` (utility, transform — command grammar)

**Analog:** `signal_io/router.py`'s anchored-regex classification pattern
(lines 31-38, 128-170):
```python
_COMMAND_RE = re.compile(
    r"^\s*￼?\s*(?:@\S+\s+)?(mute|snooze|quiet)\b",
    re.IGNORECASE,
)
_SLASH_COMMAND_RE = re.compile(r"^/(force-|cancel-)", re.IGNORECASE)
```
`snooze.py`'s `STRICT`/`SIMPLE` regexes (port of `snooze.js`) should be
module-level compiled `re.Pattern` constants in the same style — anchored,
case-insensitive, named for what they match. `router.py` already defines
`_COMMAND_RE` that overlaps semantically (mute/snooze/quiet keyword
detection) — the router's job is trigger *detection* (does this look like a
command), `chamber/snooze.py`'s job is grammar *parsing* (which alert type,
which duration). Do not duplicate the keyword-detection regex; `snooze.py`
receives text already identified as a command-shaped message.

**No-raise contract** (Security Domain, RESEARCH.md V4/Known Threat
Patterns): `parse_snooze_command` must never raise on malformed input —
mirrors `router.py`'s pure functions, none of which raise; unrecognized
input returns a `{"ok": False, ...}` dict, matching `router.py::resolve_farmer`'s
"Never returns None. Never raises." docstring convention (line 185).

---

### `chamber/heartbeat.py` (service, event-driven/batch — daily scheduler)

**Analog:** `src/farm-agent/farm_agent/capture/retention.py` (full file, 61
lines) — the closest existing daily-asyncio-loop analog in the codebase.

**Run-once-then-sleep asyncio daily-task shape to copy directly** (lines
1-21, 36-61):
```python
"""
capture/retention.py -- Daily soft-expiry asyncio task for signal_capture rows.

Port of src/agents/alerter/src/capture-retention.js createRetentionJob().
...
Python asyncio replaces node-cron -- no new dependency needed.
"""
from __future__ import annotations
import asyncio
import logging
...
logger = logging.getLogger(__name__)

async def retention_loop(pool: AsyncConnectionPool, config: TenantConfig) -> None:
    """Daily soft-expiry ... Implements the run-once-then-sleep pattern"""
    while True:
        try:
            ...
            logger.info("[retention] flagged %d rows expired (>%dd)", count, ...)
        except Exception as e:  # noqa: BLE001 -- defense-in-depth
            logger.warning("[retention] mark_expired_older_than failed: %s", e)
        await asyncio.sleep(86_400)
```
`chamber/heartbeat.py`'s `heartbeat_loop(...)` should follow this exact
`while True: try: ...; except Exception: log-and-continue; await
asyncio.sleep(...)` shape — BUT per Pitfall 10, the "day mark done" logic is
conditional on non-empty summary (defer-and-retry, not unconditional daily
sleep), so the sleep interval inside the loop must be shorter (Node retries
every 15 min when deferring) — do not blindly copy the fixed `86_400`
constant; parameterize the retry interval per RESEARCH Pitfall 10.

**Launched-from-boot.py + cancelled-on-shutdown wiring pattern**
(`boot.py:104, 136-140`):
```python
retention_task = asyncio.create_task(retention_loop(pool, config))
...
retention_task.cancel()
try:
    await retention_task
except asyncio.CancelledError:
    pass
```
`heartbeat_loop` (and `ws_client`'s reconnect loop) must be wired into
`boot.py` with this identical create_task/cancel/await-CancelledError-swallow
shape — see `boot.py` Pattern Assignment below for the full composite wiring.

---

### `chamber/ws_client.py` (service, streaming — bridge client + backoff)

**Analog:** `signal_io/client.py` (`SignalClient`, 354 lines) — closest
existing async-I/O-client-with-injected-httpx shape, though it is HTTP not
WS. Use it for: constructor-injection discipline, module docstring
convention, and the `/health` poll leg (which IS httpx, per RESEARCH.md
Standard Stack "Supporting" table — reuse the shared `httpx.AsyncClient`,
do not construct a second one).

**Constructor-injection discipline to copy** (`client.py:52-90`):
```python
def __init__(
    self,
    *,
    config: TenantConfig,
    http: httpx.AsyncClient,
    ...
    log: logging.Logger | None = None,
    timeout_s: float = 10.0,
) -> None:
    self._config = config
    self.http = http
    ...
    self._logger = log or logger
    self._timeout_s = timeout_s
```
`WsClient.__init__` should take `config: ChamberConfig`, an injected `http:
httpx.AsyncClient` (for the `/health` poll leg — reuse the boot.py-level
shared client per RESEARCH's Supporting table), and NOT construct its own
`httpx.AsyncClient`.

**Module docstring convention citing the Node port target + design
decisions** (`client.py:1-27`) — copy this exact header shape for
`ws_client.py`, listing e.g. "D-XX: hand-rolled backoff mirrors
bridge-client.js's 1s→30s doubling schedule, not the websockets library's
built-in reconnect iterator" per RESEARCH's Alternatives Considered.

**Fail-open logging-not-raising pattern for best-effort operations**
(`client.py:145-172`, `ensure_groups_loaded`):
```python
async def ensure_groups_loaded(self, force: bool = False) -> None:
    ...
    try:
        r = await self.http.get(...)
        r.raise_for_status()
        ...
    except Exception as e:  # noqa: BLE001
        self._logger.warning("[signal] groups list failed: %s — ...", e)
```
Apply this same shape to the `/health` poll leg — a failed health poll must
log-and-continue (feed `fc1LastMsgTs=None` downstream), never raise and kill
the WS client's reconnect loop.

---

### `chamber/service.py` (service, composer)

**Analog:** `signal_io/receive_loop.py` (`ReceiveLoop`, full file, 144 lines)
for the start/stop lifecycle shape; `boot.py` for the top-level composition
convention.

**start()/stop() lifecycle to copy verbatim** (`receive_loop.py:110-143`):
```python
async def start(self) -> None:
    if self._task is not None:
        return  # already running
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
```
Any chamber background task manager (ws reconnect loop, tick timer) that
needs start/stop semantics should mirror this exactly — matches the
`persistence/pool.py` build/open ↔ start/stop convention referenced in
`receive_loop.py`'s own docstring (line 14).

---

### `boot.py` (MODIFY — composer wiring)

**Analog:** itself — surgical edit, not a new-file port. Current shape
(full file read, 154 lines) shows the exact pattern every new subsystem
follows:

**Subsystem construction + task registration pattern** (`boot.py:75-118`):
```python
http = httpx.AsyncClient()
signal_client = SignalClient(config=config, http=http)
...
pipeline = create_capture_pipeline(pool, signal_client, transcribe_client, config, gate=gate, extractor=extractor)

receive_loop = ReceiveLoop(signal_client, dispatch=pipeline["handle"], config=config)
await receive_loop.start()

retention_task = asyncio.create_task(retention_loop(pool, config))
confirm_task = asyncio.create_task(confirm_watchdog_loop(pool, signal_client, config))

commit_watchdog_task = None
if config.farmos_integration:
    farmos_client = create_farmos_client(...)
    commit_watchdog_task = asyncio.create_task(commit_watchdog_loop(pool, farmos_client, config))
```
Chamber's wiring must follow this exact shape: construct `ChamberConfig`
(composing the already-loaded `TenantConfig`), construct `WsClient` (reusing
`http`), start the heartbeat task via `asyncio.create_task`, and — per D-05 —
REPLACE the `dispatch=pipeline["handle"]` argument to `ReceiveLoop` with a
composite dispatcher (see RESEARCH.md Pattern 5, reproduced below) rather
than constructing a second `ReceiveLoop`.

**D-05 composite dispatch — exact illustrative shape from RESEARCH.md**
(NOT yet verified against final `chamber/service.py`, but the wiring
contract is fixed by the A3 single-`ReceiveLoop` guard):
```python
from farm_agent.signal_io import router as _router

async def _composite_dispatch(env: dict) -> None:
    source = _router.extract_source(env)
    dm = _router.classify_envelope(env)["dm"]
    text = dm.get("message") or ""
    parsed = chamber_snooze.parse_snooze_command(text, now_ms=int(time.time() * 1000))
    if parsed["ok"]:
        chamber_service.apply_snooze(parsed)
        if parsed.get("ack_text"):
            await signal_client.send(parsed["ack_text"])
        return
    await pipeline["handle"](env)

receive_loop = ReceiveLoop(signal_client, dispatch=_composite_dispatch, config=config)
```

**Shutdown symmetry pattern to extend** (`boot.py:134-151`): every
`asyncio.create_task` started above must get a matching
`.cancel()`/`await ...` / `except asyncio.CancelledError: pass` block in the
shutdown sequence — add the chamber heartbeat task and ws_client reconnect
task here, following the `commit_watchdog_task` conditional-task precedent
(lines 111-118, 146-151) if the chamber service is ever made optional.

**T-56-06-01 no-secrets-logged discipline** (`boot.py:120-124`):
```python
log.info("boot complete in %.2fs", elapsed)
log.info("capture pipeline live")
```
Any new chamber boot-log line must follow this same discipline — elapsed
time and lifecycle-only messages, never `ChamberConfig` fields (mirrors
`tenancy/tenant.py`'s "TenantConfig is not logged at boot" comment, line 12).

---

### `tenancy/tenant.py` (MODIFY — D-03 field relocation)

**Analog:** itself. Remove these 7 fields from the `TenantConfig` dataclass
body (lines 263-267, 288) and their corresponding parse+return-site lines
(367-371, 392, 417-421, 432):
```python
# --- Alerter tuning (numeric) ---
rh_target: float
rh_band: float
pi_offline_min: int
sensor_offline_min: int
heartbeat_hour: int
...
timezone: str
```
and `max_sends_per_hour: int` (line 271, under "Receive / send limits" —
note `receive_poll_sec` on the same line-group STAYS per D-03's field list,
only `max_sends_per_hour` moves). Also remove the corresponding
`_parse_float_env(env, "ALERT_RH_TARGET", 90.0)` etc. lines (367-371) and
`timezone = env.get("TZ") or "America/Toronto"` (line 392) and their
appearances in the `TenantConfig(...)` constructor call (417-421, 432).
Leave the surrounding fields (`receive_poll_sec`, `draft_*`,
`commit_watchdog_*`, `fidelity_csv_path`, `log_level`) untouched — surgical
removal only.

---

### `.lint-imports` (MODIFY — Pitfall 7 fix)

**Analog:** itself, full file (30 lines) already read above. Required
change to `source_modules` (lines 20-28):
```ini
source_modules =
    farm_agent.tenancy
    farm_agent.persistence
    farm_agent.extraction
    farm_agent.signal_io
    farm_agent.confirm
    farm_agent.farmos_client
    farm_agent.capture
    farm_agent.llm
```
→ correct to the real current package set (drop `farm_agent.llm`, which
doesn't exist; fix `farm_agent.farmos_client` → `farm_agent.farmos`):
```ini
source_modules =
    farm_agent.tenancy
    farm_agent.persistence
    farm_agent.extraction
    farm_agent.signal_io
    farm_agent.confirm
    farm_agent.farmos
    farm_agent.capture
```
Also update the header comment (lines 9-11) — the "chamber/ does not exist
yet ... Do NOT add import-linter to the pytest run until Phase 63" note is
now stale and should be replaced/removed since this IS Phase 63.

---

### `tests/test_foray_seam.py` (MODIFY — Pitfall 8 fix)

**Analog:** itself, full file (105 lines) already read above. Required
change to `FORAY_PACKAGES` (lines 23-29):
```python
# Phase 56 foray packages that exist now.
# signal_io, confirm, farmos_client, capture, llm are not created this phase.
FORAY_PACKAGES = [
    "farm_agent/tenancy",
    "farm_agent/persistence",
    "farm_agent/extraction",
]
```
→
```python
FORAY_PACKAGES = [
    "farm_agent/tenancy",
    "farm_agent/persistence",
    "farm_agent/extraction",
    "farm_agent/signal_io",
    "farm_agent/confirm",
    "farm_agent/farmos",
    "farm_agent/capture",
    "farm_agent/gate",
]
```
Update the stale comment on line 24 accordingly. Do not touch
`test_no_chamber_imports_in_foray`, `test_seam_trips_on_violation`, or
`test_seam_trips_on_bare_import_form` (lines 46-106) — those are correct
as-is and grep the (now-corrected) `FORAY_PACKAGES` list.

---

### `signal_io/client.py` (MODIFY — Pitfall 9 fix)

**Analog:** itself, full file (354 lines) already read above. `_current_cap()`
(lines 124-133) currently falls back to `self._config.max_sends_per_hour`:
```python
def _current_cap(self) -> int:
    """Return the effective cap (dynamic hook with fallback, signal.js:48-56)."""
    if self._get_max_sends_per_hour is not None:
        try:
            v = self._get_max_sends_per_hour()
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                return int(v)
        except Exception:  # noqa: BLE001
            pass
    return self._config.max_sends_per_hour
```
Per RESEARCH.md Pitfall 9 / Assumption A4 (verified against `config.js:175`,
`parseIntEnv(env, 'ALERT_MAX_SENDS_PER_HOUR', 20)`), replace the final line
with a hardcoded module-level constant so `client.py` no longer reads
`TenantConfig.max_sends_per_hour` at all:
```python
_DEFAULT_MAX_SENDS_PER_HOUR = 20  # matches config.js ALERT_MAX_SENDS_PER_HOUR default
...
    return _DEFAULT_MAX_SENDS_PER_HOUR
```
Then `boot.py` must always pass
`get_max_sends_per_hour=lambda: chamber_config.max_sends_per_hour` when
constructing the shared `SignalClient` (currently constructed at
`boot.py:78` with no hook at all — `SignalClient(config=config, http=http)`).
`tests/test_signal_ratecap.py::_make_client` needs a matching update (not
read this pass — flag for the executor to locate and adjust the no-hook
assertions).

---

## Shared Patterns

### Sole-env-reader / frozen-dataclass config
**Source:** `src/farm-agent/farm_agent/tenancy/tenant.py` (module docstring
lines 1-13, dataclass lines 214-221, loader lines 297-306)
**Apply to:** `chamber/config.py` (ChamberConfig)
```python
@dataclass(frozen=True)
class TenantConfig:
    """Immutable config for a single tenant. ..."""
    ...
def load(env: dict[str, str] | None = None) -> TenantConfig:
    if env is None:
        env = dict(os.environ)
    ...
```

### Doc-comment-as-spec ("Port of X.js — line N-M") convention
**Source:** every file in `signal_io/` and `tenancy/tenant.py` (e.g.
`client.py:1-27`, `router.py:1-19`, `retention.py:1-21`)
**Apply to:** ALL new chamber/ modules — every function/module must cite the
Node source file + line range + any dated bug-fix comment it preserves.
RESEARCH.md is explicit that these comments ARE the spec for Phase 64
parity replay.

### Async task lifecycle: create_task → cancel → await-CancelledError-swallow
**Source:** `boot.py:104-107, 136-151`; `signal_io/receive_loop.py:114-143`
**Apply to:** `chamber/heartbeat.py`, `chamber/ws_client.py` (reconnect
loop), `chamber/service.py` (if it wraps its own task)
```python
task = asyncio.create_task(some_loop(...))
...
task.cancel()
try:
    await task
except asyncio.CancelledError:
    pass
```

### Fail-open / graceful-degradation on liveness/optional I/O
**Source:** `signal_io/client.py:145-172` (`ensure_groups_loaded`),
`capture/retention.py:48-58`
**Apply to:** `chamber/rules.py` (None-as-no-trigger per RESEARCH Pattern 2),
`chamber/ws_client.py` (`/health` poll failures), `chamber/heartbeat.py`
(deferred-retry on empty summary, Pitfall 10)
```python
try:
    ...
except Exception as e:  # noqa: BLE001
    logger.warning("[module] X failed: %s", e)
    # continue / return None-as-no-trigger — never raise, never crash the loop
```

### Exactly-one-poller / no-second-client discipline (D-05, A3 guard)
**Source:** `boot.py:76, 99` ("T-58-03-05: exactly ONE ReceiveLoop started"),
`receive_loop.py:1-15`
**Apply to:** `boot.py` wiring of `chamber/service.py` — chamber must reuse
the single `SignalClient` and single `ReceiveLoop` constructed in `boot.py`;
never construct its own.

### PII masking in logs
**Source:** `tenancy/tenant.py::mask_number` (lines 195-207), used
throughout `client.py`/`router.py`/`receive_loop.py`
**Apply to:** any chamber log line that includes a phone number (Security
Domain, Information Disclosure row in RESEARCH.md).

## No Analog Found (partial — Node is the only source of truth for shape)

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `chamber/rules.py` (behavioral content, not module shape) | utility | transform | No existing Python detector-FSM code in this domain; behavior must come from `src/agents/alerter/src/rules.js` (110 lines) directly — module *shape* (pure fn, injected config, doc-comment convention) borrowed from `router.py` as noted above. |
| `chamber/state.py` (behavioral content) | service | event-driven | No existing Python FSM; behavior must come from `src/agents/alerter/src/state.js` (718 lines) — the single highest-risk file in the port per RESEARCH.md (`resolve_effective_config`'s Tier A/B/C). |
| `chamber/message.py` (behavioral content) | utility | transform | No existing Python farmer-facing-time-formatting code beyond `mask_number`'s shape; behavior from `src/agents/alerter/src/message.js` (155 lines). |
| `chamber/snooze.py` (behavioral content) | utility | transform | No existing Python grammar parser beyond `router.py`'s narrower keyword-detection regex; full grammar from `src/agents/alerter/src/snooze.js` (63 lines). |

## Metadata

**Analog search scope:** `src/farm-agent/farm_agent/**` (all 8 existing
packages: tenancy, persistence, extraction, signal_io, confirm, farmos,
capture, gate), `src/farm-agent/boot.py`, `src/farm-agent/.lint-imports`,
`src/farm-agent/tests/test_foray_seam.py`. Node parity source scanned for
file sizes only (not fully read — RESEARCH.md already contains full
Node→Python line-level mappings; this pattern map focuses on Python-side
shape/style analogs per the task brief).
**Files scanned:** `tenancy/tenant.py` (full, 435 lines), `signal_io/client.py`
(full, 354 lines), `signal_io/router.py` (full, 187 lines),
`signal_io/receive_loop.py` (full, 143 lines), `boot.py` (full, 154 lines),
`.lint-imports` (full, 30 lines), `tests/test_foray_seam.py` (full, 105
lines), `capture/retention.py` (full, 60 lines).
**Pattern extraction date:** 2026-07-13
