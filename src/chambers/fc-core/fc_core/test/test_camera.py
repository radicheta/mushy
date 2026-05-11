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
            self._sub_count = 0

        def publish(self, msg):
            self.published.append(msg)

        def get_subscription_count(self):
            return self._sub_count

    class FakeTimer:
        def __init__(self):
            self.period = None
            self.callback = None
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

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
            self._node_sub_count = {}  # topic -> int, simulates node-level graph cache

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

        def count_subscribers(self, topic):
            return self._node_sub_count.get(topic, 0)

        def count_publishers(self, topic):
            return self._node_sub_count.get('__pub_' + topic, 1)

        def create_timer(self, period, callback):
            t = FakeTimer()
            t.period = period
            t.callback = callback
            self._timers.append(t)
            return t

        def destroy_timer(self, timer):
            if timer in self._timers:
                self._timers.remove(timer)
            return True

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


def _patch_params(overrides):
    """Return a declare_parameters patch that overrides multiple parameter defaults.

    overrides: dict of {param_name: value}
    """
    original_declare = FakeNode.declare_parameters

    def patched_declare(self_node, namespace, parameters):
        new_params = []
        for item in parameters:
            pname, default = item[0], item[1]
            if pname in overrides:
                default = overrides[pname]
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


class TestCameraReopenOnStuckRead(unittest.TestCase):
    """999.24: after N consecutive cap.read() failures, the camera releases
    its handle and reconstructs VideoCapture rather than warn-and-skip forever.
    """

    def test_reopen_fires_at_threshold(self):
        fc_camera = _load_fc_camera()

        # First VideoCapture instance: opens fine but read() always fails
        stuck_cap = MagicMock()
        stuck_cap.isOpened.return_value = True
        stuck_cap.read.return_value = (False, None)

        # Second VideoCapture instance: opens fine and reads successfully
        good_frame = MagicMock()
        good_cap = MagicMock()
        good_cap.isOpened.return_value = True
        good_cap.read.return_value = (True, good_frame)

        fake_buf = MagicMock()
        fake_buf.tobytes.return_value = b'\xff\xd8\xff\xe0jpeg'

        mock_cv2 = MagicMock()
        # First constructor call returns the stuck cap; subsequent calls return the good cap
        mock_cv2.VideoCapture.side_effect = [stuck_cap, good_cap]
        mock_cv2.imencode.return_value = (True, fake_buf)
        mock_cv2.IMWRITE_JPEG_QUALITY = 1

        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_params({
                'camera_simulation_mode': False,
                'camera_reopen_threshold': 3,  # keep test fast
            }):
                node = fc_camera.FcCamera()

                # Three failures: on the 3rd tick the threshold check fires
                # _attempt_reopen, which release()es stuck_cap and constructs good_cap.
                node.capture_and_publish()
                node.capture_and_publish()
                node.capture_and_publish()
                self.assertTrue(stuck_cap.release.called,
                                'cap.release() should fire once threshold hit')
                self.assertIs(node.cap, good_cap,
                              'node.cap should be the new (good) VideoCapture instance')

                # 4th tick uses good_cap; successful read resets the counter
                node.capture_and_publish()

        self.assertEqual(node._consecutive_read_failures, 0,
                         'counter should reset on successful read')

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


class TestSubscriberAwareCamera(unittest.TestCase):
    """Tests for subscriber-aware rate switching (CAM-01, CAM-02)."""

    def _make_node(self):
        """Create FcCamera in simulation mode with default subscriber-aware params."""
        fc_camera = _load_fc_camera()
        mock_cv2 = MagicMock()
        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_params({
                'camera_simulation_mode': True,
                'camera_fps': 0.000278,
                'camera_active_fps': 1.0,
                'camera_subscriber_grace_sec': 5.0,
            }):
                node = fc_camera.FcCamera()
        return node

    def test_starts_idle(self):
        """FcCamera starts with _is_active=False and timer period ~3600s (1 frame/hour)."""
        node = self._make_node()
        self.assertFalse(node._is_active)
        # camera_fps default is 0.000278 => period = 1.0/0.000278 ≈ 3597s
        idle_period = node._cam_timer.period
        self.assertAlmostEqual(idle_period, 1.0 / 0.000278, delta=5.0)
        node.destroy_node()

    def test_ramp_up_on_subscriber(self):
        """When subscriber connects, node transitions to active at 1.0 fps."""
        node = self._make_node()
        node._cam_pub._sub_count = 1
        node.capture_and_publish()
        self.assertTrue(node._is_active)
        self.assertAlmostEqual(node._cam_timer.period, 1.0, places=3)
        node.destroy_node()

    def test_stays_active_while_subscribed(self):
        """Stays active on subsequent ticks while subscriber is present."""
        node = self._make_node()
        node._cam_pub._sub_count = 1
        node.capture_and_publish()
        timer_count_after_ramp = len(node._timers)
        node.capture_and_publish()
        self.assertTrue(node._is_active)
        # No extra timers created on subsequent active ticks
        self.assertEqual(len(node._timers), timer_count_after_ramp)
        node.destroy_node()

    def test_new_params_declared(self):
        """camera_active_fps and camera_subscriber_grace_sec are declared as parameters."""
        node = self._make_node()
        self.assertIn('camera_active_fps', node._params)
        self.assertIn('camera_subscriber_grace_sec', node._params)
        node.destroy_node()


class TestSubscriberGracePeriod(unittest.TestCase):
    """Tests for grace period before dropping to idle (CAM-03)."""

    def _make_active_node(self):
        """Create FcCamera, ramp it up to active state."""
        fc_camera = _load_fc_camera()
        mock_cv2 = MagicMock()
        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_params({
                'camera_simulation_mode': True,
                'camera_active_fps': 1.0,
                'camera_subscriber_grace_sec': 5.0,
            }):
                node = fc_camera.FcCamera()
        node._cam_pub._sub_count = 1
        node.capture_and_publish()
        return node

    def test_grace_starts_on_unsub(self):
        """Grace timer created when last subscriber disconnects; node stays active."""
        node = self._make_active_node()
        node._cam_pub._sub_count = 0
        node.capture_and_publish()
        self.assertIsNotNone(node._grace_timer)
        self.assertTrue(node._is_active)  # still active, grace period running
        node.destroy_node()

    def test_grace_expires_drops_to_idle(self):
        """After grace timer fires with no subscribers, node drops to idle."""
        node = self._make_active_node()
        node._cam_pub._sub_count = 0
        node.capture_and_publish()
        # Fire the grace timer callback manually
        node._grace_timer.callback()
        self.assertFalse(node._is_active)
        self.assertIsNone(node._grace_timer)
        node.destroy_node()

    def test_resub_cancels_grace(self):
        """If subscriber reconnects during grace period, grace is cancelled."""
        node = self._make_active_node()
        node._cam_pub._sub_count = 0
        node.capture_and_publish()  # starts grace
        node._cam_pub._sub_count = 1
        node.capture_and_publish()  # subscriber back
        self.assertIsNone(node._grace_timer)
        self.assertTrue(node._is_active)
        node.destroy_node()

    def test_destroy_node_cleans_grace(self):
        """destroy_node removes grace timer without error."""
        node = self._make_active_node()
        node._cam_pub._sub_count = 0
        node.capture_and_publish()  # starts grace
        grace_timer = node._grace_timer
        self.assertIsNotNone(grace_timer)
        node.destroy_node()  # must not raise
        # Grace timer should have been removed from _timers
        self.assertNotIn(grace_timer, node._timers)


class TestIdleToActiveRecovery(unittest.TestCase):
    """Phase 14 regression: recover from writer-cache stale idle stalls.

    Reproduces the 2026-04-17 bug where fc_camera's publisher.get_subscription_count()
    read 0 while node.count_subscribers() saw the bridge subscription on the DDS graph.
    The fix must poll both and ramp up when EITHER says viewer-present.
    """

    TOPIC = 'fc1/camera/compressed'

    def _make_node(self):
        fc_camera = _load_fc_camera()
        mock_cv2 = MagicMock()
        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_params({
                'camera_simulation_mode': True,
                'camera_fps': 0.000278,
                'camera_active_fps': 1.0,
                'camera_subscriber_grace_sec': 5.0,
            }):
                node = fc_camera.FcCamera()
        return node

    def _fire_graph_poll(self, node):
        """Find and fire the 1 Hz graph-poll timer callback.

        The fix creates a dedicated timer whose period is 1.0 seconds and
        whose callback is node._graph_poll (or equivalent). Locate it by
        period and invoke its callback directly — faster-than-realtime.
        """
        graph_timers = [t for t in node._timers
                        if t.period is not None and abs(t.period - 1.0) < 1e-6
                        and t is not node._cam_timer]
        self.assertEqual(len(graph_timers), 1,
                         "Expected exactly one 1 Hz graph-poll timer (found {})".format(len(graph_timers)))
        graph_timers[0].callback()

    def test_node_level_sub_count_drives_ramp_up(self):
        """Stale writer cache (FakePublisher._sub_count=0) but live graph cache (=1) ramps up."""
        node = self._make_node()
        # Simulate DDS asymmetry: writer-local cache stale, node-level cache live
        node._cam_pub._sub_count = 0
        node._node_sub_count[self.TOPIC] = 1
        self._fire_graph_poll(node)
        self.assertTrue(node._is_active,
                        "fc_camera must ramp up when node.count_subscribers reports a viewer "
                        "even if publisher.get_subscription_count is stale at 0")
        self.assertAlmostEqual(node._cam_timer.period, 1.0, places=3)
        node.destroy_node()

    def test_long_idle_then_graph_sees_sub_ramps_up(self):
        """10 idle ticks with both caches 0, then graph cache sees viewer — ramp up on next poll."""
        node = self._make_node()
        node._cam_pub._sub_count = 0
        node._node_sub_count[self.TOPIC] = 0
        for _ in range(10):
            node.capture_and_publish()
        self.assertFalse(node._is_active)
        # Bridge subscribes — only node-level cache updates; writer cache remains stale (the bug)
        node._node_sub_count[self.TOPIC] = 1
        self._fire_graph_poll(node)
        self.assertTrue(node._is_active)
        node.destroy_node()

    def test_happy_path_both_caches_agree(self):
        """When both caches report the same count, Phase-12 behaviour is unchanged."""
        node = self._make_node()
        # Normal ramp-up: both say 1
        node._cam_pub._sub_count = 1
        node._node_sub_count[self.TOPIC] = 1
        node.capture_and_publish()
        self.assertTrue(node._is_active)
        # Normal ramp-down path (grace) via capture_and_publish: both say 0
        node._cam_pub._sub_count = 0
        node._node_sub_count[self.TOPIC] = 0
        node.capture_and_publish()
        self.assertIsNotNone(node._grace_timer,
                             "Grace timer must start when both caches say 0")
        node.destroy_node()


if __name__ == '__main__':
    unittest.main()
