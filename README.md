# AisleSense Robotics Darkstore ASRS System

AisleSense Robotics is a darkstore ASRS platform that combines autonomous
mobile navigation, operator-assisted pickup, and vision analytics for
store replenishment workflows. The system drives from a dock to shelf
locations, presents a live camera feed, allows manual tray operations,
and hands off to a packing area for pickup confirmation.

## Highlights

- Autonomous navigation with ROS 2, Nav2, and LiDAR-based localization.
- Assisted route flow: Dock -> SHELF -> PACKING_AREA with operator gating.
- Manual drive and tray control at the shelf via the navigator UI.
- Modular stack: robot core, desktop navigator, and vision analytics.

## System Modules

- **aislesense/**: Robot core ROS 2 stack (Pi 5, L298N, encoders, IMU, LiDAR).
- **aislesense_navigator/**: Desktop GUI for mapping, region tools, and
  assisted route operations with camera preview.
- **asvision/**: Offline vision pipeline for shelf analytics and auditing.

## Operational Flow (Assisted Route)

1. **Dock**: Robot starts at the dock pose.
2. **SHELF**: Robot navigates to `SHELF`, camera feed turns on, and the
   operator can drive and push/pull the tray.
3. **Done**: Operator clicks **Done at SHELF**.
4. **PACKING_AREA**: Robot navigates to `PACKING_AREA` and waits for
   **Pickup OK**.
5. **Loop**: Robot returns to `SHELF` and repeats until **Stop / Return to Dock**.

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
Aisle_Sense_Robotics/
├── aislesense/               # Robot core stack (ROS 2, Nav2, drivers)
├── aislesense_navigator/     # Desktop navigation GUI
├── asvision/                 # Vision analytics pipeline
├── TECHNICAL_DOCUMENTATION.md
└── LICENSE
```

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0
International (CC BY-NC 4.0). Commercial use requires explicit permission.
See [LICENSE](LICENSE).
