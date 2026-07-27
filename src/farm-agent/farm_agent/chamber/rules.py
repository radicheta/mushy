"""
chamber/rules.py -- the 5 pure detectors. Port of src/agents/alerter/src/rules.js.

Every function is pure: no I/O, no logging, no module-global config. Config
arrives as a parameter so the FSM can feed either raw ChamberConfig or the
mode-anchored EffectiveConfig (Plan 07) without the detectors knowing.

Node `!= null` is rendered as `is not None` throughout. Falsy checks would be a
bug: 0, 0.0 and "" are legitimate values in this domain.
"""

from __future__ import annotations

# rules.js:5 -- Phase 46 D-09. The chamber-dark threshold is HARD-CODED, not
# config-driven: the legacy piOfflineMin=15 (from fc_config.yaml, sized for the
# Pi-ping liveness branch) is far too slow for the data-flow signal. Surfaced by
# the 2026-05-21 46-03 live-fire smoke.
FC1_DARK_THRESHOLD_MS = 3 * 60_000


def is_rh_oob(humidity: float, effective) -> bool:
    """True when |humidity - rh_target| > rh_band. Port of rules.js:16-19.

    Phase 29 D-03: when freshness is 'stale' (mode unknown / fc1 offline) the rule
    is SUSPENDED, to avoid the 2026-05-07 false-CRITICAL pathology where a frozen
    cached RH read as wildly out of band during an 11h outage.

    Only 'stale' suspends. 'cold' (boot grace) and 'fresh' both evaluate normally,
    as does a config carrying no freshness at all -- the gate is opt-in via
    short-circuit, preserving pre-Phase-29 callers (rules.js:17).
    """
    freshness = getattr(effective, "freshness", None)
    if freshness is not None and getattr(freshness, "state", None) == "stale":
        return False
    return abs(humidity - effective.rh_target) > effective.rh_band


def is_sensor_error(sensor_health: dict) -> bool:
    """True when sensor_health.level == 2 (ERROR). Port of rules.js:25-27.

    NOT suppressed by warm-up (ALRT-05) -- that gating lives in the FSM.
    """
    return sensor_health.get("level") == 2


def is_pi_offline(
    *,
    ws_connected: bool,
    ros_connected: bool | None,
    now_ms: int,
    ws_last_connected_ms: int | None,
    ros_disconnected_since_ms: int | None,
    fc1_last_msg_ts: int | None,
    config,
) -> bool:
    """True when the chamber looks dark. Port of rules.js:47-69. Three OR-triggers:

      1. WS disconnected for > pi_offline_min minutes
      2. ROS disconnected for > pi_offline_min minutes
      3. fc1 publisher silent for > FC1_DARK_THRESHOLD_MS (Phase 46 D-03)

    Trigger 3 is the real "chamber dark" signal -- fc1 publisher silence inferred
    from data flow across every subscribed topic. Triggers 1-2 are RETAINED (D-03)
    because they catch failure modes the data-flow signal cannot see (an
    alerter<->bridge partition, a bridge container whose ROS init failed).

    A None liveness input skips its branch: no trigger, no false positive.
    """
    threshold_ms = config.pi_offline_min * 60_000

    if not ws_connected and ws_last_connected_ms is not None:
        if now_ms - ws_last_connected_ms > threshold_ms:
            return True

    # rules.js:54 tests `=== false` explicitly -- an unknown (None) ROS state is
    # not evidence of an outage.
    if ros_connected is False and ros_disconnected_since_ms is not None:
        if now_ms - ros_disconnected_since_ms > threshold_ms:
            return True

    # Phase 46 D-03 + D-09. Hard 3-minute constant, NOT config.pi_offline_min.
    if fc1_last_msg_ts is not None:
        if now_ms - fc1_last_msg_ts > FC1_DARK_THRESHOLD_MS:
            return True

    return False


def is_humidifier_stuck(
    *,
    humidifier_on_since_ms: int | None,
    rh_at_on: float | None,
    current_rh: float | None,
    now_ms: int,
    config,
    ws_connected: bool | None = None,
    humidifier_last_msg_ts: int | None = None,
) -> bool:
    """True when the humidifier has run > humidifier_stuck_min with < 3% RH rise.
    Port of rules.js:77-96.

    Phase 29 D-04 / 999.39 offline-blindness gates, checked FIRST and in this order.
    The 2026-05-07 false CRITICAL fired during the 11h fc1 outage because
    humidifier_on_since_ms was ancient and current_rh was frozen -- with no live
    data the honest answer is "no verdict", not "stuck".

    DELIBERATE SIMPLIFICATION: JS distinguished `null` (suppress) from `undefined`
    (pre-Phase-29 caller, skip the gate). Python has only None, so None suppresses.
    Every Plan 07 call site therefore passes ws_connected and humidifier_last_msg_ts
    explicitly -- audit that when wiring the FSM.
    """
    if ws_connected is False:
        return False
    if humidifier_last_msg_ts is None:
        return False
    if (now_ms - humidifier_last_msg_ts) > (config.sensor_offline_min or 5) * 60_000:
        return False

    # ---- math unchanged from pre-Phase-29 ----
    if humidifier_on_since_ms is None:
        return False
    on_duration_ms = now_ms - humidifier_on_since_ms
    if on_duration_ms <= config.humidifier_stuck_min * 60_000:
        return False
    return (current_rh - rh_at_on) < 3.0


def is_sensor_silent(*, last_seen_ms: int | None, now_ms: int, config) -> bool:
    """True when a physical sensor has been quiet past sensor_offline_min.
    Port of rules.js:104-108.

    MINUTES scale, and deliberately independent of the SECONDS-scale
    sensor_flap_min_sec floor (2026-05-12), which gates only the Pi-side
    `xxx_fresh='false'` flag path in the FSM. Merging the two thresholds would
    either reintroduce I2C-transient false alarms or mask real hard failures.
    """
    if last_seen_ms is None:
        return False
    return now_ms - last_seen_ms > config.sensor_offline_min * 60_000
