"""
chamber/config.py -- alerter configuration for the mushy-private chamber package.

Port of src/agents/alerter/src/config.js (that file's Tier A/B/C/D comments are
the spec). chamber/ is the ONLY mushy-private package; it may import Foray
packages, never the reverse (D-00).

D-02: secrets and shared identity are INJECTED from an already-loaded
TenantConfig -- this module never calls _must_env for them.
D-03: owns the 7 alerter knobs that used to sit on TenantConfig.
D-04: `timezone` defaults to America/Montevideo, NOT config.js's America/Toronto.
      The Toronto default was a Phase-13 copy-paste; the farm is in Uruguay.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from farm_agent.tenancy.tenant import TenantConfig


def _parse_int_env(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"[chamber-config] {key}={raw!r} is not a valid integer") from None


def _parse_float_env(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"[chamber-config] {key}={raw!r} is not a valid number") from None


def _parse_bool_env(env: dict[str, str], key: str, default: bool = True) -> bool:
    """config.js:161-162 semantics: ONLY the literal 'false' (any case) disables."""
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() != "false"


@dataclass(frozen=True)
class ChamberConfig:
    """Immutable alerter config. Never logged wholesale (T-63-04)."""

    # --- Injected identity (D-02, from TenantConfig) ---
    tenant_id: str
    signal_sender: str
    signal_recipient: str
    signal_api_url: str

    # --- Tier A: mode-anchored fallbacks (config.js:147-148) ---
    rh_target: float
    rh_band: float

    # --- Tier B: per-mode overridable (config.js:149-152, 169) ---
    oob_n: int
    oob_window_min: int
    cooldown_min: int
    critical_cooldown_min: int
    humidifier_stuck_min: int

    # --- Tier C: globally overridable (config.js:153-154, 170, 175) ---
    pi_offline_min: int
    sensor_offline_min: int
    heartbeat_hour: int
    max_sends_per_hour: int

    # --- Tier D: env-only, always live (config.js:130-131, 161-162, 168, 172-174, 176-177) ---
    sht30_enabled: bool
    scd41_enabled: bool
    sensor_flap_min_sec: int
    mode_stale_min: int
    mode_boot_grace_ms: int
    receive_poll_sec: int
    timezone: str
    dashboard_url: str
    bridge_ws_url: str
    bridge_health_url: str


def load(
    env: dict[str, str] | None = None,
    *,
    tenant_config: TenantConfig,
) -> ChamberConfig:
    """Build ChamberConfig from env, taking identity from an injected TenantConfig.

    Env-only: there is no tenant-YAML layer for chamber knobs (RESEARCH Open
    Question 3 -- the live alerter is configured through compose ENV, and the
    tenant YAML layer is inert in Docker anyway).
    """
    if env is None:
        env = dict(os.environ)

    return ChamberConfig(
        # D-02 injection -- NOT re-read from env
        tenant_id=tenant_config.tenant_id,
        signal_sender=tenant_config.signal_sender,
        signal_recipient=tenant_config.signal_recipient,
        signal_api_url=tenant_config.signal_api_url,
        # Tier A
        rh_target=_parse_float_env(env, "ALERT_RH_TARGET", 90.0),
        rh_band=_parse_float_env(env, "ALERT_RH_BAND", 3.0),
        # Tier B
        oob_n=_parse_int_env(env, "ALERT_OOB_N", 5),
        oob_window_min=_parse_int_env(env, "ALERT_OOB_WINDOW_MIN", 3),
        cooldown_min=_parse_int_env(env, "ALERT_COOLDOWN_MIN", 30),
        critical_cooldown_min=_parse_int_env(env, "ALERT_CRITICAL_COOLDOWN_MIN", 60),
        humidifier_stuck_min=_parse_int_env(env, "ALERT_HUMIDIFIER_STUCK_MIN", 30),
        # Tier C
        pi_offline_min=_parse_int_env(env, "ALERT_PI_OFFLINE_MIN", 5),
        sensor_offline_min=_parse_int_env(env, "ALERT_SENSOR_OFFLINE_MIN", 5),
        heartbeat_hour=_parse_int_env(env, "ALERT_HEARTBEAT_HOUR", 8),
        max_sends_per_hour=_parse_int_env(env, "ALERT_MAX_SENDS_PER_HOUR", 20),
        # Tier D
        sht30_enabled=_parse_bool_env(env, "ALERT_SHT30_ENABLED"),
        scd41_enabled=_parse_bool_env(env, "ALERT_SCD41_ENABLED"),
        sensor_flap_min_sec=_parse_int_env(env, "ALERT_SENSOR_FLAP_MIN_SEC", 60),
        mode_stale_min=_parse_int_env(env, "ALERT_MODE_STALE_MIN", 5),
        mode_boot_grace_ms=_parse_int_env(env, "ALERT_MODE_BOOT_GRACE_SEC", 60) * 1000,
        receive_poll_sec=_parse_int_env(env, "ALERT_RECEIVE_POLL_SEC", 30),
        # D-04: the flip. config.js:176 says America/Toronto -- deliberately NOT copied.
        timezone=env.get("TZ") or "America/Montevideo",
        dashboard_url=env.get("DASHBOARD_URL") or "http://elder-plops-ts:8081/farmer",
        bridge_ws_url=env.get("BRIDGE_WS_URL") or "ws://host.docker.internal:8081",
        bridge_health_url=(
            env.get("BRIDGE_HEALTH_URL") or "http://host.docker.internal:8081/health"
        ),
    )
