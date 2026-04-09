#!/usr/bin/env python3
"""Unit tests for FcCamera ROS2 node.

Tests cover: simulation mode (no cv2 calls), unavailable camera (graceful warning),
publish flow (CompressedImage with correct format/data), and parameter declaration.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


def _make_rclpy_mock():
    """Build a minimal rclpy mock that satisfies Node.__init__ without a daemon."""
    rclpy_mod = types.ModuleType('rclpy')
    node_mod = types.ModuleType('rclpy.node')
    time_mod = types.ModuleType('rclpy.time')
    param_mod = types.ModuleType('rclpy.parameter')

    class FakeTime:
        def to_msg(self):
            m = MagicMock()
            return m

    class FakeClock:
        def now(self):
            return FakeTime()

    class FakeLogger:
        def info(self, msg): pass
        def warn(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass

    class FakePublisher:
        def __init__(self):
            self.published = []

        def publish(self, msg):
            self.published.append(msg)

    class FakeTimer:
        pass

    class FakeParameter:
        def __init__(self, value):
            self.value = value

    class FakeNode:
        """Minimal Node substitute that replaces rclpy.node.Node."""
        _pub_registry = {}  # topic -> FakePublisher

        def __init__(self, name):
            self._name = name
            self._params = {}
            self._pub_registry = {}
            self._timers = []

        def get_logger(self):
            return FakeLogger()

        def get_clock(self):
            return FakeClock()

        def declare_parameters(self, namespace, parameters):
            for item in parameters:
                name, default = item[0], item[1]
                self._params[name] = default

        def get_parameter(self, name):
            return FakeParameter(self._params[name])

        def create_publisher(self, msg_type, topic, qos):
            pub = FakePublisher()
            self._pub_registry[topic] = pub
            return pub

        def create_timer(self, period, callback):
            t = FakeTimer()
            self._timers.append(t)
            return t

        def destroy_node(self):
            pass

    node_mod.Node = FakeNode
    rclpy_mod.node = node_mod
    rclpy_mod.time = time_mod
    rclpy_mod.parameter = param_mod

    return rclpy_mod, FakeNode, FakeParameter


def _inject_sensor_msgs():
    """Inject a minimal sensor_msgs.msg.CompressedImage stub."""
    sensor_msgs_mod = types.ModuleType('sensor_msgs')
    msg_mod = types.ModuleType('sensor_msgs.msg')

    class CompressedImage:
        def __init__(self):
            self.header = MagicMock()
            self.format = ''
            self.data = b''

    msg_mod.CompressedImage = CompressedImage
    sensor_msgs_mod.msg = msg_mod

    sys.modules['sensor_msgs'] = sensor_msgs_mod
    sys.modules['sensor_msgs.msg'] = msg_mod

    return CompressedImage


def _setup_mocks():
    """Install rclpy and sensor_msgs stubs into sys.modules."""
    rclpy_mod, FakeNode, FakeParameter = _make_rclpy_mock()
    CompressedImage = _inject_sensor_msgs()

    sys.modules['rclpy'] = rclpy_mod
    sys.modules['rclpy.node'] = rclpy_mod.node
    sys.modules['rclpy.time'] = rclpy_mod.time
    sys.modules['rclpy.parameter'] = rclpy_mod.parameter

    return FakeNode, FakeParameter, CompressedImage


FakeNode, FakeParameter, CompressedImage = _setup_mocks()


def _load_fc_camera():
    """Import fc_camera module fresh (or return cached)."""
    # Remove cached module if present so patches take effect
    if 'fc_core.fc_camera' in sys.modules:
        del sys.modules['fc_core.fc_camera']
    from fc_core import fc_camera
    return fc_camera


def _patch_param(name, value):
    """Return a declare_parameters patch that overrides one parameter default."""
    original_declare = FakeNode.declare_parameters

    def patched_declare(self_node, namespace, parameters):
        new_params = []
        for item in parameters:
            pname, default = item[0], item[1]
            if pname == name:
                default = value
            new_params.append((pname, default))
        original_declare(self_node, namespace, new_params)

    return patch.object(FakeNode, 'declare_parameters', patched_declare)


class TestCameraSimMode(unittest.TestCase):
    """Test 1: camera_simulation_mode=True — no cv2 calls, capture_and_publish is a no-op."""

    def test_camera_sim_mode(self):
        fc_camera = _load_fc_camera()

        # cv2 must NOT be called when simulation mode is active
        mock_cv2 = MagicMock()
        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_param('camera_simulation_mode', True):
                node = fc_camera.FcCamera()
            # In simulation mode, cap should be None
            self.assertIsNone(node.cap)
            # capture_and_publish should be a no-op
            node.capture_and_publish()
            # VideoCapture must never be constructed
            mock_cv2.VideoCapture.assert_not_called()

        node.destroy_node()


class TestCameraUnavailable(unittest.TestCase):
    """Test 2: camera_simulation_mode=False, VideoCapture.isOpened()=False -> warn, no crash."""

    def test_camera_unavailable(self):
        fc_camera = _load_fc_camera()

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.return_value = mock_cap

        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_param('camera_simulation_mode', False):
                node = fc_camera.FcCamera()
                # cap is set but isOpened() returns False
                self.assertIsNotNone(node.cap)
                # capture_and_publish must return without publishing (no crash)
                pub = node._cam_pub
                pre_count = len(pub.published)
                node.capture_and_publish()
                self.assertEqual(len(pub.published), pre_count)

        node.destroy_node()


class TestCameraPublishesCompressedImage(unittest.TestCase):
    """Test 3: mocked cv2 with isOpened=True and valid frame -> publishes CompressedImage."""

    def test_camera_publishes_compressed_image(self):
        fc_camera = _load_fc_camera()

        mock_frame = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, mock_frame)

        fake_buf = MagicMock()
        fake_buf.tobytes.return_value = b'\xff\xd8\xff\xe0fake_jpeg_data'

        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.imencode.return_value = (True, fake_buf)
        mock_cv2.IMWRITE_JPEG_QUALITY = 1

        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_param('camera_simulation_mode', False):
                node = fc_camera.FcCamera()
                pub = node._cam_pub
                node.capture_and_publish()

        # One message should have been published
        self.assertEqual(len(pub.published), 1)
        msg = pub.published[0]
        self.assertEqual(msg.format, 'jpeg')
        self.assertEqual(msg.data, b'\xff\xd8\xff\xe0fake_jpeg_data')

        node.destroy_node()


class TestCameraParametersDeclared(unittest.TestCase):
    """Test 4: All 6 required parameters are declared on the node."""

    def test_camera_parameters_declared(self):
        fc_camera = _load_fc_camera()

        mock_cv2 = MagicMock()
        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            node = fc_camera.FcCamera()

        required_params = [
            'camera_simulation_mode',
            'camera_device',
            'camera_width',
            'camera_height',
            'camera_fps',
            'camera_jpeg_quality',
        ]
        for param in required_params:
            self.assertIn(param, node._params,
                          f'Parameter {param!r} not declared on FcCamera node')

        node.destroy_node()


if __name__ == '__main__':
    unittest.main()
