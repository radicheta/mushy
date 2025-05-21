# Base image
FROM ros:jazzy-ros-core

# Install Gazebo and ROS2 integration packages
RUN apt-get update && apt-get install -y \
    ros-jazzy-ros-gz \
    ros-jazzy-ros-gz-bridge \
    ros-jazzy-ros-gz-sim \
    ros-jazzy-ros-gz-sim-demos \
    ros-jazzy-turtlebot4-simulator \
    ros-jazzy-turtlebot4-gz-bringup \
    ros-jazzy-turtlebot4-gz-toolbox \
    ros-jazzy-gz-sim-vendor \
    ros-jazzy-teleop-twist-keyboard \
    ros-jazzy-turtlebot4-description \
    ros-jazzy-irobot-create-common-bringup \
    ros-jazzy-irobot-create-gz-bringup \
    ros-jazzy-irobot-create-gz-plugins \
    ros-jazzy-irobot-create-description \
    x11-apps \
    mesa-utils \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies for ROS2 build system (colcon, rosdep, etc.)
RUN apt-get update && apt-get install -y \
    python3-rosdep \
    python3-colcon-common-extensions \
    python3-argcomplete \
    git

# Initialize rosdep and update
RUN rosdep init && rosdep update

# Clone TurtleBot 4 repo
RUN mkdir -p /home/ubuntu/turtlebot4_ws/src && \
    cd /home/ubuntu/turtlebot4_ws && \
    git clone https://github.com/turtlebot/turtlebot4.git src/turtlebot4

# Install dependencies using rosdep
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && rosdep install --from-paths /home/ubuntu/turtlebot4_ws/src --ignore-src -r -y"

# Build workspace using colcon
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && cd /home/ubuntu/turtlebot4_ws && colcon build"

# Source workspace in bashrc
RUN echo 'source /home/ubuntu/turtlebot4_ws/install/setup.bash' >> /home/ubuntu/.bashrc

# Set the working directory
WORKDIR /home/ubuntu

# Copy GUI config and set permissions
COPY gui.config /home/ubuntu/.gz/sim/8/gui.config
RUN chown -R ubuntu:ubuntu /home/ubuntu/.gz/

# Copy entrypoint script and set permissions
COPY entrypoint.sh /home/ubuntu/entrypoint.sh
RUN chown ubuntu:ubuntu /home/ubuntu/entrypoint.sh && \
    chmod 755 /home/ubuntu/entrypoint.sh

# Switch to non-root user
USER ubuntu

# Set the entrypoint
ENTRYPOINT ["/home/ubuntu/entrypoint.sh"]
