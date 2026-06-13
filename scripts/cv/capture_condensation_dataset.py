#!/usr/bin/env python3
"""Condensation dataset capture harness (SEED-005 source #3, Stage A).

Standalone rclpy tool that subscribes to the fc1 camera + sensor + control
topics, subsamples the camera stream, and writes a labeled-ready dataset:
raw JPEG frames + a per-frame manifest CSV pairing each frame with the
telemetry context at capture time.

DESIGN NOTES (see .planning/notes/2026-06-13-cv-condensation-detection-plan.md §6):
  - SPIKE INSTRUMENTATION. Deliberately NOT part of the fc_core ROS package and
    it does NOT touch the production snapshot/retention pipeline. It is just a
    viewer + writer.
  - Subscribing to fc1/camera/compressed makes us a viewer, so fc_camera ramps
    from idle to camera_active_fps (~1 fps). We subsample that to --interval-sec.
  - The four control topics are published with TRANSIENT_LOCAL + RELIABLE +
    KEEP_LAST(1). The subscriber MUST match that QoS to receive the latched last
    value (a default volatile sub gets nothing until the next publish, which for
    a latched mode topic may be never). Sensor + camera topics are default
    volatile depth-10 -> default sub is fine.
  - Never crash on a bad frame (log + skip). Flush the manifest every row.
    On SIGINT write a run summary. Dark frames are recorded + flagged, never
    silently dropped (paper trail / gap-over-noise).

RUN (on fc1, with DDS env):
  RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=... ROS_DOMAIN_ID=69 \
    python3 scripts/cv/capture_condensation_dataset.py \
      --out-dir /home/ubuntu/condensation-dataset --run-id passive-01 \
      --duration-min 0 --interval-sec 15
"""

import argparse
import csv
import os
import signal
import sys
from datetime import datetime, timezone

import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy

from sensor_msgs.msg import CompressedImage, Temperature, RelativeHumidity
from std_msgs.msg import Float32, String

try:
    import cv2
except ImportError:  # pragma: no cover - cv2 is present on fc1
    print('FATAL: OpenCV (cv2) is required. On fc1 it ships with the camera node deps.',
          file=sys.stderr)
    sys.exit(2)


# Manifest columns. `label` is left blank for Stage B (human/auto labeling).
MANIFEST_FIELDS = [
    'ts_iso', 'frame_file',
    'rh1', 'rh2', 'temp1', 'temp2', 'co2',
    'rh_target', 'duty', 'mode', 'experiment',
    'mean_luma', 'dark_flag', 'label',
]


def iso_now():
    """ISO-8601 UTC with Z suffix, filesystem-safe (matches snapshot convention)."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S-%fZ')


def lens_circle_luma(gray, cx_frac, cy_frac, r_frac):
    """Mean grayscale over the central lens-circle ROI.

    The macro lens vignettes to a central disc (black corners), so luma must be
    measured inside the disc, not over the full frame, or the dark corners drag
    the mean down. Center/radius are fractions of frame size; defaults assume a
    centered disc filling the short axis (refine once framing is final, §8).
    """
    h, w = gray.shape[:2]
    cx, cy = int(w * cx_frac), int(h * cy_frac)
    r = int(min(w, h) * r_frac)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, (cx, cy), r, 255, -1)
    return float(cv2.mean(gray, mask=mask)[0])


class CondensationCapture(Node):
    def __init__(self, args):
        super().__init__('condensation_capture')
        self.args = args

        # Output layout: <out-dir>/<run-id>/frames/*.jpg + manifest.csv
        self.run_dir = os.path.join(args.out_dir, args.run_id)
        self.frames_dir = os.path.join(self.run_dir, 'frames')
        os.makedirs(self.frames_dir, exist_ok=True)
        manifest_path = os.path.join(self.run_dir, 'manifest.csv')
        new_file = not os.path.exists(manifest_path)
        # Append mode so a resumed run on the same run-id keeps the paper trail.
        self._manifest_fh = open(manifest_path, 'a', newline='')
        self._writer = csv.DictWriter(self._manifest_fh, fieldnames=MANIFEST_FIELDS)
        if new_file:
            self._writer.writeheader()
            self._manifest_fh.flush()

        # Latest-value caches for each non-camera topic.
        self._rh1 = self._rh2 = None
        self._temp1 = self._temp2 = None
        self._co2 = None
        self._target = self._duty = None
        self._mode = ''
        self._experiment = ''

        # Run-summary accumulators.
        self._saved = 0
        self._decode_errors = 0
        self._dark = 0
        self._luma_min = None
        self._luma_max = None
        self._rh_min = None
        self._rh_max = None
        self._started_iso = iso_now()
        self._last_save_t = None  # monotonic seconds of last saved frame

        # Default volatile QoS for sensor + camera topics (depth-10).
        sensor_qos = 10

        # Must match the controller's actuator_qos to receive latched last values.
        latched_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )

        # Camera — the frame source. Subscribing ramps fc_camera to active fps.
        self.create_subscription(CompressedImage, 'fc1/camera/compressed',
                                 self._on_frame, sensor_qos)

        # Sensors (dual RH + dual temp + co2).
        self.create_subscription(RelativeHumidity, 'fc1/humidity',
                                 lambda m: setattr(self, '_rh1', m.relative_humidity), sensor_qos)
        self.create_subscription(RelativeHumidity, 'fc1/humidity_2',
                                 lambda m: setattr(self, '_rh2', m.relative_humidity), sensor_qos)
        self.create_subscription(Temperature, 'fc1/temperature',
                                 lambda m: setattr(self, '_temp1', m.temperature), sensor_qos)
        self.create_subscription(Temperature, 'fc1/temperature_2',
                                 lambda m: setattr(self, '_temp2', m.temperature), sensor_qos)
        self.create_subscription(Float32, 'fc1/co2',
                                 lambda m: setattr(self, '_co2', m.data), sensor_qos)

        # Control / actuator (latched).
        self.create_subscription(Float32, 'fc1/control/humidity_target',
                                 lambda m: setattr(self, '_target', m.data), latched_qos)
        self.create_subscription(Float32, 'fc1/actuators/humidifier_duty',
                                 lambda m: setattr(self, '_duty', m.data), latched_qos)
        self.create_subscription(String, 'fc1/control/current_mode_json',
                                 lambda m: setattr(self, '_mode', m.data), latched_qos)
        self.create_subscription(String, 'fc1/control/experiment_event',
                                 lambda m: setattr(self, '_experiment', m.data), latched_qos)

        # Optional wall-clock duration cutoff.
        self._deadline = None
        if args.duration_min and args.duration_min > 0:
            self._deadline = self.get_clock().now().nanoseconds + int(args.duration_min * 60 * 1e9)

        self.get_logger().info(
            f'condensation_capture: run={args.run_id} out={self.run_dir} '
            f'interval={args.interval_sec}s duration={"until Ctrl-C" if not self._deadline else str(args.duration_min)+"min"} '
            f'min_luma={args.min_luma}'
        )

    def _on_frame(self, msg):
        now = self.get_clock().now().nanoseconds / 1e9

        # Duration cutoff.
        if self._deadline is not None and self.get_clock().now().nanoseconds >= self._deadline:
            self.get_logger().info('condensation_capture: duration reached, shutting down.')
            raise KeyboardInterrupt

        # Subsample the ~1fps stream to --interval-sec.
        if self._last_save_t is not None and (now - self._last_save_t) < self.args.interval_sec:
            return

        try:
            buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)
            gray = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
            if gray is None:
                raise ValueError('imdecode returned None')
        except Exception as e:  # never crash on a bad frame
            self._decode_errors += 1
            self.get_logger().warn(f'frame decode failed (skipping): {e}')
            return

        luma = lens_circle_luma(gray, self.args.roi_cx, self.args.roi_cy, self.args.roi_r)
        dark = 1 if luma < self.args.min_luma else 0

        ts = iso_now()
        frame_file = f'{ts}.jpg'
        frame_path = os.path.join(self.frames_dir, frame_file)
        try:
            # Persist the ORIGINAL compressed bytes (no re-encode) so we keep the
            # exact frame the model will later see; ROI crop happens at train time.
            with open(frame_path, 'wb') as fh:
                fh.write(bytes(msg.data))
        except Exception as e:
            self.get_logger().warn(f'frame write failed (skipping): {e}')
            return

        self._writer.writerow({
            'ts_iso': ts,
            'frame_file': frame_file,
            'rh1': _fmt(self._rh1), 'rh2': _fmt(self._rh2),
            'temp1': _fmt(self._temp1), 'temp2': _fmt(self._temp2),
            'co2': _fmt(self._co2),
            'rh_target': _fmt(self._target), 'duty': _fmt(self._duty),
            'mode': self._mode, 'experiment': self._experiment,
            'mean_luma': f'{luma:.1f}', 'dark_flag': dark, 'label': '',
        })
        self._manifest_fh.flush()

        # Update accumulators.
        self._last_save_t = now
        self._saved += 1
        if dark:
            self._dark += 1
        self._luma_min = luma if self._luma_min is None else min(self._luma_min, luma)
        self._luma_max = luma if self._luma_max is None else max(self._luma_max, luma)
        for rh in (self._rh1, self._rh2):
            if rh is not None:
                self._rh_min = rh if self._rh_min is None else min(self._rh_min, rh)
                self._rh_max = rh if self._rh_max is None else max(self._rh_max, rh)

        if self._saved % 20 == 0:
            self.get_logger().info(
                f'saved={self._saved} dark={self._dark} '
                f'luma=[{self._luma_min:.0f}..{self._luma_max:.0f}] last_rh1={_fmt(self._rh1)}'
            )

    def write_summary(self):
        summary_path = os.path.join(self.run_dir, 'run-summary.txt')
        lines = [
            f'run_id:        {self.args.run_id}',
            f'started:       {self._started_iso}',
            f'ended:         {iso_now()}',
            f'frames_saved:  {self._saved}',
            f'decode_errors: {self._decode_errors}',
            f'dark_frames:   {self._dark}' + (
                f' ({100*self._dark/self._saved:.0f}%)' if self._saved else ''),
            f'luma_range:    {self._fmt_range(self._luma_min, self._luma_max)}',
            f'rh_range:      {self._fmt_range(self._rh_min, self._rh_max)}',
            f'interval_sec:  {self.args.interval_sec}',
            f'min_luma:      {self.args.min_luma}',
        ]
        text = '\n'.join(lines) + '\n'
        try:
            with open(summary_path, 'w') as fh:
                fh.write(text)
        except Exception as e:
            self.get_logger().warn(f'summary write failed: {e}')
        self.get_logger().info('run summary:\n' + text)

    @staticmethod
    def _fmt_range(lo, hi):
        if lo is None or hi is None:
            return 'n/a (no data)'
        return f'{lo:.2f}..{hi:.2f}'

    def close(self):
        try:
            self._manifest_fh.flush()
            self._manifest_fh.close()
        except Exception:
            pass


def _fmt(v):
    """Manifest cell formatter: blank for missing, else trimmed number/string."""
    if v is None:
        return ''
    if isinstance(v, float):
        return f'{v:.4f}'
    return str(v)


def parse_args(argv):
    p = argparse.ArgumentParser(description='Condensation dataset capture harness (SEED-005 Stage A).')
    p.add_argument('--out-dir', required=True, help='Base output directory (run-id subdir created under it).')
    p.add_argument('--run-id', required=True, help='Run identifier; names the dataset subdir.')
    p.add_argument('--duration-min', type=float, default=0.0, help='Wall-clock cutoff in minutes (0 = until Ctrl-C).')
    p.add_argument('--interval-sec', type=float, default=15.0, help='Min seconds between saved frames (subsamples the ~1fps stream).')
    p.add_argument('--min-luma', type=float, default=30.0, help='mean_luma below this flags a frame dark (still recorded).')
    # Lens-circle ROI as fractions of frame W/H. Defaults = centered disc on short axis.
    p.add_argument('--roi-cx', type=float, default=0.5, help='Lens-circle center x (fraction of width).')
    p.add_argument('--roi-cy', type=float, default=0.5, help='Lens-circle center y (fraction of height).')
    p.add_argument('--roi-r', type=float, default=0.5, help='Lens-circle radius (fraction of min(W,H)).')
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rclpy.init()
    node = CondensationCapture(args)

    # Clean SIGINT/SIGTERM -> summary + flush.
    def _stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('condensation_capture: stopping (signal).')
    finally:
        node.write_summary()
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
