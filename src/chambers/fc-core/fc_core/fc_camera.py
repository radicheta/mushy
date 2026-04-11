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
                ('camera_fps', 1.0),      # D-04: float — supports sub-1 for cellular thrift (e.g. 0.0167 ≈ 1 frame/min)
                ('camera_jpeg_quality', 65),  # D-06: 60-70% default
            ]
        )

        self.cap = None
        simulation_mode = self.get_parameter('camera_simulation_mode').value
        device = self.get_parameter('camera_device').value
        width = self.get_parameter('camera_width').value
        height = self.get_parameter('camera_height').value
        fps = self.get_parameter('camera_fps').value
        self._jpeg_quality = self.get_parameter('camera_jpeg_quality').value

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

        # Publisher for compressed images
        self._cam_pub = self.create_publisher(
            CompressedImage, 'fc1/camera/compressed', 10
        )

        # Timer fires at the requested FPS rate
        self.create_timer(1.0 / fps, self.capture_and_publish)

        self.get_logger().info('FcCamera node started')

    def capture_and_publish(self):
        """Capture one frame and publish as CompressedImage.

        No-op if cap is None (simulation mode) or camera is not open.
        Wraps all cv2 calls in try/except to never crash the node.
        """
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

    def destroy_node(self):
        """Release the VideoCapture handle before shutting down."""
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
