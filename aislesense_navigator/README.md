# AisleSense Region Navigator

A standalone GUI application that loads your AisleSense navigation map, lets you
draw and name regions (e.g. *shelf*, *checkout*, *entrance*), and then navigate
to any region with a single click — sending a `NavigateToPose` goal to the Nav2
stack running on your robot.

> **No files in `../aislesense/` are modified.**  This app reads the map files
> and communicates with the robot over ROS 2 topics / actions.

---

## Quick Start

```bash
# 1. Install Python dependencies
cd aislesense_navigator
pip install -r requirements.txt

# 2. (Optional) Source ROS 2 for live navigation
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=42

# 3. Launch
python main.py                            # auto-detects ../aislesense/my_room_map.yaml
python main.py --map /path/to/map.yaml    # or specify any map
```

---

## Features

| Feature | Details |
|---------|---------|
| **Map display** | Loads any ROS 2 PGM + YAML map with zoom, pan, and scroll |
| **Region drawing** | Left-click vertices → right-click to close polygon → name it |
| **Approach pose** | After drawing, click the map to set where the robot should go; orientation auto-faces the region centre |
| **One-click nav** | Each region gets a **Go ▸** button that sends `NavigateToPose` |
| **Persistence** | Regions saved to `regions.json` — survives restarts |
| **ROS 2 fallback** | Uses `rclpy` action client if available, otherwise `ros2 topic pub` via subprocess |

---

## Workflow

1. **Open a map** — `File ▸ Open Map` or `--map` flag.
2. **Add Region** — click the toolbar button, left-click to add polygon vertices,
   right-click or press Enter to finish, type a name.
3. **Set approach pose** — after naming, click where the robot should stop.
   The green arrow shows position + orientation (auto-faces region centre).
   Press Escape to default to the region centroid.
4. **Save** — toolbar or `File ▸ Save Regions`.
5. **Navigate** — press the green **Go ▸** button in the right panel.

---

## File Structure

```
aislesense_navigator/
├── main.py              ← entry point
├── app.py               ← tkinter GUI (map editor + nav buttons)
├── map_loader.py         ← load PGM + YAML, coordinate transforms
├── region_manager.py     ← region CRUD + JSON persistence
├── navigator.py          ← send NavigateToPose via rclpy or CLI
├── config.py             ← colours, paths, defaults
├── requirements.txt
├── README.md
└── regions.json          ← auto-created on first save
```

---

## Configuration

Edit `config.py` to change:

- `ROS_DOMAIN_ID` — must match your robot's domain (default `42`)
- `DEFAULT_MAP_YAML` — fallback map path
- `REGION_COLORS` — colour palette for new regions

---

## Requirements

- **Python 3.10+**
- **Pillow**, **PyYAML**, **numpy** (see `requirements.txt`)
- **ROS 2 Humble** (optional — only needed for live navigation)
- **Nav2** running on the robot (same `ROS_DOMAIN_ID`)

---

## How Navigation Works

When you click **Go ▸**, the app:

1. Reads the region's approach point `(x, y)` and orientation `θ`
2. Converts `θ` to a quaternion
3. Sends a `NavigateToPose` action goal to the Nav2 stack on your robot
4. The robot plans a path, drives to the point, and rotates to face the region

The approach orientation is automatically calculated to **face the centre of the
region** from the approach point — so the robot ends up looking at the shelf /
area you defined.
