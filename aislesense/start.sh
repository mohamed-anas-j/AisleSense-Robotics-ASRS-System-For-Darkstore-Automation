#!/bin/bash
# =============================================================
# AisleSense Launcher — run on your RPi5
# Usage:
#   ./start.sh          (interactive menu)
#   ./start.sh mapping  (skip menu, go straight to mapping)
#   ./start.sh nav      (skip menu, go straight to navigation)
#   ./start.sh stop     (stop the container)
# =============================================================

set -e
cd "$(dirname "$0")"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

show_banner() {
    echo -e "${CYAN}"
    echo "  ╔═══════════════════════════════════════╗"
    echo "  ║         AisleSense Robot v2           ║"
    echo "  ║       RPi5 + RPLidar + Nav2           ║"
    echo "  ╚═══════════════════════════════════════╝"
    echo -e "${NC}"
}

stop_robot() {
    echo -e "${YELLOW}Stopping AisleSense...${NC}"
    docker compose down
    echo -e "${GREEN}Stopped.${NC}"
}

start_robot() {
    local mode=$1
    echo -e "${GREEN}Starting AisleSense in ${mode^^} mode...${NC}"
    
    # Stop any existing container first
    docker compose down 2>/dev/null || true
    
    # Rebuild if Dockerfile changed, otherwise use cache
    ROBOT_MODE="$mode" docker compose up --build -d
    
    echo ""
    echo -e "${GREEN}Container started! Logs:${NC}"
    echo -e "  ${CYAN}docker compose logs -f${NC}"
    echo ""
    
    if [ "$mode" == "mapping" ]; then
        echo -e "${YELLOW}MAPPING mode tips:${NC}"
        echo "  1. On your laptop, open RViz2 and add the /map topic"
        echo "  2. Drive the robot with teleop_twist_keyboard:"
        echo "     ros2 run teleop_twist_keyboard teleop_twist_keyboard"
        echo "  3. When done, save the map:"
        echo "     docker exec aislesense_ros2 bash -c 'source /opt/ros/humble/setup.bash && ros2 run nav2_map_server map_saver_cli -f /ros2_ws/my_room_map'"
        echo "     (the map files are volume-mounted, so they sync back to this folder)"
    elif [ "$mode" == "nav" ]; then
        echo -e "${YELLOW}NAVIGATION mode tips:${NC}"
        echo "  1. On your laptop, open RViz2"
        echo "  2. Set the initial pose with '2D Pose Estimate'"
        echo "  3. Send goals with '2D Goal Pose'"
    fi
    echo ""
    
    # Follow logs in foreground
    docker compose logs -f
}

save_map() {
    echo -e "${YELLOW}Saving map from running container...${NC}"
    docker exec aislesense_ros2 bash -c \
      'source /opt/ros/humble/setup.bash && ros2 run nav2_map_server map_saver_cli -f /ros2_ws/my_room_map'
    echo -e "${GREEN}Map saved to my_room_map.pgm / my_room_map.yaml${NC}"
}

# --- Handle command-line argument ---
if [ -n "$1" ]; then
    case "$1" in
        mapping|MAPPING) start_robot "mapping" ;;
        nav|NAV)         start_robot "nav" ;;
        stop|STOP)       stop_robot ;;
        save)            save_map ;;
        *)
            echo "Usage: $0 [mapping|nav|stop|save]"
            exit 1
            ;;
    esac
    exit 0
fi

# --- Interactive menu ---
show_banner

echo "  Select a mode:"
echo ""
echo -e "    ${GREEN}1)${NC} Mapping   — Build a map with SLAM + teleop"
echo -e "    ${GREEN}2)${NC} Navigate  — Autonomous navigation with Nav2"
echo -e "    ${GREEN}3)${NC} Save Map  — Save map from running mapping session"
echo -e "    ${GREEN}4)${NC} Stop      — Shut down the robot container"
echo -e "    ${GREEN}5)${NC} Logs      — View live container logs"
echo ""
read -rp "  Enter choice [1-5]: " choice

case $choice in
    1) start_robot "mapping" ;;
    2) start_robot "nav" ;;
    3) save_map ;;
    4) stop_robot ;;
    5) docker compose logs -f ;;
    *) echo "Invalid choice"; exit 1 ;;
esac
