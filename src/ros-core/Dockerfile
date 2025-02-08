FROM ros:jazzy-ros-core

# FROM ubuntu:24.04

# ENV DEBIAN_FRONTEND=noninteractive

# # Install basic requirements
# RUN apt-get update && apt-get install -y \
#     curl \
#     gnupg2 \
#     lsb-release \
#     software-properties-common \
#     && rm -rf /var/lib/apt/lists/*

# # Add the ROS2 apt repository
# RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
# RUN echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/ros2.list > /dev/null

# Install ROS2 Jazzy
RUN apt-get update && apt-get install -y \
    # ros-jazzy-ros-base \
    python3-colcon-common-extensions \
    python3-rosdep \
    python3-vcstool \
    && rm -rf /var/lib/apt/lists/*

# Initialize rosdep
RUN rosdep init && rosdep update

# Set up environment
RUN echo "source /opt/ros/jazzy/setup.bash" >> /root/.bashrc

WORKDIR /workspace

CMD ["bash"]