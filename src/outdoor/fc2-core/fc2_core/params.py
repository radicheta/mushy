"""FC-2 settings: validation and the atomic persisted overlay (no ROS imports)."""
import dataclasses
import os
import re
import tempfile
from typing import Any, Mapping, Optional

import yaml

from fc2_core.rule import RuleParams

RULE_PARAM_NAMES = tuple(f.name for f in dataclasses.fields(RuleParams))
# Never changed live.
STARTUP_ONLY = ('valve_gpio_pin', 'valve_active_low', 'actuator_simulation_mode')

_HHMM = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
_RATES = ('cool_bursts_per_hour', 'hot_bursts_per_hour',
          'fallback_bursts_per_hour')
DEFAULT_OVERLAY_PATH = '/var/lib/fc2-core/runtime_overrides.yaml'
MAX_OPEN_CEILING_SEC = 600.0
MAX_OPEN_SEC_PER_HOUR = 1800.0  # 50 % duty
GUARD_MARGIN_SEC = 2.0  # the control tick is 1 s; a normal burst must close first


def params_from_mapping(m: Mapping[str, Any]) -> RuleParams:
    return RuleParams(**{k: m[k] for k in RULE_PARAM_NAMES if k in m})


def validate(p: RuleParams) -> Optional[str]:
    """None if p is acceptable, else a human-readable reason."""
    if p.cool_temp_c >= p.hot_temp_c:
        return 'cool_temp_c must be below hot_temp_c'
    for name in _RATES:
        if getattr(p, name) < 0:
            return f'{name} must not be negative'
    if p.fallback_bursts_per_hour <= 0:
        return 'fallback_bursts_per_hour must be positive (a dead feed must still water)'
    if p.pulse_sec <= 0:
        return 'pulse_sec must be positive'
    if p.max_open_sec < p.pulse_sec + GUARD_MARGIN_SEC:
        return f'max_open_sec must be at least pulse_sec + {GUARD_MARGIN_SEC:g}'
    if p.max_open_sec > MAX_OPEN_CEILING_SEC:
        return f'max_open_sec must not exceed {MAX_OPEN_CEILING_SEC:g}'
    if max(getattr(p, n) for n in _RATES) * p.pulse_sec > MAX_OPEN_SEC_PER_HOUR:
        return 'valve would be open more than 50% of the hour'
    if p.weather_stale_sec <= 0:
        return 'weather_stale_sec must be positive'
    for name in ('night_start', 'night_end'):
        v = getattr(p, name)
        if not isinstance(v, str) or not _HHMM.match(v):
            return f'{name} must be HH:MM'
    return None


def write_overlay(path: str, values: Mapping[str, Any]) -> None:
    """Atomically write a ROS parameter overlay file."""
    doc = {'/**': {'ros__parameters': dict(values)}}
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            yaml.safe_dump(doc, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def usable_overlay(path: str) -> bool:
    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
        return bool(doc['/**']['ros__parameters'])
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return False
