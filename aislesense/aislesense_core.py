#!/usr/bin/env python3
"""
AisleSense Core Node
====================
Motor control and sensor interface for the AisleSense differential-drive
robot. Subscribes to ``/cmd_vel`` for velocity commands, drives left/right
motors via GPIO PWM through an L298N H-bridge, and publishes raw encoder
ticks and IMU data received over a serial link from an Arduino co-processor.

Published Topics:
    /left_ticks  (std_msgs/Int32)   — Left wheel encoder count.
    /right_ticks (std_msgs/Int32)   — Right wheel encoder count.
    /imu/data_raw (sensor_msgs/Imu) — Raw gyroscope and accelerometer readings.

Subscribed Topics:
    /cmd_vel (geometry_msgs/Twist)  — Target linear and angular velocity.
"""
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32
from sensor_msgs.msg import Imu
import serial
import RPi.GPIO as GPIO
import threading

# GPIO pin assignments for the L298N motor driver
ENA, IN1, IN2 = 12, 17, 27   # Left motor:  enable (PWM), forward, reverse
ENB, IN3, IN4 = 13, 22, 23   # Right motor: enable (PWM), forward, reverse

class AisleSenseCore(Node):
    def __init__(self):
        super().__init__('aislesense_core')
        
        # Robot physical parameters (must match odometry_node.py)
        self.wheel_base = 0.25  # Distance between wheels in metres
        
        # ROS 2 publishers and subscribers
        self.sub_cmd_vel = self.create_subscription(Twist, 'cmd_vel', self.cmd_vel_callback, 10)
        self.pub_left_ticks = self.create_publisher(Int32, 'left_ticks', 10)
        self.pub_right_ticks = self.create_publisher(Int32, 'right_ticks', 10)
        
        # IMU publisher
        self.pub_imu = self.create_publisher(Imu, 'imu/data_raw', 10)

        # Hardware initialisation
        self.setup_gpio()
        self.setup_serial()

        self.serial_thread = threading.Thread(target=self.read_serial_loop)
        self.serial_thread.daemon = True
        self.serial_thread.start()
        
        self.get_logger().info("AisleSense core node started — IMU + encoders active")

    def setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        pins = [ENA, IN1, IN2, ENB, IN3, IN4]
        for pin in pins:
            GPIO.setup(pin, GPIO.OUT)

        self.pwm_a = GPIO.PWM(ENA, 200) 
        self.pwm_b = GPIO.PWM(ENB, 200)
        self.pwm_a.start(0)
        self.pwm_b.start(0)

    def setup_serial(self):
        try:
            self.arduino = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
        except Exception as e:
            self.get_logger().error(f"Arduino connection failed: {e}")

    def cmd_vel_callback(self, msg):
        """Convert Twist command into per-wheel speeds via differential-drive kinematics."""
        v = msg.linear.x   # Linear velocity (m/s)
        w = msg.angular.z   # Angular velocity (rad/s)
        
        # Differential-drive kinematics
        left_speed = v - (w * self.wheel_base / 2.0)
        right_speed = v + (w * self.wheel_base / 2.0)
        
        # Amplify wheel speeds during in-place rotations to overcome
        # static friction when linear velocity is near zero.
        if abs(v) < 0.01 and abs(w) > 0.05:
            turn_boost = 1.8
            left_speed *= turn_boost
            right_speed *= turn_boost
        
        self.set_motor(left_speed, right_speed)

    def set_motor(self, left, right):
        """Set GPIO direction and PWM duty cycle for both motors."""
        GPIO.output(IN1, GPIO.HIGH if left >= 0 else GPIO.LOW)
        GPIO.output(IN2, GPIO.LOW if left >= 0 else GPIO.HIGH)
        GPIO.output(IN3, GPIO.HIGH if right >= 0 else GPIO.LOW)
        GPIO.output(IN4, GPIO.LOW if right >= 0 else GPIO.HIGH)

        # Minimum PWM duty cycle required to overcome the motor dead zone
        DEAD_ZONE = 20.0

        # Velocity-to-PWM scaling (0.3 m/s maps to ~95 % duty cycle)
        pwm_l = abs(left * 320)
        pwm_r = abs(right * 320)

        # Boost duty cycle to the dead-zone floor when a non-zero speed is commanded
        if pwm_l > 0 and pwm_l < DEAD_ZONE:
            pwm_l = DEAD_ZONE
        if pwm_r > 0 and pwm_r < DEAD_ZONE:
            pwm_r = DEAD_ZONE

        pwm_l = max(0, min(100, pwm_l))
        pwm_r = max(0, min(100, pwm_r))
        
        self.pwm_a.ChangeDutyCycle(pwm_l)
        self.pwm_b.ChangeDutyCycle(pwm_r)

    def read_serial_loop(self):
        """Background thread: read encoder + IMU data from the Arduino serial port."""
        import time
        while rclpy.ok():
            try:
                if hasattr(self, 'arduino') and self.arduino.in_waiting > 0:
                    # Drain the buffer and keep only the most recent complete line
                    line = ''
                    while self.arduino.in_waiting > 0:
                        line = self.arduino.readline().decode('utf-8', errors='ignore').strip()
                    
                    if not line:
                        continue
                    
                    parts = line.split(',')
                    
                    # Require a minimum of 8 key:value fields per frame
                    if len(parts) < 8:
                        continue
                        
                    data = {}
                    for part in parts:
                        # maxsplit=1 guards against malformed payloads with extra colons
                        if ':' in part:
                            kv = part.split(':', 1)
                            try:
                                data[kv[0]] = float(kv[1])
                            except (ValueError, IndexError):
                                continue
                    
                    # Both encoder channels must be present
                    if 'L' not in data or 'R' not in data:
                        continue
                    
                    # Publish encoder tick counts
                    msg_l, msg_r = Int32(), Int32()
                    msg_l.data = int(data['L'])
                    msg_r.data = int(data['R'])
                    self.pub_left_ticks.publish(msg_l)
                    self.pub_right_ticks.publish(msg_r)
                    
                    # Publish raw IMU readings
                    imu_msg = Imu()
                    imu_msg.header.stamp = self.get_clock().now().to_msg()
                    imu_msg.header.frame_id = "imu_link"
                    
                    imu_msg.angular_velocity.x = data.get('GX', 0.0)
                    imu_msg.angular_velocity.y = data.get('GY', 0.0)
                    imu_msg.angular_velocity.z = data.get('GZ', 0.0)
                    
                    imu_msg.linear_acceleration.x = data.get('AX', 0.0)
                    imu_msg.linear_acceleration.y = data.get('AY', 0.0)
                    imu_msg.linear_acceleration.z = data.get('AZ', 0.0)
                    
                    # Covariance matrices: gyroscope is highly trusted for yaw estimation
                    imu_msg.orientation_covariance = [0.0] * 9
                    imu_msg.orientation_covariance[0] = -1.0  # Signals the EKF to ignore orientation
                    
                    imu_msg.angular_velocity_covariance = [0.0] * 9
                    imu_msg.angular_velocity_covariance[0] = 0.001  # Roll rate
                    imu_msg.angular_velocity_covariance[4] = 0.001  # Pitch rate
                    imu_msg.angular_velocity_covariance[8] = 0.001  # Yaw rate (high trust)

                    imu_msg.linear_acceleration_covariance = [0.0] * 9
                    imu_msg.linear_acceleration_covariance[0] = 0.1  # X
                    imu_msg.linear_acceleration_covariance[4] = 0.1  # Y
                    imu_msg.linear_acceleration_covariance[8] = 0.1  # Z
                    
                    self.pub_imu.publish(imu_msg)
            except Exception as e:
                self.get_logger().warn(f"Serial parse error: {e}", throttle_duration_sec=5.0)
                continue
            else:
                # Yield CPU when no serial data is available
                if not (hasattr(self, 'arduino') and self.arduino.in_waiting > 0):
                    import time
                    time.sleep(0.001)

def main(args=None):
    rclpy.init(args=args)
    node = AisleSenseCore()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.pwm_a.stop()
        node.pwm_b.stop()
        GPIO.cleanup()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
