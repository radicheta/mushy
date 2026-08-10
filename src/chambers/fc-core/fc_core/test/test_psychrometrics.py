"""Psychrometrics parity with the bridge's fc_derived.js.

Reference values generated from the live JS implementation, not hand-derived.
If these drift, simulated moisture stops being comparable to the recorded
fc.water_vapor series, which is the whole reason this module mirrors the JS.
"""
import pytest

from fc_core.sim.psychrometrics import (
    CHAMBER_VOLUME_M3,
    absolute_humidity_g_m3,
    relative_humidity_pct,
    saturation_vapor_pressure_kpa,
    water_vapor_ml,
)

# (temp_c, rh_pct, svp_kpa, water_vapor_ml, ah_g_m3) from fc_derived.js
REFERENCE = [
    (20.0,  90.00, 2.33828127093,  89.5939767126, 15.5545098459),
    (4.8,   90.00, 0.860207413492, 34.7622968402,  6.03512097920),
    (0.0,   50.00, 0.610800000000, 13.9539537587,  2.42256141644),
    (30.0, 100.00, 4.24306505876, 174.683373256,  30.3269745237),
    (10.0,  61.85, 1.22796261934,  33.4763219675,  5.81186145270),
]


def test_chamber_volume_matches_the_bridge():
    assert CHAMBER_VOLUME_M3 == 5.76


@pytest.mark.parametrize('temp_c,rh_pct,svp,wv_ml,ah', REFERENCE)
def test_saturation_vapor_pressure_matches_js(temp_c, rh_pct, svp, wv_ml, ah):
    assert saturation_vapor_pressure_kpa(temp_c) == pytest.approx(svp, rel=1e-11)


@pytest.mark.parametrize('temp_c,rh_pct,svp,wv_ml,ah', REFERENCE)
def test_absolute_humidity_matches_js(temp_c, rh_pct, svp, wv_ml, ah):
    assert absolute_humidity_g_m3(temp_c, rh_pct) == pytest.approx(ah, rel=1e-11)


@pytest.mark.parametrize('temp_c,rh_pct,svp,wv_ml,ah', REFERENCE)
def test_water_vapor_ml_matches_js(temp_c, rh_pct, svp, wv_ml, ah):
    assert water_vapor_ml(temp_c, rh_pct) == pytest.approx(wv_ml, rel=1e-11)


@pytest.mark.parametrize('temp_c,rh_pct,svp,wv_ml,ah', REFERENCE)
def test_relative_humidity_is_the_exact_inverse(temp_c, rh_pct, svp, wv_ml, ah):
    assert relative_humidity_pct(temp_c, ah) == pytest.approx(rh_pct, rel=1e-9)


def test_absolute_humidity_rises_with_temperature_at_fixed_rh():
    """The entire reason RH points are not a conserved quantity."""
    assert absolute_humidity_g_m3(20.0, 90.0) > absolute_humidity_g_m3(5.0, 90.0)


def test_absolute_humidity_is_zero_at_zero_rh():
    assert absolute_humidity_g_m3(15.0, 0.0) == 0.0


def test_rh_clamps_above_saturation_like_the_js():
    """fc_derived.js clamps rhFrac into [0,1]; the port must match."""
    assert absolute_humidity_g_m3(15.0, 120.0) == absolute_humidity_g_m3(15.0, 100.0)


def test_rh_clamps_below_zero_like_the_js():
    assert absolute_humidity_g_m3(15.0, -10.0) == absolute_humidity_g_m3(15.0, 0.0)
