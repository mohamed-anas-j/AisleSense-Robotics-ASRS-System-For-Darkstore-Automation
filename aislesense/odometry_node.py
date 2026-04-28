#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Quaternion
import math

class OdometryNode(Node):
    def __init__(self):
        super().__init__('odometry_node')
        
        # --- Robot Physical Parameters (all ROS2 params — tunable without code change) ---
        self.declare_parameter('wheel_radius', 0.05)
        self.declare_parameter('wheel_base', 0.25)
        self.declare_parameter('ticks_per_rev', 1170.0)
        # Correction factors: measure 1m in real life, see what odom reports, adjust.
        # e.g., if odom says 0.5m for a real 1m push, set linear_correction to 2.0
        self.declare_parameter('linear_correction', 1.0)
        self.declare_parameter('angular_correction', 1.0)
        
        self.wheel_radius = self.get_parameter('wheel_radius').value
        self.wheel_base = self.get_parameter('wheel_base').value
        self.ticks_per_rev = self.get_parameter('ticks_per_rev').value
        self.linear_correction = self.get_parameter('linear_correction').value
        self.angular_correction = self.get_parameter('angular_correction').value
        
        # Precompute and log for easy verification
        self.meters_per_tick = (2.0 * math.pi * self.wheel_radius) / self.ticks_per_rev
        self.get_logger().info(
            f"Wheel radius: {self.wheel_radius}m | Wheel base: {self.wheel_base}m | "
            f"Ticks/rev: {self.ticks_per_rev} | Meters/tick: {self.meters_per_tick:.6f} | "
            f"Linear correction: {self.linear_correction} | Angular correction: {self.angular_correction}")
        
        # --- State Variables ---
        self.x = 0.0
        self.y = 0.0
        self.th = 0.0
        
        self.last_left_ticks = 0
        self.last_right_ticks = 0
        self.last_time = self.get_clock().now()
        self.first_reading = True
        self.total_distance = 0.0  # For calibration logging
        self.log_counter = 0

        # --- Encoder Health Monitoring ---
        self.left_tick_accumulator = 0
        self.right_tick_accumulator = 0
        self.health_window_counter = 0
        self.HEALTH_WINDOW = 50  # Check every 50 updates (1s at 50Hz)
        self.left_encoder_healthy = True
        self.right_encoder_healthy = True
        # Max reasonable ticks per update (spike rejection)
        self.max_ticks_per_update = max(int(0.015 / self.meters_per_tick), 50)

        # --- Publishers & Subscribers ---
        self.odom_pub = self.create_publisher(Odometry, 'odom', 10)
        
        self.create_subscription(Int32, 'left_ticks', self.left_ticks_callback, 10)
        self.create_subscription(Int32, 'right_ticks', self.right_ticks_callback, 10)
        
        self.current_left_ticks = 0
        self.current_right_ticks = 0
        
        self.timer = self.create_timer(0.02, self.update_odometry)
        self.get_logger().info("Odometry Node Started (TF Disabled for EKF)!")

    def left_ticks_callback(self, msg):
        self.current_left_ticks = msg.data

    def right_ticks_callback(self, msg):
        self.current_right_ticks = msg.data

    @staticmethod
    def normalize_angle(angle):
        """Wrap angle to [-pi, pi]."""
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle

    def update_odometry(self):
        current_time = self.get_clock().now()
        dt = (current_time - self.last_time).nanoseconds / 1e9

        if dt <= 0 or self.first_reading:
            self.last_time = current_time
            self.last_left_ticks = self.current_left_ticks
            self.last_right_ticks = self.current_right_ticks
            self.first_reading = False
            return

        delta_left = self.current_left_ticks - self.last_left_ticks
        delta_right = self.current_right_ticks - self.last_right_ticks

        # --- Spike rejection: clamp unreasonable tick deltas ---
        delta_left = max(-self.max_ticks_per_update, min(self.max_ticks_per_update, delta_left))
        delta_right = max(-self.max_ticks_per_update, min(self.max_ticks_per_update, delta_right))

        # --- Encoder health monitoring ---
        self.left_tick_accumulator += abs(delta_left)
        self.right_tick_accumulator += abs(delta_right)
        self.health_window_counter += 1

        if self.health_window_counter >= self.HEALTH_WINDOW:
            total = self.left_tick_accumulator + self.right_tick_accumulator
            if total > 50:  # Only evaluate health during significant movement
                self.left_encoder_healthy = (self.left_tick_accumulator / total) > 0.1
                self.right_encoder_healthy = (self.right_tick_accumulator / total) > 0.1
                if not self.left_encoder_healthy or not self.right_encoder_healthy:
                    self.get_logger().warn(
                        f"[ENCODER HEALTH] L={'OK' if self.left_encoder_healthy else 'STUCK'} "
                        f"({self.left_tick_accumulator}) | "
                        f"R={'OK' if self.right_encoder_healthy else 'STUCK'} "
                        f"({self.right_tick_accumulator}) — "
                        f"fallback: mirroring good encoder, heading delegated to IMU",
                        throttle_duration_sec=5.0)
            else:
                # Not enough movement to judge — assume healthy
                self.left_encoder_healthy = True
                self.right_encoder_healthy = True
            self.left_tick_accumulator = 0
            self.right_tick_accumulator = 0
            self.health_window_counter = 0

        # --- Encoder fallback: if one encoder is stuck, mirror the good one ---
        if self.left_encoder_healthy and self.right_encoder_healthy:
            # Both healthy: normal differential drive
            d_left = delta_left * self.meters_per_tick * self.linear_correction
            d_right = delta_right * self.meters_per_tick * self.linear_correction
        elif self.left_encoder_healthy:
            # Right encoder stuck: use left for both (assume straight motion)
            d_left = delta_left * self.meters_per_tick * self.linear_correction
            d_right = d_left
        elif self.right_encoder_healthy:
            # Left encoder stuck: use right for both
            d_right = delta_right * self.meters_per_tick * self.linear_correction
            d_left = d_right
        else:
            # Both stuck: no movement
            d_left = 0.0
            d_right = 0.0

        d_center = (d_left + d_right) / 2.0
        delta_th = ((d_right - d_left) / self.wheel_base) * self.angular_correction

        # Clamp max heading change per update (~286 deg/s max at 50Hz)
        max_delta_th = 0.10
        delta_th = max(-max_delta_th, min(max_delta_th, delta_th))

        v = d_center / dt
        w = delta_th / dt

        self.x += d_center * math.cos(self.th + (delta_th / 2.0))
        self.y += d_center * math.sin(self.th + (delta_th / 2.0))
        self.th = self.normalize_angle(self.th + delta_th)

        # Calibration logging: every 2.5 seconds
        self.total_distance += abs(d_center)
        self.log_counter += 1
        if self.log_counter >= 125:  # 125 * 0.02s = 2.5s
            self.get_logger().info(
                f"[CALIBRATION] total_dist={self.total_distance:.3f}m | "
                f"ticks L={self.current_left_ticks} R={self.current_right_ticks} | "
                f"pos=({self.x:.3f}, {self.y:.3f}) th={math.degrees(self.th):.1f}° | "
                f"enc L={'OK' if self.left_encoder_healthy else 'STUCK'} "
                f"R={'OK' if self.right_encoder_healthy else 'STUCK'}")
            self.log_counter = 0

        odom_quat = Quaternion()
        odom_quat.z = math.sin(self.th / 2.0)
        odom_quat.w = math.cos(self.th / 2.0)

        # --- Publish Odometry Message ---
        odom = Odometry()
        odom.header.stamp = current_time.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_link'

        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.position.z = 0.0
        odom.pose.pose.orientation = odom_quat

        odom.twist.twist.linear.x = v
        odom.twist.twist.angular.z = w

        # --- Adaptive covariance: degrade trust when encoder(s) unhealthy ---
        both_healthy = self.left_encoder_healthy and self.right_encoder_healthy
        odom.pose.covariance[0] = 0.01 if both_healthy else 0.05   # X
        odom.pose.covariance[7] = 0.01 if both_healthy else 0.05   # Y
        odom.pose.covariance[35] = 0.05 if both_healthy else 1.0   # Yaw

        odom.twist.covariance[0] = 0.01 if both_healthy else 0.05  # vX
        odom.twist.covariance[35] = 0.05 if both_healthy else 1.0  # vYaw

        self.odom_pub.publish(odom)

        self.last_left_ticks = self.current_left_ticks
        self.last_right_ticks = self.current_right_ticks
        self.last_time = current_time

def main(args=None):
    rclpy.init(args=args)
    node = OdometryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
