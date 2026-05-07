#!/usr/bin/env python3
"""Phase 28 — Mode primitive + 2 baseline modes (`fruiting`, `pinning`) + runtime config.

Wave 0 RED test scaffolds. Each stub fails with a "RED — landed in plan 28-NN"
message naming the plan that will turn it GREEN. Collection MUST succeed.

See:
- .planning/phases/28-.../28-VALIDATION.md (Phase Requirements → Test Map)
- .planning/phases/28-.../28-RESEARCH.md §Validation Architecture (test_name → behavior)
- .planning/phases/28-.../28-CONTEXT.md (D-01..D-22)
"""
import math

import pytest
import rclpy
import rclpy.time
from rclpy.parameter import Parameter
from sensor_msgs.msg import RelativeHumidity, Temperature
from std_msgs.msg import Float32
from unittest.mock import patch, MagicMock

from fc_core.fc_controller import FruitingChamberController, ModeView

_ROS_TIME = rclpy.time.ClockType.ROS_TIME


def _mock_clock_at(nanoseconds):
    mc = MagicMock()
    mc.now.return_value = rclpy.time.Time(
        nanoseconds=nanoseconds, clock_type=_ROS_TIME
    )
    return mc


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def _send_humidity(node, value):
    msg = RelativeHumidity()
    msg.relative_humidity = value
    node.humidity_callback(msg)


def _make_node(parameter_overrides=None):
    """Build a controller with optional parameter overrides applied at __init__ time."""
    if parameter_overrides is None:
        return FruitingChamberController()
    # rclpy.node.Node accepts parameter_overrides via the constructor signature,
    # but FruitingChamberController.__init__ doesn't surface it; we use
    # set_parameters after construction since all params are pre-declared.
    node = FruitingChamberController()
    node.set_parameters(parameter_overrides)
    return node


# --- MODE-01: mode resolution + back-compat + param-callback validation -------

def test_resolve_active_mode_fruiting(ros_context):
    """plan 28-03; MODE-01 — _resolve_active_mode() returns ModeView matching D-05.

    Override the declared NaN-sentinel band defaults with the farmer-locked v0
    values from fc_config.yaml D-05. After this Phase 27's HUMID-04 contract
    (target=0.96, band ±1.5%) is preserved.
    """
    node = _make_node([
        Parameter('active_mode', value='fruiting'),
        Parameter('modes.fruiting.target_humidity', value=0.96),
        Parameter('modes.fruiting.band_low', value=0.945),
        Parameter('modes.fruiting.band_high', value=0.975),
        Parameter('modes.fruiting.defend_side', value='both'),
    ])
    mv = node._resolve_active_mode()
    assert isinstance(mv, ModeView)
    assert mv.name == 'fruiting'
    assert mv.target == pytest.approx(0.96)
    assert mv.band_low == pytest.approx(0.945)
    assert mv.band_high == pytest.approx(0.975)
    assert mv.defend_side == 'both'
    assert math.isnan(mv.t_target)
    node.destroy_node()


def test_back_compat_default_fruiting(ros_context):
    """plan 28-03; MODE-01 D-04 — absent `modes:` block synthesizes fruiting from
    target_humidity + humidity_tolerance.

    Simulate an old YAML (no modes block) by leaving band_low/band_high at the
    NaN sentinel defaults — those are the in-code defaults declared in
    declare_parameters when YAML doesn't override.
    """
    node = _make_node([
        Parameter('active_mode', value='fruiting'),
        Parameter('target_humidity', value=0.94),
        Parameter('humidity_tolerance', value=0.01),
        # Leave modes.fruiting.band_low / band_high at default NaN — D-04 trigger.
    ])
    mv = node._resolve_active_mode()
    assert mv.name == 'fruiting'
    assert mv.target == pytest.approx(0.94)
    assert mv.band_low == pytest.approx(0.93)
    assert mv.band_high == pytest.approx(0.95)
    assert mv.defend_side == 'both'
    assert math.isnan(mv.t_target)
    node.destroy_node()


def test_pinning_resolves(ros_context):
    """plan 28-03; MODE-01 — pinning ModeView matches D-06 farmer-locked v0 values."""
    node = _make_node([
        Parameter('active_mode', value='pinning'),
        Parameter('modes.pinning.target_humidity', value=0.85),
        Parameter('modes.pinning.band_low', value=0.90),
        Parameter('modes.pinning.band_high', value=0.99),
        Parameter('modes.pinning.defend_side', value='low'),
    ])
    mv = node._resolve_active_mode()
    assert mv.name == 'pinning'
    assert mv.target == pytest.approx(0.85)
    assert mv.band_low == pytest.approx(0.90)
    assert mv.band_high == pytest.approx(0.99)
    assert mv.defend_side == 'low'
    assert math.isnan(mv.t_target)
    node.destroy_node()


def test_param_callback_band_invariant():
    """plan 28-04; MODE-01 — on_set_parameters_callback rejects band_low >= band_high."""
    pytest.fail("RED — landed in plan 28-04")


def test_param_callback_defend_side_enum():
    """plan 28-04; MODE-01 — defend_side ∉ {low, high, both} → reject."""
    pytest.fail("RED — landed in plan 28-04")


def test_param_callback_unknown_mode():
    """plan 28-04; MODE-01 — active_mode not in declared modes → reject."""
    pytest.fail("RED — landed in plan 28-04")


def test_param_callback_batched_band_edit_atomic():
    """plan 28-04; MODE-05 Pitfall 4 — batched [band_low=0.94, band_high=0.96]
    passes atomically; lone [band_low=0.99] when current band_high=0.97 fails atomically."""
    pytest.fail("RED — landed in plan 28-04")


# --- MODE-02: fruiting + pinning baseline behavior ---------------------------

def test_fruiting_preserves_humid04():
    """plan 28-03; MODE-02 — fruiting v0 reproduces Phase 27 narrow-band PID; HUMID-04 holds."""
    pytest.fail("RED — landed in plan 28-03")


def test_pinning_clamps_on_high_excursion():
    """plan 28-03; MODE-02 D-09 — defend_side=low: rh > band_high → duty=0,
    integrator frozen, bumpless re-engage on return into band."""
    pytest.fail("RED — landed in plan 28-03")


def test_pinning_defends_floor():
    """plan 28-03; MODE-02 — pinning still drives humidifier when rh < band_low (0.90)."""
    pytest.fail("RED — landed in plan 28-03")


# --- MODE-03: set_mode service ------------------------------------------------

def test_set_mode_service_takes_effect_in_one_tick():
    """plan 28-04; MODE-03 — SetMode call writes active_mode param; new mode
    applied on next control tick (≤1s)."""
    pytest.fail("RED — landed in plan 28-04")


def test_set_mode_rejects_unknown():
    """plan 28-04; MODE-03 — SetMode with non-declared name → success=false."""
    pytest.fail("RED — landed in plan 28-04")


def test_mode_swap_bumpless():
    """plan 28-04; MODE-03 D-12 — mode swap calls _engage_pid_bumplessly with
    current duty; no integrator-bump on band change."""
    pytest.fail("RED — landed in plan 28-04")


# --- MODE-04: current_mode topic ---------------------------------------------

def test_current_mode_topic_payload():
    """plan 28-04; MODE-04 — current_mode publishes fc_msgs/Mode with all D-13 fields."""
    pytest.fail("RED — landed in plan 28-04")


def test_current_mode_late_subscribe():
    """plan 28-04; MODE-04 D-14 — TRANSIENT_LOCAL durability: late subscriber
    receives last value on subscribe."""
    pytest.fail("RED — landed in plan 28-04")


def test_current_mode_republishes_on_band_change():
    """plan 28-04; MODE-04 D-15 — band_low/band_high tweak triggers republish."""
    pytest.fail("RED — landed in plan 28-04")


def test_current_mode_published_at_startup():
    """plan 28-04; MODE-04 — TRANSIENT_LOCAL does NOT survive process restart;
    controller publishes once at startup after _resolve_active_mode."""
    pytest.fail("RED — landed in plan 28-04")
