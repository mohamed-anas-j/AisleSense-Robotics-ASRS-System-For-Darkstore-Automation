#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32, String
from sensor_msgs.msg import Imu
import serial
import RPi.GPIO as GPIO
import threading

# Pin Definitions
ENA, IN1, IN2 = 12, 17, 27
ENB, IN3, IN4 = 13, 22, 23

class AisleSenseCore(Node):
    def __init__(self):
        super().__init__('aislesense_core')
        
        # Robot physical parameters (must match odometry_node.py)
        self.wheel_base = 0.25  # meters between wheels
        
        # ROS2 Publishers & Subscribers
        self.sub_cmd_vel = self.create_subscription(Twist, 'cmd_vel', self.cmd_vel_callback, 10)
        self.sub_tray_cmd = self.create_subscription(String, 'tray_cmd', self.tray_cmd_callback, 10)
        self.pub_left_ticks = self.create_publisher(Int32, 'left_ticks', 10)
        self.pub_right_ticks = self.create_publisher(Int32, 'right_ticks', 10)
        self.pub_tray_status = self.create_publisher(String, 'tray_status', 10)
        
        # NEW: IMU Publisher
        self.pub_imu = self.create_publisher(Imu, 'imu/data_raw', 10)

        # Hardware Setup
        self.setup_gpio()
        self.setup_serial()

        self._serial_lock = threading.Lock()

        self.serial_thread = threading.Thread(target=self.read_serial_loop)
        self.serial_thread.daemon = True
        self.serial_thread.start()
        
        self.get_logger().info("AisleSense UNLEASHED: IMU + Encoders Active!")

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

    def send_tray_command(self, cmd: str) -> bool:
        if not hasattr(self, 'arduino'):
            return False
        safe = cmd.strip()[:1].upper()
        if safe not in {'I', 'O', 'S'}:
            return False
        try:
            with self._serial_lock:
                self.arduino.write(safe.encode('ascii'))
            return True
        except Exception as exc:
            self.get_logger().warn(f"Tray command failed: {exc}")
            return False

    def tray_cmd_callback(self, msg: String):
        self.send_tray_command(msg.data)

    def cmd_vel_callback(self, msg):
        v = msg.linear.x   # m/s
        w = msg.angular.z   # rad/s
        
        # Differential drive kinematics
        left_speed = v - (w * self.wheel_base / 2.0)   # m/s
        right_speed = v + (w * self.wheel_base / 2.0)   # m/s
        
        # Boost pure rotations: when v≈0 and w is commanded, scale up wheel speeds
        # so motors can overcome friction during in-place turns
        if abs(v) < 0.01 and abs(w) > 0.05:
            turn_boost = 1.8
            left_speed *= turn_boost
            right_speed *= turn_boost
        
        self.set_motor(left_speed, right_speed)

    def set_motor(self, left, right):
        GPIO.output(IN1, GPIO.HIGH if left >= 0 else GPIO.LOW)
        GPIO.output(IN2, GPIO.LOW if left >= 0 else GPIO.HIGH)
        GPIO.output(IN3, GPIO.HIGH if right >= 0 else GPIO.LOW)
        GPIO.output(IN4, GPIO.LOW if right >= 0 else GPIO.HIGH)

        # Minimum PWM to overcome motor dead zone
        DEAD_ZONE = 40.0

        # Scale: 0.3 m/s -> ~95% PWM (full speed). Higher gain = more responsive turns.
        pwm_l = abs(left * 320)
        pwm_r = abs(right * 320)

        # If a velocity was commanded but PWM is below dead zone, boost it
        if pwm_l > 0 and pwm_l < DEAD_ZONE:
            pwm_l = DEAD_ZONE
        if pwm_r > 0 and pwm_r < DEAD_ZONE:
            pwm_r = DEAD_ZONE

        pwm_l = max(0, min(100, pwm_l))
        pwm_r = max(0, min(100, pwm_r))
        
        self.pwm_a.ChangeDutyCycle(pwm_l)
        self.pwm_b.ChangeDutyCycle(pwm_r)

    def read_serial_loop(self):
        import time
        while rclpy.ok():
            try:
                if hasattr(self, 'arduino') and self.arduino.in_waiting > 0:
                    # Drain buffer — always use the LATEST complete line
                    line = ''
                    while self.arduino.in_waiting > 0:
                        line = self.arduino.readline().decode('utf-8', errors='ignore').strip()
                    
                    if not line:
                        continue

                    if line.startswith("STATUS:"):
                        status = line.split("STATUS:", 1)[1].strip()
                        if status:
                            status_msg = String()
                            status_msg.data = status
                            self.pub_tray_status.publish(status_msg)
                        continue
                    
                    parts = line.split(',')
                    
                    # Ensure we have a full string before unpacking
                    if len(parts) < 8:
                        continue
                        
                    data = {}
                    for part in parts:
                        # Use split with maxsplit=1 to handle corrupted data with extra colons
                        if ':' in part:
                            kv = part.split(':', 1)
                            try:
                                data[kv[0]] = float(kv[1])
                            except (ValueError, IndexError):
                                continue
                    
                    # Verify we got the required encoder keys
                    if 'L' not in data or 'R' not in data:
                        continue
                    
                    # 1. Publish Encoder Ticks
                    msg_l, msg_r = Int32(), Int32()
                    msg_l.data = int(data['L'])
                    msg_r.data = int(data['R'])
                    self.pub_left_ticks.publish(msg_l)
                    self.pub_right_ticks.publish(msg_r)
                    
                    # 2. Publish IMU Data
                    imu_msg = Imu()
                    imu_msg.header.stamp = self.get_clock().now().to_msg()
                    imu_msg.header.frame_id = "imu_link"
                    
                    imu_msg.angular_velocity.x = data.get('GX', 0.0)
                    imu_msg.angular_velocity.y = data.get('GY', 0.0)
                    imu_msg.angular_velocity.z = data.get('GZ', 0.0)
                    
                    imu_msg.linear_acceleration.x = data.get('AX', 0.0)
                    imu_msg.linear_acceleration.y = data.get('AY', 0.0)
                    imu_msg.linear_acceleration.z = data.get('AZ', 0.0)
                    
                    # IMU covariances — HIGH trust on gyro for yaw
                    imu_msg.orientation_covariance = [0.0] * 9
                    imu_msg.orientation_covariance[0] = -1.0  # -1 tells EKF to ignore orientation
                    
                    imu_msg.angular_velocity_covariance = [0.0] * 9
                    imu_msg.angular_velocity_covariance[0] = 0.001  # X
                    imu_msg.angular_velocity_covariance[4] = 0.001  # Y
                    imu_msg.angular_velocity_covariance[8] = 0.001  # Z (Yaw) — VERY trusted

                    imu_msg.linear_acceleration_covariance = [0.0] * 9
                    imu_msg.linear_acceleration_covariance[0] = 0.1  # X
                    imu_msg.linear_acceleration_covariance[4] = 0.1  # Y
                    imu_msg.linear_acceleration_covariance[8] = 0.1  # Z
                    
                    self.pub_imu.publish(imu_msg)
            except Exception as e:
                self.get_logger().warn(f"Serial parse error: {e}", throttle_duration_sec=5.0)
                continue
            else:
                # Small sleep to prevent CPU spin when no data available
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
