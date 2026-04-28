# AisleSense Robotics Darkstore ASRS System - Technical Documentation

## Overview

AisleSense Robotics is a darkstore ASRS system built around a ROS 2 mobile base,
a desktop navigator UI, and an offline vision analytics pipeline. The system
supports an assisted route workflow that combines autonomous navigation with
operator-controlled tray handling at shelf locations.

## Hardware Stack

- **Compute**: Raspberry Pi 5 (robot), laptop/desktop (navigator UI)
- **LiDAR**: RPLidar A1M8 (2D laser scan)
- **Drive**: Differential drive via L298N H-bridge
- **Encoders**: Arduino-based wheel encoders (1170 ticks/rev)
- **IMU**: MPU6050 (gyro + accel)
- **Tray**: DC motor with limit switch for tray in/out
- **Camera**: USB webcam used by the navigator UI

## Software Stack

- **ROS 2 Humble**
- **Nav2** for autonomous navigation
- **SLAM Toolbox** for mapping
- **robot_localization** EKF for sensor fusion
- **Python 3.10** (ROS 2 Humble Python bindings)

Repository modules:

- **aislesense/**: Core robot nodes, Docker stack, hardware drivers
- **aislesense_navigator/**: Tkinter UI for mapping and assisted route control
- **asvision/**: Offline ONNX pipeline and Streamlit analytics

## ROS Interfaces

### Topics (Robot Core)

| Topic | Type | Direction | Description |
|---|---|---|---|
| `cmd_vel` | `geometry_msgs/Twist` | Sub | Motor velocity commands |
| `left_ticks` | `std_msgs/Int32` | Pub | Left wheel encoder ticks |
| `right_ticks` | `std_msgs/Int32` | Pub | Right wheel encoder ticks |
| `imu/data_raw` | `sensor_msgs/Imu` | Pub | Raw IMU data |
| `tray_cmd` | `std_msgs/String` | Sub | Tray command: `I`, `O`, `S` |
| `tray_status` | `std_msgs/String` | Pub | Tray status text |
| `/scan` | `sensor_msgs/LaserScan` | Pub | Raw LiDAR scan |
| `/scan_stable` | `sensor_msgs/LaserScan` | Pub | Resampled scan |
| `/odom` | `nav_msgs/Odometry` | Pub | Odometry |

### Actions and Other Topics

| Interface | Type | Description |
|---|---|---|
| `navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Nav2 goal action |
| `/initialpose` | `geometry_msgs/PoseWithCovarianceStamped` | Initial pose estimate |

## Arduino Serial Protocol

Telemetry is emitted at 115200 baud as comma-separated key:value pairs:

```
L:<left_ticks>,R:<right_ticks>,GX:<gyro_x>,GY:<gyro_y>,GZ:<gyro_z>,AX:<accel_x>,AY:<accel_y>,AZ:<accel_z>
```

Tray control commands (single characters):

| Command | Action | Status |
|---|---|---|
| `I` | Pull tray in | `STATUS: IN_LIMIT_HIT` |
| `O` | Push tray out | `STATUS: OUT_COMPLETE` |
| `S` | Stop tray | `STATUS: STOPPED` |

The robot core node parses `STATUS:` messages and republishes them as
`tray_status`.

## Assisted Route State Machine

The assisted route flow is controlled in the navigator UI:

1. **Navigate to SHELF**
2. **At SHELF**: camera preview on, manual drive and tray buttons enabled
3. **Done at SHELF** triggers navigation to PACKING_AREA
4. **At PACKING_AREA**: wait for **Pickup OK**
5. Loop back to SHELF until **Stop / Return to Dock**

Key gating rules:

- Manual drive and tray controls are enabled only at SHELF.
- Assisted route requires `rclpy` (ROS 2 Python bindings).
- Return-to-dock navigation runs even after a stop signal.

## Configuration

Navigator configuration is in `aislesense_navigator/config.py`:

- `ASSISTED_WAYPOINT_A` (default `SHELF`)
- `ASSISTED_WAYPOINT_B` (default `PACKING_AREA`)
- `CAMERA_INDEX` (USB camera index)
- `MANUAL_LIN_SPEED`, `MANUAL_ANG_SPEED`

Robot parameters are set via environment variables in `aislesense/entrypoint.sh`:

- `WHEEL_RADIUS`, `WHEEL_BASE`, `TICKS_PER_REV`
- `LINEAR_CORRECTION`, `ANGULAR_CORRECTION`

## Deployment

### Robot (Pi 5)

```bash
cd aislesense
./start.sh
```

### Navigator (Laptop)

```bash
cd aislesense_navigator
pip install -r requirements.txt
source /opt/ros/humble/setup.bash
python main.py
```

Ensure the same `ROS_DOMAIN_ID` on robot and laptop.

## Safety and Operations

- Use a clear operating area and verify obstacle-free motion before running Nav2.
- Keep an operator near the robot during assisted mode.
- Use **Stop / Return to Dock** in the navigator UI to end a session.

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0
International (CC BY-NC 4.0). Commercial use requires explicit permission.
See `LICENSE` for details.
