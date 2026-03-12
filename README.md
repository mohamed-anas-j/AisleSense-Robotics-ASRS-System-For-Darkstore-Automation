<p align="center">
  <h1 align="center">AisleSense</h1>
  <p align="center">
    Autonomous retail shelf auditing robot — LiDAR navigation meets computer vision analytics
  </p>
</p>

<p align="center">
  <a href="#demo">Demo</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#modules">Modules</a> •
  <a href="#vision-pipeline">Vision Pipeline</a> •
  <a href="#license">License</a>
</p>

---

## Objective

AisleSense is an autonomous mobile robot designed to patrol retail store aisles and audit shelf conditions in real time. The system combines a ROS 2-based differential-drive robot with a multi-stage computer vision pipeline to detect shelf gaps, estimate restock needs, and compute share-of-shelf metrics — all without human intervention.

The robot navigates pre-mapped store environments, stops at designated shelf locations, and captures images for offline analysis. The result is an actionable audit report that tells store staff exactly where stock is missing, how urgently it needs restocking, and how product facings are distributed across shelf space.

---

## Demo

### 🤖 Robot Navigation in Action

Real-world autonomous navigation demonstration showing the robot patrolling aisles with LiDAR-based localization and path planning:

[**Watch Demo Video →** Demo_IRL_Real.mp4](aislesense/Demo_IRL_Real.mp4)

### 📊 RViz Visualization

ROS 2 visualization showing the robot's sensor fusion, costmaps, and real-time trajectory planning in RViz2:

[**Watch RViz Demo →** Demo_IRL_Rviz.webm](aislesense/Demo_IRL_Rviz.webm)

### 🔍 Vision Pipeline Analytics

Complete vision pipeline demonstration — shelf segmentation, product detection, depth estimation, and retail analytics dashboard:

[**Watch Pipeline Demo →** AisleSense_Detection_Pipeline_Demo.mp4](aislesense/AisleSense_Detection_Pipeline_Demo.mp4)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              AISLESENSE ROBOT  (Raspberry Pi 5)         │
│                                                         │
│   RPLidar A1M8 ──► rplidar_node ──► scan_stabilizer    │
│                                      (720-beam resample)│
│                                            │            │
│   Arduino ──► aislesense_core              │            │
│    ├─ Wheel encoders (1170 ticks/rev)      │            │
│    └─ MPU6050 IMU                          │            │
│         │                                  │            │
│         ▼                                  ▼            │
│   odometry_node ──►┌──────────┐◄── /scan_stable        │
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
│    L298N H-bridge ◄── cmd_vel ◄── DWB Local Planner    │
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
│   • Interactive region drawing (polygon tool)            │
│   • Approach pose placement per region                   │
│   • Dock pose (robot home position)                      │
│   • Scan tour: ordered multi-region autonomous patrol    │
│   • Sends NavigateToPose goals via ROS 2 action client   │
└─────────────────────────────────────────────────────────┘
                        │
                  Shelf images
                        │
┌───────────────────────▼─────────────────────────────────┐
│              ASVISION  (Offline Analytics)               │
│                                                         │
│   Stage 1 ─ Shelf Segmentation    (YOLO11x-seg)        │
│   Stage 2 ─ Product Detection     (YOLO11x)            │
│   Stage 3 ─ Depth Estimation      (Depth Anything V2)  │
│   Stage 4 ─ Text Verification     (OCR — planned)       │
│                                                         │
│   Analytics Engine                                       │
│   ├── Gap detection (geometry + depth severity grading)  │
│   ├── Restock volume estimation                          │
│   ├── Share of shelf % (SOS)                             │
│   └── Per-shelf item density                             │
│                                                         │
│   Output ─ Streamlit dashboard with KPI cards,           │
│            annotated visualisations, action reports       │
└─────────────────────────────────────────────────────────┘
```

---

## Modules

### `aislesense/` — Robot Core

The physical robot and its entire ROS 2 stack, containerised with Docker on a Raspberry Pi 5.

| Component | Detail |
|---|---|
| **Compute** | Raspberry Pi 5 |
| **LiDAR** | RPLidar A1M8 — 360° scanning, ~720 beams/rev |
| **Drive** | Differential drive, L298N H-bridge, PWM motor control |
| **Odometry** | Wheel encoders (1170 ticks/rev) via Arduino |
| **IMU** | MPU6050 (gyro + accelerometer) via Arduino |
| **Chassis** | 35 × 35 cm, 5 cm wheels, 25 cm wheelbase |

**Operating modes** (selected at launch):

| Mode | Stack | Purpose |
|---|---|---|
| **Mapping** | SLAM Toolbox + EKF | Build occupancy grid of the store |
| **Navigation** | Nav2 + AMCL + EKF | Autonomous point-to-point driving |
| **Standby** | Hardware nodes only | Sensor streams without planning |

**Sensor fusion** — An Extended Kalman Filter fuses encoder-derived linear velocity with IMU gyroscope yaw rate. Separate noise profiles are used for mapping (tight, slow teleop) and navigation (looser, fast autonomous turns).

**Scan stabiliser** — Resamples variable RPLidar beam counts into a fixed 720-beam output using nearest-neighbour mapping, preserving invalid (`inf`) readings so SLAM and Nav2 never hallucinate phantom obstacles.

**TF tree:**
```
map ── (AMCL) ──► odom ── (EKF) ──► base_link ──► laser
                                         ├──► imu_link
                                         └──► base_footprint
```

### `aislesense_navigator/` — Navigation GUI

A Tkinter desktop application for managing the robot's patrol routes.

- **Map viewer** — Renders the occupancy grid with zoom, pan, and scroll
- **Region tool** — Draw named polygons (e.g. "Aisle 3 — Top Shelf") directly on the map
- **Approach poses** — Click to place where the robot should stop; orientation auto-faces the region centroid
- **Dock pose** — Set the robot's home/charging position
- **Scan tour** — Order regions into a patrol sequence; one click starts an autonomous multi-stop tour
- **ROS 2 integration** — Sends `NavigateToPose` action goals and publishes initial pose estimates

### `asvision/` — Vision & Analytics

An offline, four-stage ONNX inference pipeline with a Streamlit dashboard for retail shelf auditing.

| Stage | Model | Output |
|---|---|---|
| **1. Shelf Segmentation** | YOLO11x-seg | Shelf instance polygons & masks, sorted top → bottom |
| **2. Product Detection** | YOLO11x | Item bounding boxes assigned to shelves (IoU / containment / nearest centroid) |
| **3. Depth Estimation** | Depth Anything V2 Large | Normalised depth map — high values = deep voids |
| **4. Text Verification** | EasyOCR (planned) | Brand / price / expiry OCR |

ONNX sessions are created and destroyed sequentially so the pipeline stays within a 4 GB VRAM budget.

---

## Vision Pipeline

### Gap Detection

Gaps are detected **geometry-first**: any horizontal span on a shelf with no product coverage is a gap, regardless of depth. Depth is then used to grade severity:

| Depth | Severity | Meaning |
|---|---|---|
| ≥ 0.85 | **HIGH** | Deep void — urgent restock |
| ≥ 0.65 | **MEDIUM** | Partial gap — items pushed back |
| < 0.65 | **LOW** | Shallow gap — minor facing issue |

### Restock Estimation

Items with high median depth indicate empty space in front of them on the shelf. The system estimates void depth in centimetres (assuming a 45 cm shelf depth) and calculates how many product units would fill the gap.

### Share of Shelf

Per-class share of shelf is computed as the ratio of each product class's total bounding-box width to the shelf's total width, reported as a percentage.

### Dashboard

The Streamlit dashboard presents:
- KPI summary cards (total items, gaps, restock needs, top SOS %)
- Six visualisation panels: camera feed, shelf segmentation, product detection, gap overlay, depth heatmap, full composite
- Action reports with restock priority rankings
- Raw data table for every detected item

---

## ROS 2 Topic Map

| Topic | Message Type | Publisher | Subscriber |
|---|---|---|---|
| `/scan` | `LaserScan` | rplidar_node | scan_stabilizer |
| `/scan_stable` | `LaserScan` | scan_stabilizer | SLAM / AMCL / costmaps |
| `/left_ticks` | `Int32` | aislesense_core | odometry_node |
| `/right_ticks` | `Int32` | aislesense_core | odometry_node |
| `/imu/data_raw` | `Imu` | aislesense_core | EKF |
| `/odom` | `Odometry` | odometry_node | EKF / Nav2 controller |
| `/cmd_vel` | `Twist` | Nav2 / teleop | aislesense_core |
| `/goal_pose` | `PoseStamped` | Navigator / RViz2 | waypoint_collector |
| `/initialpose` | `PoseWithCovarianceStamped` | Navigator | AMCL |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Robot middleware | ROS 2 Humble |
| Autonomous navigation | Nav2 (AMCL + DWB planner) |
| Mapping | SLAM Toolbox |
| Sensor fusion | robot_localization (EKF) |
| LiDAR driver | rplidar_ros |
| Containerisation | Docker + docker-compose |
| Navigator GUI | Tkinter + Pillow |
| Vision inference | ONNX Runtime (CPU / GPU) |
| Vision models | YOLO11x, YOLO11x-seg, Depth Anything V2 Large |
| Analytics dashboard | Streamlit |
| Robot compute | Raspberry Pi 5 |

---

## Repository Structure

```
aislesense/
├── aislesense/                  # Robot core — ROS 2 nodes, configs, Docker
│   ├── aislesense_core.py       # Motor control + sensor I/O node
│   ├── odometry_node.py         # Encoder-based odometry publisher
│   ├── scan_stabilizer.py       # LiDAR beam-count normaliser
│   ├── waypoint_collector.py    # Nav2 waypoint action client
│   ├── nav2_params.yaml         # Nav2 stack parameters
│   ├── ekf.yaml                 # EKF config (navigation mode)
│   ├── ekf_mapping.yaml         # EKF config (mapping mode)
│   ├── slam_params.yaml         # SLAM Toolbox parameters
│   ├── docker-compose.yml       # Container orchestration
│   ├── Dockerfile               # ROS 2 Humble + dependencies
│   ├── entrypoint.sh            # Node launch orchestrator
│   └── start.sh                 # Mode selector (mapping/nav/standby)
│
├── aislesense_navigator/        # Desktop navigation GUI
│   ├── app.py                   # Tkinter application
│   ├── navigator.py             # ROS 2 action client
│   ├── map_loader.py            # PGM/YAML map I/O
│   ├── region_manager.py        # Region polygon persistence
│   └── regions.json             # Saved regions + scan tour
│
└── asvision/                    # Offline vision analytics
    ├── app.py                   # Streamlit dashboard
    ├── pipeline/
    │   ├── shelf_segmenter.py   # Stage 1 — shelf instance segmentation
    │   ├── item_detector.py     # Stage 2 — product detection
    │   ├── depth_estimator.py   # Stage 3 — monocular depth
    │   ├── text_verifier.py     # Stage 4 — OCR (planned)
    │   ├── preprocessor.py      # Image preprocessing
    │   ├── postprocessor.py     # YOLO output parsing + NMS
    │   └── session_manager.py   # ONNX session lifecycle
    ├── analytics/
    │   └── retail_analytics.py  # KPI computation engine
    └── utils/
        └── visualization.py     # Annotated image rendering
```

---

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** license.

You are free to:
- **Share** — copy and redistribute the material in any medium or format
- **Adapt** — remix, transform, and build upon the material

Under the following terms:
- **Attribution** — You must give appropriate credit, provide a link to the license, and indicate if changes were made.
- **NonCommercial** — You may not use the material for commercial purposes.

Full license text: [https://creativecommons.org/licenses/by-nc/4.0/legalcode](https://creativecommons.org/licenses/by-nc/4.0/legalcode)

© 2026 AisleSense. All rights reserved for commercial use.
