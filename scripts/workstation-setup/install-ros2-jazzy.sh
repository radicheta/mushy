#!/usr/bin/env bash
# install-ros2-jazzy.sh
# Install ROS2 Jazzy + CycloneDDS on elder-plops.
#
# IMPORTANT: elder-plops is Linux Mint 21.2 (Ubuntu 22.04 Jammy base).
# ROS2 Jazzy binaries target Ubuntu 24.04 Noble and require:
#   - libstdc++6 >= 13.1 (Jammy has 12.3)
#   - libpython3.12t64 (not available on Jammy)
# Native apt install WILL FAIL on Mint 21.x.
#
# RECOMMENDED: Use Docker (Option A below) — Docker is already installed.
# FALLBACK: SSH to Pi and run ros2 commands there (Option B).
#
# =============================================================================
# OPTION A: Docker-based ros2 CLI (recommended for Mint 21.x)
# =============================================================================
#
# Pull the official ROS2 Jazzy image:
#   docker pull ros:jazzy
#
# Run ros2 commands with VPN network access:
#   docker run --rm --network host \
#     -e ROS_DOMAIN_ID=69 \
#     -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
#     -e CYCLONEDDS_URI=/cyclonedds.xml \
#     -v ~/.config/cyclonedds.xml:/cyclonedds.xml:ro \
#     ros:jazzy \
#     ros2 topic echo /fc/humidity --once
#
# Add a shell alias for convenience (add to ~/.bashrc):
#   alias ros2='docker run --rm --network host \
#     -e ROS_DOMAIN_ID=69 \
#     -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
#     -e CYCLONEDDS_URI=/cyclonedds.xml \
#     -v ~/.config/cyclonedds.xml:/cyclonedds.xml:ro \
#     ros:jazzy ros2'
#
# Then: ros2 topic list, ros2 topic echo /fc/humidity --once
#
# =============================================================================
# OPTION B: Run ros2 commands via SSH on Pi
# =============================================================================
#
#   ssh fc1 "source /opt/ros/jazzy/setup.bash && \
#     source /home/ubuntu/mushroom_farm_ws/install/setup.bash && \
#     ROS_DOMAIN_ID=69 ros2 topic echo /fc/humidity --once"
#
# =============================================================================
# OPTION C: Native install (Ubuntu Noble 24.04 only — NOT for Mint 21.x)
# =============================================================================
# This script is provided for reference. It will fail on Mint 21.x due to
# missing libpython3.12t64 and libstdc++ >= 13.1 system requirements.
#
# Run once on Ubuntu 24.04 Noble only:
#   sudo bash scripts/workstation-setup/install-ros2-jazzy.sh
#
# After running, open a new terminal (or run: source ~/.bashrc)
# then verify:
#   source /opt/ros/jazzy/setup.bash
#   ros2 --version
#
# CycloneDDS env vars are already in ~/.bashrc (added by project setup).
# The CycloneDDS XML config is already at ~/.config/cyclonedds.xml.

set -euo pipefail

OS_CODENAME=$(. /etc/os-release && echo "${UBUNTU_CODENAME:-unknown}")
if [ "$OS_CODENAME" != "noble" ]; then
    echo "ERROR: This script requires Ubuntu 24.04 Noble. Detected: $OS_CODENAME"
    echo ""
    echo "For Linux Mint 21.x (Jammy-based), use Docker instead:"
    echo "  docker pull ros:jazzy"
    echo "  docker run --rm --network host -e ROS_DOMAIN_ID=69 \\"
    echo "    -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \\"
    echo "    -e CYCLONEDDS_URI=/cyclonedds.xml \\"
    echo "    -v ~/.config/cyclonedds.xml:/cyclonedds.xml:ro \\"
    echo "    ros:jazzy ros2 topic echo /fc/humidity --once"
    exit 1
fi

echo "[1/4] Installing prerequisites..."
apt-get update
apt-get install -y software-properties-common curl gnupg

echo "[2/4] Adding ROS2 apt repository..."
curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu noble main" \
  > /etc/apt/sources.list.d/ros2.list

echo "[3/4] Installing ros-jazzy-ros-base + CycloneDDS RMW..."
apt-get update
apt-get install -y ros-jazzy-ros-base ros-jazzy-rmw-cyclonedds-cpp

echo "[4/4] Done. ROS2 Jazzy installed at /opt/ros/jazzy/"
echo ""
echo "Next steps:"
echo "  1. Open a new terminal (or: source ~/.bashrc)"
echo "  2. source /opt/ros/jazzy/setup.bash"
echo "  3. Confirm VPN is up: ping 172.16.10.5"
echo "  4. Verify Pi topics: ros2 topic list"
echo "  5. Read live sensor data: ros2 topic echo /fc/humidity --once"
