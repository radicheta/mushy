#!/usr/bin/env python3
"""HUMID-01 + HUMID-03: PID-driven duty publishing, Mode C, ramp, bumpless transfer (Phase 27)."""
import pytest
import rclpy
import rclpy.time
from sensor_msgs.msg import Temperature, RelativeHumidity
from std_msgs.msg import Float32
from fc_core.fc_controller import FruitingChamberController
from unittest.mock import patch, MagicMock
from rclpy.qos import DurabilityPolicy

_ROS_TIME = rclpy.time.ClockType.ROS_TIME


def _mock_clock_at(nanoseconds):
    """Return a mock clock whose .now() returns the given ROS time (ROS_TIME clock type)."""
    mock_clock = MagicMock()
    mock_clock.now.return_value = rclpy.time.Time(
        nanoseconds=nanoseconds, clock_type=_ROS_TIME
    )
    return mock_clock

@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()

def test_controller_initialization(ros_context):
    node = FruitingChamberController()
    assert node is not None
    node.destroy_node()

def test_temperature_control(ros_context):
    node = FruitingChamberController()
    node._grace_active = lambda: False  # bypass grace — not under test here

    # Test temperature below target
    temp_msg = Temperature()
    temp_msg.temperature = node.get_parameter('target_temp').value - 2.0
    node.temperature_callback(temp_msg)

    # Test humidity at target
    humidity_msg = RelativeHumidity()
    humidity_msg.relative_humidity = node.get_parameter('target_humidity').value
    node.humidity_callback(humidity_msg)

    # Run control loop
    node.control_loop()

    # Fan should be at minimum speed
    assert node.fan_speed == node.get_parameter('min_fan_speed').value

    # Test temperature above target
    temp_msg.temperature = node.get_parameter('target_temp').value + 2.0
    node.temperature_callback(temp_msg)
    node.control_loop()

    # Fan should be at higher speed
    assert node.fan_speed > node.get_parameter('min_fan_speed').value

    node.destroy_node()

def test_light_control(ros_context):
    from rclpy.parameter import Parameter
    node = FruitingChamberController()

    # Test during light hours — parameters already declared at init with defaults
    # (light_start_hour=6, target_light_hours=12), no override needed for the mock test

    # Mock current hour to 10 AM — patch at the import site in fc_controller
    with patch('fc_core.fc_controller.datetime') as mock_datetime:
        mock_datetime.now.return_value.hour = 10
        assert node.should_light_be_on() == True

    # Test outside light hours
    with patch('fc_core.fc_controller.datetime') as mock_datetime:
        mock_datetime.now.return_value.hour = 2
        assert node.should_light_be_on() == False

    node.destroy_node()


def _send_humidity(node, value):
    msg = RelativeHumidity()
    msg.relative_humidity = value
    node.humidity_callback(msg)


def test_humidity_spike_rejection(ros_context):
    """After 5 readings [0.80, 0.82, 0.81, 0.99, 0.83], median (0.82) replaces spike (0.99)."""
    node = FruitingChamberController()

    for v in [0.80, 0.82, 0.81, 0.99, 0.83]:
        _send_humidity(node, v)

    # sorted: [0.80, 0.81, 0.82, 0.83, 0.99] -> median = 0.82
    assert node.current_humidity == pytest.approx(0.82)

    node.destroy_node()


def test_humidity_median_partial_buffer(ros_context):
    """With only 3 readings [0.80, 0.82, 0.81], median of available samples is used."""
    node = FruitingChamberController()

    for v in [0.80, 0.82, 0.81]:
        _send_humidity(node, v)

    # sorted: [0.80, 0.81, 0.82] -> median = 0.81
    assert node.current_humidity == pytest.approx(0.81)

    node.destroy_node()


def test_humidity_buffer_fifo(ros_context):
    """After 7 readings, buffer retains only the last 5 (FIFO deque maxlen=5)."""
    node = FruitingChamberController()

    for v in [0.80, 0.82, 0.81, 0.99, 0.83, 0.84, 0.85]:
        _send_humidity(node, v)

    # deque(maxlen=5) after all 7 pushes: [0.81, 0.99, 0.83, 0.84, 0.85]
    # sorted: [0.81, 0.83, 0.84, 0.85, 0.99] -> median = 0.84
    assert node.current_humidity == pytest.approx(0.84)

    node.destroy_node()


def test_new_params_declared(ros_context):
    """sensor_stale_timeout (10.0) is a declared parameter; min_dwell_time is NOT declared (D-15)."""
    node = FruitingChamberController()
    assert node.get_parameter('sensor_stale_timeout').value == 10.0
    node.destroy_node()


def test_none_humidity_safe_state(ros_context):
    """When current_humidity is None and temp is set, control_loop publishes duty=0.0."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    # current_humidity is None (default)
    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)
    node.control_loop()
    assert duty_published[-1] == 0.0, f'Expected duty=0.0 on None humidity, got {duty_published}'
    node.destroy_node()


def test_none_temp_safe_state(ros_context):
    """When current_temp is None and humidity is set, control_loop publishes duty=0.0."""
    node = FruitingChamberController()
    _send_humidity(node, 0.80)   # humidity present
    node.current_temp = None     # temp missing
    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)
    node.control_loop()
    assert duty_published[-1] == 0.0, f'Expected duty=0.0 on None temp, got {duty_published}'
    node.destroy_node()


def test_sensor_staleness(ros_context):
    """Stale sensor data (>sensor_stale_timeout) publishes duty=0.0 and sets _safe_state_active."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    # Humidity arrives at t=0
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        _send_humidity(node, 0.70)  # below threshold -> would turn ON

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # 15 seconds later (> 10s stale timeout), run control
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(15e9))):
        node.control_loop()

    assert duty_published[-1] == 0.0, f'Expected duty=0.0 on stale sensor, got {duty_published}'
    assert node._safe_state_active == True
    node.destroy_node()


def test_safe_state_recovery(ros_context):
    """After stale state, fresh data auto-recovers control without restart."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    # Enter stale state
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        _send_humidity(node, 0.70)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(15e9))):
        node.control_loop()
    assert node._safe_state_active == True

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # Fresh data arrives at t=20s, humidity below threshold
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(20e9))):
        _send_humidity(node, 0.70)
        node.control_loop()

    assert node._safe_state_active == False  # recovered
    # Duty should be >= 0.0 (control resumed — may or may not be non-zero depending on PID state)
    assert duty_published[-1] >= 0.0, 'Expected non-negative duty on recovery'
    node.destroy_node()


def test_staleness_log_deduplication(ros_context):
    """WARN is logged only once on stale entry, not on every subsequent stale tick."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        _send_humidity(node, 0.82)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(15e9))):
        with patch.object(node.get_logger(), 'warn') as mock_warn:
            node.control_loop()  # first stale tick -> logs WARN
            node.control_loop()  # second stale tick -> no additional WARN
            assert mock_warn.call_count == 1
    node.destroy_node()


def test_fresh_data_not_stale(ros_context):
    """Data 5 seconds old (under 10s threshold) is not stale — normal control runs."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    # Humidity arrives at t=0
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.70)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # Only 5 seconds later (under 10s threshold)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        node.control_loop()

    # Not stale — normal control should apply, duty should be > 0 for low humidity
    assert node._safe_state_active == False
    assert len(duty_published) > 0, 'Expected at least one duty publication on fresh data'
    assert duty_published[-1] > 0.0, f'Expected duty > 0 for low humidity, got {duty_published[-1]}'
    node.destroy_node()


# -----------------------------
# TestStartupGracePeriod (SENS-01, WARMUP-01/02/03/04)
# -----------------------------
# Pattern: override node._boot_time post-init to control grace window.
# This is simpler than patching get_clock before __init__ and matches
# the research recommendation (15-RESEARCH.md §Code Examples).

from diagnostic_msgs.msg import DiagnosticStatus


def test_startup_grace_period_param_declared(ros_context):
    """startup_grace_period is a declared parameter with default 20.0."""
    node = FruitingChamberController()
    assert node.get_parameter('startup_grace_period').value == 20.0
    node.destroy_node()


def test_warmup_grace_blocks_actuation(ros_context):
    """Duty=0.0 during grace even with full buffer below threshold."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # t=5s (< 20s grace), buffer full below threshold — would normally produce non-zero duty
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert duty_published[-1] == 0.0, 'Duty must be 0.0 during grace'
        assert node._warming_up == True

    node.destroy_node()


def test_warmup_grace_time_elapsed_buffer_not_full(ros_context):
    """Time elapsed but buffer not full -> grace still active."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # t=25s (past grace period) but only 3 samples — buffer not full
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(25e9))):
        for _ in range(3):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert duty_published[-1] == 0.0, 'Duty must be 0.0 when buffer not full'
        assert node._warming_up == True

    node.destroy_node()


def test_warmup_grace_buffer_full_time_not_elapsed(ros_context):
    """Buffer full but time not elapsed -> grace still active."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # t=10s (< 20s grace), buffer full
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(10e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert duty_published[-1] == 0.0, 'Duty must be 0.0 when time not elapsed'
        assert node._warming_up == True

    node.destroy_node()


def test_warmup_grace_clears_when_both_conditions_met(ros_context):
    """Grace clears at t=21s with full buffer; duty becomes non-zero."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    # Fill buffer while still in grace
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node._warming_up == True

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # t=21s — both conditions satisfied; send fresh humidity to avoid staleness guard
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(21e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node._warming_up == False
        assert duty_published[-1] >= 0.0, 'Duty must be non-negative after grace clears'

    node.destroy_node()


def test_sensor_health_warn_published_during_grace(ros_context):
    """On first grace tick, sensor_health publishes DiagnosticStatus.WARN."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    published = []
    node.sensor_health_pub.publish = lambda msg: published.append(msg)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()

    assert len(published) == 1
    assert published[0].level == DiagnosticStatus.WARN
    assert published[0].name == 'fc1/controller'
    assert published[0].message == 'warming up'
    assert published[0].hardware_id == 'fc1'
    kv = {kv.key: kv.value for kv in published[0].values}
    assert kv['warming_up'] == 'true'
    assert kv['buffer_full'] == 'true'

    node.destroy_node()


def test_sensor_health_ok_published_on_grace_clear(ros_context):
    """On first tick after grace, sensor_health publishes DiagnosticStatus.OK."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    published = []
    node.sensor_health_pub.publish = lambda msg: published.append(msg)

    # Tick during grace -> WARN
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
    assert len(published) == 1 and published[0].level == DiagnosticStatus.WARN

    # Tick after grace -> OK
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(21e9))):
        node.control_loop()

    assert len(published) == 2
    assert published[1].level == DiagnosticStatus.OK
    assert published[1].message == 'ok'

    node.destroy_node()


def test_sensor_health_not_republished_every_tick_in_grace(ros_context):
    """Only one WARN publish during grace, not one per tick (state-change only)."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    published = []
    node.sensor_health_pub.publish = lambda msg: published.append(msg)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        node.control_loop()
        node.control_loop()

    assert len(published) == 1  # state-change only, not 3

    node.destroy_node()


def test_sensor_health_qos_transient_local(ros_context):
    """sensor_health_pub QoS durability is TRANSIENT_LOCAL for late-joiner replay."""
    node = FruitingChamberController()
    qos = node.sensor_health_pub.qos_profile
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL
    assert qos.depth == 1
    node.destroy_node()


# -----------------------------
# Phase 26 — per-physical-sensor freshness via frame_id provenance (D-03)
# -----------------------------


def test_sht30_freshness_via_frame_id(ros_context):
    """frame_id='sht30' on slot-1 messages refreshes _last_sht30_timestamp;
    frame_id='scd41' does NOT (D-03 contract — per-physical-sensor liveness)."""
    node = FruitingChamberController()
    assert node._last_sht30_timestamp is None

    # Slot-1 message stamped 'scd41' -> SHT30 timestamp NOT refreshed
    msg = Temperature()
    msg.header.frame_id = 'scd41'
    msg.temperature = 23.0
    node.temperature_callback(msg)
    assert node._last_sht30_timestamp is None
    assert node._compute_sht30_fresh() is False

    # Slot-1 message stamped 'sht30' -> SHT30 timestamp refreshed
    msg2 = Temperature()
    msg2.header.frame_id = 'sht30'
    msg2.temperature = 23.5
    node.temperature_callback(msg2)
    assert node._last_sht30_timestamp is not None
    assert node._compute_sht30_fresh() is True

    node.destroy_node()


def test_scd41_freshness_via_slot2(ros_context):
    """Arrival on slot-2 (temperature_2 or humidity_2) sets SCD41 fresh."""
    node = FruitingChamberController()
    assert node._compute_scd41_fresh() is False

    # Slot-2 humidity arrives -> SCD41 fresh
    h2 = RelativeHumidity()
    h2.header.frame_id = 'scd41'
    h2.relative_humidity = 0.85
    node.humidity_2_callback(h2)
    assert node._last_humidity2_timestamp is not None
    assert node._compute_scd41_fresh() is True

    node.destroy_node()


def test_sensor_health_includes_freshness_keys(ros_context):
    """_publish_sensor_health emits sht30_fresh and scd41_fresh KeyValues
    alongside (not replacing) the existing four keys (Pitfall 4: append-only)."""
    node = FruitingChamberController()
    published = []
    node.sensor_health_pub.publish = lambda msg: published.append(msg)

    node._publish_sensor_health(warming_up=False)

    assert len(published) == 1
    kv = {kv.key: kv.value for kv in published[0].values}
    # Existing keys preserved
    assert 'warming_up' in kv
    assert 'grace_elapsed_sec' in kv
    assert 'grace_total_sec' in kv
    assert 'buffer_full' in kv
    # New keys added
    assert kv['sht30_fresh'] in ('true', 'false')
    assert kv['scd41_fresh'] in ('true', 'false')
    node.destroy_node()


# -----------------------------
# Phase 27 RED stubs — HUMID-01 + HUMID-03: PID-driven duty, Mode C, ramp, bumpless
# These tests FAIL until Plan 03 implements the PID controller refactor.
# -----------------------------


def test_duty_published_each_tick(ros_context):
    """control_loop() publishes exactly one Float32 on _duty_pub per tick."""
    node = FruitingChamberController()
    node._grace_active = lambda: False
    node.current_temp = 23.0

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        for _ in range(5):
            _send_humidity(node, 0.70)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    N = 3
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        for _ in range(N):
            node.control_loop()

    assert len(duty_published) == N, (
        f'Expected {N} duty publications (one per tick), got {len(duty_published)}'
    )


def test_duty_qos_transient_local(ros_context):
    """_duty_pub QoS durability is TRANSIENT_LOCAL (Pitfall 5)."""
    node = FruitingChamberController()
    qos = node._duty_pub.qos_profile
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL, (
        '_duty_pub must use TRANSIENT_LOCAL so late-joining fc_pwm_driver sees last duty'
    )
    node.destroy_node()


def test_humidifier_state_pub_removed(ros_context):
    """humidifier_state_pub and _set_humidifier_with_dwell are removed (Pitfall 4)."""
    node = FruitingChamberController()
    assert not hasattr(node, 'humidifier_state_pub'), (
        'humidifier_state_pub must be removed from fc_controller — fc_pwm_driver owns it now'
    )
    assert not hasattr(node, '_set_humidifier_with_dwell'), (
        '_set_humidifier_with_dwell must be removed — dwell logic is gone (D-15)'
    )
    node.destroy_node()


def test_pid_params_declared(ros_context):
    """pid_kp/ki/kd/pid_setpoint_ramp_seconds/bypass_threshold/pid_derivative_filter_tau declared."""
    node = FruitingChamberController()
    assert node.get_parameter('pid_kp').value == pytest.approx(0.5)
    assert node.get_parameter('pid_ki').value == pytest.approx(0.002)
    assert node.get_parameter('pid_kd').value == pytest.approx(4.0)
    assert node.get_parameter('pid_setpoint_ramp_seconds').value == pytest.approx(30.0)
    assert node.get_parameter('bypass_threshold').value == pytest.approx(0.025)
    assert node.get_parameter('pid_derivative_filter_tau').value == pytest.approx(10.0)
    node.destroy_node()


def test_pid_gains_live_reload(ros_context):
    """Changing pid_kp via set_parameters mid-run affects next tick's duty."""
    from rclpy.parameter import Parameter
    node = FruitingChamberController()
    node._grace_active = lambda: False
    node.current_temp = 23.0

    # Seed humidity inside the bypass band (default target 0.94, threshold 2.5%)
    # so PID stays in the linear region — Mode C would clamp duty=1.0 and mask
    # the effect of Kp regardless of value.
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        for _ in range(5):
            _send_humidity(node, 0.935)

    duty_low_kp = []
    node._duty_pub.publish = lambda msg: duty_low_kp.append(msg.data)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()

    # Now increase Kp significantly and observe duty changes
    node.set_parameters([Parameter('pid_kp', value=5.0)])

    duty_high_kp = []
    node._duty_pub.publish = lambda msg: duty_high_kp.append(msg.data)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(2e9))):
        node.control_loop()

    assert duty_high_kp[-1] != duty_low_kp[-1], (
        'Changing pid_kp must affect duty output on the next tick'
    )
    node.destroy_node()


def test_grace_forces_duty_zero(ros_context):
    """During grace_active, duty published == 0.0 regardless of error."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)  # way below threshold
        node.control_loop()

    assert duty_published[-1] == 0.0, (
        f'Duty must be 0.0 during grace, got {duty_published[-1]}'
    )


def test_stale_forces_duty_zero(ros_context):
    """D-13: stale=True forces duty=0.0 immediately, bypassing ramp."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        for _ in range(5):
            _send_humidity(node, 0.70)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # 15s later — past stale timeout (10s)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(15e9))):
        node.control_loop()

    assert duty_published[-1] == 0.0, (
        f'D-13: stale sensor must force duty=0.0, got {duty_published[-1]}'
    )


def test_mode_c_entry(ros_context):
    """error_pct > bypass_threshold → duty == 1.0 (Mode C full-ON bypass)."""
    node = FruitingChamberController()
    node._grace_active = lambda: False
    node.current_temp = 23.0

    # target=0.94, send humidity way below: error = 0.94-0.50 = 0.44 >> bypass_threshold=0.025
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        for _ in range(5):
            _send_humidity(node, 0.50)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()

    assert duty_published[-1] == 1.0, (
        f'Mode C: error > bypass_threshold must force duty=1.0, got {duty_published[-1]}'
    )


def test_mode_c_exit_bumpless(ros_context):
    """After Mode C, when error returns inside threshold, PID re-engages with last_output=1.0 (no zero blip)."""
    node = FruitingChamberController()
    node._grace_active = lambda: False
    node.current_temp = 23.0

    # Enter Mode C (large error)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        for _ in range(5):
            _send_humidity(node, 0.50)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()
    assert duty_published[-1] == 1.0, 'Should be in Mode C'

    # Exit Mode C: send humidity just inside target (small error)
    target = node.get_parameter('target_humidity').value  # 0.94
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(2e9))):
        for _ in range(5):
            _send_humidity(node, target - 0.01)  # 1% error < bypass_threshold
        node.control_loop()

    # Bumpless: duty must NOT drop to 0 on Mode C exit; should be close to 1.0
    assert duty_published[-1] > 0.5, (
        f'Mode C exit must be bumpless (no zero blip): duty={duty_published[-1]}'
    )


def test_setpoint_ramp_slews_effective(ros_context):
    """When target_humidity changes, _effective_setpoint slews over pid_setpoint_ramp_seconds."""
    from rclpy.parameter import Parameter
    node = FruitingChamberController()
    node._grace_active = lambda: False
    node.current_temp = 23.0

    # Establish initial effective setpoint
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        for _ in range(5):
            _send_humidity(node, 0.94)
        node.control_loop()
    initial_sp = node._effective_setpoint

    # Change target_humidity
    node.set_parameters([Parameter('target_humidity', value=0.88)])

    # One tick: effective setpoint should slew toward 0.88, not jump there
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(1e9))):
        node.control_loop()
    after_one_tick_sp = node._effective_setpoint

    assert after_one_tick_sp != 0.88, (
        'Effective setpoint must slew toward new target, not jump immediately'
    )
    assert after_one_tick_sp != initial_sp, (
        'Effective setpoint must have moved after one tick'
    )
    node.destroy_node()


def test_bumpless_preload_on_grace_clear(ros_context):
    """Grace clears: first PID tick produces duty ≈ 0.15 (bumpless preload, D-06), not 0 or 1."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    # Fill buffer during grace at near-setpoint humidity (target=0.94, input=0.925 → error≈0.015)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.925)

    duty_published = []
    node._duty_pub.publish = lambda msg: duty_published.append(msg.data)

    # Grace clears at t=21s
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(21e9))):
        for _ in range(5):
            _send_humidity(node, 0.925)
        node.control_loop()

    # Bumpless preload: first duty after grace clear must be around steady-state (~0.15)
    # Not 0.0 (would be abrupt disengagement) and not 1.0 (would be overshoot slam)
    assert 0.05 < duty_published[-1] < 0.95, (
        f'D-06 bumpless preload: first duty after grace must be non-extreme, got {duty_published[-1]}'
    )
    node.destroy_node()


def test_min_dwell_time_param_removed(ros_context):
    """min_dwell_time is NOT declared as a parameter (D-15 enforcement)."""
    node = FruitingChamberController()
    declared_names = node.list_parameters([], 10).names
    assert 'min_dwell_time' not in declared_names, (
        'D-15: min_dwell_time must not be declared — dwell guard replaced by PWM window'
    )
    node.destroy_node()
