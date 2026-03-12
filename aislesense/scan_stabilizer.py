#!/usr/bin/env python3
"""
Scan Stabilizer Node
====================
Resamples incoming RPLidar scans from a variable beam count to a fixed
720-beam output via nearest-neighbour lookup.  Invalid readings (inf, NaN,
out-of-range) are preserved as ``inf`` so that downstream consumers such
as SLAM Toolbox and Nav2 costmaps never see phantom obstacles.

Subscribed Topics:
    /scan         (sensor_msgs/LaserScan) — Raw LiDAR scan.

Published Topics:
    /scan_stable  (sensor_msgs/LaserScan) — Fixed-beam-count scan.

Configure SLAM Toolbox and Nav2 costmaps to subscribe to ``/scan_stable``
instead of ``/scan`` for consistent angular resolution.
"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from sensor_msgs.msg import LaserScan
import numpy as np

# QoS profile matching the rplidar_node publisher (BEST_EFFORT, VOLATILE)
SENSOR_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5
)


class ScanStabilizer(Node):
    def __init__(self):
        super().__init__('scan_stabilizer')

        # Target output beam count (720 beams = 0.5° angular resolution)
        self.target_beams = 720

        self.sub = self.create_subscription(LaserScan, '/scan', self.scan_cb, SENSOR_QOS)
        self.pub = self.create_publisher(LaserScan, '/scan_stable', SENSOR_QOS)

        self.get_logger().info(
            f'Scan Stabilizer: resampling /scan -> /scan_stable ({self.target_beams} beams, 0.5° resolution)')

    def scan_cb(self, msg: LaserScan):
        n_in = len(msg.ranges)
        if n_in < 2:
            return

        ranges_in = np.array(msg.ranges, dtype=np.float32)

        # Mark invalid readings — these must remain invalid in the output
        valid = np.isfinite(ranges_in) & (ranges_in >= msg.range_min) & (ranges_in <= msg.range_max)

        # Build uniform input and output angle arrays
        angles_in = np.linspace(msg.angle_min, msg.angle_max, n_in)
        angles_out = np.linspace(msg.angle_min, msg.angle_max, self.target_beams)

        # Nearest-neighbour resampling (avoids interpolation through invalid zones)
        # For each output angle, pick the closest input beam
        indices = np.searchsorted(angles_in, angles_out, side='left')
        indices = np.clip(indices, 0, n_in - 1)

        # Check the neighbour on the other side and pick the actual closest
        left_idx = np.clip(indices - 1, 0, n_in - 1)
        use_left = np.abs(angles_in[left_idx] - angles_out) < np.abs(angles_in[indices] - angles_out)
        nearest = np.where(use_left, left_idx, indices)

        ranges_out = ranges_in[nearest]
        valid_out = valid[nearest]

        # Invalid input beams map to inf in the output (ignored by SLAM)
        ranges_out[~valid_out] = float('inf')

        # Intensities: nearest-neighbour mapping
        if len(msg.intensities) == n_in:
            intensities_in = np.array(msg.intensities, dtype=np.float32)
            intensities_out = intensities_in[nearest]
        else:
            intensities_out = np.zeros(self.target_beams, dtype=np.float32)

        # Build stabilized message
        out = LaserScan()
        out.header = msg.header
        out.angle_min = msg.angle_min
        out.angle_max = msg.angle_max
        out.angle_increment = (msg.angle_max - msg.angle_min) / (self.target_beams - 1)
        out.time_increment = msg.time_increment * (n_in / self.target_beams) if msg.time_increment > 0 else 0.0
        out.scan_time = msg.scan_time
        out.range_min = msg.range_min
        out.range_max = msg.range_max
        out.ranges = ranges_out.tolist()
        out.intensities = intensities_out.tolist()

        self.pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = ScanStabilizer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
