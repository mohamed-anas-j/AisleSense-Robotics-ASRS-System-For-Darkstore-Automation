# AisleSense Robot

Autonomous navigation robot built on **Raspberry Pi 5**, **RPLidar**, and **ROS 2 Humble** with Nav2. Runs entirely inside Docker — map a room with SLAM, then navigate autonomously.

## Hardware

| Component | Details |
|---|---|
| Compute | Raspberry Pi 5 |
| LiDAR | RPLidar (Express mode, `/dev/ttyUSB0`) |
| Motors | Differential drive, L298N H-bridge (GPIO PWM) |
| Encoders | 1170 ticks/rev, via Arduino (`/dev/ttyACM0`) |
| IMU | MPU6050 (gyro + accelerometer), via Arduino |
| Wheels | 5cm radius, 25cm wheel base |
| Chassis | 35×35cm square footprint |

### Wiring

| Function | GPIO Pin |
|---|---|
| Left Motor Enable (PWM) | 12 |
| Left Motor IN1 / IN2 | 17 / 27 |
| Right Motor Enable (PWM) | 13 |
| Right Motor IN3 / IN4 | 22 / 23 |

### Arduino Serial Protocol

The Arduino sends comma-separated key:value pairs at 115200 baud:

```
L:<left_ticks>,R:<right_ticks>,GX:<gyro_x>,GY:<gyro_y>,GZ:<gyro_z>,AX:<accel_x>,AY:<accel_y>,AZ:<accel_z>
```

Tray control commands are single characters sent over the same serial link:

| Command | Action | Status | Notes |
|---|---|---|---|
| `I` | Pull tray in | `STATUS: IN_LIMIT_HIT` | Stops when limit switch hits |
| `O` | Push tray out | `STATUS: OUT_COMPLETE` | Timed 0.5s extension |
| `S` | Stop tray | `STATUS: STOPPED` | Immediately stops motors |

These commands are published in ROS as `tray_cmd` and status messages are
published as `tray_status` by `aislesense_core.py`.

## Quick Start

```bash
# Clone and enter the project
cd aislesense

# Interactive menu
./start.sh

# Or directly:
./start.sh mapping   # Build a map with SLAM + teleop
./start.sh nav       # Autonomous navigation with Nav2
./start.sh stop      # Stop the container
./start.sh save      # Save map from running mapping session
```

## Modes

### 1. Mapping

```bash
./start.sh mapping
```

1. On your laptop (same network, `ROS_DOMAIN_ID=42`), open RViz2 and add the `/map` topic
2. Drive the robot with teleop:
   ```bash
   ros2 run teleop_twist_keyboard teleop_twist_keyboard
   ```
3. When the map looks good, save it:
   ```bash
   docker exec aislesense_ros2 bash -c \
     'source /opt/ros/humble/setup.bash && ros2 run nav2_map_server map_saver_cli -f /ros2_ws/my_room_map'
   ```
   The map files (`my_room_map.pgm` / `my_room_map.yaml`) sync back to this folder via volume mounts.

### 2. Navigation

```bash
./start.sh nav
```

1. Open RViz2 on your laptop
2. Set the initial pose with **2D Pose Estimate**
3. Send goals with **2D Goal Pose**

### RViz2 Setup (Laptop)

```bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
rviz2
```

Add these displays: **Map** (`/map`), **LaserScan** (`/scan`), **TF**, and the **Navigation 2** panel.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Docker Container                │
│                                                  │
│  aislesense_core.py ──► /left_ticks, /right_ticks│
│         │               /imu/data_raw            │
│         │               /tray_cmd, /tray_status  │
│         │               cmd_vel → GPIO motors    │
│         │                                        │
│  odometry_node.py ──► /odom                      │
│         │                                        │
│  rplidar_node ──► /scan                          │
│         │                                        │
│  EKF (robot_localization) ──► odom→base_link TF  │
│         │                                        │
│  ┌──────┴──────────────────────┐                 │
│  │  MAPPING: SLAM Toolbox     │                  │
│  │  NAV: Nav2 + AMCL          │                  │
│  └─────────────────────────────┘                 │
└─────────────────────────────────────────────────┘
```

### TF Tree

```
map ──(AMCL)──► odom ──(EKF)──► base_link ──► laser (yaw=π, z=0.15m)
                                    ├──► imu_link (z=0.075m)
                                    └──► base_footprint
```

### EKF Sensor Fusion

Two separate EKF configs are used depending on the mode:

| | Mapping (`ekf_mapping.yaml`) | Navigation (`ekf.yaml`) |
|---|---|---|
| **Encoders** | Linear vel + angular vel | Linear vel only |
| **IMU Gyro** | Yaw rate (secondary) | Yaw rate (primary) |
| **IMU Accel** | Disabled | Disabled |
| **Rationale** | Slow teleop = encoders reliable | Fast turns = encoders slip, gyro is more reliable |

## Odometry Calibration

The odometry node supports runtime calibration via environment variables:

| Variable | Default | Description |
|---|---|---|
| `WHEEL_RADIUS` | `0.05` | Wheel radius in meters |
| `WHEEL_BASE` | `0.25` | Distance between wheels in meters |
| `TICKS_PER_REV` | `1170.0` | Encoder ticks per wheel revolution |
| `LINEAR_CORRECTION` | `1.0` | Multiplier for linear distance |
| `ANGULAR_CORRECTION` | `1.0` | Multiplier for angular rotation |

### How to Calibrate

1. Start the robot in nav or standby mode
2. Mark exactly 1 meter on the floor
3. Push the robot that distance by hand
4. Check logs:
   ```bash
   docker compose logs | grep CALIBRATION
   ```
5. If it shows `total_dist=0.50m` for a real 1m push, set `LINEAR_CORRECTION=2.0`
6. Restart:
   ```bash
   LINEAR_CORRECTION=2.0 ./start.sh nav
   ```

For angular calibration, spin the robot exactly 360° and check the reported angle.

## File Structure

```
aislesense/
├── aislesense_core.py      # Motor control, encoder/IMU serial parsing
├── odometry_node.py         # Encoder ticks → /odom (diff-drive kinematics)
├── scan_stabilizer.py       # Resamples /scan to fixed beam count (optional)
├── nav2_params.yaml         # Nav2 stack config (AMCL, DWB, costmaps, planner)
├── ekf.yaml                 # EKF config for NAVIGATION (IMU gyro dominant)
├── ekf_mapping.yaml         # EKF config for MAPPING (encoders dominant)
├── slam_params.yaml         # SLAM Toolbox parameters
├── my_room_map.pgm          # Saved occupancy grid map
├── my_room_map.yaml         # Map metadata
├── entrypoint.sh            # Container entrypoint (launches all nodes)
├── start.sh                 # Host-side launcher script (interactive menu)
├── docker-compose.yml       # Container orchestration
└── Dockerfile               # ROS 2 Humble + dependencies
```

## Key Parameters

### Nav2 Tuning

| Parameter | Value | Notes |
|---|---|---|
| Controller frequency | 5 Hz | Tuned for RPi5 compute |
| Planner frequency | 2 Hz | Matches RPi5 capability |
| Max linear velocity | 0.3 m/s | |
| Max angular velocity | 0.8 rad/s | |
| Goal tolerance (xy) | 0.15 m | |
| Goal tolerance (yaw) | 0.25 rad | |
| Inflation radius | 0.40 m | |
| Progress checker | 0.08m in 25s | Relaxed for slow starts |

### AMCL

| Parameter | Value |
|---|---|
| Particles | 500–2000 |
| Scan topic | `/scan` |
| Update min distance | 0.03 m |
| Update min angle | 0.03 rad |
| Transform tolerance | 0.5 s |

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| "Failed to make progress" | Motors not spinning at low PWM | Dead zone is set to 25% — check motor wiring |
| Scan drifts from map walls | EKF odom drift / AMCL too slow | Verify `transform_tolerance`, check IMU connection |
| Robot overshoots goals | Encoder calibration off | Run calibration procedure above |
| "Planner loop missed rate" | RPi5 overloaded | Already tuned to 2 Hz — close other processes |
| Container won't start | Device not found | Check `/dev/ttyACM0` (Arduino) and `/dev/ttyUSB0` (LiDAR) |
| No laser data in RViz | LiDAR not connected | Verify `/dev/ttyUSB0`, check `ros2 topic echo /scan` |

## Network Setup

The container uses `network_mode: host` with:
- `ROS_DOMAIN_ID=42`
- `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`

Your laptop must use the same settings to see topics. Both devices must be on the same network.
