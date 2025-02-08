FROM ros:jazzy-ros-core

# Install Gazebo Harmonic and ROS2 integration
RUN apt-get update && apt-get install -y \
    ros-jazzy-ros-gz \
    x11-apps \
    mesa-utils \
    && rm -rf /var/lib/apt/lists/*

# Setup display environment variables
ENV DISPLAY=:0
ENV QT_X11_NO_MITSHM=1

# Add a non-root user and set up video group
RUN useradd -m developer && \
    usermod -a -G video developer

# Create script directory and copy entrypoint
COPY --chown=developer:developer entrypoint.sh /home/developer/entrypoint.sh
RUN chmod +x /home/developer/entrypoint.sh

# Switch to developer user
USER developer
WORKDIR /home/developer

# Set the entrypoint
ENTRYPOINT ["/home/developer/entrypoint.sh"]