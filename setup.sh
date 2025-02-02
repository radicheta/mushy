#!/bin/bash

# Add Gazebo Fortress installation to PATH
export PATH=$HOME/robotics/gz_ws/install/bin:~/ros2_iron_ws/install/bin:$PATH

# Set Ignition configuration path
export IGN_CONFIG_PATH="/usr/local/share/ignition:$HOME/robotics/gz_ws/install/share/ignition"

# Optional? Source the ROS and Gazebo setup scripts
source ~/ros2_iron_ws/install/setup.sh
source ~/robotics/gz_ws/install/setup.sh


source ~/mushroom_farm_ws/install/setup.sh