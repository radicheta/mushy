FROM ros:jazzy-ros-core

# Install dependencies
RUN apt-get update && apt-get install -y \
    ros-jazzy-rosbridge-suite \
    python3-colcon-common-extensions \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create workspace
WORKDIR /opt/bridge

# Copy package files
COPY . .

# Clean build/install/log and build the package
RUN rm -rf build install log && \
    . /opt/ros/jazzy/setup.sh && \
    colcon build --symlink-install && \
    pip install . --break-system-packages

# Make entrypoint executable
RUN chmod +x /opt/bridge/entrypoint.sh

# Expose WebSocket port
EXPOSE 8081

# Use entrypoint
ENTRYPOINT ["/opt/bridge/entrypoint.sh"]
