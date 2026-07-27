"""
tenancy/tenant.py — the SOLE reader of os.environ in farm_agent business code.

Ports src/agents/alerter/src/config.js to a frozen Python dataclass with
layered YAML+env+default loading (tenant YAML → env → hardcoded default).

Secrets (SIGNAL_SENDER, TIMESCALE_PASSWORD, ANTHROPIC_API_KEY, FARMOS_PASSWORD)
resolve ONLY from env via _must_env() — never from tenant YAML (FND-02 / W9 policy).

T-56-02-01: path-traversal guard — _load_tenant_file resolves the path and
rejects any result that escapes the TENANTS_BASE directory.
T-56-02-02: secrets never persisted to YAML; TenantConfig is not logged at boot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

# Canonical tenants directory — five parents up from this file:
#   farm_agent/tenancy/tenant.py
#   → farm_agent/tenancy/   (.parent)
#   → farm_agent/           (.parent.parent)
#   → src/farm-agent/       (.parent.parent.parent)
#   → src/                  (.parent.parent.parent.parent)
#   → repo root             (.parent.parent.parent.parent.parent)
# → repo_root/tenants/
#
# In Docker (WORKDIR=/app, farm_agent/ copied to /app/farm_agent/):
#   five parents resolves to /tenants/ which does not exist, so
#   _load_tenant_file returns {} for all lookups (config comes from
#   compose environment: block, not tenant YAML files).
TENANTS_BASE = Path(__file__).parent.parent.parent.parent.parent / "tenants"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _must_env(env: dict[str, str], key: str) -> str:
    """Return env[key], raising RuntimeError (not KeyError) when absent or falsy.

    Mirrors config.js mustEnv() — falsy (empty string, missing) is treated as
    "not provided" per the W9 secrets policy.
    """
    v = env.get(key)
    if not v:
        raise RuntimeError(f"[config] Required env var {key} is missing")
    return v


def _load_tenant_file(tenant_id: str, filename: str) -> dict[str, Any]:
    """Load tenants/<tenant_id>/<filename> under TENANTS_BASE with traversal guard.

    Returns {} on:
    - Path that resolves outside TENANTS_BASE (traversal attempt)
    - Non-existent file
    - YAML parse failure (graceful degradation, per T-56-02-03 accept disposition)
    """
    p = (TENANTS_BASE / tenant_id / filename).resolve()
    boundary = str(TENANTS_BASE)
    # Boundary-safe: must equal base (impossible for a file) or start with base + sep.
    # NOT a glob prefix check — that would allow siblings like "tenants-evil/...".
    if str(p) != boundary and not str(p).startswith(boundary + os.sep):
        return {}
    if not p.exists():
        return {}
    try:
        yaml = YAML()
        result = yaml.load(p)
        return result if isinstance(result, dict) else {}
    except Exception:  # noqa: BLE001 — graceful on malformed YAML
        import warnings
        warnings.warn(f"[config] {p} parse failed", stacklevel=2)
        return {}


def _pick(tenant_cfg: dict[str, Any], env: dict[str, str], key: str, default: Any) -> Any:
    """Layered get: tenant YAML → env → hardcoded default.

    Mirrors config.js pick(): None and undefined both fall through to the next
    layer (consistent with YAML omission vs explicit null).
    """
    v = tenant_cfg.get(key)
    if v is not None:
        return v
    ev = env.get(key)
    if ev is not None:
        return ev
    return default


def _parse_int_env(env: dict[str, str], key: str, default: int) -> int:
    """Parse an integer env var, returning default when absent.

    Raises RuntimeError naming the key and bad value on non-numeric input
    (e.g. operator typo, unexpanded ${VAR} placeholder).
    """
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(
            f"[config] {key}={raw!r} is not a valid integer"
        ) from None


def _parse_float_env(env: dict[str, str], key: str, default: float) -> float:
    """Parse a float env var, returning default when absent.

    Raises RuntimeError naming the key and bad value on non-numeric input.
    """
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(
            f"[config] {key}={raw!r} is not a valid float"
        ) from None


def _resolve_farmer_map(
    tenant_cfg: dict[str, Any],
    env: dict[str, str],
) -> dict[str, str]:
    """Resolve SIGNAL_FARMER_MAP from YAML object form or env string form.

    YAML object form (preferred):
        SIGNAL_FARMER_MAP:
          "+59892893012": f1
          "+59891840205": bot

    Legacy env string form:
        SIGNAL_FARMER_MAP="+59892893012:f1,+59891840205:bot"
    """
    from_yaml = tenant_cfg.get("SIGNAL_FARMER_MAP")
    if from_yaml and isinstance(from_yaml, dict) and not isinstance(from_yaml, list):
        return {str(k): str(v) for k, v in from_yaml.items() if k and v}
    # Fall back to env string form
    raw = env.get("SIGNAL_FARMER_MAP", "")
    return _parse_farmer_map_string(raw)


def _parse_farmer_map_string(raw: str) -> dict[str, str]:
    """Parse '+phone:slug,...' string into {phone: slug}.

    Splits on FIRST colon only (phones contain no ':').
    Silently drops malformed entries.
    """
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        idx = entry.find(":")
        if idx <= 0:
            continue
        phone = entry[:idx].strip()
        slug = entry[idx + 1:].strip()
        if phone and slug:
            result[phone] = slug
    return result


def _resolve_farmos_integration(
    tenant_cfg: dict[str, Any],
    env: dict[str, str],
) -> bool:
    """Coerce FARMOS_INTEGRATION from YAML bool or env string.

    YAML: true/false (native bool)
    Env: '1' → True, anything else → False
    Default: False
    """
    v = tenant_cfg.get("FARMOS_INTEGRATION")
    if v is not None:
        return v is True or v == "true" or v == "1"
    return (env.get("FARMOS_INTEGRATION") or "0") == "1"


# ---------------------------------------------------------------------------
# Public helper — phone masking (V7: never log full e164)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# TenantConfig dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TenantConfig:
    """Immutable config for a single tenant.

    Secrets (signal_sender, timescale_password, anthropic_api_key, farmos_password)
    are populated exclusively from env — never from tenant YAML (W9 policy).
    All other fields use the YAML → env → default layer order.
    """

    # Identity
    tenant_id: str

    # --- Secrets (env-only) ---
    signal_sender: str
    timescale_password: str
    anthropic_api_key: str
    farmos_password: str

    # --- Signal ---
    signal_api_url: str
    signal_additional_senders: list[str]
    signal_recipient: str
    signal_group_id: str | None
    signal_farmer_map: dict[str, str]        # e164 → slug

    # --- Strains ---
    strains: list[str]                       # from strains.yaml STRAIN_CODES

    # --- Event gate ---
    event_gate_convo_mode: str               # silent | negative_only | off

    # --- farmOS ---
    farmos_url: str
    farmos_username: str
    farmos_integration: bool

    # --- TimescaleDB (non-secret fields) ---
    timescale_host: str
    timescale_db: str
    timescale_user: str

    # --- Transcription ---
    whisper_url: str

    # --- Capture ---
    capture_base_dir: str
    capture_retention_days: int

    # --- Receive / send limits ---
    receive_poll_sec: int

    # --- Draft confirm loop ---
    draft_pending_timeout_min: int
    draft_watchdog_interval_ms: int
    draft_nudge_fraction: float
    max_edit_turns: int

    # --- Commit watchdog ---
    commit_watchdog_interval_ms: int
    commit_watchdog_batch_cap: int
    commit_retry_max: int

    # --- farmOS fidelity gate ---
    fidelity_csv_path: str

    # --- General ---
    log_level: str


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load(env: dict[str, str] | None = None) -> TenantConfig:
    """Load TenantConfig from the given env dict (default: os.environ).

    Layer order: tenants/<id>/config.yaml → tenants/<id>/strains.yaml → env → default.
    Secrets bypass the layer order and ALWAYS come from env via _must_env().
    """
    if env is None:
        env = dict(os.environ)

    tenant_id = env.get("TENANT_ID") or "mossrock"

    # Merge config.yaml + strains.yaml into a single tenant config dict.
    # strains.yaml contributes ONLY STRAIN_CODES -- not arbitrary keys.
    # A stray FARMOS_URL or SIGNAL_RECIPIENT in strains.yaml must NOT
    # silently redirect writes to an attacker-controlled host (WR-03).
    strains_raw = _load_tenant_file(tenant_id, "strains.yaml")
    tenant_cfg: dict[str, Any] = {
        **_load_tenant_file(tenant_id, "config.yaml"),
        **({"STRAIN_CODES": strains_raw["STRAIN_CODES"]}
           if "STRAIN_CODES" in strains_raw else {}),
    }

    # --- Secrets (env-only, via _must_env) ---
    signal_sender = _must_env(env, "SIGNAL_SENDER")
    timescale_password = _must_env(env, "TIMESCALE_PASSWORD")
    anthropic_api_key = _must_env(env, "ANTHROPIC_API_KEY")
    # FARMOS_PASSWORD: env-only but defaults to '' for back-compat when
    # farmosIntegration=false (config.js: env.FARMOS_PASSWORD || '')
    farmos_password = env.get("FARMOS_PASSWORD") or ""

    # --- Signal ---
    signal_api_url = _pick(tenant_cfg, env, "SIGNAL_API_URL", "http://signal-cli:8080")
    _raw_additional = env.get("SIGNAL_ADDITIONAL_SENDERS", "")
    signal_additional_senders = [s for s in (x.strip() for x in _raw_additional.split(",")) if s]

    signal_recipient = _pick(tenant_cfg, env, "SIGNAL_RECIPIENT", None) or _must_env(
        env, "SIGNAL_RECIPIENT"
    )
    _raw_group_id = _pick(tenant_cfg, env, "SIGNAL_GROUP_ID", None)
    signal_group_id = None if (_raw_group_id == "" or _raw_group_id is None) else _raw_group_id

    signal_farmer_map = _resolve_farmer_map(tenant_cfg, env)

    # --- Strains ---
    strains = _pick(tenant_cfg, env, "STRAIN_CODES", [])
    # Ensure it's a plain list of strings (ruamel may return CommentedSeq)
    if strains and not isinstance(strains, list):
        strains = list(strains)

    # --- Event gate ---
    event_gate_convo_mode = _pick(tenant_cfg, env, "EVENT_GATE_CONVO_MODE", "silent")

    # --- farmOS ---
    farmos_url = _pick(tenant_cfg, env, "FARMOS_URL", "http://10.68.155.50:18080")
    farmos_username = _pick(tenant_cfg, env, "FARMOS_USERNAME", "")
    farmos_integration = _resolve_farmos_integration(tenant_cfg, env)

    # --- TimescaleDB ---
    timescale_host = env.get("TIMESCALE_HOST") or "host.docker.internal"
    timescale_db = env.get("TIMESCALE_DB") or "postgres"
    timescale_user = env.get("TIMESCALE_USER") or "postgres"

    # --- Transcription ---
    whisper_url = env.get("WHISPER_URL") or "http://host.docker.internal:8090"

    # --- Capture ---
    capture_base_dir = env.get("CAPTURE_BASE_PATH") or "/data/signal-capture"
    capture_retention_days = _parse_int_env(env, "CAPTURE_RETENTION_DAYS", 30)

    # --- Receive / send limits ---
    receive_poll_sec = _parse_int_env(env, "ALERT_RECEIVE_POLL_SEC", 30)

    # --- Draft confirm loop ---
    draft_pending_timeout_min = _parse_int_env(env, "DRAFT_PENDING_TIMEOUT_MIN", 30)
    draft_watchdog_interval_ms = _parse_int_env(env, "DRAFT_WATCHDOG_INTERVAL_MS", 60000)
    draft_nudge_fraction = _parse_float_env(env, "DRAFT_NUDGE_FRACTION", 0.8)
    max_edit_turns = _parse_int_env(env, "MAX_EDIT_TURNS", 3)

    # --- Commit watchdog ---
    commit_watchdog_interval_ms = _parse_int_env(env, "COMMIT_WATCHDOG_INTERVAL_MS", 30000)
    commit_watchdog_batch_cap = _parse_int_env(env, "COMMIT_WATCHDOG_BATCH_CAP", 10)
    commit_retry_max = _parse_int_env(env, "COMMIT_RETRY_MAX", 3)

    # --- farmOS fidelity gate ---
    fidelity_csv_path = _pick(tenant_cfg, env, "FIDELITY_CSV_PATH", "")

    # --- General ---
    log_level = env.get("LOG_LEVEL") or "info"

    return TenantConfig(
        tenant_id=tenant_id,
        signal_sender=signal_sender,
        timescale_password=timescale_password,
        anthropic_api_key=anthropic_api_key,
        farmos_password=farmos_password,
        signal_api_url=str(signal_api_url),
        signal_additional_senders=signal_additional_senders,
        signal_recipient=signal_recipient,
        signal_group_id=signal_group_id,
        signal_farmer_map=signal_farmer_map,
        strains=list(strains),
        event_gate_convo_mode=str(event_gate_convo_mode),
        farmos_url=str(farmos_url),
        farmos_username=str(farmos_username),
        farmos_integration=farmos_integration,
        timescale_host=timescale_host,
        timescale_db=timescale_db,
        timescale_user=timescale_user,
        whisper_url=whisper_url,
        capture_base_dir=capture_base_dir,
        capture_retention_days=capture_retention_days,
        receive_poll_sec=receive_poll_sec,
        draft_pending_timeout_min=draft_pending_timeout_min,
        draft_watchdog_interval_ms=draft_watchdog_interval_ms,
        draft_nudge_fraction=draft_nudge_fraction,
        max_edit_turns=max_edit_turns,
        commit_watchdog_interval_ms=commit_watchdog_interval_ms,
        commit_watchdog_batch_cap=commit_watchdog_batch_cap,
        commit_retry_max=commit_retry_max,
        fidelity_csv_path=str(fidelity_csv_path),
        log_level=log_level,
    )
