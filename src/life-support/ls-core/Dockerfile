FROM ros:jazzy-ros-core

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3-pytest \
    python3-pytest-cov \
    python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /mushroom_farm_ws/src

# Copy files
COPY . /mushroom_farm_ws/src

# Build the workspace
WORKDIR /mushroom_farm_ws
RUN /bin/bash -c '. /opt/ros/jazzy/setup.bash && colcon build --symlink-install'
# Source the workspace in .bashrc
RUN echo "source /mushroom_farm_ws/install/setup.bash" >> /root/.bashrc

# Command to source setup files and run tests
CMD ["/bin/bash", "-c", "source /opt/ros/jazzy/setup.bash && \
    source /mushroom_farm_ws/install/setup.bash && \
    colcon test && \
    colcon test-result --verbose"]