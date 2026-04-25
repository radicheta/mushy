#!/usr/bin/env python3
"""Phase 26-01 unit tests — dual-slot sensor publishing + frame_id provenance.

Covers Phase 26 D-01 / D-02 / D-03 + frame_id provenance:
  - Slot 1 (fc1/temperature, fc1/humidity) prefers SHT30, falls back to SCD41.
  - Slot 2 (fc1/temperature_2, fc1/humidity_2) is SCD41-only and independent of SHT30.
  - No publishes when underlying value is None / data not ready (gap-over-noise).
  - Each published Temperature / RelativeHumidity carries header.frame_id set to
    the physical sensor that backed the value ('sht30' or 'scd41').

Mirrors the lifecycle pattern from test_controller.py: rclpy.init/shutdown via
fixture, MagicMock per publisher, replace node.sht / node.scd handles in-place.
"""
import pytest
import rclpy
from unittest.mock import patch, MagicMock
from sensor_msgs.msg import Temperature, RelativeHumidity
from fc_core.fc_sensors import FruitingChamberSensors


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def _force_hardware_mode(node):
    """Patch get_parameter so read_sensors takes the hardware path.

    The node was constructed in default sim mode (so we don't need real I2C);
    we then flip sensor_simulation_mode to False at read_sensors() invocation
    time and inject MagicMock sensor handles directly on node.sht / node.scd.
    """
    real_get_param = node.get_parameter

    def fake_get_param(name):
        if name == 'sensor_simulation_mode':
            return MagicMock(value=False)
        return real_get_param(name)

    node.get_parameter = fake_get_param


def _patch_publishers(node):
    """Replace each publisher's .publish with a MagicMock for assertion."""
    node.temp_pub.publish = MagicMock()
    node.humidity_pub.publish = MagicMock()
    node.co2_pub.publish = MagicMock()
    # Slot-2 publishers may not exist before Task 2 — that is the RED failure mode.
    if hasattr(node, 'temp_2_pub'):
        node.temp_2_pub.publish = MagicMock()
    if hasattr(node, 'humidity_2_pub'):
        node.humidity_2_pub.publish = MagicMock()


def _make_sht30_mock(temperature=23.5, relative_humidity=88.0):
    m = MagicMock()
    m.temperature = temperature
    m.relative_humidity = relative_humidity
    return m


def _make_scd41_mock(temperature=99.0, relative_humidity=50.0, co2=500, data_ready=True):
    m = MagicMock()
    m.data_ready = data_ready
    m.temperature = temperature
    m.relative_humidity = relative_humidity
    m.CO2 = co2
    return m


def test_slot1_uses_sht30_when_present(ros_context):
    """D-01: Slot-1 carries SHT30 values when both sensors are alive,
    and stamps header.frame_id == 'sht30'."""
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = _make_sht30_mock(temperature=23.5, relative_humidity=88.0)
    node.scd = _make_scd41_mock(temperature=99.0, relative_humidity=50.0, co2=500)
    _patch_publishers(node)

    node.read_sensors()

    # SHT30 wins — value 23.5°C / 88% RH (NOT 99.0 / 50.0)
    assert node.temp_pub.publish.called
    temp_msg = node.temp_pub.publish.call_args.args[0]
    assert temp_msg.temperature == pytest.approx(23.5)
    assert temp_msg.header.frame_id == 'sht30'

    assert node.humidity_pub.publish.called
    humid_msg = node.humidity_pub.publish.call_args.args[0]
    assert humid_msg.relative_humidity == pytest.approx(0.88)
    assert humid_msg.header.frame_id == 'sht30'

    node.destroy_node()


def test_slot1_falls_back_to_scd41(ros_context):
    """D-01: When SHT30 is absent, slot-1 silently falls back to SCD41 values
    and stamps header.frame_id == 'scd41'."""
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = None
    node.scd = _make_scd41_mock(temperature=99.0, relative_humidity=50.0, co2=500)
    _patch_publishers(node)

    node.read_sensors()

    assert node.temp_pub.publish.called
    temp_msg = node.temp_pub.publish.call_args.args[0]
    assert temp_msg.temperature == pytest.approx(99.0)
    assert temp_msg.header.frame_id == 'scd41'

    assert node.humidity_pub.publish.called
    humid_msg = node.humidity_pub.publish.call_args.args[0]
    assert humid_msg.relative_humidity == pytest.approx(0.50)
    assert humid_msg.header.frame_id == 'scd41'

    node.destroy_node()


def test_slot2_publishes_scd41(ros_context):
    """D-02: Slot 2 publishes SCD41 readings even when SHT30 is alive
    and stamps header.frame_id == 'scd41'."""
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = _make_sht30_mock(temperature=23.5, relative_humidity=88.0)
    node.scd = _make_scd41_mock(temperature=99.0, relative_humidity=50.0, co2=500)
    _patch_publishers(node)

    node.read_sensors()

    # Slot 2 must exist (Task 2 creates these publishers)
    assert hasattr(node, 'temp_2_pub'), 'temp_2_pub publisher missing'
    assert hasattr(node, 'humidity_2_pub'), 'humidity_2_pub publisher missing'

    assert node.temp_2_pub.publish.called
    t2 = node.temp_2_pub.publish.call_args.args[0]
    assert t2.temperature == pytest.approx(99.0)        # SCD41 value, NOT 23.5
    assert t2.header.frame_id == 'scd41'

    assert node.humidity_2_pub.publish.called
    h2 = node.humidity_2_pub.publish.call_args.args[0]
    assert h2.relative_humidity == pytest.approx(0.50)  # SCD41 value, NOT 0.88
    assert h2.header.frame_id == 'scd41'

    node.destroy_node()


def test_slot2_independent_of_sht30(ros_context):
    """D-02: Slot 2 publishes SCD41 readings even when SHT30 is absent."""
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = None
    node.scd = _make_scd41_mock(temperature=22.0, relative_humidity=85.0, co2=600)
    _patch_publishers(node)

    node.read_sensors()

    assert hasattr(node, 'temp_2_pub'), 'temp_2_pub publisher missing'
    assert hasattr(node, 'humidity_2_pub'), 'humidity_2_pub publisher missing'

    assert node.temp_2_pub.publish.called
    t2 = node.temp_2_pub.publish.call_args.args[0]
    assert t2.temperature == pytest.approx(22.0)
    assert t2.header.frame_id == 'scd41'

    assert node.humidity_2_pub.publish.called
    h2 = node.humidity_2_pub.publish.call_args.args[0]
    assert h2.header.frame_id == 'scd41'

    node.destroy_node()


def test_no_stale_publish(ros_context):
    """D-03: When neither sensor produces a value, no publish on any slot."""
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = None
    node.scd = None
    _patch_publishers(node)

    node.read_sensors()

    node.temp_pub.publish.assert_not_called()
    node.humidity_pub.publish.assert_not_called()
    if hasattr(node, 'temp_2_pub'):
        node.temp_2_pub.publish.assert_not_called()
    if hasattr(node, 'humidity_2_pub'):
        node.humidity_2_pub.publish.assert_not_called()
    # CO2 must also not publish if SCD41 is gone
    node.co2_pub.publish.assert_not_called()

    node.destroy_node()


def test_frame_id_provenance(ros_context):
    """Phase 26 frame_id contract — three sub-cases:
    (a) SHT30 fresh + SCD41 fresh → slot-1='sht30', slot-2='scd41'
    (b) SHT30 absent + SCD41 fresh → slot-1='scd41', slot-2='scd41'
    (c) SHT30 raises during read + SCD41 fresh → slot-1='scd41', slot-2='scd41'
    """
    # --- (a) both fresh ---
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = _make_sht30_mock(23.5, 88.0)
    node.scd = _make_scd41_mock(99.0, 50.0, 500)
    _patch_publishers(node)
    node.read_sensors()
    assert node.temp_pub.publish.call_args.args[0].header.frame_id == 'sht30'
    assert node.humidity_pub.publish.call_args.args[0].header.frame_id == 'sht30'
    assert node.temp_2_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    assert node.humidity_2_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    node.destroy_node()

    # --- (b) SHT30 absent ---
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = None
    node.scd = _make_scd41_mock(99.0, 50.0, 500)
    _patch_publishers(node)
    node.read_sensors()
    assert node.temp_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    assert node.humidity_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    assert node.temp_2_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    node.destroy_node()

    # --- (c) SHT30 raises (Pitfall 1: per-sensor try/except keeps SCD41 alive) ---
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    sht_broken = MagicMock()
    type(sht_broken).temperature = property(
        lambda self: (_ for _ in ()).throw(IOError('simulated I2C bus hang'))
    )
    node.sht = sht_broken
    node.scd = _make_scd41_mock(99.0, 50.0, 500)
    _patch_publishers(node)
    node.read_sensors()
    # SHT30 raised → slot-1 must fall back to SCD41 provenance
    assert node.temp_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    assert node.humidity_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    assert node.temp_2_pub.publish.call_args.args[0].header.frame_id == 'scd41'
    node.destroy_node()
