#!/usr/bin/env bash
set -euo pipefail

# Test SHT30 sensor through ROS2 stack on Pi
# Prerequisites: fc-core service running (deployed via 01-02 workflow)
#
# NOTE: The original plan called for DHT22 (adafruit_dht / GPIO4), but the
# actual implementation in fc_sensors.py uses SHT30 (adafruit-circuitpython-sht31d
# / I2C 0x44). This script validates the real hardware configuration.

PI_HOST="${PI_HOST:-fc1}"
TIMEOUT=30
TOPIC_HUMIDITY="fc/humidity"
TOPIC_TEMPERATURE="fc/temperature"

echo "=== SHT30 ROS2 Topic Validation ==="
echo "Host: ${PI_HOST}"
echo "Topics: ${TOPIC_HUMIDITY}, ${TOPIC_TEMPERATURE}"
echo "Timeout: ${TIMEOUT}s"
echo ""

# Step 1: Ensure sensor_simulation_mode: false in fc_config.yaml
echo "[1/4] Checking sensor_simulation_mode on Pi..."
SIM_MODE=$(ssh "${PI_HOST}" "grep 'sensor_simulation_mode' ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml" || echo "NOT_FOUND")
echo "  Config: ${SIM_MODE}"
if echo "${SIM_MODE}" | grep -q "true"; then
    echo ""
    echo "  WARNING: sensor_simulation_mode is true. Switching to false for real hardware test..."
    ssh "${PI_HOST}" "sed -i 's/sensor_simulation_mode: true/sensor_simulation_mode: false/' ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml"
    echo "  Rebuilding and restarting..."
    ssh "${PI_HOST}" "cd ~/mushroom_farm_ws && source /opt/ros/jazzy/setup.bash && colcon build --packages-select fc_core --symlink-install 2>&1 | tail -5"
    ssh "${PI_HOST}" "sudo systemctl restart fc-core"
    echo "  Waiting 10s for node startup..."
    sleep 10
else
    echo "  sensor_simulation_mode is false — real hardware mode active."
fi

# Step 2: Check fc_sensors node is running
echo ""
echo "[2/4] Checking fc_sensors node..."
NODE_LIST=$(ssh "${PI_HOST}" "source /opt/ros/jazzy/setup.bash && source ~/mushroom_farm_ws/install/setup.bash && export ROS_DOMAIN_ID=69 && ros2 node list 2>/dev/null" || echo "NONE")
echo "  Active nodes: ${NODE_LIST}"
if ! echo "${NODE_LIST}" | grep -q "fc_sensors"; then
    echo "  ERROR: fc_sensors node not running."
    echo "  Check logs: ssh ${PI_HOST} 'journalctl -u fc-core -n 50'"
    exit 1
fi
echo "  fc_sensors node is running."

# Step 3: Check topics exist
echo ""
echo "[3/4] Checking topics..."
TOPICS=$(ssh "${PI_HOST}" "source /opt/ros/jazzy/setup.bash && source ~/mushroom_farm_ws/install/setup.bash && export ROS_DOMAIN_ID=69 && ros2 topic list 2>/dev/null" || echo "NONE")
TOPICS_OK=true
for TOPIC in "${TOPIC_HUMIDITY}" "${TOPIC_TEMPERATURE}"; do
    if echo "${TOPICS}" | grep -q "${TOPIC}"; then
        echo "  Topic ${TOPIC} exists."
    else
        echo "  ERROR: ${TOPIC} topic not found."
        TOPICS_OK=false
    fi
done
if [ "${TOPICS_OK}" = "false" ]; then
    echo "  Available topics:"
    echo "  ${TOPICS}"
    exit 1
fi

# Step 4: Read actual humidity data from fc/humidity
echo ""
echo "[4/4] Reading humidity data from ${TOPIC_HUMIDITY} (${TIMEOUT}s timeout)..."
DATA=$(ssh "${PI_HOST}" "source /opt/ros/jazzy/setup.bash && source ~/mushroom_farm_ws/install/setup.bash && export ROS_DOMAIN_ID=69 && timeout ${TIMEOUT} ros2 topic echo ${TOPIC_HUMIDITY} --once 2>/dev/null | head -20" || echo "TIMEOUT")

if [ "${DATA}" = "TIMEOUT" ] || [ -z "${DATA}" ]; then
    echo "  ERROR: No data received on ${TOPIC_HUMIDITY} within ${TIMEOUT}s"
    echo "  Check sensor wiring (SDA=pin3, SCL=pin5) and logs:"
    echo "  ssh ${PI_HOST} 'journalctl -u fc-core -n 50'"
    exit 1
fi

echo "  Received data:"
echo "${DATA}" | sed 's/^/  /'
echo ""
echo "=== SHT30 ROS2 TOPIC TEST PASSED ==="
echo "Humidity data is being published to ${TOPIC_HUMIDITY} from real SHT30 hardware."
