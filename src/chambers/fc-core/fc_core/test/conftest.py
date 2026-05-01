import rclpy
import rclpy.time
from unittest.mock import MagicMock
import pytest

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
