# AisleSense Robot — Dockerfile
# ROS 2 Humble base image with Nav2, SLAM Toolbox, and RPLidar driver.
FROM ros:humble-ros-base

# Install ROS 2 packages and system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-serial \
    nano \
    ros-humble-rplidar-ros \
    ros-humble-slam-toolbox \
    ros-humble-navigation2 \
    ros-humble-nav2-bringup \
    ros-humble-robot-localization \
    ros-humble-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

# Raspberry Pi 5 GPIO library and numerical computing
RUN pip3 install rpi-lgpio numpy

WORKDIR /ros2_ws
COPY aislesense_core.py odometry_node.py scan_stabilizer.py waypoint_collector.py /ros2_ws/

RUN echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
CMD ["/bin/bash"]
