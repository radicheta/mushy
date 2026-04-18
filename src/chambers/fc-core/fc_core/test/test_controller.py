#!/usr/bin/env python3
import pytest
import rclpy
import rclpy.time
from sensor_msgs.msg import Temperature, RelativeHumidity
from fc_core.fc_controller import FruitingChamberController
import time
from unittest.mock import patch, MagicMock

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

def test_humidity_control(ros_context):
    node = FruitingChamberController()
    node._grace_active = lambda: False  # bypass grace — not under test here

    # Test temperature at target
    temp_msg = Temperature()
    temp_msg.temperature = node.get_parameter('target_temp').value
    node.temperature_callback(temp_msg)

    # Test humidity below target — advance clock to t=0 for first toggle
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, node.get_parameter('target_humidity').value - 0.1)
        node.control_loop()
        # Humidifier should be ON
        assert node.humidifier_state == True

    # Test humidity above target — advance clock 301s past dwell time
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(301e9))):
        for _ in range(5):
            _send_humidity(node, node.get_parameter('target_humidity').value + 0.1)
        node.control_loop()
        # Humidifier should be OFF
        assert node.humidifier_state == False

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
    """min_dwell_time (300.0) and sensor_stale_timeout (10.0) are declared parameters."""
    node = FruitingChamberController()
    assert node.get_parameter('min_dwell_time').value == 300.0
    assert node.get_parameter('sensor_stale_timeout').value == 10.0
    node.destroy_node()


def test_none_humidity_safe_state(ros_context):
    """When current_humidity is None and temp is set, control_loop drives humidifier OFF."""
    node = FruitingChamberController()
    node.humidifier_state = True   # simulate humidifier was ON
    node.current_temp = 23.0       # temp is present
    # current_humidity is None (default)
    node.control_loop()
    assert node.humidifier_state == False  # driven OFF, not frozen
    node.destroy_node()


def test_none_temp_safe_state(ros_context):
    """When current_temp is None and humidity is set, control_loop drives humidifier OFF."""
    node = FruitingChamberController()
    node.humidifier_state = True
    _send_humidity(node, 0.80)   # humidity present
    node.current_temp = None     # temp missing
    node.control_loop()
    assert node.humidifier_state == False
    node.destroy_node()


def test_dwell_time_blocks_toggle(ros_context):
    """Humidifier stays ON when dwell time has not elapsed since last toggle."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.70)  # fill buffer well below threshold -> humidifier ON
        node.control_loop()
        assert node.humidifier_state == True

    # 10 seconds later (way under 300s dwell time)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(10e9))):
        for _ in range(5):
            _send_humidity(node, 0.95)  # fill buffer well above threshold -> wants OFF
        node.control_loop()
        assert node.humidifier_state == True  # blocked by dwell time

    node.destroy_node()


def test_dwell_time_allows_toggle_after_wait(ros_context):
    """Humidifier can toggle after min_dwell_time has elapsed."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == True

    # 301 seconds later (past 300s dwell time)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(301e9))):
        for _ in range(5):
            _send_humidity(node, 0.95)
        node.control_loop()
        assert node.humidifier_state == False  # toggle permitted

    node.destroy_node()


def test_dwell_time_first_toggle_always_allowed(ros_context):
    """First toggle is always allowed when _last_humidifier_toggle is None."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here
    assert node._last_humidifier_toggle is None

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == True  # first toggle always allowed

    node.destroy_node()


def test_dwell_time_applies_both_directions(ros_context):
    """Dwell guard blocks OFF->ON toggle the same as ON->OFF when time has not elapsed."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    # Pre-set humidifier ON so the first control_loop has a real ON->OFF transition
    node.humidifier_state = True

    # Turn OFF first (send humidity above threshold, humidifier was ON -> transitions to OFF)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.95)
        node.control_loop()
        assert node.humidifier_state == False  # turned OFF, _last_toggle recorded at t=0

    # Try to turn ON 10s later (under 300s dwell time)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(10e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == False  # blocked by dwell time

    node.destroy_node()


def test_sensor_staleness(ros_context):
    """Stale sensor data (>sensor_stale_timeout) drives humidifier OFF and sets _safe_state_active."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    # Humidity arrives at t=0
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        _send_humidity(node, 0.70)  # below threshold -> would turn ON

    # 15 seconds later (> 10s stale timeout), run control
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(15e9))):
        node.control_loop()

    assert node.humidifier_state == False  # safe state, not ON
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

    # Fresh data arrives at t=20s, humidity below threshold
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(20e9))):
        _send_humidity(node, 0.70)
        node.control_loop()

    assert node._safe_state_active == False  # recovered
    # Note: humidifier may or may not be ON depending on dwell time from safe-state OFF.
    # The key assertion is _safe_state_active == False (control resumed).
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


def test_safe_state_updates_dwell_toggle(ros_context):
    """Safe-state forced OFF updates _last_humidifier_toggle (dwell timer resets)."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()  # humidifier ON

    # Go stale at t=15s
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(15e9))):
        node.control_loop()  # safe state OFF

    # _last_humidifier_toggle should be updated to t=15s
    assert node._last_humidifier_toggle is not None
    assert node._last_humidifier_toggle == rclpy.time.Time(nanoseconds=int(15e9), clock_type=_ROS_TIME)
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

    # Only 5 seconds later (under 10s threshold)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        node.control_loop()

    # Not stale — normal control should apply (humidifier ON for low humidity)
    assert node._safe_state_active == False
    assert node.humidifier_state == True  # below threshold -> ON
    node.destroy_node()


def test_humidifier_state_published(ros_context):
    """control_loop publishes current humidifier state on fc1/actuators/humidifier."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._grace_active = lambda: False  # bypass grace — not under test here

    published = []
    node.humidifier_state_pub.publish = lambda msg: published.append(msg.data)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(0))):
        for _ in range(5):
            _send_humidity(node, 0.70)  # below threshold -> humidifier ON
        node.control_loop()

    assert len(published) == 1
    assert published[0] == True

    node.destroy_node()


# -----------------------------
# TestStartupGracePeriod (SENS-01, WARMUP-01/02/03/04)
# -----------------------------
# Pattern: override node._boot_time post-init to control grace window.
# This is simpler than patching get_clock before __init__ and matches
# the research recommendation (15-RESEARCH.md §Code Examples).

from diagnostic_msgs.msg import DiagnosticStatus
from rclpy.qos import DurabilityPolicy


def test_startup_grace_period_param_declared(ros_context):
    """startup_grace_period is a declared parameter with default 20.0."""
    node = FruitingChamberController()
    assert node.get_parameter('startup_grace_period').value == 20.0
    node.destroy_node()


def test_warmup_grace_blocks_actuation(ros_context):
    """Humidifier stays OFF during grace even with full buffer below threshold."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    # t=5s (< 20s grace), buffer full below threshold — would normally turn ON
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == False
        assert node._warming_up == True

    node.destroy_node()


def test_warmup_grace_time_elapsed_buffer_not_full(ros_context):
    """Time elapsed but buffer not full -> grace still active."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    # t=25s (past grace period) but only 3 samples — buffer not full
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(25e9))):
        for _ in range(3):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == False
        assert node._warming_up == True

    node.destroy_node()


def test_warmup_grace_buffer_full_time_not_elapsed(ros_context):
    """Buffer full but time not elapsed -> grace still active."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    # t=10s (< 20s grace), buffer full
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(10e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == False
        assert node._warming_up == True

    node.destroy_node()


def test_warmup_grace_clears_when_both_conditions_met(ros_context):
    """Grace clears at t=21s with full buffer; humidifier engages."""
    node = FruitingChamberController()
    node.current_temp = 23.0
    node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)

    # Fill buffer while still in grace
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node._warming_up == True

    # t=21s — both conditions satisfied; send fresh humidity to avoid staleness guard
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(21e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == True
        assert node._warming_up == False

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