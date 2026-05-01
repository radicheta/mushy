try:
    import rclpy
    import rclpy.time
    _ROS_TIME = rclpy.time.ClockType.ROS_TIME
    _RCLPY_AVAILABLE = True
except ImportError:  # noqa: BLE001
    _RCLPY_AVAILABLE = False

from unittest.mock import MagicMock
import pytest


def _mock_clock_at(nanoseconds):
    """Return a mock clock whose .now() returns the given ROS time (ROS_TIME clock type)."""
    mock_clock = MagicMock()
    if _RCLPY_AVAILABLE:
        mock_clock.now.return_value = rclpy.time.Time(
            nanoseconds=nanoseconds, clock_type=_ROS_TIME
        )
    return mock_clock


@pytest.fixture
def ros_context():
    if not _RCLPY_AVAILABLE:
        pytest.skip('rclpy not available')
    rclpy.init()
    yield
    rclpy.shutdown()
