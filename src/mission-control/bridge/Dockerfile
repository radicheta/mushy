FROM ros:jazzy-ros-core

# Install ROS2 + colcon (for fc_msgs srv generation) + native build deps
RUN apt-get update && apt-get install -y \
    ros-jazzy-rmw-cyclonedds-cpp \
    ros-jazzy-rosidl-default-generators \
    ros-jazzy-rosidl-default-runtime \
    ros-jazzy-builtin-interfaces \
    python3-colcon-common-extensions \
    cmake \
    curl \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Build fc_msgs into a local overlay (Phase 31: bridge calls /fc_controller/start_experiment + cancel_experiment)
WORKDIR /opt/fc_msgs_ws
COPY src/chambers/fc-msgs/ ./src/fc_msgs/
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_msgs"

WORKDIR /opt/bridge

# Copy package files first for Docker layer caching
COPY src/mission-control/bridge/package.json src/mission-control/bridge/package-lock.json* ./

# rclnodejs native addon needs both ROS env AND fc_msgs overlay sourced at npm install
# (msg/srv JS bindings are generated at install time from AMENT_PREFIX_PATH)
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && source /opt/fc_msgs_ws/install/setup.bash && npm install --production"

# Copy remaining bridge source
COPY src/mission-control/bridge/ ./

# Make entrypoint executable
RUN chmod +x /opt/bridge/entrypoint.sh

EXPOSE 8081

ENTRYPOINT ["/opt/bridge/entrypoint.sh"]
