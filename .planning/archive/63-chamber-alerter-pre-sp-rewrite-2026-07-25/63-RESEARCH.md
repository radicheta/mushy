# Phase 63: Chamber Alerter - Research

**Researched:** 2026-07-13
**Domain:** Node→Python port of an asyncio WebSocket alerting daemon (FSM + TZ formatting + Foray-seam CI enforcement)
**Confidence:** HIGH (mapping/pitfalls verified against both live Node source and live Python source in this repo); MEDIUM on exact asyncio idiom choices (Claude's Discretion per CONTEXT.md)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-00 (canonical clarification):** ROADMAP SC3 wording — *"the `chamber/` package has
  zero imports from any non-chamber Foray package"* — is **INVERTED** relative to the actual
  Phase-56 gate. The enforced contract (`.lint-imports` `foray-seam` + `tests/test_foray_seam.py`)
  is a `forbidden` contract in the OPPOSITE direction: **Foray packages must NOT import
  `farm_agent.chamber`**. `chamber/`, as the composing app, is **free to import** `signal_io`,
  `persistence`, `tenancy`, etc. The seam test file itself documents this "ROADMAP token
  divergence." Plan against the real gate direction, not the SC3 prose. Phase 63 activates the
  secondary gate: add `chamber/` to the pytest run so `.lint-imports` is enforced (per
  `.lint-imports` header note "Do NOT add import-linter to the pytest run until Phase 63").

- **D-01 — Port the full Tier A/B/C effective-config resolver.** Reproduce
  `resolveEffectiveConfig(state, envConfig, nowMs)` verbatim: detectors consume the
  **effective** config, never raw env. Layers:
  - **Tier A (mode-anchored):** `rhTarget = currentMode.target_humidity * 100`, `rhBand` from the
    live ROS `mode` message received over the WS bridge — applies only when mode is FRESH
    (`modeAge <= modeStaleMin`, ws connected).
  - **Tier B (per-mode override):** `oobN`, `oobWindowMin`, `cooldownMin`, `criticalCooldownMin`,
    `humidifierStuckMin` from `alerterOverrides[mode.name]`.
  - **Tier C (global override):** `piOfflineMin`, `sensorOfflineMin`, `heartbeatHour`,
    `maxSendsPerHour` from `alerterGlobals` — apply **independent of mode freshness** (e.g.
    `piOfflineMin` must hold precisely when fc1 is offline / ws disconnected).
  - **Freshness / cold-start gate:** `freshness = {state: fresh|stale|cold, source: mode|env}`;
    stale/cold falls back to env config. This freshness state ALSO feeds `isRhOob` (stale ⇒
    suspend RH rule — the 2026-05-07 false-CRITICAL guard).
  - Rationale: this dynamic RH target IS the live prod behavior (pinning→fruiting setpoint
    moves), and Phase 64's ≥95% parity gate requires it. Static-only would count as a parity
    failure. See memory `dynamic_rh_target_groundwork`, `alerter_rh_two_source_bug`.

- **D-02 — Chamber config lives in a chamber-local `ChamberConfig`, not TenantConfig.** New
  `chamber/config.py` owns ALL alerter knobs. `ChamberConfig` reads only **secrets + shared
  identity** (signal_sender, signal_recipient, signal_api_url, tenant_id, timescale creds) from
  the Foray `TenantConfig`. Keeps the extractable Foray island genuinely free of mushy-private
  alerter concerns (consistent with the ChamberConfig choice).

- **D-03 — MOVE the 7 alerter knobs already sitting in `TenantConfig` into `ChamberConfig`.**
  `rh_target`, `rh_band`, `pi_offline_min`, `sensor_offline_min`, `heartbeat_hour`,
  `max_sends_per_hour`, `timezone` are alerter-only (no extraction/confirm/farmos package reads
  them) and must relocate to `ChamberConfig`. This touches `TenantConfig` + its Phase-56 tests —
  update those references. ChamberConfig then owns the full alerter knob set, including the ones
  not yet ported: `oob_n`, `oob_window_min`, `cooldown_min`, `critical_cooldown_min`,
  `humidifier_stuck_min`, `sht30_enabled`, `scd41_enabled`, `sensor_flap_min_sec`,
  `mode_stale_min`, `mode_boot_grace_ms`, `bridge_ws_url`, `bridge_health_url`, `dashboard_url`,
  `receive_poll_sec`.
  - **Verify no orphaned references:** grep the ported Foray packages (signal_io, confirm,
    extraction, farmos_client, persistence) for reads of these 7 fields before moving — if any
    non-chamber package reads one, that read is itself a latent mis-layering to flag.

- **D-04 — TZ fix (CHM-02): ChamberConfig-driven, default `America/Montevideo`, `TZ` env may
  override.** Message-formatting reads `ChamberConfig.timezone`; the code **default flips
  Toronto→Montevideo**. Preserves Node's config-driven formatting shape (best parity for
  Phase 64) and keeps the knob for future Foray multi-tenant. The *actual* bug fix (per memory
  `alerter_tz_toronto_legacy`): route **ALL** farmer-facing time formatting through the
  configured zone via `ZoneInfo` — the legacy `hhmm()` ignored config entirely and emitted UTC.
  A snapshot test pins a formatted alert to Montevideo/UYT (UTC-3), satisfying SC2. This TZ
  change is **pre-declared as an intentional parity delta** for Phase 64.

- **D-05 — Signal I/O: reuse, do not duplicate.** chamber **reuses** `signal_io.client` for
  outbound sends and hooks the shared `signal_io.receive_loop`/`router` for INBOUND snooze/mute
  commands (the seam permits chamber→signal_io). One Signal number, one receive loop (built in
  Phase 57) — a second client would double-poll and conflict. Planner: define how the router
  dispatches snooze/mute text to a chamber handler.

- **D-06 — Alert FSM state is IN-MEMORY (Node parity).** Snooze/cooldown/`humidifierOnSinceMs`
  reset on restart, exactly like Node. Required for the Phase-64 parity gate; persisting would
  itself be a parity delta. Durable-snooze deferred to a follow-on only if the farmer hits it.

- **D-07 — Port ALL 6 alert types:** `rh, sensor, pi, humidifier, sht30, scd41`. The roadmap
  goal's "4" is shorthand. `sht30_enabled`/`scd41_enabled` are live prod flags (SHT30 physically
  disconnected since 2026-04-11, muted via flag, not removed). Full parity needed for Phase 64.
  Also carry the `sensor_flap_min_sec` single-tick flap floor (2026-05-12) and the Phase-29/46
  offline-blindness gates on humidifier-stuck.

### Claude's Discretion

- Async mechanics: asyncio task loop + `ZoneInfo` for the heartbeat (replacing Node
  `setInterval` + `Intl.DateTimeFormat`); WS reconnect/backoff shape; how `resolveEffectiveConfig`
  is structured in Python. Planner/executor decide, constrained by parity with Node outputs.

### Deferred Ideas (OUT OF SCOPE)

- **Durable snooze/cooldown across restart** — considered (D-06); deferred. Only revisit if the
  farmer is bitten by a restart un-muting alerts. Would be a Phase-64 parity delta if added now.
- Parity validation against the golden corpus — Phase 64.
- Cutover / stopping the Node alerter — Phase 65.
- Any new alerting capability beyond Node parity.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CHM-01 | The ROS-bridge WebSocket client + alert state machine (RH out-of-band, pi-offline/chamber-dark, sensor staleness, humidifier-stuck) with cooldown/snooze/mute and daily heartbeat are reproduced in the `chamber/` package. | Full Node→Python mapping tables for `rules.js`/`state.js`/`bridge-client.js`/`heartbeat.js`/`snooze.js` below; `websockets` library recommendation + reconnect pattern; FSM transition table; D-05 router-dispatch wiring. |
| CHM-02 | Farmer-facing time/number formatting uses `ZoneInfo('America/Montevideo')` (Toronto bug fixed) and round-number formatting; TZ change is a pre-declared parity delta. | `message.js` → `message.py` mapping (`fmt_num`, `hhmm`, `fmt_duration`, `fmt_relative`); exact call-site list where `hhmm()`/`Intl.DateTimeFormat` must route through `ZoneInfo(ChamberConfig.timezone)`; Validation Architecture snapshot test spec. |
</phase_requirements>

## Summary

Phase 63 is a **behavior-preserving port**, not a redesign. The Node alerter (`src/agents/alerter/src/{rules,state,bridge-client,heartbeat,snooze,message,config}.js`) is ~1400 lines of pure-function detectors plus a hand-rolled FSM driven by discrete events (`humidity`, `mode_update`, `pi_liveness`, `tick`, `heartbeat_tick`, `snooze`, ...). Every detector already documents its own historical bug fix in a comment (2026-05-07 false-CRITICAL, 2026-05-12 flap-floor, Phase-46 chamber-dark hard-3-min threshold) — these comments **are** the spec and must be preserved as Python docstrings citing the same dates, because Phase 64's parity gate will replay real historical traffic against both.

On the Python side, the `chamber/` package does not exist yet — this phase creates it from scratch inside an already-mature Foray-island codebase (Phases 56-62 shipped `tenancy`, `persistence`, `signal_io`, `capture`, `confirm`, `farmos`, `gate`, `extraction`). Two concrete pre-existing seams matter enormously for planning:

1. **`signal_io.client.SignalClient` already has a `get_max_sends_per_hour` hook** (`farm_agent/signal_io/client.py:59,126-133`) designed for exactly this override pattern — but its **fallback** path reads `self._config.max_sends_per_hour` directly off `TenantConfig`. D-03 moves `max_sends_per_hour` OUT of `TenantConfig` into `ChamberConfig`. This is the exact "orphaned reference" D-03 asks researchers to flag: `signal_io` (a Foray package) currently depends on an alerter-tier field. The fix is mechanical (give `SignalClient._current_cap()` a hardcoded fallback constant and always wire the hook from `boot.py`), but it must be an explicit task or Phase 64 parity will break silently.

2. **`.lint-imports` is currently broken against the real codebase** — its `source_modules` list references `farm_agent.farmos_client`, which does not exist (the real package is `farm_agent.farmos`), and omits `signal_io`, `confirm`, `farmos`, `capture` entirely while listing a nonexistent `llm` package. Running `lint-imports --config .lint-imports` today **hard-errors** ("Module 'farm_agent.farmos_client' does not exist") rather than silently skipping. This was verified live in this research session. D-00's "activate `.lint-imports`" instruction is not just "flip a switch" — the contract file itself needs a source_modules correction before it can run, let alone pass.

**Primary recommendation:** Build `chamber/` as a set of pure-function modules (`rules.py`, `state.py`, `message.py`, `snooze.py`) mirroring the Node files 1:1 by function signature, wired together by an async `chamber/service.py` that owns the WS client (via the `websockets` library), the heartbeat asyncio task, and registers a dispatch handler with the existing `signal_io.router`/`ReceiveLoop`. Fix `.lint-imports` source_modules and `test_foray_seam.py`'s `FORAY_PACKAGES` list to the real, current package set as part of the same phase that activates them.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| WS bridge client (fc1 telemetry ingest) | API/Backend (chamber daemon) | — | Chamber is a backend asyncio daemon consuming the ROS-bridge WS server; no browser/CDN tier involved. |
| Alert detectors (rules.py) | API/Backend | — | Pure functions, no I/O; owned by chamber/ (mushy-private, per D-00/D-02). |
| Alert FSM (state.py) | API/Backend | — | In-memory process state (D-06); owned by chamber/. |
| Effective-config resolver (Tier A/B/C) | API/Backend | — | Consumes cached WS-delivered mode/override messages; pure function within chamber/. |
| Outbound Signal send | API/Backend | Foray (`signal_io.client`) | Chamber reuses the Foray `SignalClient` singleton (D-05) — chamber owns *when* to send, Foray owns *how* to send safely (rate cap, quote validation, persistence). |
| Inbound snooze/mute parsing | API/Backend | Foray (`signal_io.receive_loop`/`router`) | Foray owns envelope reception + whitelist gating; chamber owns snooze grammar semantics and FSM mutation (D-05). |
| TZ-aware time formatting | API/Backend | — | `message.py` formatting happens server-side before the Signal send; no client tier renders it. |
| Config (ChamberConfig) | API/Backend | — | Frozen dataclass, boot-time load, mirrors `TenantConfig` pattern (D-02/D-03). |
| Foray-seam CI enforcement | API/Backend (build/test tooling) | — | `.lint-imports` + `tests/test_foray_seam.py` are pytest-time static checks, not runtime. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `websockets` | 16.1 (verified via `pip install` + slopcheck, 2026-07-13) | Async WebSocket client for the ROS-bridge connection, replacing Node's `ws` package | De facto standard asyncio-native WS client for Python; stdlib-adjacent, actively maintained, used with `async for message in websocket:` reconnect-friendly idiom `[ASSUMED: API shape from training knowledge — verify exact reconnect idiom against the installed 16.1 docs before writing the WS client task, since the `websockets` library changed its top-level client API across major versions (legacy `websockets.connect` context-manager style vs newer `websockets.asyncio.client.connect`)]` |
| `zoneinfo` (stdlib) | Python 3.12 stdlib | TZ-aware local-time formatting (`America/Montevideo`) replacing `Intl.DateTimeFormat` | `[VERIFIED: ran `ZoneInfo('America/Montevideo')` in this session — resolved to UTC-3 correctly using the host's system tzdata]`. No new dependency needed for the *interpreter* — but see `tzdata` below for portability. |
| `tzdata` | 2026.3 (verified via `pip install` + slopcheck OK, 2026-07-13) | Bundles the IANA tz database as a pip package so `ZoneInfo` works inside a minimal/slim Docker image that lacks system tzdata | `[CITED: Python docs — zoneinfo — "if system tz data is not available, tzdata... can be installed" — https://docs.python.org/3/library/zoneinfo.html]`. Recommended defensively: the `farm-agent` Dockerfile's base image (Phase 56) was not audited in this research pass for system tzdata presence; add `tzdata` to `pyproject.toml` `dependencies` rather than assume the container has `/usr/share/zoneinfo`. |
| `asyncio` (stdlib) | Python 3.12 stdlib | Task loop for heartbeat scheduler, WS reconnect/backoff, tick timer | Already the concurrency model for the entire `farm_agent` package (`boot.py`, `receive_loop.py`, `retention.py`). |

**Installation:**
```bash
# from src/farm-agent/
uv add websockets tzdata
```

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `httpx` (already a dependency) | ≥0.28 (pyproject-pinned) | `/health` poll (`fc1LastMsgTs`) mirrors Node's `fetch(healthUrl)` | Already used everywhere else in `farm_agent` (`signal_io.client`, `capture.transcribe_client`) — reuse the shared `httpx.AsyncClient`, do not construct a second one for chamber. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `websockets` | `aiohttp` (has WS client support) | `aiohttp` is heavier (also an HTTP server framework) and would be a second HTTP stack alongside the already-used `httpx`; no reason to add it just for the WS leg. `websockets` is the narrower, purpose-fit choice. |
| Hand-rolled reconnect/backoff loop | `websockets`'s built-in reconnecting iterator (`websockets.asyncio.client.connect` used as an async iterator auto-reconnects) | Node's `bridge-client.js` hand-rolls exponential backoff (1s→30s doubling) with explicit state (`backoffMs`, `reconnectTimer`). For byte-for-byte parity of reconnect timing (relevant to the "pi-offline fires within configured timeout window" SC1), a **hand-rolled** backoff loop mirroring Node's exact doubling schedule is safer than relying on library-default reconnect semantics, which may differ in timing. Recommend porting Node's backoff loop explicitly rather than trusting a library default. |

**Version verification:** `websockets` and `tzdata` versions above were confirmed to exist and install cleanly via `uv run --with slopcheck slopcheck install websockets tzdata` (both returned `[OK]`) followed by a live `pip install` in this session (2026-07-13) — see Package Legitimacy Audit. Package **names** are `[ASSUMED]` per the provenance rule (drawn from training knowledge, not Context7/official-docs-first), despite passing the registry check.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `websockets` | PyPI | Long-established (Python asyncio-era library; exact first-release date not verified in this session) | High (used across the asyncio ecosystem) `[ASSUMED — not independently queried via PyPI stats API this session]` | https://github.com/python-websockets/websockets `[ASSUMED]` | `[OK]` (verified live via `slopcheck install`, 2026-07-13) | Approved |
| `tzdata` | PyPI | Long-established (maintained by the CPython core team's tz working group) `[ASSUMED]` | High `[ASSUMED]` | https://github.com/python/tzdata `[ASSUMED]` | `[OK]` (verified live via `slopcheck install`, 2026-07-13) | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

Both packages also passed a live `pip install` in this sandbox (2026-07-13), and `websockets 16.1` / `tzdata 2026.3` are consistent with actively-maintained major-version-current releases. Because package identity was sourced from training knowledge rather than Context7/official docs, per the provenance rule both remain `[ASSUMED]` in the Standard Stack table even though the registry+slopcheck check passed — the planner should insert a lightweight `checkpoint:human-verify` (or at minimum a `uv add` + `uv run python -c "import websockets"` smoke check) before relying on the exact API surface assumed in the Code Examples section below.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────┐
                         │   ROS-bridge (mission_control │
                         │   _bridge, existing service)  │
                         │   ws://…:8081  +  /health     │
                         └───────────┬──────────┬────────┘
                                     │ WS msgs  │ HTTP GET
                                     ▼          ▼
                    ┌────────────────────────────────────────┐
                    │        chamber/service.py (asyncio)      │
                    │  ┌────────────┐   ┌───────────────────┐ │
                    │  │ ws_client  │──▶│ event dispatch     │ │
                    │  │ (reconnect)│   │ (mirrors state.js   │ │
                    │  └────────────┘   │  `transition()`)    │ │
                    │  ┌────────────┐   │        │            │ │
                    │  │health_poll │──▶│        ▼            │ │
                    │  │(10s timer) │   │  ┌────────────────┐ │ │
                    │  └────────────┘   │  │ rules.py        │ │ │
                    │  ┌────────────┐   │  │ (pure detectors)│ │ │
                    │  │heartbeat   │──▶│  └───────┬────────┘ │ │
                    │  │scheduler   │   │          ▼          │ │
                    │  │(asyncio    │   │  ┌────────────────┐ │ │
                    │  │ loop)      │   │  │ state.py FSM    │ │ │
                    │  └────────────┘   │  │ OK→PENDING→     │ │ │
                    │                   │  │ FIRING→(SNOOZED)│ │ │
                    │                   │  └───────┬────────┘ │ │
                    │                   └──────────┼──────────┘ │
                    │                              ▼            │
                    │                     ┌──────────────────┐ │
                    │                     │ message.py        │ │
                    │                     │ (TZ + fmtNum)     │ │
                    │                     └────────┬──────────┘ │
                    └──────────────────────────────┼────────────┘
                                                     │ .send(body)
                                                     ▼
                          ┌──────────────────────────────────────┐
                          │  signal_io.client.SignalClient (SHARED │
                          │  singleton, constructed once in boot.py│
                          │  — chamber does NOT build its own)     │
                          └──────────────────┬─────────────────────┘
                                              │ outbound
                                              ▼
                                        Signal REST API
                                              ▲
                                              │ inbound envelopes
                          ┌──────────────────────────────────────┐
                          │ signal_io.receive_loop.ReceiveLoop     │
                          │ (SHARED singleton — A3: exactly one)   │
                          │  dispatch(envelope) ──▶ boot.py wires  │
                          │  a composite dispatcher: router checks │
                          │  'command' trigger (mute/snooze/quiet) │
                          │  → chamber.snooze_handler(envelope)    │
                          │  else → pipeline["handle"] (capture)   │
                          └────────────────────────────────────────┘
```

### Recommended Project Structure

```
src/farm-agent/farm_agent/chamber/
├── __init__.py
├── config.py          # ChamberConfig frozen dataclass (D-02/D-03) — mirrors tenancy/tenant.py
├── rules.py            # port of rules.js — pure detector functions
├── state.py             # port of state.js — FSM, resolveEffectiveConfig, transition()
├── message.py           # port of message.js — fmt_num/fmt_duration/fmt_relative/hhmm + formatters
├── snooze.py             # port of snooze.js — parse_snooze_command grammar
├── heartbeat.py          # port of heartbeat.js — asyncio-loop daily scheduler
├── ws_client.py           # port of bridge-client.js — websockets client + /health poll + backoff
└── service.py              # composes the above; exposes register(boot) or run() entrypoint

src/farm-agent/tests/chamber/
├── test_rules.py
├── test_state.py
├── test_message.py          # includes the D-04 Montevideo snapshot test (SC2)
├── test_snooze.py
├── test_config.py
├── test_ws_client.py         # reconnect/backoff unit tests (fake WS server or mocked)
└── test_service_wiring.py     # boot.py integration: dispatch composition, seam compliance
```

### Pattern 1: Pure detector functions, config injected (not read from globals)

**What:** Every `rules.js` function takes `config` (or `effective` config) as an explicit parameter — never reaches into module-level state. Preserve this exactly: Python `rules.py` functions must be pure, side-effect-free, and take a config object/dict as a parameter.
**When to use:** All 5 detector functions (`is_rh_oob`, `is_sensor_error`, `is_pi_offline`, `is_humidifier_stuck`, `is_sensor_silent`).
**Example:**
```python
# Source: port of src/agents/alerter/src/rules.js (this repo, read 2026-07-13)
from dataclasses import dataclass

FC1_DARK_THRESHOLD_MS = 3 * 60_000  # Phase 46 D-09: hard-coded, NOT config-driven

def is_rh_oob(humidity: float, effective: "EffectiveConfig") -> bool:
    """Phase 29 D-03: stale freshness suspends the rule (2026-05-07 false-CRITICAL guard)."""
    if effective.freshness is not None and effective.freshness.state == "stale":
        return False
    return abs(humidity - effective.rh_target) > effective.rh_band
```

### Pattern 2: `None`/absent liveness inputs mean "no trigger" (graceful degradation), never coerced to falsy-zero

**What:** Node uses `!= null` (catches both `undefined` and `null`) as the gate for "have we ever observed this signal." A Python port that naively does `if not fc1_last_msg_ts:` would misfire on `fc1_last_msg_ts == 0` (a legitimate epoch-adjacent timestamp, unlikely but structurally wrong) and, more importantly, would NOT distinguish "never observed" from "observed and falsy." Preserve `is not None` checks exactly where Node used `!= null` / `!== undefined`.
**When to use:** `is_pi_offline`'s `fc1_last_msg_ts`, `is_humidifier_stuck`'s `humidifier_last_msg_ts`/`ws_connected`, `resolveEffectiveConfig`'s `state.current_mode`.
**Example:**
```python
# Source: port of rules.js isPiOffline (lines 47-69, read 2026-07-13)
def is_pi_offline(*, ws_connected, ros_connected, now_ms, ws_last_connected_ms,
                   ros_disconnected_since_ms, fc1_last_msg_ts, config) -> bool:
    threshold_ms = config.pi_offline_min * 60_000
    if not ws_connected and ws_last_connected_ms is not None:
        if now_ms - ws_last_connected_ms > threshold_ms:
            return True
    if ros_connected is False and ros_disconnected_since_ms is not None:
        if now_ms - ros_disconnected_since_ms > threshold_ms:
            return True
    # fc1_last_msg_ts is None (old caller) or explicitly None (old bridge, no fc1 block)
    # -- graceful degradation, NOT a trigger. Hard-coded 3-min threshold (Phase 46 D-09).
    if fc1_last_msg_ts is not None:
        if now_ms - fc1_last_msg_ts > FC1_DARK_THRESHOLD_MS:
            return True
    return False
```

### Pattern 3: FSM `driveAlertType` is generic, alert-type-parameterized

**What:** `state.js`'s `driveAlertType(entry, alertType, oobNow, fields, now, config)` is the single state-transition function reused by all 6 alert types (with per-call-site `oobN`/`oobWindowMin` overrides for the fast-firing `pi`/`sensor`/`sht30`/`scd41` types, which set `{oobN: 1, oobWindowMin: 0}` to bypass the generic debounce). Port this as ONE function, not six copy-pasted FSMs.
**When to use:** All 6 alert types route through the same `drive_alert_type()`.

### Pattern 4: `resolveEffectiveConfig` gates on `hasModeContext`, not unconditionally

**What:** Node only routes through `resolveEffectiveConfig` once the alerter has EVER received a `mode_update`/`overrides_update`/`globals_update` event (`hasModeContext(state)`). Before that, raw `envConfig` (now: `ChamberConfig`) is fed directly to detectors. This preserves pre-Phase-29 test/production semantics and matters for cold-boot behavior — a naive "always call resolveEffectiveConfig" port would diverge during the first few seconds after boot before any mode message arrives, when `resolveEffectiveConfig` would return `freshness.state == 'cold'` anyway, but the `hasModeContext` gate is a distinct code path Node takes and Phase 64 parity will surface any divergence in cold-start replay windows.
**When to use:** Every FSM event handler (`humidity`, `pi_liveness`, `tick`) must check `has_mode_context(state)` before deciding whether to call `resolve_effective_config` or use raw config.

### Pattern 5: `boot.py` composite-dispatch wiring for D-05

**What:** `receive_loop.ReceiveLoop` accepts exactly ONE `dispatch: Callable[[dict], Awaitable[None]]` (A3 dual-poller guard, T-58-03-05). Chamber's snooze/mute handling must be composed INTO that single callable, not registered as a second loop.
**When to use:** In `boot.py`, replace `dispatch=pipeline["handle"]` with a small async composite function:
```python
# Illustrative — NOT verified against final chamber/service.py shape (planner/executor decide exact wiring)
from farm_agent.signal_io import router as _router

async def _composite_dispatch(env: dict) -> None:
    source = _router.extract_source(env)
    dm = _router.classify_envelope(env)["dm"]
    text = dm.get("message") or ""
    parsed = chamber_snooze.parse_snooze_command(text, now_ms=int(time.time() * 1000))
    if parsed["ok"]:
        chamber_service.apply_snooze(parsed)  # mutates in-memory FSM state
        if parsed.get("ack_text"):
            await signal_client.send(parsed["ack_text"])
        return
    await pipeline["handle"](env)

receive_loop = ReceiveLoop(signal_client, dispatch=_composite_dispatch, config=config)
```
Note: Node's `snooze.js` `parseSnoozeCommand` already handles "let anything else fall through" (`return { ok: false, reply: null }`) — the composite dispatcher's fallthrough-to-pipeline branch mirrors that shape.

### Anti-Patterns to Avoid

- **Reading `ChamberConfig` fields directly inside `rules.py` detector functions instead of the `effective` config parameter:** breaks Tier A/B/C override behavior — the whole point of D-01 is that live mode messages override static config under the detectors' feet.
- **Constructing a second `SignalClient` or a second `ReceiveLoop` for chamber:** violates D-05 and T-58-03-05 (A3 dual-poller guard); will double-poll signal-cli and corrupt attribution per `feedback_verify_signal_send_attribution`.
- **Persisting FSM state to Postgres "for safety":** violates D-06 (explicit parity requirement — Node resets on restart; a persisted FSM is itself a parity delta that Phase 64 would need to separately account for).
- **Using `datetime.now(tz=...)` with a hardcoded `timezone.utc` anywhere in `message.py`:** this is the exact class of bug D-04 fixes (Node's `hhmm()` did `new Date(tsMs).toISOString()` — always UTC, ignoring `config.timezone`). Every farmer-facing timestamp render in `message.py` must go through `datetime.fromtimestamp(ts_ms / 1000, tz=ZoneInfo(config.timezone))`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TZ-aware local time / DST-correct hour extraction | Manual UTC-offset arithmetic | stdlib `zoneinfo.ZoneInfo` + `datetime.astimezone()` | Handles DST transitions correctly (Uruguay currently does not observe DST as of training-knowledge cutoff, `[ASSUMED — verify current Uruguay DST status if this matters for a specific historical replay date in Phase 64]`, but the general pattern must still be DST-safe for any future tenant). |
| Async WebSocket reconnect | Hand-rolled socket state machine from scratch | `websockets` library's connection object + Node-mirrored explicit backoff loop (Pattern in Alternatives Considered above) | `websockets` handles the wire protocol (framing, ping/pong, close handshake) correctly; hand-roll only the backoff *timing* to match Node's exact schedule. |
| Rate-capped outbound Signal sends | A second rate limiter inside chamber | The existing `signal_io.client.SignalClient` (`_current_cap`/`_prune_history`/`asyncio.Lock`) via the `get_max_sends_per_hour` hook | Already built (Phase 57), already has a documented Phase-64 parity delta note about slot-reservation-before-POST — reuse it rather than building a second cap enforcement point that could double-count or diverge. |
| Snooze/mute command grammar parsing | A new regex ad hoc | Direct port of `snooze.js`'s `STRICT`/`SIMPLE` regexes + `VALID_DURATIONS` map | The exact regex shape (anchored, case-insensitive, whitelist of 6 alert types + "all") is the parity target; a "cleaner" reimplementation risks accepting/rejecting different inputs than Node did historically. |

**Key insight:** Nearly everything in this domain (WS reconnect, rate limiting, TZ math) has a correct, boring, off-the-shelf answer. The actual hard part of Phase 63 is **behavioral fidelity to six years of accumulated bug-fix comments in `rules.js`/`state.js`**, not novel engineering — treat every comment referencing a date or a "999.NN" ticket number as a load-bearing spec line, not incidental color.

## Common Pitfalls

### Pitfall 1: The stale-RH-suspend guard is easy to invert or drop silently

**What goes wrong:** A straightforward re-implementation of `isRhOob` might check `freshness.state === 'fresh'` (require freshness to *positively* be fresh) instead of Node's actual check (`freshness.state === 'stale'` → suppress; everything else, including `'cold'` and legacy callers with no `freshness` sub-object at all, passes through to the real comparison).
**Why it happens:** The Node comment says "legacy callers passing `{rhTarget, rhBand}` without a `freshness` sub-object are treated as fresh (gate is opt-in via short-circuit)" — this is backwards-compat behavior for OLD test fixtures, not a general safety default. A Python port without pre-29 legacy call sites might reasonably assume every caller always supplies `freshness`, but the *cold* state must NOT suspend the rule (only `stale` does) — this is easy to get backwards.
**How to avoid:** Port the exact three-way branch: `freshness is None` → proceed (compare); `freshness.state == 'stale'` → suppress; `freshness.state in ('fresh', 'cold')` → proceed (compare).
**Warning signs:** A parity-replay divergence specifically during the 2026-05-07-style event window (fc1 outage, mode data going stale) where Python fires RH alerts Node didn't, or vice versa.

### Pitfall 2: The pi-offline "chamber-dark" 3-minute threshold is a SEPARATE constant, not `config.piOfflineMin`

**What goes wrong:** `isPiOffline`'s third OR-branch (fc1LastMsgTs staleness) uses a **hard-coded** `FC1_DARK_THRESHOLD_MS = 3 * 60000`, explicitly NOT `config.piOfflineMin` (which defaults to 5 min and is sized for the ws/ros liveness branches). A port that reuses `effective.pi_offline_min` for all three OR-branches will make chamber-dark detection ~40% slower than Node (5min vs 3min), which is exactly the kind of thing SC1 ("fires within the configured timeout window") is designed to catch — but only if the test actually measures the fc1-dark path specifically, not the ws/ros-disconnect path.
**Why it happens:** It looks like it "should" be config-driven since the other two branches are; the comment explains why it isn't (chamber-dark must fire fast; legacy `piOfflineMin=15` from `fc_config.yaml` was sized for the slower branch).
**How to avoid:** Keep `FC1_DARK_THRESHOLD_MS` as a literal module constant in `rules.py`, separate from any `ChamberConfig` field.
**Warning signs:** SC1's induced-bridge-disconnect test fires at ~5min instead of ~3min.

### Pitfall 3: `pi` alert type bypasses the generic oobN/oobWindowMin debounce entirely

**What goes wrong:** `state.js`'s `pi_liveness` and `tick` handlers construct `piCfg = { ...effective, oobN: 1, oobWindowMin: 0 }` before calling `driveAlertType` — this is intentional (Phase 46 D-10 comment: the 3-min hard threshold in `isPiOffline` IS the flap protection; applying the generic 5-count/8-min debounce ON TOP would push FIRING to T0+~11min). The same override pattern (`oobN: 1, oobWindowMin: 0`) is reused for `sensor`, `sht30`, `scd41` — but NOT for `rh` or `humidifier`, which keep the real `effective.oobN`/`effective.oobWindowMin`.
**Why it happens:** Easy to miss because it's constructed inline as an object spread at each of ~6 call sites in `state.js`, not a single named constant.
**How to avoid:** Extract this as one shared Python helper (e.g., `_fast_fire_config(effective) -> EffectiveConfig` returning a copy with `oob_n=1, oob_window_min=0`) used consistently at all 6 call sites (`sensor_health` handler ×1 error branch, `sht30`/`scd41` branches ×2, `sensor_freshness` handler, `pi_liveness` handler, `tick` handler's pi/sht30/scd41 branches) — but do NOT apply it to `rh` or `humidifier`.
**Warning signs:** `sensor`/`pi`/`sht30`/`scd41` alerts firing on the 5th occurrence over 8 minutes instead of on the first occurrence (parity replay would show systematically delayed CRITICAL alerts).

### Pitfall 4: `sensor_flap_min_sec` gates only the Pi-side `xxx_fresh='false'` FLAG path, not the slow-silence (`isSensorSilent`) path

**What goes wrong:** The 2026-05-12 flap-floor fix (`piFlagStale` helper in `sensor_health`/`sensor_freshness` handlers) applies ONLY to the fast "Pi explicitly said `sht30_fresh: 'false'`" trigger. The independent `isSensorSilent` check (elapsed time since last freshness signal exceeds `sensorOfflineMin` **minutes**, not seconds) is unchanged and NOT subject to the flap floor. A port that applies `sensor_flap_min_sec` uniformly to both paths would suppress legitimate slow-silence detections.
**Why it happens:** Both paths feed into the same `stale = (condition_a) or (condition_b)` boolean and it's easy to conflate them as "the same staleness check" when porting.
**How to avoid:** Keep the two conditions as textually separate as Node does: `piFlagStale(lastSeenMs)` (seconds-scale, `config.sensorFlapMinSec`) OR `isSensorSilent(...)` (minutes-scale, `config.sensorOfflineMin`), combined with `or`, never merged into one threshold.
**Warning signs:** A sensor going hard-silent (no `_fresh` flag messages at all, not even a `'false'` one) fails to trigger the watchdog because the port waits for the flap floor to elapse on a signal that never arrives.

### Pitfall 5: `humidifier-stuck`'s offline-blindness gates check THREE things in a specific order, and order matters for the `sensorOfflineMin` default fallback

**What goes wrong:** `isHumidifierStuck` checks, in order: (1) `wsConnected === false` → suppress; (2) `humidifierLastMsgTs === null` (explicit null, not undefined) → suppress; (3) `humidifierLastMsgTs !== undefined && staleness > (config.sensorOfflineMin || 5) * 60000` → suppress. Note step 3's `=== undefined` check specifically differs from step 2's `=== null` check — this is Node distinguishing "old caller never passed this field" (`undefined`, skip the staleness check, proceed to the math) from "bridge explicitly told us null" (suppress at step 2) from "bridge gave a real but stale timestamp" (suppress at step 3). A Python port collapsing `None`-checks into one uniform `is None` test for all three will silently change behavior for pre-Phase-29 callers (if any remain relevant) or, more importantly, misinterpret the null-vs-undefined distinction that doesn't exist as cleanly in Python (there's only `None`).
**Why it happens:** JS's `null`/`undefined` duality has no 1:1 Python equivalent; a literal-minded port needs an explicit sentinel (e.g., a distinct `_UNSET` sentinel vs `None`) OR — more practically — since `state.py`'s Python FSM will always construct these calls explicitly (not receive raw JS objects), the "old caller omitted the field" case may not exist in the ported call graph at all, making the distinction moot IF the researcher confirms all Python call sites always pass explicit values.
**How to avoid:** Audit whether the Python `state.py`'s `tick`/`humidity` event handlers always pass explicit `humidifier_last_msg_ts` (they should, since Python has no "old pre-Phase-29 caller" — that history is JS-only). If so, the port can simplify to a single `is None` check without behavioral change, but this must be a **documented, deliberate decision** in the plan, not an oversight — because it changes the code shape even though it (should) preserve behavior for all Python-native call sites.
**Warning signs:** None expected if the simplification is deliberate and every Python call site is audited; a silent divergence would only appear if some future call site relies on the undefined/null distinction.

### Pitfall 6: `mode_update` resets `rh`/`humidifier` dedup state but explicitly does NOT reset `lastFiredAt` (cooldown survives mode swaps)

**What goes wrong:** On every ROS mode change (e.g., pinning→fruiting), Node resets `oobCount`/`firstOobAt`/`ctx.inBandCount` for `rh` and `humidifier` types (so a stale OOB streak from the old mode's target doesn't bleed into the new mode's evaluation) but **intentionally preserves** `lastFiredAt` (cooldown timer keeps running across the mode swap — a farmer who just got an RH alert 5 minutes ago shouldn't get a duplicate immediately after a mode change even though the OOB streak reset). A naive "reset everything on mode change" port breaks the cooldown-continuity guarantee.
**Why it happens:** It's counter-intuitive that a "reset" event resets some fields but not others; the comment explicitly flags this ("lastFiredAt INTENTIONALLY NOT reset").
**How to avoid:** Port the `mode_update` handler's per-field reset list exactly: `oob_count = 0`, `first_oob_at = None`, `ctx['in_band_count'] = 0` — and nothing else. `sensor`, `pi`, `sht30`, `scd41` types are NOT touched by `mode_update` at all (only `rh`/`humidifier` are in the reset loop).
**Warning signs:** Parity replay shows duplicate RH alerts immediately after a mode-change event that Node's log does not show.

### Pitfall 7: `.lint-imports`'s `source_modules` list is stale/broken against the CURRENT codebase — fix this BEFORE claiming the gate is "activated"

**What goes wrong:** `.lint-imports` references `farm_agent.farmos_client` (does not exist — real package is `farm_agent.farmos`) and omits `farm_agent.signal_io`, `farm_agent.confirm`, `farm_agent.farmos`, `farm_agent.capture` (all shipped in Phases 57-62) while listing a nonexistent `farm_agent.llm`. **Verified live in this research session:** running `lint-imports --config .lint-imports` against the current tree hard-errors with `Module 'farm_agent.farmos_client' does not exist.` — it does NOT silently skip the way the file's own header comment claims ("import-linter skips forbidden_modules that don't exist" — true only for `forbidden_modules`, NOT `source_modules`, which is the field with the bad entry). Fixing `source_modules` to the real, current package list (`tenancy`, `persistence`, `extraction`, `signal_io`, `confirm`, `farmos`, `capture`; drop `llm`, fix `farmos_client`→`farmos`) makes it pass cleanly (verified: `Analyzed 68 files, 89 dependencies... Contracts: 1 kept, 0 broken`, exit 0).
**Why it happens:** `.lint-imports` was authored in Phase 56 as a forward-looking stub before `signal_io`/`confirm`/`farmos`/`capture` existed, and nobody has run it since (the pytest suite never invokes `lint-imports`, so this rot went undetected for 6+ phases).
**How to avoid:** Phase 63 must include a task to (a) correct `.lint-imports`'s `source_modules` list to match the real current package set (verified command: `uv run lint-imports --config .lint-imports`), and (b) add a `tests/test_import_linter_contract.py` that runs `lint-imports` via subprocess and asserts exit 0, wiring it into the pytest suite for the first time — satisfying D-00's "add `chamber/` to the pytest run" instruction literally.
**Warning signs:** If this fix is skipped, the very first attempt to "activate" the gate will hard-fail on an unrelated pre-existing bug, and it will look like a chamber/-caused regression when it isn't.

### Pitfall 8: `test_foray_seam.py`'s `FORAY_PACKAGES` grep-scope list is ALSO stale

**What goes wrong:** `tests/test_foray_seam.py`'s primary grep-based gate only scans `["farm_agent/tenancy", "farm_agent/persistence", "farm_agent/extraction"]` — its own docstring says "signal_io, confirm, farmos_client, capture, llm are not created this phase," which was true in Phase 56 but is now false (they all exist). This is the PRIMARY (not secondary) enforcement mechanism per the file's own comments, so its coverage gap is more load-bearing than the `.lint-imports` gap.
**Why it happens:** Same root cause as Pitfall 7 — written forward-looking in Phase 56, never updated as packages landed.
**How to avoid:** Update `FORAY_PACKAGES` to include `farm_agent/signal_io`, `farm_agent/confirm`, `farm_agent/farmos`, `farm_agent/capture`, `farm_agent/gate` (drop `llm`, which still doesn't exist) as part of the same Phase 63 task that fixes `.lint-imports`.
**Warning signs:** A future accidental `from farm_agent.chamber import X` inside `signal_io/` or `farmos/` would currently NOT be caught by `test_no_chamber_imports_in_foray` even after chamber/ exists, silently defeating the seam's entire purpose for 5 of 8 Foray packages.

### Pitfall 9: `signal_io.client.SignalClient`'s rate-cap fallback depends on a TenantConfig field D-03 is removing

**What goes wrong:** `SignalClient._current_cap()` (`farm_agent/signal_io/client.py:120-133`) falls back to `self._config.max_sends_per_hour` when no `get_max_sends_per_hour` hook is supplied. D-03 explicitly moves `max_sends_per_hour` out of `TenantConfig` into `ChamberConfig`. If the field is simply deleted from `TenantConfig` without updating `client.py`, `_current_cap()` raises `AttributeError` the first time any code path constructs a `SignalClient` without the hook — including the existing test `tests/test_signal_ratecap.py::_make_client` (default `get_max_hook=None`), which currently relies on `load_config(env)`'s `ALERT_MAX_SENDS_PER_HOUR` → `TenantConfig.max_sends_per_hour` plumbing.
**Why it happens:** This is a genuine cross-package coupling that predates chamber/ — `signal_io` is a Foray package that (today) legitimately needs SOME default send-rate cap independent of whether chamber/alerter exists at all (e.g., for confirm/capture-pipeline sends). D-03's "move the 7 fields" instruction, read literally, breaks this.
**How to avoid:** Give `SignalClient._current_cap()` a hardcoded module-level fallback constant (e.g., `_DEFAULT_MAX_SENDS_PER_HOUR = 20`, matching Node's `ALERT_MAX_SENDS_PER_HOUR` default) so it no longer reads `self._config.max_sends_per_hour` at all, and update `boot.py` to always pass `get_max_sends_per_hour=lambda: chamber_config.max_sends_per_hour` when constructing the shared `SignalClient`. Update `tests/test_signal_ratecap.py::_make_client` to either supply the hook explicitly or accept the new hardcoded default in its no-hook assertions.
**Warning signs:** `AttributeError: 'TenantConfig' object has no attribute 'max_sends_per_hour'` at test-collection or boot time immediately after the D-03 field move lands, if `client.py` isn't updated in the same PR.

### Pitfall 10: Heartbeat's "defer if bridge summary empty" retry logic is stateful across ticks and easy to lose in translation

**What goes wrong:** `heartbeat.js`'s `tick()` only sets `lastFiredDay = day` (marking the day as "done") when the summary actually has at least one non-null field (`rh`/`temp`/`co2`). If the daemon restarts at exactly `heartbeatHour` before any telemetry has arrived, Node defers and retries every 15 minutes until data arrives OR the day rolls over (in which case that day's heartbeat is silently skipped forever — "better than sending nulls"). A port that marks the day "done" unconditionally on the first tick at the right hour would send a heartbeat full of `?` placeholders instead of deferring.
**How to avoid:** Port the exact conditional: only set `last_heartbeat_day` when `summary` has at least one of `rh`/`temp`/`co2` non-`None`.
**Warning signs:** A heartbeat message containing `RH: ?%  ·  Temp: ?°C  ·  CO2: ? ppm` in production.

## Code Examples

### Node→Python full mapping table (rules.js)

| Node function | Python function | Key semantic to preserve |
|---|---|---|
| `isRhOob(humidity, effective)` | `is_rh_oob(humidity, effective)` | stale-freshness suspend (Pitfall 1) |
| `isSensorError(sensorHealth)` | `is_sensor_error(sensor_health)` | `level === 2` → error; not suppressed by warm-up (per `state.js` comment `ALRT-05`) |
| `isPiOffline({...})` | `is_pi_offline(*, ...)` | hard 3-min `FC1_DARK_THRESHOLD_MS` constant (Pitfall 2); `!= null` graceful degradation |
| `isHumidifierStuck({...})` | `is_humidifier_stuck(*, ...)` | 3-gate offline-blindness order (Pitfall 5); `rhRise < 3.0` unchanged math |
| `isSensorSilent({...})` | `is_sensor_silent(*, ...)` | minutes-scale threshold, independent of flap floor (Pitfall 4) |

### Node→Python full mapping table (state.js)

| Node symbol | Python symbol | Key semantic to preserve |
|---|---|---|
| `STATES` (OK/PENDING/FIRING/SNOOZED) | `class AlertState(str, Enum)` or plain string constants | Exact 4-state names (parity replay may assert on state strings) |
| `ALERT_TYPES` list (6 types) | same list, same order | D-07: all 6, not 4 |
| `SEVERITY` map | same map | `rh`/`humidifier` = WARN; `sensor`/`pi`/`sht30`/`scd41` = CRITICAL |
| `initialState(nowMs)` | `initial_state(now_ms)` | `sht30LastSeenMs`/`scd41LastSeenMs` init to `bootedAtMs`, NEVER `None` (comment: "so a never-seen sensor doesn't fire spuriously") |
| `cooldownMs(alertType, config)` | `cooldown_ms(alert_type, config)` | severity-conditional (`critical_cooldown_min` vs `cooldown_min`) |
| `isSnoozed(entry, now)` | `is_snoozed(entry, now)` | `snoozedUntil != null and now < snoozedUntil` |
| `driveAlertType(entry, alertType, oobNow, fields, now, config)` | `drive_alert_type(entry, alert_type, oob_now, fields, now, config)` | Pattern 3 — generic, reused by all 6 types |
| `resolveEffectiveConfig(state, envConfig, nowMs)` | `resolve_effective_config(state, env_config, now_ms)` | D-01 full Tier A/B/C + freshness — this is the highest-risk function in the whole port |
| `hasModeContext(state)` | `has_mode_context(state)` | Pattern 4 gate |
| `transition(prev, event, now, config)` | `transition(prev, event, now, config)` (or split per-event-type handler functions) | `JSON.parse(JSON.stringify(prev))` deep-clone → Python `copy.deepcopy(prev)` or a frozen-dataclass-with-`dataclasses.replace` approach; **recommend dataclasses over dict+deepcopy** for type safety, but the deep-clone-then-mutate-copy SHAPE must be preserved (no accidental shared mutable references across ticks) |

### D-04 TZ formatting — the exact fix

```python
# Source: port of message.js hhmm() (line 50-52) + Phase 63 D-04 fix.
# Node BEFORE (the bug): new Date(tsMs).toISOString().slice(11, 16)  -- ALWAYS UTC.
from datetime import datetime
from zoneinfo import ZoneInfo

def hhmm(ts_ms: int, tz_name: str) -> str:
    """Render a UTC epoch-ms timestamp as zero-padded local HH:MM (D-04 fix).

    Every farmer-facing call site (pi-offline 'last RH XX% @ HH:MM', any future
    time-of-day render) MUST route through this — never format via UTC directly.
    """
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=ZoneInfo(tz_name))
    return dt.strftime("%H:%M")
```

### D-04 snapshot test shape (for Validation Architecture / SC2)

```python
# Illustrative shape for tests/chamber/test_message.py
from zoneinfo import ZoneInfo
from datetime import datetime

def test_hhmm_renders_montevideo_not_utc():
    # 2026-07-13T23:30:00Z == 2026-07-13T20:30:00-03:00 (Montevideo, UTC-3, no DST)
    ts_ms = int(datetime(2026, 7, 13, 23, 30, 0, tzinfo=ZoneInfo("UTC")).timestamp() * 1000)
    assert hhmm(ts_ms, "America/Montevideo") == "20:30"
    # negative control: must NOT equal the UTC rendering (proves the bug is actually fixed)
    assert hhmm(ts_ms, "America/Montevideo") != "23:30"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `Intl.DateTimeFormat(...).formatToParts()` for TZ-aware hour/day extraction (Node) | `datetime.astimezone(ZoneInfo(...))` + `.hour`/`.strftime("%Y-%m-%d")` (Python stdlib) | This port (Phase 63) | Simpler API; stdlib-only (with `tzdata` for portability), no ICU dependency |
| `env.TZ \|\| 'America/Toronto'` default (Node `config.js:176`) | `env.get("TZ") or "America/Montevideo"` default (Python `ChamberConfig`) | D-04, this phase | The actual bug fix — closes `alerter_tz_toronto_legacy` |
| Hand-rolled `ws` reconnect loop (Node) | `websockets` library connection object + hand-rolled backoff timing (Python) | This port | See Alternatives Considered — timing parity intentionally preserved via explicit backoff, not library defaults |

**Deprecated/outdated:**
- Node's `Intl.DateTimeFormat('en-CA', ...)` locale trick (used purely to get `YYYY-MM-DD` string ordering) has no Python equivalent needed — `date.isoformat()` or `strftime("%Y-%m-%d")` gives the same string shape directly.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `websockets` is the correct/standard package name and its top-level async client API shape (`async for message in websockets.connect(url):` or similar) matches training-knowledge expectations for v16.x | Standard Stack, Code Examples | If the actual v16.1 API differs (e.g., import path moved under `websockets.asyncio.client`), the WS client task would need a signature correction; low risk since it's a well-known, actively-maintained package and the exact connect/reconnect idiom is easily verified by reading the installed package's own docstrings during implementation. |
| A2 | `tzdata` package is needed because the target Docker base image may lack system tzdata | Standard Stack | If the Phase-56 Dockerfile's base image already bundles tzdata (common for `python:3.12-slim` derivatives, which DO include it by default in most recent builds), this is a harmless extra dependency, not a functional risk. |
| A3 | Uruguay (`America/Montevideo`) does not currently observe DST, so the D-04 snapshot test's fixed UTC-3 offset is stable year-round | Code Examples, Pitfall — Don't Hand-Roll | If Uruguay's DST policy has changed since training-knowledge cutoff, the snapshot test's assumed fixed offset could be wrong for part of the year; `ZoneInfo` itself would still be correct (it reads real tz rules), only the illustrative test fixture's assumed offset could be stale — verify against the installed `tzdata`/system tz database at implementation time rather than hardcoding "always UTC-3" as a comment claim. |
| A4 | `SignalClient._current_cap()`'s recommended hardcoded fallback default of 20 matches Node's `ALERT_MAX_SENDS_PER_HOUR` default | Pitfall 9 | Verified directly from `config.js:175` (`parseIntEnv(env, 'ALERT_MAX_SENDS_PER_HOUR', 20)`) — this one is actually `[VERIFIED: config.js]`, not assumed; listed here only because it's a load-bearing constant choice for the fix. |

**Note on A4:** this is the only near-assumption backed by direct source verification; included in the log for visibility since it's a concrete numeric default the planner must not silently drop.

## Open Questions

1. **Does the current Phase-56 Dockerfile base image bundle system tzdata?**
   - What we know: `ZoneInfo` worked correctly in this research session's Linux dev environment without an explicit `tzdata` pip install.
   - What's unclear: Whether the `farm-agent` production Docker image (not audited in this pass) is a minimal/slim base lacking `/usr/share/zoneinfo`.
   - Recommendation: Add `tzdata` to `pyproject.toml` dependencies defensively (near-zero cost, closes the risk regardless of the answer) rather than spend a research/planning cycle auditing the Dockerfile.

2. **Exact `websockets` v16.x async client API surface (context-manager vs iterator vs explicit `.recv()` loop)?**
   - What we know: the library is the standard choice and was verified installable at v16.1.
   - What's unclear: v16.x's precise recommended usage pattern for a long-lived reconnecting client with custom backoff (vs the library's own built-in reconnect iterator) was not verified against live docs in this session (no Context7 lookup performed for this specific library/version).
   - Recommendation: the planner should schedule a small spike/verification step in the first WS-client-touching task — read the installed `websockets` package's own docstrings/type stubs (`python3 -c "import websockets; help(websockets)"` or equivalent) before finalizing the exact connect/backoff code shape, since Alternatives Considered already recommends hand-rolling backoff timing regardless (reducing reliance on library-specific reconnect API details).

3. **Should `ChamberConfig` be validated at boot the same way `TenantConfig` is (secrets via `_must_env`, non-secrets via a `_pick`-equivalent), or does it need tenant-YAML layering at all?**
   - What we know: D-02 says ChamberConfig reads secrets+identity FROM TenantConfig (composition), and owns all alerter knobs itself.
   - What's unclear: whether ChamberConfig's alerter knobs should ALSO support the tenant-YAML layer (`tenants/<id>/config.yaml`) the way Node's `config.js` does via `pick(tenantConfig, env, key, def)`, or whether Phase 63 can simplify to env-only (since `alerter_config_env_not_tenant_yaml_live` memory notes "live config comes from compose ENV; tenant YAML layer is inert in Docker" — suggesting the YAML layer may be dead weight in practice).
   - Recommendation: given the memory note, recommend `ChamberConfig` be **env-only + hardcoded defaults** (no tenant-YAML layer) unless the planner has evidence a specific alerter knob is actually YAML-configured in production today — simpler code, and the live-prod memory suggests YAML layering for alerter knobs was never actually exercised.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Entire `farm_agent` package (pyproject `requires-python = ">=3.12"`) | ✓ | 3.12.13 (verified this session) | — |
| `zoneinfo` stdlib | D-04 TZ formatting | ✓ | stdlib (3.9+) | — |
| System IANA tzdata | `ZoneInfo` correctness without pip `tzdata` | ✓ (dev sandbox only — verified `ZoneInfo('America/Montevideo')` resolves correctly) | — | Add `tzdata` pip package (Open Question 1) for production image safety |
| `websockets` pip package | ROS-bridge WS client | ✗ (not yet a project dependency) | 16.1 available on PyPI (verified) | None needed — must be added via `uv add websockets` |
| `uv` | dependency management, running lint-imports/pytest | ✓ | present (`/home/santi/.local/bin/uv`) | — |
| `import-linter` (`lint-imports` CLI) | D-00 secondary Foray-seam gate | ✓ (already a `dev` optional-dependency, `>=2.11`) | Confirmed runnable this session; contract file itself needs the Pitfall-7 fix before it passes | — |

**Missing dependencies with no fallback:**
- `websockets` — must be added to `pyproject.toml` before the WS-client task can be implemented.

**Missing dependencies with fallback:**
- System tzdata in the production Docker image (unverified) — fallback is adding the `tzdata` pip package, recommended regardless.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥9.1 + pytest-asyncio ≥1.4 (already the project standard; `asyncio_mode = "auto"` in `pyproject.toml`) |
| Config file | `src/farm-agent/pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `cd src/farm-agent && uv run pytest tests/chamber/ -x` |
| Full suite command | `cd src/farm-agent && uv run pytest tests/` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CHM-01 | `is_rh_oob` stale-suspend guard (Pitfall 1) | unit | `uv run pytest tests/chamber/test_rules.py::test_rh_oob_suspended_when_stale -x` | ❌ Wave 0 |
| CHM-01 | `is_pi_offline` fc1-dark hard 3-min threshold, independent of `pi_offline_min` (Pitfall 2) | unit | `uv run pytest tests/chamber/test_rules.py::test_pi_offline_fc1_dark_hardcoded_3min -x` | ❌ Wave 0 |
| CHM-01 | `is_humidifier_stuck` offline-blindness 3-gate order (Pitfall 5) | unit | `uv run pytest tests/chamber/test_rules.py::test_humidifier_stuck_offline_blindness -x` | ❌ Wave 0 |
| CHM-01 | `is_sensor_silent` independent of flap floor (Pitfall 4) | unit | `uv run pytest tests/chamber/test_rules.py::test_sensor_silent_ignores_flap_floor -x` | ❌ Wave 0 |
| CHM-01 | `resolve_effective_config` full Tier A/B/C + freshness matrix (fresh/stale/cold × mode-present/absent) | unit | `uv run pytest tests/chamber/test_state.py::test_resolve_effective_config_tiers -x` | ❌ Wave 0 |
| CHM-01 | `drive_alert_type` fast-fire override (`oob_n=1, oob_window_min=0`) applied to `pi`/`sensor`/`sht30`/`scd41` but NOT `rh`/`humidifier` (Pitfall 3) | unit | `uv run pytest tests/chamber/test_state.py::test_fast_fire_types -x` | ❌ Wave 0 |
| CHM-01 | `mode_update` resets `oob_count`/`first_oob_at` but preserves `last_fired_at` (Pitfall 6) | unit | `uv run pytest tests/chamber/test_state.py::test_mode_update_preserves_cooldown -x` | ❌ Wave 0 |
| CHM-01 | Snooze/mute grammar (`STRICT` + `SIMPLE`) parity with `snooze.js` | unit | `uv run pytest tests/chamber/test_snooze.py -x` | ❌ Wave 0 |
| CHM-01 | Heartbeat "defer if summary empty" retry semantics (Pitfall 10) | unit | `uv run pytest tests/chamber/test_heartbeat.py::test_heartbeat_defers_on_empty_summary -x` | ❌ Wave 0 |
| CHM-01 | WS reconnect/backoff schedule (1s→30s doubling, matches `bridge-client.js`) | unit (fake/mock WS) | `uv run pytest tests/chamber/test_ws_client.py::test_reconnect_backoff_doubles -x` | ❌ Wave 0 |
| CHM-01 (SC1) | Induced bridge disconnect fires pi-offline alert within timeout | integration | `uv run pytest tests/chamber/test_service_wiring.py::test_bridge_disconnect_fires_pi_alert -x` (or a manual/live-fire marker if a real bridge fixture isn't feasible in CI) | ❌ Wave 0 |
| CHM-01 (D-05) | Composite dispatch routes snooze/mute text to chamber, all else to capture pipeline | integration | `uv run pytest tests/chamber/test_service_wiring.py::test_composite_dispatch_routing -x` | ❌ Wave 0 |
| CHM-02 (SC2) | `hhmm()` / all farmer-facing time formatting renders `America/Montevideo`, not UTC/Toronto | unit (snapshot) | `uv run pytest tests/chamber/test_message.py::test_hhmm_renders_montevideo_not_utc -x` | ❌ Wave 0 |
| CHM-02 | `fmt_num` round-number formatting parity (`?` for null/NaN, 1-decimal trailing-zero strip) | unit | `uv run pytest tests/chamber/test_message.py::test_fmt_num_parity -x` | ❌ Wave 0 |
| D-00 (SC3, real gate direction) | `.lint-imports` passes with corrected `source_modules`, `chamber/` in `forbidden_modules` scope | integration | `uv run pytest tests/test_import_linter_contract.py -x` (new file) | ❌ Wave 0 |
| D-00 | `test_foray_seam.py`'s `FORAY_PACKAGES` covers all current Foray packages (Pitfall 8) | integration | `uv run pytest tests/test_foray_seam.py -x` (update existing) | ✓ exists, needs list update |
| D-03 | `TenantConfig` no longer has the 7 relocated fields; `ChamberConfig` has them; existing `test_tenancy.py` field tests updated | unit | `uv run pytest tests/test_tenancy.py -x` (update existing `test_int_field_from_env`, `test_float_field_from_env`, `test_int_default_used_when_absent`) | ✓ exists, needs update |
| D-03 (Pitfall 9) | `SignalClient` rate cap works with the hardcoded fallback + boot.py hook wiring, no `AttributeError` | unit | `uv run pytest tests/test_signal_ratecap.py -x` (update existing `_make_client`) | ✓ exists, needs update |

### Sampling Rate
- **Per task commit:** `cd src/farm-agent && uv run pytest tests/chamber/ -x`
- **Per wave merge:** `cd src/farm-agent && uv run pytest tests/`
- **Phase gate:** Full suite green (including the newly-activated `lint-imports` contract test) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/chamber/` directory + `__init__.py` — does not exist yet, entire chamber test tree is new
- [ ] `tests/chamber/conftest.py` — a chamber-scoped fixture set (e.g., a `ChamberConfig` test factory mirroring `tests/conftest.py`'s `TEST_ENV` pattern) — needed before any chamber unit test can run
- [ ] `tests/test_import_linter_contract.py` — new file, wires `lint-imports` into pytest for the first time (D-00)
- [ ] Framework install: `uv add websockets tzdata` (from `src/farm-agent/`) — no new test framework needed, `pytest`/`pytest-asyncio` already present
- [ ] Update (not create) `tests/test_tenancy.py` — remove/adjust the 3 tests asserting on the 7 fields being on `TenantConfig`
- [ ] Update (not create) `tests/test_signal_ratecap.py::_make_client` — adjust for the Pitfall-9 fix
- [ ] Update (not create) `tests/test_foray_seam.py`'s `FORAY_PACKAGES` list (Pitfall 8)
- [ ] Fix (not create) `.lint-imports`'s `source_modules` list (Pitfall 7)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Chamber has no user-facing auth surface; Signal sender whitelist is the existing `signal_io.router.is_whitelisted` gate (already built, Phase 57), reused unchanged. |
| V3 Session Management | no | No session concept in this phase. |
| V4 Access Control | yes | Snooze/mute command dispatch MUST go through the existing whitelist gate (`ReceiveLoop.tick()` already gates BEFORE dispatch, per T-57-03-01) — chamber's composite dispatcher does not need to re-implement this, but must not bypass it (e.g., must not add a second, ungated ingestion path for snooze commands). |
| V5 Input Validation | yes | `snooze.py`'s anchored, whitelisted regex (`STRICT`/`SIMPLE`) is the existing control — port verbatim, do not loosen the regex "for convenience." |
| V6 Cryptography | no | No crypto surface introduced by this phase (Signal transport crypto is handled entirely by the existing `signal-cli` REST sidecar, out of scope). |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/attacker-crafted snooze text causing a crash in the composite dispatcher (denial of alerting) | Denial of Service | `receive_loop.tick()`'s existing per-envelope try/except (loop-never-dies) already wraps the composite dispatch call — chamber's `parse_snooze_command` must never raise on malformed input (Node's `snooze.js` never raises; always returns `{ok: false, ...}` or a fuzzy-help reply) — preserve that no-raise contract. |
| A second `SignalClient`/`ReceiveLoop` accidentally constructed for chamber, causing signal-cli receive-poll contention/duplication | Tampering (message duplication / dropped receipts) | D-05 + T-58-03-05 A3 guard — enforce via the Pattern 5 composite-dispatch wiring; add an explicit `test_service_wiring.py` assertion that `boot.py` constructs exactly one `ReceiveLoop`. |
| Logging a full phone number or secret config value in chamber's structured logs | Information Disclosure | Reuse `tenancy.mask_number()` (already imported/re-exported by `signal_io.router`) for any chamber log line that includes a phone number; never log `ChamberConfig` object wholesale (mirrors `boot.py`'s existing T-56-06-01 discipline). |

## Sources

### Primary (HIGH confidence)
- `src/agents/alerter/src/rules.js`, `state.js`, `bridge-client.js`, `heartbeat.js`, `snooze.js`, `message.js`, `config.js` — read in full this session (2026-07-13), the Node parity source of truth.
- `src/farm-agent/farm_agent/tenancy/tenant.py`, `boot.py`, `signal_io/client.py`, `signal_io/router.py`, `signal_io/receive_loop.py` — read in full this session, the current Python port targets.
- `src/farm-agent/.lint-imports`, `src/farm-agent/tests/test_foray_seam.py` — read in full this session; the `.lint-imports` failure and fix were **directly executed and verified** via `uv run lint-imports --config .lint-imports` (before-fix: hard error; after-fix: `Contracts: 1 kept, 0 broken`, exit 0).
- `src/farm-agent/tests/test_tenancy.py`, `tests/test_signal_ratecap.py`, `tests/conftest.py` — read this session to confirm the exact test blast-radius of the D-03 field move.
- `.planning/phases/63-chamber-alerter/63-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md` — read this session per the research brief.
- Python `zoneinfo('America/Montevideo')` — directly executed in this session, confirmed UTC-3 resolution.
- `websockets`/`tzdata` package existence + `[OK]` slopcheck verdict — directly executed via `uv run --with slopcheck slopcheck install websockets tzdata` and a live `pip install`, this session.

### Secondary (MEDIUM confidence)
- Python docs `zoneinfo` module (cited for the `tzdata` pip-package recommendation — general stdlib documentation knowledge, not fetched via Context7/WebFetch this session).

### Tertiary (LOW confidence)
- `websockets` v16.x exact top-level client API shape (async-iterator vs context-manager idiom) — training-knowledge based, NOT verified against live docs or Context7 this session; flagged in Open Questions and Assumptions Log.
- Uruguay's current DST policy (assumed unchanged, no DST) — training-knowledge based, flagged in Assumptions Log A3.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM — `websockets`/`tzdata` package identity and general fitness are well-established training knowledge and passed live registry+slopcheck verification, but the exact `websockets` v16.x API idiom was not verified against live docs (no Context7 available in this session's tool surface).
- Architecture: HIGH — the Node→Python mapping, FSM shape, and Foray-seam wiring recommendations are grounded directly in reading both the full Node source and the full current Python source in this session, including live execution of the `.lint-imports` fix.
- Pitfalls: HIGH — every pitfall traces to a specific, dated comment in the Node source (Phase-46 D-09/D-10, 2026-05-07, 2026-05-12) or a live-verified defect in the current Python tree (`.lint-imports`, `SignalClient` rate cap coupling).

**Research date:** 2026-07-13
**Valid until:** 2026-08-13 (30 days — the Node source and the current Python `farm_agent` tree are both actively-changing but this phase's port target is a frozen historical snapshot; re-verify `.lint-imports`/`test_foray_seam.py` state if Phase 63 planning is delayed past this window, since Phases 57-62 landed the packages this research audited)
