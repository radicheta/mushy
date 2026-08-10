"""Temperature/RH to absolute-moisture conversions.

Mirrors ``src/mission-control/bridge/src/fc_derived.js`` EXACTLY -- same Tetens
saturation curve, same Mw/R, same 5.76 m3 chamber volume. That parity is
load-bearing: the recorded ``fc.water_vapor`` telemetry was produced by the JS,
so any divergence makes fitted values incomparable to the historical series.

RH points are not a conserved quantity -- the same gram of water is a different
number of RH points at 3 C than at 20 C. These conversions are what let the
chamber model balance moisture instead of balancing RH.
"""
from math import exp

# FC-1 interior: 1.2 x 2.4 x 2.0 m.
CHAMBER_VOLUME_M3 = 5.76

# Molar mass of water (g/mol) over the universal gas constant (J/(mol*K)).
MW_OVER_R = 18.01528 / 8.31446


def _clamp_rh_frac(rh_pct: float) -> float:
    """fc_derived.js clamps into [0, 1]; match it exactly."""
    return max(0.0, min(1.0, rh_pct / 100.0))


def saturation_vapor_pressure_kpa(temp_c: float) -> float:
    """Tetens equation over liquid water."""
    return 0.6108 * exp((17.27 * temp_c) / (temp_c + 237.3))


def absolute_humidity_g_m3(temp_c: float, rh_pct: float) -> float:
    """Water vapour mass per cubic metre of air."""
    avp_pa = saturation_vapor_pressure_kpa(temp_c) * 1000.0 * _clamp_rh_frac(rh_pct)
    return MW_OVER_R * (avp_pa / (temp_c + 273.15))


def relative_humidity_pct(temp_c: float, ah_g_m3: float) -> float:
    """Inverse of absolute_humidity_g_m3. Not clamped -- a value above 100
    means the air is supersaturated, and the caller should see that rather
    than have it silently hidden."""
    avp_pa = ah_g_m3 * (temp_c + 273.15) / MW_OVER_R
    return 100.0 * avp_pa / (saturation_vapor_pressure_kpa(temp_c) * 1000.0)


def water_vapor_ml(temp_c: float, rh_pct: float,
                   volume_m3: float = CHAMBER_VOLUME_M3) -> float:
    """Total vapour in the chamber air, grams (~= mL). Matches fc.water_vapor."""
    return absolute_humidity_g_m3(temp_c, rh_pct) * volume_m3
