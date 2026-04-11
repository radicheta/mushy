FROM ros:jazzy-ros-core

# Install ROS2 dependencies + build tools for native Node.js addons (rclnodejs/ref)
RUN apt-get update && apt-get install -y \
    ros-jazzy-rmw-cyclonedds-cpp \
    curl \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/bridge

# Copy package files first for Docker layer caching
COPY package.json package-lock.json* ./

# rclnodejs native addon (ref) requires AMENT_PREFIX_PATH at build time — source ROS first
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && npm install --production"

# Copy remaining source
COPY . .

# Make entrypoint executable
RUN chmod +x /opt/bridge/entrypoint.sh

EXPOSE 8081

ENTRYPOINT ["/opt/bridge/entrypoint.sh"]
