"""
tests/chamber/test_config.py -- ChamberConfig (D-02/D-03/D-04).

Defaults are the port target from src/agents/alerter/src/config.js; the ONE
deliberate divergence is timezone (D-04: Toronto -> Montevideo).
"""

import dataclasses

import pytest


def test_relocated_knobs_have_config_js_defaults(chamber_config):
    """The 7 fields moved off TenantConfig keep their config.js defaults."""
    cfg = chamber_config()
    assert cfg.rh_target == 90.0            # config.js:147
    assert cfg.rh_band == 3.0               # config.js:148
    assert cfg.pi_offline_min == 5          # config.js:153
    assert cfg.sensor_offline_min == 5      # config.js:154
    assert cfg.heartbeat_hour == 8          # config.js:170
    assert cfg.max_sends_per_hour == 20     # config.js:175


def test_not_yet_ported_knobs_have_config_js_defaults(chamber_config):
    """The rest of the alerter knob set (Tier B/C/D) lands with the right defaults."""
    cfg = chamber_config()
    assert cfg.oob_n == 5                       # config.js:149
    assert cfg.oob_window_min == 3              # config.js:150
    assert cfg.cooldown_min == 30               # config.js:151
    assert cfg.critical_cooldown_min == 60      # config.js:152
    assert cfg.sht30_enabled is True            # config.js:161
    assert cfg.scd41_enabled is True            # config.js:162
    assert cfg.sensor_flap_min_sec == 60        # config.js:168
    assert cfg.humidifier_stuck_min == 30       # config.js:169
    assert cfg.mode_stale_min == 5              # config.js:172
    assert cfg.mode_boot_grace_ms == 60_000     # config.js:173 (SEC x 1000)
    assert cfg.receive_poll_sec == 30           # config.js:174
    assert cfg.dashboard_url == "http://elder-plops-ts:8081/farmer"      # config.js:177
    assert cfg.bridge_ws_url == "ws://host.docker.internal:8081"          # config.js:130
    assert cfg.bridge_health_url == "http://host.docker.internal:8081/health"  # config.js:131


def test_timezone_defaults_to_montevideo(chamber_config):
    """D-04 / CHM-02: the code default flips Toronto -> Montevideo."""
    cfg = chamber_config()
    assert cfg.timezone == "America/Montevideo"


def test_tz_env_overrides_timezone(chamber_config):
    """D-04 keeps the knob: TZ still wins, for future multi-tenant."""
    cfg = chamber_config(TZ="Europe/Madrid")
    assert cfg.timezone == "Europe/Madrid"


def test_numeric_knobs_coerce_from_env(chamber_config):
    """Int and float knobs parse from env strings (the coercion coverage that
    moved here from test_tenancy when the fields relocated)."""
    cfg = chamber_config(ALERT_RH_TARGET="92.5", ALERT_PI_OFFLINE_MIN="99")
    assert cfg.rh_target == 92.5
    assert isinstance(cfg.rh_target, float)
    assert cfg.pi_offline_min == 99
    assert isinstance(cfg.pi_offline_min, int)


def test_bool_knobs_parse_false(chamber_config):
    """999.42 mute flags: only the literal 'false' disables (config.js:161-162)."""
    cfg = chamber_config(ALERT_SHT30_ENABLED="false", ALERT_SCD41_ENABLED="FALSE")
    assert cfg.sht30_enabled is False
    assert cfg.scd41_enabled is False
    assert chamber_config(ALERT_SHT30_ENABLED="0").sht30_enabled is True  # only 'false' mutes


def test_malformed_int_raises(chamber_config):
    """Fail fast at boot rather than silently defaulting (tenant.py parse contract)."""
    with pytest.raises(RuntimeError, match="ALERT_OOB_N"):
        chamber_config(ALERT_OOB_N="not-a-number")


def test_identity_comes_from_tenant_config_not_env(chamber_config, tenant_config):
    """D-02: secrets/identity are injected, never re-read from env.

    The env dict here claims a DIFFERENT sender. If ChamberConfig re-read env,
    it would pick up the impostor.
    """
    cfg = chamber_config(SIGNAL_SENDER="+19999999999", SIGNAL_RECIPIENT="+19999999998")
    assert cfg.signal_sender == tenant_config.signal_sender
    assert cfg.signal_recipient == tenant_config.signal_recipient
    assert cfg.signal_api_url == tenant_config.signal_api_url
    assert cfg.tenant_id == tenant_config.tenant_id
    assert cfg.signal_sender != "+19999999999"


def test_chamber_config_is_frozen(chamber_config):
    """Immutable, like TenantConfig."""
    cfg = chamber_config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.rh_target = 1.0
