#!/usr/bin/env bash
# Builds fc_msgs from source (custom interface package, not on apt), then runs
# the fc_core suite against the mounted sources.
#
# Runs the whole test directory in ONE pytest process. This used to be
# impossible: test_camera.py installed mock 'rclpy' and 'sensor_msgs' modules
# into sys.modules at import time, and because pytest imports every test module
# during collection before running any of them, every module collected after it
# got the stubs instead of the real message types. The workaround was one file
# per process, which was slower and hid genuine cross-file interactions.
#
# Fixed under MUSHY-66: the stubs are built at import but installed only in
# test_camera's setUpModule, and removed again in tearDownModule.
set -eo pipefail   # NOT -u: ROS setup.bash references unbound vars

source /opt/ros/jazzy/setup.bash

mkdir -p /ws/src
cp -r /src/fc-msgs /ws/src/
cp -r /src/fc-core /ws/src/

cd /ws
colcon build --packages-select fc_msgs --cmake-args -DCMAKE_BUILD_TYPE=Release >/tmp/build.log 2>&1 || {
    echo "=== fc_msgs build FAILED ==="; tail -30 /tmp/build.log; exit 1; }
source /ws/install/setup.bash

cd /ws/src/fc-core
export PYTHONPATH="/ws/src/fc-core:${PYTHONPATH}"

exec python3 -m pytest fc_core/test/ -p no:cacheprovider "$@"
