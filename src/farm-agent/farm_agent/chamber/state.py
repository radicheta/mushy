"""
chamber/state.py -- the alert FSM. Port of src/agents/alerter/src/state.js (718 lines).

Transitions are pure: (state, event, now, config) -> (next_state, actions).
Plan 08's service performs the actions; nothing here does I/O.

State is IN-MEMORY and resets on restart, matching Node exactly (D-06). Persisting
snooze/cooldown across restarts would itself be a Phase-64 parity delta.

NOTE: state.js is internally inconsistent about which config object reaches
drive_alert_type (see the call-site matrix in 63-07-PLAN.md). Those asymmetries
are reproduced deliberately and pinned by *_parity_quirk_* tests. Do not tidy them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

# js:9
STATES = {"OK": "OK", "PENDING": "PENDING", "FIRING": "FIRING", "SNOOZED": "SNOOZED"}

# js:11 -- D-07: all six, in this order
ALERT_TYPES = ["rh", "sensor", "pi", "humidifier", "sht30", "scd41"]

# js:14-21
SEVERITY = {
    "rh": "WARN",
    "sensor": "CRITICAL",
    "pi": "CRITICAL",
    "humidifier": "WARN",
    "sht30": "CRITICAL",
    "scd41": "CRITICAL",
}

# js:514, 560, 385, 436, 609 -- a literal 60s in Node, NOT mode_boot_grace_ms.
STARTUP_GRACE_MS = 60_000


@dataclass(frozen=True)
class Freshness:
    """js:190 -- {state: fresh|stale|cold, source: mode|env}."""

    state: str
    source: str


@dataclass(frozen=True)
class EffectiveConfig:
    """The config detectors actually consume. js:213-236.

    Tier A/B come from the live ROS mode when it is fresh; Tier C from runtime
    globals in every branch; everything else passes through from env.
    """

    # Tier A (mode-anchored when fresh, else env)
    rh_target: float
    rh_band: float
    # Tier B (per-mode override when fresh, else env)
    oob_n: int
    oob_window_min: int
    cooldown_min: int
    critical_cooldown_min: int
    humidifier_stuck_min: int
    # Tier C (global override, ALWAYS)
    pi_offline_min: int
    sensor_offline_min: int
    heartbeat_hour: int
    max_sends_per_hour: int
    # Tier D passthrough
    sensor_flap_min_sec: int
    sht30_enabled: bool
    scd41_enabled: bool
    timezone: str
    dashboard_url: str
    freshness: Freshness
    # Tier A extras -- None unless mode-anchored
    band_low: float | None = None
    band_high: float | None = None
    defend_side: str | None = None
    mode_name: str | None = None


@dataclass
class AlertEntry:
    """js:26-33 -- per-alert-type FSM entry."""

    state: str = "OK"
    oob_count: int = 0
    first_oob_at: int | None = None
    last_fired_at: int | None = None
    snoozed_until: int | None = None
    ctx: dict = field(default_factory=dict)


@dataclass
class ChamberState:
    """js:35-69 -- the whole in-memory alerter state."""

    booted_at_ms: int
    per_type: dict[str, AlertEntry]
    current_mode: dict | None = None
    mode_received_at_ms: int | None = None
    alerter_overrides: dict | None = None
    overrides_received_at_ms: int | None = None
    alerter_globals: dict | None = None
    globals_received_at_ms: int | None = None
    warming_up: bool = False
    last_heartbeat_day: str | None = None
    ws_connected: bool | None = False
    ws_last_connected_ms: int | None = None
    ros_connected: bool | None = False
    ros_disconnected_since_ms: int | None = None
    fc1_last_msg_ts: int | None = None
    humidifier_last_msg_ts: int | None = None
    humidifier_on_since_ms: int | None = None
    rh_at_on: float | None = None
    current_rh: float | None = None
    last_rh_msg_ts: int | None = None
    current_temp: float | None = None
    current_co2: float | None = None
    humidifier_cycles_last_24h: int = 0
    humidifier_cycle_log: list = field(default_factory=list)
    sht30_last_seen_ms: int | None = None
    scd41_last_seen_ms: int | None = None


def initial_state(now_ms: int) -> ChamberState:
    """js:23-70. sht30/scd41 last-seen seed to boot, NEVER None, so a sensor that
    has never reported does not fire before the grace window elapses."""
    return ChamberState(
        booted_at_ms=now_ms,
        per_type={t: AlertEntry() for t in ALERT_TYPES},
        ws_last_connected_ms=now_ms,
        sht30_last_seen_ms=now_ms,
        scd41_last_seen_ms=now_ms,
    )


def cooldown_ms(alert_type: str, config) -> int:
    """js:75-78 -- CRITICAL types use the critical cooldown."""
    if SEVERITY[alert_type] == "CRITICAL":
        return config.critical_cooldown_min * 60_000
    return config.cooldown_min * 60_000


def is_snoozed(entry: AlertEntry, now_ms: int) -> bool:
    """js:83-85. Strict `<`: the instant snooze expires, alerts resume."""
    return entry.snoozed_until is not None and now_ms < entry.snoozed_until


def has_mode_context(state: ChamberState) -> bool:
    """js:244-248 -- the cold-boot gate.

    Until a mode/overrides/globals envelope has EVER arrived, handlers feed raw
    ChamberConfig to the detectors rather than an EffectiveConfig. Raw config has
    no `freshness`, so is_rh_oob evaluates normally (Plan 04's back-compat path).
    """
    return (
        state.mode_received_at_ms is not None
        or state.overrides_received_at_ms is not None
        or state.globals_received_at_ms is not None
    )


def _pick(overrides: dict, key: str, fallback):
    """Node's `x != null ? x : fallback` over an override dict."""
    v = overrides.get(key)
    return fallback if v is None else v


def resolve_effective_config(state: ChamberState, env_config, now_ms: int) -> EffectiveConfig:
    """js:192-237 -- the Tier A/B/C + freshness resolver (D-01).

    Three branches:
      1. mode present, ws connected, mode fresh -> Tier A (mode-anchored RH target
         and band) + Tier B (per-mode overrides), freshness fresh/mode
      2. mode never arrived, still inside the boot grace -> freshness cold/env
      3. otherwise -> freshness stale/env, which suspends the RH rule (2026-05-07)

    Tier C is applied in ALL THREE branches. That is deliberate: pi_offline_min has
    to be honoured precisely when fc1 is offline, which is exactly when the mode has
    gone stale.
    """
    mode_stale_ms = (env_config.mode_stale_min or 5) * 60_000
    cold_grace_ms = env_config.mode_boot_grace_ms or 60_000
    ws_connected = state.ws_connected is not False   # js:195 -- None counts as connected
    mode_age = (
        now_ms - state.mode_received_at_ms
        if state.mode_received_at_ms is not None
        else math.inf
    )
    globals_ = state.alerter_globals or {}

    base = dict(
        # Tier C -- independent of mode freshness (js:202-207)
        pi_offline_min=_pick(globals_, "pi_offline_min", env_config.pi_offline_min),
        sensor_offline_min=_pick(globals_, "sensor_offline_min", env_config.sensor_offline_min),
        heartbeat_hour=_pick(globals_, "heartbeat_hour", env_config.heartbeat_hour),
        max_sends_per_hour=_pick(globals_, "max_sends_per_hour", env_config.max_sends_per_hour),
        # Tier D passthrough
        sensor_flap_min_sec=env_config.sensor_flap_min_sec,
        sht30_enabled=env_config.sht30_enabled,
        scd41_enabled=env_config.scd41_enabled,
        timezone=env_config.timezone,
        dashboard_url=env_config.dashboard_url,
    )

    # Branch 1 -- mode known and fresh (js:210)
    if state.current_mode and ws_connected and mode_age <= mode_stale_ms:
        m = state.current_mode
        ov = (state.alerter_overrides or {}).get(m["name"]) or {}
        return EffectiveConfig(
            **base,
            rh_target=m["target_humidity"] * 100,
            rh_band=((m["band_high"] - m["band_low"]) / 2) * 100,
            band_low=m["band_low"] * 100,
            band_high=m["band_high"] * 100,
            defend_side=m.get("defend_side"),
            mode_name=m["name"],
            oob_n=_pick(ov, "oob_n", env_config.oob_n),
            oob_window_min=_pick(ov, "oob_window_min", env_config.oob_window_min),
            cooldown_min=_pick(ov, "cooldown_min", env_config.cooldown_min),
            critical_cooldown_min=_pick(
                ov, "critical_cooldown_min", env_config.critical_cooldown_min
            ),
            humidifier_stuck_min=_pick(
                ov, "humidifier_stuck_min", env_config.humidifier_stuck_min
            ),
            freshness=Freshness("fresh", "mode"),
        )

    env_layer = dict(
        rh_target=env_config.rh_target,
        rh_band=env_config.rh_band,
        oob_n=env_config.oob_n,
        oob_window_min=env_config.oob_window_min,
        cooldown_min=env_config.cooldown_min,
        critical_cooldown_min=env_config.critical_cooldown_min,
        humidifier_stuck_min=env_config.humidifier_stuck_min,
    )

    # Branch 2 -- cold-start grace (js:232)
    boot_age = now_ms - state.booted_at_ms if state.booted_at_ms is not None else math.inf
    if state.current_mode is None and boot_age <= cold_grace_ms:
        return EffectiveConfig(**base, **env_layer, freshness=Freshness("cold", "env"))

    # Branch 3 -- stale or never-arrived past grace (js:236)
    return EffectiveConfig(**base, **env_layer, freshness=Freshness("stale", "env"))


def _fast_fire(cfg):
    """Return a copy of cfg with the generic debounce disabled (oob_n=1, window=0).

    js builds `{...cfg, oobN: 1, oobWindowMin: 0}` inline at several call sites.
    Which BASE config is spread (raw env vs effective) differs per site and is
    NOT this helper's business -- see the call-site matrix in 63-07-PLAN.md.
    """
    return replace(cfg, oob_n=1, oob_window_min=0)


def drive_alert_type(entry, alert_type, oob_now, fields, now_ms, config):
    """The single generic FSM transition, shared by all 6 alert types. js:94-178.

    Returns (new_entry, actions). The input entry is never mutated.

    OOB:  OK -> PENDING (and straight to FIRING when oob_n==1 and the window is 0)
          PENDING -> FIRING once count >= oob_n AND the window has elapsed
          FIRING  -> repeat send once the cooldown passes
          SNOOZED -> the FSM advances but nothing is sent
    In-band:
          PENDING -> OK, silently
          FIRING  -> OK after oob_n consecutive in-band samples, emitting recovery
    """
    from farm_agent.chamber import message  # local import avoids a cycle

    actions: list[dict] = []
    nxt = replace(entry, ctx=dict(entry.ctx))
    severity = SEVERITY[alert_type]

    def _fire():
        nxt.state = STATES["FIRING"]
        nxt.last_fired_at = now_ms
        if not is_snoozed(nxt, now_ms):
            actions.append({
                "kind": "send",
                "alert_type": alert_type,
                "severity": severity,
                "body": message.format_problem(
                    alert_type=alert_type, severity=severity,
                    fields=fields, config=config, now_ms=now_ms,
                ),
            })

    if oob_now:
        if nxt.state == STATES["OK"]:
            nxt.state = STATES["PENDING"]
            nxt.oob_count = 1
            nxt.first_oob_at = now_ms
            nxt.ctx["in_band_count"] = 0
            # checked immediately so oob_n == 1 fires on this very sample (js:106)
            if nxt.oob_count >= config.oob_n and (
                now_ms - nxt.first_oob_at
            ) >= config.oob_window_min * 60_000:
                _fire()
        elif nxt.state == STATES["PENDING"]:
            nxt.oob_count += 1
            nxt.ctx["in_band_count"] = 0
            if nxt.oob_count >= config.oob_n and (
                now_ms - nxt.first_oob_at
            ) >= config.oob_window_min * 60_000:
                _fire()
        elif nxt.state == STATES["FIRING"]:
            nxt.ctx["in_band_count"] = 0
            if not is_snoozed(nxt, now_ms) and (
                now_ms - nxt.last_fired_at
            ) > cooldown_ms(alert_type, config):
                _fire()
        # SNOOZED: hold; it resumes naturally once snoozed_until passes
    else:
        if nxt.state == STATES["PENDING"]:
            nxt.state = STATES["OK"]
            nxt.oob_count = 0
            nxt.first_oob_at = None
            nxt.ctx["in_band_count"] = 0
        elif nxt.state == STATES["FIRING"]:
            nxt.ctx["in_band_count"] = nxt.ctx.get("in_band_count", 0) + 1
            if nxt.ctx["in_band_count"] >= config.oob_n:
                duration_ms = now_ms - nxt.first_oob_at if nxt.first_oob_at is not None else 0
                nxt.state = STATES["OK"]
                nxt.oob_count = 0
                nxt.first_oob_at = None
                nxt.last_fired_at = None
                nxt.ctx["in_band_count"] = 0
                actions.append({
                    "kind": "recovery",
                    "alert_type": alert_type,
                    "body": message.format_recovery(
                        alert_type=alert_type, fields=fields,
                        duration_ms=duration_ms, config=config,
                    ),
                    "duration_ms": duration_ms,
                })

    return nxt, actions


def _last_known(st: ChamberState) -> dict | None:
    """js:530-538 / 571-578 -- the last-known sample summary for the pi message body.

    999.39: only built when RH, temp AND the timestamp are all present; a partial
    snapshot would render '?' fields into a CRITICAL the farmer needs to trust.
    """
    if st.current_rh is not None and st.current_temp is not None and st.last_rh_msg_ts is not None:
        return {
            "rh": st.current_rh,
            "temp": st.current_temp,
            "humidifier": "ON" if st.humidifier_on_since_ms is not None else "OFF",
            "ts_ms": st.last_rh_msg_ts,
        }
    return None


def _eval_pi(nxt, config, now_ms, pi_config_is_fast_fire: bool):
    """Shared pi evaluation for the pi_liveness (js:514-551) and tick (js:560-582) paths.

    `pi_config_is_fast_fire` is the ONLY difference between the two call sites, and
    it is a real Node asymmetry, not a simplification -- see the call-site matrix.
    """
    from farm_agent.chamber import rules

    effective = resolve_effective_config(nxt, config, now_ms) if has_mode_context(nxt) else config
    offline = rules.is_pi_offline(
        ws_connected=nxt.ws_connected,
        ros_connected=nxt.ros_connected,
        now_ms=now_ms,
        ws_last_connected_ms=nxt.ws_last_connected_ms,
        ros_disconnected_since_ms=nxt.ros_disconnected_since_ms,
        fc1_last_msg_ts=nxt.fc1_last_msg_ts,
        config=effective,
    )
    pi_fields = {"last_seen_ms": nxt.ws_last_connected_ms, "last_known": _last_known(nxt)}
    pi_cfg = _fast_fire(effective) if pi_config_is_fast_fire else effective
    entry, acts = drive_alert_type(nxt.per_type["pi"], "pi", offline, pi_fields, now_ms, pi_cfg)
    nxt.per_type["pi"] = entry
    return acts


def _eval_physical_sensors(nxt, config, now_ms, values: dict | None = None):
    """sht30/scd41 watchdogs. js:385-414 (sensor_health) and js:609-626 (tick).

    PARITY: sensorCfg is built from RAW `config`, never `effective`, and
    is_sensor_silent likewise receives raw `config` -- so a Tier C
    sensor_offline_min override never reaches these watchdogs (pinned quirk).
    """
    from farm_agent.chamber import rules

    actions: list[dict] = []
    v = values or {}
    sensor_cfg = _fast_fire(config)
    # 2026-05-12 flap floor: honour a Pi-side `xxx_fresh=='false'` flag only once
    # sustained for sensor_flap_min_sec. The slow-silence path (is_sensor_silent)
    # is deliberately untouched and keeps gating on sensor_offline_min (MINUTES).
    flap_ms = (config.sensor_flap_min_sec or 0) * 1000

    def _flag_stale(last_seen_ms):
        return last_seen_ms is not None and (now_ms - last_seen_ms) >= flap_ms

    for sensor in ("sht30", "scd41"):
        enabled = config.sht30_enabled if sensor == "sht30" else config.scd41_enabled
        if enabled is False:
            continue  # 999.42: a muted sensor is not evaluated at all
        last_ms = nxt.sht30_last_seen_ms if sensor == "sht30" else nxt.scd41_last_seen_ms
        stale = (v.get(f"{sensor}_fresh") == "false" and _flag_stale(last_ms)) or (
            rules.is_sensor_silent(last_seen_ms=last_ms, now_ms=now_ms, config=config)
        )
        entry, acts = drive_alert_type(
            nxt.per_type[sensor], sensor, stale, {"last_seen_ms": last_ms}, now_ms, sensor_cfg
        )
        nxt.per_type[sensor] = entry
        actions.extend(acts)
    return actions


def transition(prev: ChamberState, event: dict, now_ms: int, config):
    """js:253-678 -- the pure event dispatch. Returns (next_state, actions).

    `prev` is never mutated. An unknown event type is a no-op (js:673).
    """
    import copy

    from farm_agent.chamber import message, rules

    nxt = copy.deepcopy(prev)
    actions: list[dict] = []
    etype = event.get("type")

    if etype == "humidity":
        nxt.current_rh = event["value"]
        nxt.last_rh_msg_ts = now_ms
        effective = (
            resolve_effective_config(nxt, config, now_ms) if has_mode_context(nxt) else config
        )
        # Suppressed during warm-up and, per Phase 46 D-07, while chamber-dark is
        # FIRING -- the chamber-level alert subsumes per-sensor noise (js:270).
        if not nxt.warming_up and nxt.per_type["pi"].state != STATES["FIRING"]:
            oob_now = rules.is_rh_oob(event["value"], effective)
            rh_fields = {"value": event["value"], "first_oob_ms": nxt.per_type["rh"].first_oob_at}
            entry, acts = drive_alert_type(
                nxt.per_type["rh"], "rh", oob_now, rh_fields, now_ms, effective
            )
            nxt.per_type["rh"] = entry
            actions.extend(acts)

            if nxt.humidifier_on_since_ms is not None:
                stuck = rules.is_humidifier_stuck(
                    humidifier_on_since_ms=nxt.humidifier_on_since_ms,
                    rh_at_on=nxt.rh_at_on,
                    current_rh=event["value"],
                    now_ms=now_ms,
                    config=effective,
                    ws_connected=nxt.ws_connected,
                    humidifier_last_msg_ts=nxt.humidifier_last_msg_ts,
                )
                hum_fields = {
                    "on_since_ms": nxt.humidifier_on_since_ms,
                    "rh_at_on": nxt.rh_at_on,
                    "current_rh": event["value"],
                }
                entry, acts = drive_alert_type(
                    nxt.per_type["humidifier"], "humidifier", stuck, hum_fields, now_ms, effective
                )
                nxt.per_type["humidifier"] = entry
                actions.extend(acts)

    elif etype == "mode_update":
        nxt.current_mode = event["mode"]
        nxt.mode_received_at_ms = now_ms
        # D-09 / Pitfall 6: reset in-progress dedup for rh + humidifier ONLY, and
        # deliberately preserve last_fired_at so cooldown carries across a mode swap.
        for t in ("rh", "humidifier"):
            e = nxt.per_type.get(t)
            if e is not None:
                e.oob_count = 0
                e.first_oob_at = None
                if e.ctx is not None:
                    e.ctx["in_band_count"] = 0

    elif etype == "overrides_update":
        nxt.alerter_overrides = event["overrides"]
        nxt.overrides_received_at_ms = now_ms

    elif etype == "globals_update":
        nxt.alerter_globals = event["globals"]
        nxt.globals_received_at_ms = now_ms

    elif etype == "temperature":
        nxt.current_temp = event["value"]      # store-only, no transitions

    elif etype == "co2":
        nxt.current_co2 = event["value"]       # store-only, no transitions

    elif etype == "sensor_health":
        level = event.get("level")
        if level == 1:
            nxt.warming_up = True
        elif level == 0:
            nxt.warming_up = False

        # NOT suppressed by warm-up (ALRT-05).
        sensor_fields = {"message": event.get("message")}
        if rules.is_sensor_error(event):
            # js:353 -- fires on the FIRST error event; base is RAW config.
            entry, acts = drive_alert_type(
                nxt.per_type["sensor"], "sensor", True, sensor_fields, now_ms,
                _fast_fire(config),
            )
            nxt.per_type["sensor"] = entry
            actions.extend(acts)
        elif level in (0, 1):
            # js:359 -- recovery path uses RAW config, so it needs oob_n clean events.
            entry, acts = drive_alert_type(
                nxt.per_type["sensor"], "sensor", False, sensor_fields, now_ms, config
            )
            nxt.per_type["sensor"] = entry
            actions.extend(acts)

        # Phase 26 Plan 03: strict string-bool equality; unknown values fail safe
        # (no refresh -> the watchdog eventually trips).
        v = event.get("values") or {}
        if v.get("sht30_fresh") == "true":
            nxt.sht30_last_seen_ms = now_ms
        if v.get("scd41_fresh") == "true":
            nxt.scd41_last_seen_ms = now_ms
        # last-seen refreshes above are UNCONDITIONAL (js:382-384) so evaluation
        # resumes with accurate liveness once pi clears.
        if (now_ms - nxt.booted_at_ms) >= STARTUP_GRACE_MS and (
            nxt.per_type["pi"].state != STATES["FIRING"]
        ):
            actions.extend(_eval_physical_sensors(nxt, config, now_ms, v))

    elif etype == "sensor_freshness":
        sensor = event.get("sensor")
        if sensor in ("sht30", "scd41"):
            last_seen = event.get("last_seen_ms")
            resolved = last_seen if last_seen is not None else now_ms
            if sensor == "sht30":
                nxt.sht30_last_seen_ms = resolved
            else:
                nxt.scd41_last_seen_ms = resolved

            enabled = config.sht30_enabled if sensor == "sht30" else config.scd41_enabled
            if (
                enabled is not False
                and (now_ms - nxt.booted_at_ms) >= STARTUP_GRACE_MS
                and nxt.per_type["pi"].state != STATES["FIRING"]
            ):
                last_ms = nxt.sht30_last_seen_ms if sensor == "sht30" else nxt.scd41_last_seen_ms
                stale = rules.is_sensor_silent(
                    last_seen_ms=last_ms, now_ms=now_ms, config=config
                )
                entry, acts = drive_alert_type(
                    nxt.per_type[sensor], sensor, stale, {"last_seen_ms": last_ms},
                    now_ms, _fast_fire(config),
                )
                nxt.per_type[sensor] = entry
                actions.extend(acts)

    elif etype == "humidifier":
        prev_value = 1 if nxt.humidifier_on_since_ms is not None else 0
        new_value = event["value"]
        if prev_value == 0 and new_value == 1:
            nxt.humidifier_on_since_ms = now_ms
            nxt.rh_at_on = nxt.current_rh
            nxt.humidifier_cycle_log.append(now_ms)
            nxt.humidifier_cycle_log = [
                ts for ts in nxt.humidifier_cycle_log if now_ms - ts <= 86_400_000
            ]
            nxt.humidifier_cycles_last_24h = len(nxt.humidifier_cycle_log)
        elif prev_value == 1 and new_value == 0:
            nxt.humidifier_on_since_ms = None
            nxt.rh_at_on = None
            hum = nxt.per_type["humidifier"]
            if hum.state == STATES["FIRING"]:
                duration_ms = now_ms - hum.first_oob_at if hum.first_oob_at is not None else 0
                hum.state = STATES["OK"]
                hum.oob_count = 0
                hum.first_oob_at = None
                hum.last_fired_at = None
                hum.ctx = {}
                actions.append({
                    "kind": "recovery",
                    "alert_type": "humidifier",
                    "body": message.format_recovery(
                        alert_type="humidifier", fields={},
                        duration_ms=duration_ms, config=config,
                    ),
                    "duration_ms": duration_ms,
                })
        nxt.humidifier_last_msg_ts = now_ms

    elif etype == "pi_liveness":
        ws_connected = event.get("ws_connected")
        ros_connected = event.get("ros_connected")
        if ws_connected != nxt.ws_connected:
            if ws_connected:
                nxt.ws_last_connected_ms = now_ms
            nxt.ws_connected = ws_connected
        if ros_connected != nxt.ros_connected:
            nxt.ros_disconnected_since_ms = None if ros_connected else now_ms
            nxt.ros_connected = ros_connected
        if event.get("humidifier_last_msg_ts") is not None:
            nxt.humidifier_last_msg_ts = event["humidifier_last_msg_ts"]
        # js:507 -- absent key leaves the prior value; an explicit None overwrites.
        if "fc1_last_msg_ts" in event:
            nxt.fc1_last_msg_ts = event["fc1_last_msg_ts"]

        if (now_ms - nxt.booted_at_ms) >= STARTUP_GRACE_MS:
            # js:547 -- this call site DOES fast-fire.
            actions.extend(_eval_pi(nxt, config, now_ms, pi_config_is_fast_fire=True))

    elif etype == "tick":
        nxt.humidifier_cycle_log = [
            ts for ts in nxt.humidifier_cycle_log if now_ms - ts <= 86_400_000
        ]
        nxt.humidifier_cycles_last_24h = len(nxt.humidifier_cycle_log)

        if (now_ms - nxt.booted_at_ms) >= STARTUP_GRACE_MS:
            # js:580 -- this call site does NOT fast-fire. Pinned parity quirk.
            actions.extend(_eval_pi(nxt, config, now_ms, pi_config_is_fast_fire=False))

        if (
            not nxt.warming_up
            and nxt.humidifier_on_since_ms is not None
            and nxt.current_rh is not None
            and nxt.per_type["pi"].state != STATES["FIRING"]
        ):
            effective = (
                resolve_effective_config(nxt, config, now_ms) if has_mode_context(nxt) else config
            )
            stuck = rules.is_humidifier_stuck(
                humidifier_on_since_ms=nxt.humidifier_on_since_ms,
                rh_at_on=nxt.rh_at_on,
                current_rh=nxt.current_rh,
                now_ms=now_ms,
                config=effective,
                ws_connected=nxt.ws_connected,
                humidifier_last_msg_ts=nxt.humidifier_last_msg_ts,
            )
            hum_fields = {
                "on_since_ms": nxt.humidifier_on_since_ms,
                "rh_at_on": nxt.rh_at_on,
                "current_rh": nxt.current_rh,
            }
            entry, acts = drive_alert_type(
                nxt.per_type["humidifier"], "humidifier", stuck, hum_fields, now_ms, effective
            )
            nxt.per_type["humidifier"] = entry
            actions.extend(acts)

        # Required: during prolonged silence no sensor_health/sensor_freshness
        # events arrive, so without this the FIRING transition would never happen.
        if (now_ms - nxt.booted_at_ms) >= STARTUP_GRACE_MS and (
            nxt.per_type["pi"].state != STATES["FIRING"]
        ):
            actions.extend(_eval_physical_sensors(nxt, config, now_ms))

    elif etype == "snooze":
        alert_type = event.get("alert_type")
        until_ms = event.get("until_ms")
        if alert_type == "all":
            for t in ALERT_TYPES:
                nxt.per_type[t].snoozed_until = until_ms
        elif alert_type in nxt.per_type:
            nxt.per_type[alert_type].snoozed_until = until_ms

    elif etype == "heartbeat_tick":
        from datetime import datetime
        from zoneinfo import ZoneInfo

        local = datetime.fromtimestamp(now_ms / 1000, tz=ZoneInfo(config.timezone))
        local_date = local.strftime("%Y-%m-%d")
        # SANCTIONED DELTA from js:662 (MUSHY-44 item 4). Node uses `hour ===
        # heartbeat_hour` here while heartbeat.js dispatches at `hour >=
        # heartbeat_hour` and consumes its own day, so an alerter restarted after
        # the hour burned the day with no message. `>=` aligns the two stages.
        # The day-consumed guard below still caps it at one heartbeat per day.
        if local.hour >= config.heartbeat_hour and nxt.last_heartbeat_day != local_date:
            nxt.last_heartbeat_day = local_date
            actions.append({
                "kind": "heartbeat",       # bypasses ALL snoozes by design (js:664)
                "body": message.format_heartbeat(
                    summary=event["summary"], config=config, now_ms=now_ms
                ),
            })

    # Unknown event type: no-op (js:673)
    return nxt, actions
