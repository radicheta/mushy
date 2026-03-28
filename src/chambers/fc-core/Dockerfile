FROM ros:jazzy-ros-core

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-colcon-common-extensions \
    python3-rosdep \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip3 install --break-system-packages \
    RPi.GPIO \
    rpi-hardware-pwm \
    adafruit-circuitpython-dht

# Initialize rosdep
RUN rosdep init && rosdep update

# Set up workspace
WORKDIR /mushroom_farm_ws/src

# Copy package files
COPY . /mushroom_farm_ws/src/

# Build the workspace
WORKDIR /mushroom_farm_ws
RUN /bin/bash -c '. /opt/ros/jazzy/setup.bash && colcon build --symlink-install'

# Workaround for missing libexec and lib dirs in pure Python packages
RUN mkdir -p /mushroom_farm_ws/install/fc_core/libexec/fc_core
RUN mkdir -p /mushroom_farm_ws/install/fc_core/lib/fc_core

# Source the workspace in .bashrc
RUN echo "source /mushroom_farm_ws/install/setup.bash" >> /root/.bashrc

# Create launch script
RUN echo '#!/bin/bash\n\
source /opt/ros/jazzy/setup.bash\n\
source /mushroom_farm_ws/install/setup.bash\n\
ros2 launch fc_core fc.launch.py\n\
' > /launch.sh && chmod +x /launch.sh

# Set the entrypoint
ENTRYPOINT ["/launch.sh"] 