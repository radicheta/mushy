#!/usr/bin/env python3
"""Phase 29 — `_validate_params` extension tests for Tier B (per-mode alerter
overrides) + Tier C (global alerter knobs).

Mirrors the fixture pattern in `test_controller_modes.py`:
- `ros_context` fixture init/shutdown rclpy.
- `_make_node()` builds a controller with parameter overrides applied at
  __init__ time, so the validator and startup republish observe the test's
  param shape rather than declared NaN-sentinel defaults.
"""
import pytest

try:
    import rclpy
    from rclpy.parameter import Parameter
    from fc_core.fc_controller import FruitingChamberController
    _RCLPY_AVAILABLE = True
except ImportError:  # noqa: BLE001
    _RCLPY_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not _RCLPY_AVAILABLE, reason='rclpy not available'
)


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def _v0_overrides():
    """Minimal overrides so __init__ runs without GPIO + has both modes declared."""
    return [
        Parameter('actuator_simulation_mode', Parameter.Type.BOOL, True),
        Parameter('active_mode', Parameter.Type.STRING, 'fruiting'),
        Parameter('modes.fruiting.target_humidity', Parameter.Type.DOUBLE, 0.96),
        Parameter('modes.fruiting.band_low', Parameter.Type.DOUBLE, 0.945),
        Parameter('modes.fruiting.band_high', Parameter.Type.DOUBLE, 0.975),
        Parameter('modes.fruiting.defend_side', Parameter.Type.STRING, 'both'),
        Parameter('modes.fruiting.t_target', Parameter.Type.DOUBLE, float('nan')),
        Parameter('modes.pinning.target_humidity', Parameter.Type.DOUBLE, 0.85),
        Parameter('modes.pinning.band_low', Parameter.Type.DOUBLE, 0.90),
        Parameter('modes.pinning.band_high', Parameter.Type.DOUBLE, 0.99),
        Parameter('modes.pinning.defend_side', Parameter.Type.STRING, 'low'),
        Parameter('modes.pinning.t_target', Parameter.Type.DOUBLE, float('nan')),
    ]


def _make_node():
    return FruitingChamberController(parameter_overrides=_v0_overrides())


# --- Tier B: per-mode alerter overrides ---------------------------------------

class TestAlerterParams:
    """Phase 29 — validator extension tests."""

    def test_alerter_cooldown_min_in_range(self, ros_context):
        """`modes.fruiting.alerter.cooldown_min` accepts [1,240], rejects 0/241."""
        node = _make_node()
        try:
            r_ok = node.set_parameters([
                Parameter('modes.fruiting.alerter.cooldown_min', Parameter.Type.INTEGER, 30)
            ])
            assert r_ok[0].successful, f'30 must be accepted; got {r_ok[0].reason}'

            r_lo = node.set_parameters([
                Parameter('modes.fruiting.alerter.cooldown_min', Parameter.Type.INTEGER, 0)
            ])
            assert not r_lo[0].successful

            r_hi = node.set_parameters([
                Parameter('modes.fruiting.alerter.cooldown_min', Parameter.Type.INTEGER, 241)
            ])
            assert not r_hi[0].successful
            # Param store unchanged from last accepted value.
            assert node.get_parameter('modes.fruiting.alerter.cooldown_min').value == 30
        finally:
            node.destroy_node()

    def test_alerter_critical_cooldown_min_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('modes.fruiting.alerter.critical_cooldown_min',
                          Parameter.Type.INTEGER, 60)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.critical_cooldown_min',
                          Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.critical_cooldown_min',
                          Parameter.Type.INTEGER, 241)
            ])[0].successful
        finally:
            node.destroy_node()

    def test_alerter_humidifier_stuck_min_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('modes.fruiting.alerter.humidifier_stuck_min',
                          Parameter.Type.INTEGER, 30)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.humidifier_stuck_min',
                          Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.humidifier_stuck_min',
                          Parameter.Type.INTEGER, 241)
            ])[0].successful
        finally:
            node.destroy_node()

    def test_alerter_oob_n_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('modes.fruiting.alerter.oob_n', Parameter.Type.INTEGER, 5)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.oob_n', Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.oob_n', Parameter.Type.INTEGER, 21)
            ])[0].successful
        finally:
            node.destroy_node()

    def test_alerter_oob_window_min_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('modes.fruiting.alerter.oob_window_min',
                          Parameter.Type.INTEGER, 3)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.oob_window_min',
                          Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('modes.fruiting.alerter.oob_window_min',
                          Parameter.Type.INTEGER, 61)
            ])[0].successful
        finally:
            node.destroy_node()

    # --- Tier C: global alerter knobs -----------------------------------------

    def test_pi_offline_min_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('pi_offline_min', Parameter.Type.INTEGER, 10)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('pi_offline_min', Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('pi_offline_min', Parameter.Type.INTEGER, 61)
            ])[0].successful
        finally:
            node.destroy_node()

    def test_sensor_offline_min_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('sensor_offline_min', Parameter.Type.INTEGER, 10)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('sensor_offline_min', Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('sensor_offline_min', Parameter.Type.INTEGER, 61)
            ])[0].successful
        finally:
            node.destroy_node()

    def test_heartbeat_hour_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('heartbeat_hour', Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert node.set_parameters([
                Parameter('heartbeat_hour', Parameter.Type.INTEGER, 23)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('heartbeat_hour', Parameter.Type.INTEGER, -1)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('heartbeat_hour', Parameter.Type.INTEGER, 24)
            ])[0].successful
        finally:
            node.destroy_node()

    def test_max_sends_per_hour_in_range(self, ros_context):
        node = _make_node()
        try:
            assert node.set_parameters([
                Parameter('max_sends_per_hour', Parameter.Type.INTEGER, 20)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('max_sends_per_hour', Parameter.Type.INTEGER, 0)
            ])[0].successful
            assert not node.set_parameters([
                Parameter('max_sends_per_hour', Parameter.Type.INTEGER, 201)
            ])[0].successful
        finally:
            node.destroy_node()

    # --- Independence + atomicity ---------------------------------------------

    def test_pinning_alerter_cooldown_independent_of_fruiting(self, ros_context):
        """Setting pinning's cooldown_min must NOT mutate fruiting's value."""
        node = _make_node()
        try:
            initial_fruiting = node.get_parameter(
                'modes.fruiting.alerter.cooldown_min'
            ).value
            r = node.set_parameters([
                Parameter('modes.pinning.alerter.cooldown_min',
                          Parameter.Type.INTEGER, 90)
            ])
            assert r[0].successful, f'pinning cooldown_min=90 must accept; got {r[0].reason}'
            assert node.get_parameter(
                'modes.pinning.alerter.cooldown_min'
            ).value == 90
            assert node.get_parameter(
                'modes.fruiting.alerter.cooldown_min'
            ).value == initial_fruiting
        finally:
            node.destroy_node()

    def test_alerter_param_set_atomic_rollback(self, ros_context):
        """Batch with one valid + one invalid alerter param: whole batch rejected,
        previous values preserved.

        Note: rclpy's set_parameters returns one SetParametersResult per parameter
        but our atomic validator returns on first failure. The batch is presented
        as a list to the callback; on failure the param store is unchanged.
        """
        node = _make_node()
        try:
            # First land a known-good value.
            assert node.set_parameters([
                Parameter('modes.fruiting.alerter.cooldown_min',
                          Parameter.Type.INTEGER, 30)
            ])[0].successful

            # Batch: one valid + one out-of-range. Validator rejects the batch.
            results = node.set_parameters([
                Parameter('modes.fruiting.alerter.oob_n', Parameter.Type.INTEGER, 5),
                Parameter('modes.fruiting.alerter.cooldown_min',
                          Parameter.Type.INTEGER, 999),
            ])
            assert not all(r.successful for r in results), (
                'batch with invalid cooldown_min=999 must not all-succeed'
            )
            # Param store unchanged from prior accepted state.
            assert node.get_parameter(
                'modes.fruiting.alerter.cooldown_min'
            ).value == 30
        finally:
            node.destroy_node()

    def test_validator_sets_pending_republish_overrides_flag(self, ros_context):
        """Successful set of `modes.*.alerter.*` queues overrides republish."""
        node = _make_node()
        try:
            # Drain any startup-queued state (none expected for overrides).
            node._pending_alerter_overrides_republish = None
            r = node.set_parameters([
                Parameter('modes.fruiting.alerter.cooldown_min',
                          Parameter.Type.INTEGER, 45)
            ])
            assert r[0].successful, f'expected accept; got {r[0].reason}'
            assert node._pending_alerter_overrides_republish is not None
        finally:
            node.destroy_node()

    def test_validator_sets_pending_republish_globals_flag(self, ros_context):
        """Successful set of a Tier C global queues globals republish."""
        node = _make_node()
        try:
            node._pending_alerter_globals_republish = None
            r = node.set_parameters([
                Parameter('pi_offline_min', Parameter.Type.INTEGER, 10)
            ])
            assert r[0].successful, f'expected accept; got {r[0].reason}'
            assert node._pending_alerter_globals_republish is not None
        finally:
            node.destroy_node()


# --- Phase 30 SCHED-01 — schedule_windows validator extension ----------------

class TestScheduleWindowsParam:
    """Plan 30-01 Task 2 — `_validate_params` arm for `schedule_windows`."""

    def test_schedule_windows_default_empty(self, ros_context):
        node = _make_node()
        try:
            assert node.get_parameter('schedule_windows').value == '[]'
        finally:
            node.destroy_node()

    def test_schedule_windows_set_valid(self, ros_context):
        node = _make_node()
        try:
            new = '[{"start":"06:00","end":"22:00","mode":"fruiting"}]'
            r = node.set_parameters([
                Parameter('schedule_windows', Parameter.Type.STRING, new)
            ])
            assert r[0].successful, f'valid schedule must accept; got {r[0].reason}'
            assert node.get_parameter('schedule_windows').value == new
        finally:
            node.destroy_node()

    def test_schedule_windows_reject_malformed_json(self, ros_context):
        node = _make_node()
        try:
            r = node.set_parameters([
                Parameter('schedule_windows', Parameter.Type.STRING, '{not json')
            ])
            assert not r[0].successful
            assert 'JSON' in r[0].reason
            assert node.get_parameter('schedule_windows').value == '[]'
        finally:
            node.destroy_node()

    def test_schedule_windows_reject_missing_key(self, ros_context):
        node = _make_node()
        try:
            r = node.set_parameters([
                Parameter('schedule_windows', Parameter.Type.STRING,
                          '[{"start":"06:00","end":"22:00"}]')
            ])
            assert not r[0].successful
            assert 'mode' in r[0].reason
            assert node.get_parameter('schedule_windows').value == '[]'
        finally:
            node.destroy_node()

    def test_schedule_windows_reject_bad_time(self, ros_context):
        node = _make_node()
        try:
            r = node.set_parameters([
                Parameter('schedule_windows', Parameter.Type.STRING,
                          '[{"start":"6:00","end":"22:00","mode":"fruiting"}]')
            ])
            assert not r[0].successful
            assert 'HH:MM' in r[0].reason
        finally:
            node.destroy_node()

    def test_schedule_windows_reject_unknown_mode(self, ros_context):
        node = _make_node()
        try:
            r = node.set_parameters([
                Parameter('schedule_windows', Parameter.Type.STRING,
                          '[{"start":"06:00","end":"22:00","mode":"composting"}]')
            ])
            assert not r[0].successful
            assert 'declared' in r[0].reason or 'composting' in r[0].reason
        finally:
            node.destroy_node()

    def test_schedule_windows_reject_not_array(self, ros_context):
        node = _make_node()
        try:
            r = node.set_parameters([
                Parameter('schedule_windows', Parameter.Type.STRING,
                          '{"start":"06:00"}')
            ])
            assert not r[0].successful
            assert 'array' in r[0].reason
        finally:
            node.destroy_node()

    def test_schedule_windows_empty_array_always_valid(self, ros_context):
        node = _make_node()
        try:
            r = node.set_parameters([
                Parameter('schedule_windows', Parameter.Type.STRING, '[]')
            ])
            assert r[0].successful
        finally:
            node.destroy_node()
