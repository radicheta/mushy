#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="/app:${PYTHONPATH}"
exec python3 -m farmos_agent.farmos_agent_node
