#!/usr/bin/env python3
"""
Scan Stabilizer Node — fixes inconsistent RPLidar beam counts.

Subscribes to /scan, resamples to a fixed number of beams via
nearest-neighbour lookup, and republishes on /scan_stable.
Invalid readings stay invalid (inf) so SLAM never sees phantom walls.

Point SLAM Toolbox and Nav2 costmaps at /scan_stable instead of /scan.
"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from sensor_msgs.msg import LaserScan
import numpy as np

# QoS matching sensor data convention (BEST_EFFORT) — MUST match rplidar_node's publisher
SENSOR_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5
)


class ScanStabilizer(Node):
    def __init__(self):
        super().__init__('scan_stabilizer')

        # Fixed output beam count (RPLidar Express mode ~500+/rev, standardize to 720 = 0.5° resolution)
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

        # Mark invalid readings (inf, nan, out-of-range) — these MUST stay invalid
        valid = np.isfinite(ranges_in) & (ranges_in >= msg.range_min) & (ranges_in <= msg.range_max)

        # Build input/output angle arrays
        angles_in = np.linspace(msg.angle_min, msg.angle_max, n_in)
        angles_out = np.linspace(msg.angle_min, msg.angle_max, self.target_beams)

        # ---- Nearest-neighbour resampling (no interpolation through invalid zones) ----
        # For each output angle, pick the closest input beam
        indices = np.searchsorted(angles_in, angles_out, side='left')
        indices = np.clip(indices, 0, n_in - 1)

        # Check the neighbour on the other side and pick the actual closest
        left_idx = np.clip(indices - 1, 0, n_in - 1)
        use_left = np.abs(angles_in[left_idx] - angles_out) < np.abs(angles_in[indices] - angles_out)
        nearest = np.where(use_left, left_idx, indices)

        ranges_out = ranges_in[nearest]
        valid_out = valid[nearest]

        # Invalid input beams → inf in output (SLAM correctly ignores these)
        ranges_out[~valid_out] = float('inf')

        # Intensities: nearest-neighbour too
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
