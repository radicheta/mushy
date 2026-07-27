"""
tests/chamber/test_rules.py -- the 5 pure detectors (port of rules.js).

Each guard here exists because it once fired a false alert at a farmer:
  - stale-suspend        2026-05-07 false CRITICAL during the 11h fc1 outage
  - fc1-dark 3 min       Phase 46 D-09, piOfflineMin=15 was too slow for data-flow
  - offline blindness    Phase 29 D-04 / 999.39, cached values during an outage
"""

from dataclasses import dataclass

import pytest

from farm_agent.chamber import rules

MIN = 60_000


@dataclass
class _Freshness:
    state: str


@dataclass
class _Effective:
    """Minimal stand-in for Plan 07's EffectiveConfig."""

    rh_target: float = 90.0
    rh_band: float = 3.0
    freshness: object = None


# ---------------------------------------------------------------------------
# is_rh_oob -- Pitfall 1 (stale-suspend)
# ---------------------------------------------------------------------------


def test_rh_oob_true_when_outside_band():
    assert rules.is_rh_oob(80.0, _Effective()) is True


def test_rh_oob_false_when_inside_band():
    assert rules.is_rh_oob(91.0, _Effective()) is False


def test_rh_oob_boundary_is_exclusive():
    """rules.js:18 uses `>` -- exactly on the band edge is NOT out of band."""
    assert rules.is_rh_oob(93.0, _Effective()) is False   # |93-90| == 3
    assert rules.is_rh_oob(93.01, _Effective()) is True


def test_rh_oob_suspended_when_stale():
    """Phase 29 D-03: stale freshness suspends the rule (2026-05-07 false CRITICAL)."""
    eff = _Effective(freshness=_Freshness("stale"))
    assert rules.is_rh_oob(10.0, eff) is False


def test_rh_oob_active_when_cold_or_fresh():
    """Only 'stale' suspends. 'cold' and 'fresh' still evaluate (Pitfall 1)."""
    assert rules.is_rh_oob(10.0, _Effective(freshness=_Freshness("cold"))) is True
    assert rules.is_rh_oob(10.0, _Effective(freshness=_Freshness("fresh"))) is True


def test_rh_oob_active_when_freshness_absent():
    """Back-compat: a config with no freshness attribute is treated as fresh (rules.js:17)."""
    assert rules.is_rh_oob(10.0, _Effective(freshness=None)) is True


# ---------------------------------------------------------------------------
# is_sensor_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level,expected", [(0, False), (1, False), (2, True)])
def test_is_sensor_error_only_level_2(level, expected):
    assert rules.is_sensor_error({"level": level}) is expected


# ---------------------------------------------------------------------------
# is_pi_offline -- Pitfall 2 (fc1-dark is a SEPARATE hardcoded threshold)
# ---------------------------------------------------------------------------


def _pi_args(**over):
    base = dict(
        ws_connected=True,
        ros_connected=True,
        now_ms=10_000_000,
        ws_last_connected_ms=None,
        ros_disconnected_since_ms=None,
        fc1_last_msg_ts=None,
    )
    base.update(over)
    return base


def test_pi_offline_false_when_all_healthy(chamber_config):
    assert rules.is_pi_offline(**_pi_args(), config=chamber_config()) is False


def test_pi_offline_all_none_inputs_no_trigger(chamber_config):
    """Graceful degradation: absent liveness inputs must never fire (rules.js:45)."""
    cfg = chamber_config()
    assert rules.is_pi_offline(**_pi_args(ws_connected=False), config=cfg) is False


def test_pi_offline_ws_branch_uses_config_threshold(chamber_config):
    cfg = chamber_config(ALERT_PI_OFFLINE_MIN="5")
    now = 10_000_000
    assert rules.is_pi_offline(
        **_pi_args(ws_connected=False, now_ms=now, ws_last_connected_ms=now - 6 * MIN),
        config=cfg,
    ) is True
    assert rules.is_pi_offline(
        **_pi_args(ws_connected=False, now_ms=now, ws_last_connected_ms=now - 4 * MIN),
        config=cfg,
    ) is False


def test_pi_offline_ros_branch_requires_explicit_false(chamber_config):
    """rules.js:54 tests `rosConnected === false` -- None must not trigger."""
    cfg = chamber_config(ALERT_PI_OFFLINE_MIN="5")
    now = 10_000_000
    assert rules.is_pi_offline(
        **_pi_args(ros_connected=False, now_ms=now, ros_disconnected_since_ms=now - 6 * MIN),
        config=cfg,
    ) is True
    assert rules.is_pi_offline(
        **_pi_args(ros_connected=None, now_ms=now, ros_disconnected_since_ms=now - 6 * MIN),
        config=cfg,
    ) is False


def test_pi_offline_fc1_dark_hardcoded_3min_ignores_config(chamber_config):
    """Phase 46 D-09: the chamber-dark branch is 3 min FLAT, not pi_offline_min.

    With pi_offline_min=15 a config-driven threshold would stay quiet for 15 min.
    The farmer needs to know the chamber is uncontrolled in 3.
    """
    cfg = chamber_config(ALERT_PI_OFFLINE_MIN="15")
    now = 10_000_000
    assert rules.is_pi_offline(
        **_pi_args(now_ms=now, fc1_last_msg_ts=now - int(3.5 * MIN)), config=cfg
    ) is True
    assert rules.is_pi_offline(
        **_pi_args(now_ms=now, fc1_last_msg_ts=now - 2 * MIN), config=cfg
    ) is False


def test_fc1_dark_threshold_constant_is_three_minutes():
    assert rules.FC1_DARK_THRESHOLD_MS == 3 * 60_000


# ---------------------------------------------------------------------------
# is_humidifier_stuck -- Pitfall 5 (three gates, order matters)
# ---------------------------------------------------------------------------


def _hum_args(**over):
    now = 10_000_000
    base = dict(
        humidifier_on_since_ms=now - 45 * MIN,
        rh_at_on=80.0,
        current_rh=81.0,          # +1% in 45 min == stuck
        now_ms=now,
        ws_connected=True,
        humidifier_last_msg_ts=now - 10_000,
    )
    base.update(over)
    return base


def test_humidifier_stuck_true_when_live_and_no_rh_rise(chamber_config):
    cfg = chamber_config(ALERT_HUMIDIFIER_STUCK_MIN="30")
    assert rules.is_humidifier_stuck(**_hum_args(), config=cfg) is True


def test_humidifier_stuck_false_when_rh_rose(chamber_config):
    cfg = chamber_config(ALERT_HUMIDIFIER_STUCK_MIN="30")
    assert rules.is_humidifier_stuck(**_hum_args(current_rh=84.0), config=cfg) is False


def test_humidifier_stuck_gate1_ws_disconnected(chamber_config):
    """Phase 29 D-04 gate 1: no live data, no verdict (2026-05-07)."""
    cfg = chamber_config()
    assert rules.is_humidifier_stuck(**_hum_args(ws_connected=False), config=cfg) is False


def test_humidifier_stuck_gate2_no_humidifier_timestamp(chamber_config):
    """Gate 2: humidifier_last_msg_ts None means we have no liveness signal."""
    cfg = chamber_config()
    assert rules.is_humidifier_stuck(**_hum_args(humidifier_last_msg_ts=None), config=cfg) is False


def test_humidifier_stuck_gate3_stale_humidifier_timestamp(chamber_config):
    """Gate 3: humidifier telemetry older than sensor_offline_min is frozen, not live."""
    cfg = chamber_config(ALERT_SENSOR_OFFLINE_MIN="5")
    now = 10_000_000
    assert rules.is_humidifier_stuck(
        **_hum_args(now_ms=now, humidifier_last_msg_ts=now - 6 * MIN), config=cfg
    ) is False


def test_humidifier_stuck_false_before_threshold(chamber_config):
    cfg = chamber_config(ALERT_HUMIDIFIER_STUCK_MIN="30")
    now = 10_000_000
    assert rules.is_humidifier_stuck(
        **_hum_args(now_ms=now, humidifier_on_since_ms=now - 20 * MIN), config=cfg
    ) is False


def test_humidifier_stuck_false_when_never_turned_on(chamber_config):
    cfg = chamber_config()
    assert rules.is_humidifier_stuck(
        **_hum_args(humidifier_on_since_ms=None), config=cfg
    ) is False


# ---------------------------------------------------------------------------
# is_sensor_silent -- Pitfall 4 (minutes scale, independent of the flap floor)
# ---------------------------------------------------------------------------


def test_sensor_silent_true_past_threshold(chamber_config):
    cfg = chamber_config(ALERT_SENSOR_OFFLINE_MIN="5")
    now = 10_000_000
    assert rules.is_sensor_silent(last_seen_ms=now - 6 * MIN, now_ms=now, config=cfg) is True


def test_sensor_silent_false_within_threshold(chamber_config):
    cfg = chamber_config(ALERT_SENSOR_OFFLINE_MIN="5")
    now = 10_000_000
    assert rules.is_sensor_silent(last_seen_ms=now - 4 * MIN, now_ms=now, config=cfg) is False


def test_sensor_silent_none_last_seen_no_trigger(chamber_config):
    assert rules.is_sensor_silent(
        last_seen_ms=None, now_ms=10_000_000, config=chamber_config()
    ) is False


def test_sensor_silent_ignores_flap_floor(chamber_config):
    """Pitfall 4: the seconds-scale flap floor gates the Pi-FLAG path only.

    A sensor silent for 6 minutes is silent regardless of sensor_flap_min_sec.
    Never merge the two thresholds.
    """
    cfg = chamber_config(ALERT_SENSOR_OFFLINE_MIN="5", ALERT_SENSOR_FLAP_MIN_SEC="3600")
    now = 10_000_000
    assert rules.is_sensor_silent(last_seen_ms=now - 6 * MIN, now_ms=now, config=cfg) is True
