#!/bin/bash
set -x  # Print commands for debugging
source /opt/ros/jazzy/setup.bash

# Test NVIDIA GPU access
echo "Testing NVIDIA GPU access:"
nvidia-smi || echo "NVIDIA GPU not accessible"

# Print graphics info
echo "Graphics information:"
glxinfo | grep "OpenGL renderer" || echo "glxinfo not available"

# # Launch TurtleBot4 in Gazebo
# ros2 launch turtlebot4_gz_bringup turtlebot4_gz.launch.py

# Launch TurtleBot4 with custom position (away from dock)
ros2 launch turtlebot4_gz_bringup turtlebot4_gz.launch.py x:=1.0 y:=1.0 yaw:=0.0

exec "$@"