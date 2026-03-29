#!/usr/bin/env bash
# install-ros2-jazzy.sh
# Install ROS2 Jazzy + CycloneDDS on elder-plops (requires sudo).
#
# Run once manually:
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

echo "[1/4] Installing prerequisites..."
apt-get update
apt-get install -y software-properties-common curl gnupg

echo "[2/4] Adding ROS2 apt repository..."
curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg

UBUNTU_CODENAME=$(. /etc/os-release && echo "$UBUNTU_CODENAME")
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu ${UBUNTU_CODENAME} main" \
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
