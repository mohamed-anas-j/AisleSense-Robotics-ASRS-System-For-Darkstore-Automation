# AisleSense Robotics — Darkstore ASRS System

AisleSense Robotics is a darkstore ASRS platform that combines autonomous
mobile navigation with operator-assisted pickup for store replenishment
workflows. The system drives from a dock to shelf locations, presents a
live camera feed, allows manual tray operations, and hands off to a
packing area for pickup confirmation.

## Highlights

- Autonomous navigation with ROS 2, Nav2, and LiDAR-based localization.
- Assisted route flow: Dock -> SHELF -> PACKING_AREA with operator gating.
- Manual drive and tray control at the shelf via the navigator UI.
- Modular stack: robot core and desktop navigator.

## System Modules

- **aislesense/**: Robot core ROS 2 stack (Pi 5, L298N, encoders, IMU, LiDAR).
- **aislesense_navigator/**: Desktop GUI for mapping, region tools, and
  assisted route operations with camera preview.

## Operational Flow (Assisted Route)

1. **Dock**: Robot starts at the dock pose.
2. **SHELF**: Robot navigates to `SHELF`, camera feed turns on, and the
   operator can drive and push/pull the tray.
3. **Done**: Operator clicks **Done at SHELF**.
4. **PACKING_AREA**: Robot navigates to `PACKING_AREA` and waits for
   **Pickup OK**.
5. **Loop**: Robot returns to `SHELF` and repeats until **Stop / Return to Dock**.

## Demo

<video src="https://github.com/mohamed-anas-j/AisleSense-Robotics-ASRS-System-For-Darkstore-Automation/raw/main/Demo.mp4" controls width="100%"></video>

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              AISLESENSE ROBOT  (Raspberry Pi 5)         │
│                                                         │
│   RPLidar A1M8 ──► rplidar_node ──► scan_stabilizer     │
│                                      (720-beam resample)│
│                                            │            │
│   Arduino ──► aislesense_core              │            │
│    ├─ Wheel encoders (1170 ticks/rev)      │            │
│    └─ MPU6050 IMU                          │            │
│         │                                  │            │
│         ▼                                  ▼            │
│   odometry_node ──►┌──────────┐◄── /scan_stable         │
│    (/odom @ 50Hz)  │   EKF    │                         │
│                    │  Sensor  │                         │
│   /imu/data_raw ──►│  Fusion  │                         │
│                    └────┬─────┘                         │
│                         │ odom → base_link TF           │
│                         ▼                               │
│              ┌─────────────────────┐                    │
│              │   SLAM Toolbox      │  ◄── Mapping mode  │
│              │      ── OR ──       │                    │
│              │   Nav2 + AMCL       │  ◄── Nav mode      │
│              └────────┬────────────┘                    │
│                       │                                 │
│    L298N H-bridge ◄── cmd_vel ◄── DWB Local Planner     │
│    (PWM motor ctrl)                                     │
└─────────────────────────────────────────────────────────┘
                        │
                   ROS 2 Topics
                  (DOMAIN_ID=42)
                        │
┌───────────────────────▼─────────────────────────────────┐
│           AISLESENSE NAVIGATOR  (Desktop App)           │
│                                                         │
│   • Loads occupancy grid map (PGM + YAML)               │
│   • Interactive region drawing (polygon tool)           │
│   • Approach pose placement per region                  │
│   • Dock pose (robot home position)                     │
│   • Scan tour: ordered multi-region autonomous patrol   │
│   • Sends NavigateToPose goals via ROS 2 action client  │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### Robot Core (Pi 5)

```bash
cd aislesense
./start.sh
```

### Navigator UI (Laptop)

```bash
cd aislesense_navigator
pip install -r requirements.txt
source /opt/ros/humble/setup.bash
python main.py
```

For more details, see:
- [aislesense/README.md](aislesense/README.md)
- [aislesense_navigator/README.md](aislesense_navigator/README.md)
- [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)

## Repository Layout

```
AisleSense-Robotics-ASRS-System-For-Darkstore-Automation/
├── aislesense/               # Robot core stack (ROS 2, Nav2, drivers)
├── aislesense_navigator/     # Desktop navigation GUI
├── Demo.mp4                  # System demo video
├── TECHNICAL_DOCUMENTATION.md
├── CONTRIBUTING.md
└── LICENSE
```

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0
International (CC BY-NC 4.0). Commercial use requires explicit permission.
See [LICENSE](LICENSE).
