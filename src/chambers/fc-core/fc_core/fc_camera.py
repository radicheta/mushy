#!/usr/bin/env python3
"""ROS2 camera node for fruiting chamber.

Captures frames from a USB webcam via OpenCV and publishes compressed JPEG
images to the fc1/camera/compressed topic. Follows the exact same pattern as
fc_sensors.py -- timer-based, config-driven, non-blocking.

Pi prerequisite: sudo apt install python3-opencv
Verify: python3 -c "import cv2; print(cv2.__version__)"
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage


class FcCamera(Node):
    """Capture frames from a USB webcam and publish as CompressedImage."""

    def __init__(self):
        super().__init__('fc_camera')

        # Declare parameters with conservative defaults
        self.declare_parameters(
            namespace='',
            parameters=[
                ('camera_simulation_mode', False),
                ('camera_device', 0),
                ('camera_width', 640),    # D-05: 640x480 default
                ('camera_height', 480),
                ('camera_fps', 1.0),      # D-02: idle rate — 1 frame/hour when no viewers
                ('camera_jpeg_quality', 65),  # D-06: 60-70% default
                ('camera_active_fps', 1.0),           # D-01: FPS when Mission Control viewers connected
                ('camera_subscriber_grace_sec', 5.0),  # D-07: seconds before dropping to idle after last viewer
            ]
        )

        self.cap = None
        simulation_mode = self.get_parameter('camera_simulation_mode').value
        device = self.get_parameter('camera_device').value
        width = self.get_parameter('camera_width').value
        height = self.get_parameter('camera_height').value
        fps = self.get_parameter('camera_fps').value
        self._jpeg_quality = self.get_parameter('camera_jpeg_quality').value
        self._idle_fps = fps  # camera_fps is now the idle rate (D-03)
        self._active_fps = self.get_parameter('camera_active_fps').value
        self._grace_sec = self.get_parameter('camera_subscriber_grace_sec').value
        self._is_active = False
        self._grace_timer = None

        if simulation_mode:
            self.get_logger().info('fc_camera: running in simulation mode (no USB webcam)')
        else:
            # Lazy import: OpenCV is a system package (python3-opencv) on the Pi.
            # Importing here rather than at module level avoids ImportError on
            # machines where OpenCV is not installed (e.g., dev workstations).
            import cv2  # noqa: F401 -- available on Pi via apt
            self.cap = cv2.VideoCapture(device)
            if not self.cap.isOpened():
                # Camera unavailable: log warning but never crash. Timer ticks
                # will be no-ops until the camera becomes available (or node restart).
                self.get_logger().warn(
                    f'fc_camera: camera device {device!r} not available '
                    f'(VideoCapture.isOpened()=False). Capture will be skipped.'
                )
            else:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.get_logger().info(
                    f'fc_camera: opened /dev/video{device} at {width}x{height} '
                    f'{fps}fps quality={self._jpeg_quality}'
                )

        # Topic name — used by both the publisher and the graph-poll fallback
        # (Phase 14 fix for Phase 12 stall: writer-local matched-readers cache goes
        # stale over CycloneDDS unicast on Tailscale; node-level graph cache does not.
        # See 14-RESEARCH.md §1 H1.)
        self._camera_topic = 'fc1/camera/compressed'

        # Publisher for compressed images
        self._cam_pub = self.create_publisher(
            CompressedImage, self._camera_topic, 10
        )

        # Timer fires at the idle FPS rate; ramps up when subscribers connect
        self._cam_timer = self.create_timer(1.0 / self._idle_fps, self.capture_and_publish)

        # Phase 14 (HFIX-01): fast-path viewer detection via node-level graph cache.
        # The capture timer runs at idle rate (~1/hr in production) so cannot recover
        # the feed within the 10 s MC LIVE-badge SLA. This dedicated 1 Hz timer polls
        # self.count_subscribers() which reads the rcl/rmw graph cache — a different
        # cache from publisher.get_subscription_count()'s writer-local matched-readers
        # set (the latter goes stale over lossy unicast DDS).
        self._graph_poll_timer = self.create_timer(1.0, self._graph_poll)

        self.get_logger().info(
            f'FcCamera node started (idle: {self._idle_fps} fps, '
            f'active: {self._active_fps} fps, grace: {self._grace_sec}s)'
        )

    def _graph_poll(self):
        """1 Hz subscriber-presence check via node-level graph introspection.

        Complements the writer-local get_subscription_count() polling inside
        capture_and_publish. If the writer's matched-readers cache goes stale
        (see 14-RESEARCH.md §1 H1), this path still detects the viewer and
        ramps up within ~1 second.

        Cheap: one rclpy call, no capture, no publish. Safe to run at 1 Hz.
        """
        if self._is_active:
            # Already active — writer-cache or graph-cache agreement doesn't matter.
            # If a subscriber leaves, capture_and_publish handles the grace-period
            # transition via its own get_subscription_count() check.
            return
        try:
            n = self.count_subscribers(self._camera_topic)
        except Exception as e:
            # Never crash the node on an introspection hiccup — log and retry next tick.
            self.get_logger().warn(f'fc_camera: graph poll failed: {e}')
            return
        if n > 0:
            self._ramp_up()

    def capture_and_publish(self):
        """Capture one frame and publish as CompressedImage.

        Checks subscriber count on every tick to switch between idle and active
        rates. No-op capture if cap is None (simulation mode) or camera is not open.
        Wraps all cv2 calls in try/except to never crash the node.
        """
        writer_count = self._cam_pub.get_subscription_count()
        try:
            graph_count = self.count_subscribers(self._camera_topic)
        except Exception:
            graph_count = 0
        count = writer_count if writer_count > 0 else graph_count  # prefer live count
        if count > 0 and not self._is_active:
            self._ramp_up()
        elif count > 0 and self._is_active and self._grace_timer is not None:
            # Subscriber reconnected during grace — cancel grace, stay active
            self.destroy_timer(self._grace_timer)
            self._grace_timer = None
        elif count == 0 and self._is_active and self._grace_timer is None:
            self._start_grace()

        if self.cap is None or not self.cap.isOpened():
            return

        try:
            import cv2

            ret, frame = self.cap.read()
            if not ret:
                self.get_logger().warn('fc_camera: cap.read() failed, skipping frame')
                return

            ok, buf = cv2.imencode(
                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
            )
            if not ok:
                self.get_logger().warn('fc_camera: imencode failed, skipping frame')
                return

            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = 'jpeg'
            msg.data = buf.tobytes()

            self._cam_pub.publish(msg)

        except Exception as e:
            # Non-blocking: log and skip frame. Next timer tick retries automatically.
            self.get_logger().error(f'fc_camera: capture_and_publish error: {e}')

    def _ramp_up(self):
        """Switch from idle to active rate (per D-05)."""
        if self._grace_timer is not None:
            self.destroy_timer(self._grace_timer)
            self._grace_timer = None
        self.destroy_timer(self._cam_timer)
        self._cam_timer = self.create_timer(1.0 / self._active_fps, self.capture_and_publish)
        self._is_active = True
        self.get_logger().info(
            f'fc_camera: active ({self._active_fps} fps, '
            f'writer={self._cam_pub.get_subscription_count()} '
            f'graph={self.count_subscribers(self._camera_topic)} subscriber(s))'
        )

    def _start_grace(self):
        """Begin grace period before dropping to idle (per D-06, D-07)."""
        self._grace_timer = self.create_timer(self._grace_sec, self._grace_expired)

    def _grace_expired(self):
        """Grace period elapsed — drop to idle if still no subscribers."""
        self.destroy_timer(self._grace_timer)
        self._grace_timer = None
        if self._cam_pub.get_subscription_count() == 0:
            self._ramp_down()

    def _ramp_down(self):
        """Switch from active to idle rate."""
        self.destroy_timer(self._cam_timer)
        self._cam_timer = self.create_timer(1.0 / self._idle_fps, self.capture_and_publish)
        self._is_active = False
        self.get_logger().info(f'fc_camera: idle ({self._idle_fps} fps)')

    def destroy_node(self):
        """Release the VideoCapture handle and clean up timers before shutting down."""
        if self._grace_timer is not None:
            self.destroy_timer(self._grace_timer)
            self._grace_timer = None
        if hasattr(self, '_graph_poll_timer') and self._graph_poll_timer is not None:
            self.destroy_timer(self._graph_poll_timer)
            self._graph_poll_timer = None
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FcCamera()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
