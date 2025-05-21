#!/bin/bash

# # Add Gazebo Fortress installation to PATH
# export PATH=$HOME/robotics/gz_ws/install/bin:~/ros2_iron_ws/install/bin:$PATH

# # Set Ignition configuration path
# export IGN_CONFIG_PATH="/usr/local/share/ignition:$HOME/robotics/gz_ws/install/share/ignition"
# export IGN_GAZEBO_SYSTEM_PLUGIN_PATH=$HOME/robotics/gz_ws/install/lib/ign-gazebo-6/plugins:$IGN_GAZEBO_SYSTEM_PLUGIN_PATH

# Source ROS2 Jazzy
source /opt/ros/jazzy/setup.bash

# Source the workspace
source ~/mushroom_farm_ws/install/setup.sh

# Optional? Source the ROS and Gazebo setup scripts
# source ~/ros2_iron_ws/install/setup.sh
# source ~/robotics/gz_ws/install/setup.sh

# On all devices, add to ~/.bashrc
export ROS_DOMAIN_ID=69  # Choose any number between 0-101, use same on all devices
export ROS_LOCALHOST_ONLY=0  # Allow external connections