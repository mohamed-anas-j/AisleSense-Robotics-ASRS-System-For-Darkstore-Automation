#!/bin/bash
set -e

source /opt/ros/humble/setup.bash

echo "============================================="
echo "  AisleSense Robot — Mode: ${ROBOT_MODE:-STANDBY}"
echo "============================================="

# -----------------------------------------------
# 1. Hardware nodes (always needed)
# -----------------------------------------------
python3 /ros2_ws/aislesense_core.py &

# Odometry node — encoder parameters are tunable via environment variables.
# Calibration: push the robot exactly 1 m and compare against [CALIBRATION] logs.
python3 /ros2_ws/odometry_node.py --ros-args \
  -p wheel_radius:=${WHEEL_RADIUS:-0.05} \
  -p wheel_base:=${WHEEL_BASE:-0.25} \
  -p ticks_per_rev:=${TICKS_PER_REV:-1170.0} \
  -p linear_correction:=${LINEAR_CORRECTION:-1.0} \
  -p angular_correction:=${ANGULAR_CORRECTION:-1.0} &

# RPLidar A1M8 — Express scan mode (~4 K samples/s, ~720 points/rev)
# angle_compensate distributes beams at uniform angular spacing for cleaner SLAM input
MALLOC_CHECK_=0 ros2 run rplidar_ros rplidar_node \
  --ros-args -p serial_port:=/dev/ttyUSB0 -p serial_baudrate:=115200 -p frame_id:=laser \
  -p scan_mode:=Express -p angle_compensate:=true &

# Scan stabilizer — resamples variable RPLidar beam counts to a fixed 720-beam output
python3 /ros2_ws/scan_stabilizer.py &

# -----------------------------------------------
# Static TF frames:
#   odom <-(EKF)-> base_link -> laser
#                  base_link -> imu_link
#                  base_link -> base_footprint
# -----------------------------------------------
ros2 run tf2_ros static_transform_publisher \
  --x 0 --y 0 --z 0.15 --roll 0 --pitch 0 --yaw 3.14159 \
  --frame-id base_link --child-frame-id laser &

ros2 run tf2_ros static_transform_publisher \
  --x 0 --y 0 --z 0.075 --roll 0 --pitch 0 --yaw 0 \
  --frame-id base_link --child-frame-id imu_link &

ros2 run tf2_ros static_transform_publisher \
  --x 0 --y 0 --z 0 --roll 0 --pitch 0 --yaw 0 \
  --frame-id base_link --child-frame-id base_footprint &

# Give hardware nodes time to initialize
sleep 3

# -----------------------------------------------
# EKF sensor fusion (odom -> base_link TF)
#   Mapping mode uses tighter encoder noise; navigation mode trusts the IMU more.
# -----------------------------------------------
if [ "$ROBOT_MODE" == "mapping" ] || [ "$ROBOT_MODE" == "MAPPING" ]; then
    EKF_CONFIG="/ros2_ws/ekf_mapping.yaml"
else
    EKF_CONFIG="/ros2_ws/ekf.yaml"
fi
echo ">>> Using EKF config: $EKF_CONFIG"

ros2 run robot_localization ekf_node \
  --ros-args --params-file "$EKF_CONFIG" &

sleep 2

# -----------------------------------------------
# Mode-specific launch
# -----------------------------------------------
if [ "$ROBOT_MODE" == "mapping" ] || [ "$ROBOT_MODE" == "MAPPING" ]; then
    echo ""
    echo ">>> MAPPING MODE — SLAM Toolbox"
    echo ">>> Drive the robot with teleop from your laptop."
    echo ">>> When done mapping, save the map with:"
    echo ">>>   ros2 run nav2_map_server map_saver_cli -f /ros2_ws/my_room_map"
    echo ""
    ros2 launch slam_toolbox online_async_launch.py \
      use_sim_time:=false \
      slam_params_file:=/ros2_ws/slam_params.yaml

elif [ "$ROBOT_MODE" == "nav" ] || [ "$ROBOT_MODE" == "NAV" ]; then
    echo ""
    echo ">>> NAVIGATION MODE — Nav2 + AMCL"
    echo ">>> Send goals from RViz2 on your laptop."
    echo ""
    ros2 launch nav2_bringup bringup_launch.py \
      use_sim_time:=false \
      autostart:=true \
      map:=/ros2_ws/my_room_map.yaml \
      params_file:=/ros2_ws/nav2_params.yaml &

    # Wait for Nav2 to be ready before starting the waypoint collector
    sleep 5

    echo ""
    echo ">>> Waypoint Collector active!"
    echo ">>>   1. Click '2D Goal Pose' in RViz2 to queue waypoints"
    echo ">>>   2. ros2 topic pub --once /start_waypoints std_msgs/Empty"
    echo ">>>   3. ros2 topic pub --once /clear_waypoints std_msgs/Empty"
    echo ""
    python3 /ros2_ws/waypoint_collector.py

else
    echo ""
    echo ">>> STANDBY MODE — hardware running, no SLAM or Nav2."
    echo ">>> Set ROBOT_MODE=mapping or ROBOT_MODE=nav to activate."
    echo ""
    # Keep container alive
    tail -f /dev/null
fi
