#!/usr/bin/env python3
"""
AisleSense Region Navigator — Entry Point
=========================================
Launches the Tkinter GUI for loading a navigation map, drawing named
regions, and sending one-click goal poses to the Nav2 stack.

Usage:
    python main.py                                # Auto-detect map in ../aislesense/
    python main.py --map ../aislesense/my_room_map.yaml
    python main.py --map /path/to/map.yaml --regions my_regions.json
    python main.py --ros-domain-id 42
"""
import argparse
import os
import sys
import tkinter as tk

# Ensure this package's directory is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import AisleSenseNavigatorApp
from config import DEFAULT_MAP_YAML, DEFAULT_REGIONS_FILE


def main():
    parser = argparse.ArgumentParser(
        description="AisleSense Region Navigator — "
                    "map region editor + one‑click Nav2 navigation")
    parser.add_argument(
        "--map", "-m", type=str, default=None,
        help="Path to map YAML file (default: ../aislesense/my_room_map.yaml)")
    parser.add_argument(
        "--regions", "-r", type=str, default=DEFAULT_REGIONS_FILE,
        help="Path to regions JSON file (default: regions.json)")
    parser.add_argument(
        "--ros-domain-id", type=int, default=42,
        help="ROS_DOMAIN_ID for Nav2 communication (default: 42)")
    args = parser.parse_args()

    map_yaml = args.map
    if map_yaml is None:
        # Try the default location relative to this script
        if os.path.isfile(DEFAULT_MAP_YAML):
            map_yaml = DEFAULT_MAP_YAML

    root = tk.Tk()
    _app = AisleSenseNavigatorApp(
        root,
        map_yaml=map_yaml,
        regions_file=args.regions,
        ros_domain_id=args.ros_domain_id,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
