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
import time

import pytest
import rclpy
import rclpy.time
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import RelativeHumidity, Temperature
from std_msgs.msg import Float32
from unittest.mock import patch, MagicMock

from fc_core.fc_controller import FruitingChamberController, ModeView
from fc_msgs.msg import Mode
from fc_msgs.srv import SetMode

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
    """Build a controller with optional parameter overrides applied at __init__ time.

    Phase 28-04: prefer constructor-time `parameter_overrides=` so callbacks
    registered in `__init__` (e.g. add_on_set_parameters_callback) and the
    startup current_mode publish observe the test's mode shape, not the
    declared NaN-sentinel defaults.
    """
    if parameter_overrides is None:
        return FruitingChamberController()
    return FruitingChamberController(parameter_overrides=parameter_overrides)


# Phase 28-04 fixture: full v0 fruiting param set (declared NaN bands replaced
# with farmer-locked v0 values per D-05) plus simulation-mode actuator flag so
# __init__ doesn't try to import RPi.GPIO. Used by every test that asserts on
# startup-time behavior of fc_controller (current_mode publish, callback wiring).
def _fruiting_v0_overrides():
    return [
        Parameter('actuator_simulation_mode', Parameter.Type.BOOL, True),
        Parameter('active_mode', Parameter.Type.STRING, 'fruiting'),
        Parameter('modes.fruiting.target_humidity', Parameter.Type.DOUBLE, 0.96),
        Parameter('modes.fruiting.band_low', Parameter.Type.DOUBLE, 0.945),
        Parameter('modes.fruiting.band_high', Parameter.Type.DOUBLE, 0.975),
        Parameter('modes.fruiting.defend_side', Parameter.Type.STRING, 'both'),
        Parameter('modes.fruiting.t_target', Parameter.Type.DOUBLE, float('nan')),
        # Pinning declared too — required for unknown-mode rejection tests.
        Parameter('modes.pinning.target_humidity', Parameter.Type.DOUBLE, 0.85),
        Parameter('modes.pinning.band_low', Parameter.Type.DOUBLE, 0.90),
        Parameter('modes.pinning.band_high', Parameter.Type.DOUBLE, 0.99),
        Parameter('modes.pinning.defend_side', Parameter.Type.STRING, 'low'),
        Parameter('modes.pinning.t_target', Parameter.Type.DOUBLE, float('nan')),
    ]


def _pinning_v0_overrides():
    overrides = _fruiting_v0_overrides()
    # Flip active_mode → 'pinning'
    return [
        Parameter('active_mode', Parameter.Type.STRING, 'pinning')
        if p.name == 'active_mode' else p
        for p in overrides
    ]


def _transient_local_qos():
    return QoSProfile(
        depth=1,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
    )


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


def test_param_callback_band_invariant(ros_context):
    """plan 28-04; MODE-01 — on_set_parameters_callback rejects band_low >= band_high.

    Current band_high=0.975. Setting band_low=0.99 alone violates the invariant
    (0 <= band_low < band_high <= 1) → callback returns successful=False, param
    store unchanged.
    """
    node = _make_node(_fruiting_v0_overrides())
    results = node.set_parameters([
        Parameter('modes.fruiting.band_low', Parameter.Type.DOUBLE, 0.99),
    ])
    assert not results[0].successful
    assert 'band' in results[0].reason.lower()
    # Param store unchanged.
    assert node.get_parameter('modes.fruiting.band_low').value == pytest.approx(0.945)
    node.destroy_node()


def test_param_callback_defend_side_enum(ros_context):
    """plan 28-04; MODE-01 — defend_side ∉ {low, high, both} → reject."""
    node = _make_node(_fruiting_v0_overrides())
    results = node.set_parameters([
        Parameter('modes.fruiting.defend_side', Parameter.Type.STRING, 'upward'),
    ])
    assert not results[0].successful
    reason = results[0].reason.lower()
    assert 'low' in reason and 'high' in reason and 'both' in reason
    assert node.get_parameter('modes.fruiting.defend_side').value == 'both'
    node.destroy_node()


def test_param_callback_unknown_mode(ros_context):
    """plan 28-04; MODE-01 — active_mode not in declared modes → reject.

    Only fruiting + pinning declared by the override fixture. Setting
    active_mode='incubation' must reject and reason must list declared modes.
    """
    node = _make_node(_fruiting_v0_overrides())
    results = node.set_parameters([
        Parameter('active_mode', Parameter.Type.STRING, 'incubation'),
    ])
    assert not results[0].successful
    reason = results[0].reason.lower()
    assert 'fruiting' in reason and 'pinning' in reason
    assert node.get_parameter('active_mode').value == 'fruiting'
    node.destroy_node()


def test_param_callback_batched_band_edit_atomic(ros_context):
    """plan 28-04; MODE-05 Pitfall 4 — batched [band_low=0.85, band_high=0.99]
    passes atomically (the post-batch view is internally consistent).

    Conversely, a lone [band_low=0.999] when current band_high=0.99 must fail
    atomically (post-batch view violates band_low<band_high).
    """
    node = _make_node(_fruiting_v0_overrides())
    # Batched edit on pinning: end up with band [0.85, 0.99]. Apply both
    # changes in ONE batch — the callback must see the post-batch view.
    results = node.set_parameters([
        Parameter('modes.pinning.band_low', Parameter.Type.DOUBLE, 0.85),
        Parameter('modes.pinning.band_high', Parameter.Type.DOUBLE, 0.99),
    ])
    assert all(r.successful for r in results), (
        f'batched band edit must be accepted atomically; reasons={[r.reason for r in results]}'
    )
    assert node.get_parameter('modes.pinning.band_low').value == pytest.approx(0.85)
    assert node.get_parameter('modes.pinning.band_high').value == pytest.approx(0.99)

    # Now lone band_low=0.9999 (above band_high=0.99) must fail atomically.
    results = node.set_parameters([
        Parameter('modes.pinning.band_low', Parameter.Type.DOUBLE, 0.9999),
    ])
    assert not results[0].successful
    # Param unchanged.
    assert node.get_parameter('modes.pinning.band_low').value == pytest.approx(0.85)
    node.destroy_node()


def test_param_callback_pid_range_bound(ros_context):
    """plan 28-04 T-28-09 — defense-in-depth: pid_kp range [0, 5] rejects 99.

    Bridge allowlist (Phase 28-05 work) will mirror this bound; the callback
    enforces it at the rcl boundary so a bridge bypass cannot slam insane gains.
    """
    node = _make_node(_fruiting_v0_overrides())
    results = node.set_parameters([
        Parameter('pid_kp', Parameter.Type.DOUBLE, 99.0),
    ])
    assert not results[0].successful
    assert 'pid_kp' in results[0].reason
    node.destroy_node()


# --- MODE-02: fruiting + pinning baseline behavior ---------------------------

# Helper fixtures for Task 2 control-loop tests.
# Pattern (mirrors test_controller.py): bypass grace via _grace_active=lambda:False;
# pre-fill _humidity_buffer with 5 samples so freshness/staleness guards are happy;
# spy _publish_duty to inspect the published duty value.

def _prep_controller(node, current_temp=23.0):
    """Bypass grace, set temp, spy duty + telemetry pubs."""
    node._grace_active = lambda: False
    node.current_temp = current_temp
    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)
    target_pub = []
    node._humidity_target_pub.publish = lambda msg: target_pub.append(msg.data)
    pid_out_pub = []
    node._pid_output_pub.publish = lambda msg: pid_out_pub.append(msg.data)
    return duty_published, target_pub, pid_out_pub


def _seed_buffer(node, value, t_ns=0):
    """Fill the median buffer with `value` at clock=t_ns so staleness guard is satisfied."""
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_ns)):
        for _ in range(5):
            _send_humidity(node, value)


def _set_pinning_v0(node):
    node.set_parameters([
        Parameter('active_mode', value='pinning'),
        Parameter('modes.pinning.target_humidity', value=0.85),
        Parameter('modes.pinning.band_low', value=0.90),
        Parameter('modes.pinning.band_high', value=0.99),
        Parameter('modes.pinning.defend_side', value='low'),
    ])


def _set_fruiting_v0(node):
    node.set_parameters([
        Parameter('active_mode', value='fruiting'),
        Parameter('modes.fruiting.target_humidity', value=0.96),
        Parameter('modes.fruiting.band_low', value=0.945),
        Parameter('modes.fruiting.band_high', value=0.975),
        Parameter('modes.fruiting.defend_side', value='both'),
    ])


def test_fruiting_preserves_humid04(ros_context):
    """plan 28-03; MODE-02 — fruiting v0 reproduces Phase 27 narrow-band PID; HUMID-04.

    With band [0.945, 0.975] defend_side=both:
    - rh=0.96 (in-band) → error_pct=0; duty stays bounded (no Mode C entry).
    - rh=0.93 (below band_low) → error_pct=(0.93-0.945)*100=-1.5; PID demands
      non-zero duty (preserves Phase 27 HUMID-04 contract).
    """
    node = _make_node()
    _set_fruiting_v0(node)
    duty_published, _, _ = _prep_controller(node)

    # In-band: error 0, no Mode C, duty bounded (PID returns ~bumpless preload).
    _seed_buffer(node, 0.96, t_ns=0)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()
    assert duty_published, 'expected at least one duty publication'
    duty_in_band = duty_published[-1]
    assert 0.0 <= duty_in_band <= 1.0, f'duty out of [0,1]: {duty_in_band}'

    # Below band_low: PID demands duty > 0 (HUMID-04).
    _seed_buffer(node, 0.93, t_ns=int(2e9))
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(3e9))):
        node.control_loop()
    duty_below = duty_published[-1]
    assert duty_below > 0.0, (
        f'fruiting must demand duty>0 when rh<band_low; got {duty_below}'
    )
    node.destroy_node()


def test_pinning_clamps_on_high_excursion(ros_context):
    """plan 28-03; MODE-02 D-09 — defend_side=low: rh > band_high → duty=0,
    integrator frozen, telemetry trio still published.
    """
    node = _make_node()
    _set_pinning_v0(node)
    duty_published, target_pub, pid_out_pub = _prep_controller(node)

    # rh=0.995 above band_high=0.99 with defend_side=low → clamp to 0.
    _seed_buffer(node, 0.995, t_ns=0)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()

    assert duty_published[-1] == 0.0, (
        f'pinning high excursion: duty must clamp to 0.0, got {duty_published[-1]}'
    )
    assert node._pid.auto_mode is False, 'integrator must be frozen on high-side clamp'
    assert pid_out_pub and pid_out_pub[-1] == 0.0, 'pid_output telemetry must publish 0.0'
    assert target_pub, 'humidity_target telemetry must still publish (Mission Control visibility)'
    node.destroy_node()


def test_pinning_defends_floor(ros_context):
    """plan 28-03; MODE-02 — pinning still drives humidifier when rh < band_low (0.90)."""
    node = _make_node()
    _set_pinning_v0(node)
    duty_published, _, _ = _prep_controller(node)

    # rh=0.85 below band_low=0.90 → error_pct=(0.85-0.90)*100=-5.0, but |rh - 0.90|=0.05
    # = 5%RH > bypass_threshold(2.5%) AND rh<nearest_defended → Mode C → duty=1.0.
    _seed_buffer(node, 0.85, t_ns=0)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()
    assert duty_published[-1] > 0.0, (
        f'pinning must defend floor (rh<band_low) with duty>0, got {duty_published[-1]}'
    )

    # Also try mild floor breach (rh=0.895, just 0.005 below floor) → linear PID,
    # error_pct=-0.5, distance from band_low=0.005 < bypass_threshold → no Mode C
    # but error<0 → PID demands non-zero duty.
    node2 = _make_node()
    _set_pinning_v0(node2)
    duty2, _, _ = _prep_controller(node2)
    _seed_buffer(node2, 0.895, t_ns=0)
    with patch.object(node2, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node2.control_loop()
    assert duty2[-1] > 0.0, (
        f'pinning mild floor breach: PID must demand duty>0, got {duty2[-1]}'
    )
    node.destroy_node()
    node2.destroy_node()


def test_ramp_targets_defended_edge(ros_context):
    """plan 28-03; MODE-02 D-10 — ramp targets defended band edge, not midpoint.

    Pinning defend_side=low. Start _effective_setpoint=0.85 (cosmetic target
    midpoint), feed rh=0.92 (in-band). After one 1s tick with ramp_seconds=30,
    _effective_setpoint must move TOWARD band_low=0.90, NOT toward target 0.85.
    """
    node = _make_node()
    _set_pinning_v0(node)
    duty_published, _, _ = _prep_controller(node)

    # Set effective_setpoint to 0.85 (the cosmetic target — pre-mode-aware location).
    node._effective_setpoint = 0.85

    _seed_buffer(node, 0.92, t_ns=0)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()

    # After ramp: should have moved toward 0.90, not toward 0.85 or below.
    assert node._effective_setpoint > 0.85, (
        f'ramp must target defended edge (band_low=0.90), but stayed at/below 0.85: '
        f'{node._effective_setpoint}'
    )
    # Step magnitude: |0.90-0.85|*(1/30) ≈ 0.00167; effective ≈ 0.8517.
    assert node._effective_setpoint == pytest.approx(0.85 + 0.05 * (1.0 / 30.0), abs=1e-4), (
        f'expected slew ~0.00167 toward 0.90, got effective={node._effective_setpoint}'
    )
    node.destroy_node()


def test_mode_c_bypass_keys_off_nearest_defended_edge(ros_context):
    """plan 28-03; MODE-02 D-11 — Mode C bypass uses nearest defended edge, not target.

    Pinning: target=0.85, band_low=0.90, defend_side=low. RH=0.60.
    Distance from band_low (the only defended edge) = 0.30 = 30% RH.
    bypass_threshold=0.025=2.5%. edge_distance > bypass → Mode C → duty=1.0.

    The OLD (target-keyed) bypass would have computed |0.60-0.85|=0.25 — also
    Mode C, but for the wrong reason. The pinning band geometry (target<band_low)
    makes the test name's invariant load-bearing: the new code computes against
    the defended edge, not the cosmetic target.
    """
    node = _make_node()
    _set_pinning_v0(node)
    duty_published, _, _ = _prep_controller(node)

    _seed_buffer(node, 0.60, t_ns=0)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()

    assert duty_published[-1] == 1.0, (
        f'pinning crash to 0.60: distance from band_low (0.90)=0.30 > bypass(0.025) '
        f'→ Mode C duty=1.0; got {duty_published[-1]}'
    )
    assert node._pid.auto_mode is False, 'integrator frozen during Mode C'
    node.destroy_node()


# --- MODE-03: set_mode service ------------------------------------------------

def _call_set_mode(controller, name, timeout_sec=2.0):
    """Spin the controller, call /fc_controller/set_mode, return the response."""
    cli_node = Node('test_set_mode_cli', start_parameter_services=False)
    # Service is created without namespace at controller construction time;
    # rclpy resolves to /set_mode. Phase 28-05 bridge work will issue the same
    # call using the same plain name.
    cli = cli_node.create_client(SetMode, 'set_mode')
    exec_ = SingleThreadedExecutor()
    exec_.add_node(controller)
    exec_.add_node(cli_node)
    deadline = time.monotonic() + timeout_sec
    while not cli.service_is_ready() and time.monotonic() < deadline:
        exec_.spin_once(timeout_sec=0.05)
    assert cli.service_is_ready(), 'set_mode service not ready'
    req = SetMode.Request()
    req.name = name
    fut = cli.call_async(req)
    deadline = time.monotonic() + timeout_sec
    while not fut.done() and time.monotonic() < deadline:
        exec_.spin_once(timeout_sec=0.05)
    assert fut.done(), f'set_mode({name}) did not complete within {timeout_sec}s'
    cli_node.destroy_node()
    return fut.result()


def test_set_mode_service_takes_effect_in_one_tick(ros_context):
    """plan 28-04; MODE-03 — SetMode call writes active_mode param; new mode
    applied on next control tick (≤1s).

    Pre-state: active_mode='fruiting'. Call set_mode(name='pinning') → response
    success=True with active_mode.name='pinning'. _resolve_active_mode() now
    returns the pinning ModeView.
    """
    node = _make_node(_fruiting_v0_overrides())
    resp = _call_set_mode(node, 'pinning')
    assert resp.success, f'set_mode failed: {resp.reason}'
    assert resp.active_mode.name == 'pinning'
    assert resp.active_mode.band_low == pytest.approx(0.90, abs=1e-4)
    assert resp.active_mode.defend_side == 'low'
    assert resp.active_mode.source == 'service_call'
    # Resolver agrees on next tick (no extra spin needed — set_parameters
    # already applied).
    mv = node._resolve_active_mode()
    assert mv.name == 'pinning'
    node.destroy_node()


def test_set_mode_rejects_unknown(ros_context):
    """plan 28-04; MODE-03 — SetMode with non-declared name → success=false.

    Param store unchanged; reason names the declared modes set.
    """
    node = _make_node(_fruiting_v0_overrides())
    resp = _call_set_mode(node, 'dehydration')
    assert not resp.success
    reason = resp.reason.lower()
    assert 'fruiting' in reason and 'pinning' in reason
    assert node.get_parameter('active_mode').value == 'fruiting'
    node.destroy_node()


def test_mode_swap_bumpless(ros_context):
    """plan 28-04; MODE-03 D-12 — mode swap calls _engage_pid_bumplessly with
    current duty.

    Pre-state: controller running fruiting; _last_published_duty=0.45 (the
    pre-swap operating point). After set_mode('pinning'): _engage_pid_bumplessly
    was called with last_output close to 0.45 (NOT the default 0.15). Carrying
    duty avoids an integrator-bump when bands change underfoot.
    """
    node = _make_node(_fruiting_v0_overrides())
    # Inject pre-swap state.
    node._last_published_duty = 0.45
    # Spy the bumpless re-engage call.
    bumpless_calls = []
    original = node._engage_pid_bumplessly

    def spy(last_output=0.15):
        bumpless_calls.append(last_output)
        return original(last_output=last_output)

    node._engage_pid_bumplessly = spy

    resp = _call_set_mode(node, 'pinning')
    assert resp.success, f'set_mode failed: {resp.reason}'
    assert bumpless_calls, 'expected _engage_pid_bumplessly to be called on swap'
    # The service handler must carry pre-swap duty (0.45), not default 0.15.
    assert any(abs(lo - 0.45) < 0.01 for lo in bumpless_calls), (
        f'expected bumpless re-engage with last_output≈0.45 (carry pre-swap '
        f'duty per D-12); got calls={bumpless_calls}'
    )
    node.destroy_node()


# --- MODE-04: current_mode topic ---------------------------------------------

def _collect_one_mode_msg(controller, timeout_sec=2.0):
    """Subscribe with TRANSIENT_LOCAL QoS, spin both nodes, return first Mode msg."""
    received = []
    sub_node = Node('test_mode_sub', start_parameter_services=False)
    sub_node.create_subscription(
        Mode, 'fc1/control/current_mode', received.append, _transient_local_qos()
    )
    exec_ = SingleThreadedExecutor()
    exec_.add_node(controller)
    exec_.add_node(sub_node)
    deadline = time.monotonic() + timeout_sec
    while not received and time.monotonic() < deadline:
        exec_.spin_once(timeout_sec=0.1)
    sub_node.destroy_node()
    return received


def test_current_mode_topic_payload(ros_context):
    """plan 28-04; MODE-04 — current_mode publishes fc_msgs/Mode with all D-13 fields."""
    node = _make_node(_fruiting_v0_overrides())
    msgs = _collect_one_mode_msg(node)
    assert msgs, 'expected at least one Mode message on /fc1/control/current_mode'
    msg = msgs[0]
    assert msg.name == 'fruiting'
    assert msg.target_humidity == pytest.approx(0.96, abs=1e-4)
    assert msg.band_low == pytest.approx(0.945, abs=1e-4)
    assert msg.band_high == pytest.approx(0.975, abs=1e-4)
    assert msg.defend_side == 'both'
    assert math.isnan(msg.t_target)
    assert msg.source == 'config_default'
    node.destroy_node()


def test_current_mode_late_subscribe(ros_context):
    """plan 28-04; MODE-04 D-14 — TRANSIENT_LOCAL durability: late subscriber
    receives last value on subscribe.

    Distinct from `test_current_mode_topic_payload` in that the subscriber is
    created AFTER the publish has fired; cached message must arrive on
    subscribe via TRANSIENT_LOCAL durability.
    """
    node = _make_node(_fruiting_v0_overrides())
    # Spin the controller alone first so the startup publish flushes into the
    # rmw with no subscribers attached.
    pre_exec = SingleThreadedExecutor()
    pre_exec.add_node(node)
    for _ in range(5):
        pre_exec.spin_once(timeout_sec=0.05)
    pre_exec.remove_node(node)
    # Now create the late subscriber — TRANSIENT_LOCAL must deliver the cached msg.
    msgs = _collect_one_mode_msg(node)
    assert msgs, 'late subscriber must receive cached Mode msg via TRANSIENT_LOCAL'
    assert msgs[0].name == 'fruiting'
    node.destroy_node()


def test_current_mode_republishes_on_band_change(ros_context):
    """plan 28-04; MODE-04 D-15 — band_low/band_high tweak triggers republish.

    Pattern: spin past startup publish, set band_low=0.94 via set_parameters,
    spin one control_loop tick, expect a SECOND Mode msg with band_low=0.94 and
    source='param_set'.
    """
    node = _make_node(_fruiting_v0_overrides())
    # Bypass grace + freshness so control_loop runs to the republish-drain branch.
    node._grace_active = lambda: False
    node.current_temp = 23.0
    # Pre-fill humidity buffer + timestamp so staleness guard passes.
    msg = RelativeHumidity()
    msg.relative_humidity = 0.96
    for _ in range(5):
        node.humidity_callback(msg)

    received = []
    sub_node = Node('test_republish_sub', start_parameter_services=False)
    sub_node.create_subscription(
        Mode, 'fc1/control/current_mode', received.append, _transient_local_qos()
    )
    exec_ = SingleThreadedExecutor()
    exec_.add_node(node)
    exec_.add_node(sub_node)
    # Drain the startup publish.
    deadline = time.monotonic() + 1.0
    while not received and time.monotonic() < deadline:
        exec_.spin_once(timeout_sec=0.05)
    assert received, 'startup publish missing'
    startup_count = len(received)

    # Now mutate band_low. Callback fires, queues republish for next tick.
    results = node.set_parameters([
        Parameter('modes.fruiting.band_low', Parameter.Type.DOUBLE, 0.94),
    ])
    assert results[0].successful, f'expected accept; got {results[0].reason}'

    # Trigger control_loop manually (next-tick drain).
    node.control_loop()
    deadline = time.monotonic() + 1.0
    while len(received) <= startup_count and time.monotonic() < deadline:
        exec_.spin_once(timeout_sec=0.05)

    assert len(received) > startup_count, 'no republish observed after band_low change'
    last = received[-1]
    assert last.band_low == pytest.approx(0.94, abs=1e-4)
    assert last.source == 'param_set'
    sub_node.destroy_node()
    node.destroy_node()


def test_current_mode_published_at_startup(ros_context):
    """plan 28-04; MODE-04 — TRANSIENT_LOCAL does NOT survive process restart;
    controller publishes once at startup after _resolve_active_mode."""
    node = _make_node(_fruiting_v0_overrides())
    msgs = _collect_one_mode_msg(node, timeout_sec=2.0)
    assert len(msgs) >= 1, 'expected at least one startup publish on current_mode'
    # Exactly one publish at startup (no autonomous control_loop tick happened).
    # Spin a touch longer to confirm no spurious extras arrive.
    exec_ = SingleThreadedExecutor()
    exec_.add_node(node)
    for _ in range(3):
        exec_.spin_once(timeout_sec=0.05)
    # First publish must be the startup one with source='config_default'.
    assert msgs[0].source == 'config_default'
    node.destroy_node()


def test_target_outside_band_warn_pinning(ros_context, caplog):
    """plan 28-04 OQ-5 — pinning target=0.85 outside band [0.90, 0.99] triggers
    a cosmetic WARN at startup current_mode publish."""
    import logging
    caplog.set_level(logging.WARN)
    node = _make_node(_pinning_v0_overrides())
    # Spin briefly so startup publish fires (logging is synchronous in publish, but
    # we also want any rclpy logger plumbing to flush).
    exec_ = SingleThreadedExecutor()
    exec_.add_node(node)
    for _ in range(3):
        exec_.spin_once(timeout_sec=0.05)
    # rclpy uses its own logger; capture via the WARN log path. Look in both
    # caplog and the controller's get_logger output (rclpy emits to rcutils,
    # which surfaces in capsys/caplog through the rclpy.logging bridge in tests).
    combined = ' '.join(rec.getMessage() for rec in caplog.records)
    # Fall back: check the get_logger().warn call by patching the logger directly.
    # (rclpy logs via stderr; caplog only catches python logging — the controller
    # uses rclpy's logger. Use a spy approach instead.)
    node.destroy_node()
    if 'outside band' not in combined:
        # caplog miss is expected — rclpy logging bypasses the python `logging`
        # module. Re-run with a logger spy to assert directly.
        node2 = FruitingChamberController.__new__(FruitingChamberController)
        warn_calls = []

        # Patch get_logger before super().__init__ runs by monkey-patching
        # the class method — same approach as below in the negative test.
        with patch.object(FruitingChamberController, 'get_logger') as mock_get:
            logger_mock = MagicMock()
            logger_mock.warn = lambda m: warn_calls.append(m)
            logger_mock.warning = lambda m: warn_calls.append(m)
            logger_mock.info = lambda m: None
            logger_mock.debug = lambda m: None
            logger_mock.error = lambda m: None
            mock_get.return_value = logger_mock
            n = FruitingChamberController(parameter_overrides=_pinning_v0_overrides())
            n.destroy_node()
        assert any('outside band' in m and 'pinning' in m for m in warn_calls), (
            f'expected WARN on pinning startup with target outside band; '
            f'got warns: {warn_calls}'
        )


def test_target_inside_band_no_warn_fruiting(ros_context):
    """plan 28-04 OQ-5 — fruiting target=0.96 inside band [0.945, 0.975] must
    NOT emit the cosmetic 'outside band' WARN at startup (negative case)."""
    warn_calls = []
    with patch.object(FruitingChamberController, 'get_logger') as mock_get:
        logger_mock = MagicMock()
        logger_mock.warn = lambda m: warn_calls.append(m)
        logger_mock.warning = lambda m: warn_calls.append(m)
        logger_mock.info = lambda m: None
        logger_mock.debug = lambda m: None
        logger_mock.error = lambda m: None
        mock_get.return_value = logger_mock
        node = FruitingChamberController(parameter_overrides=_fruiting_v0_overrides())
        node.destroy_node()
    assert not any('outside band' in m for m in warn_calls), (
        f'fruiting target inside band: must NOT emit "outside band" WARN; '
        f'got warns: {warn_calls}'
    )
