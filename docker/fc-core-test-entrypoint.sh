#!/usr/bin/env bash
# Builds fc_msgs from source (custom interface package, not on apt), then runs
# the fc_core suite against the mounted sources.
#
# Tests run ONE FILE PER PROCESS. This is not a style choice: test_camera.py
# installs a mock 'sensor_msgs' into sys.modules at collection time and never
# restores it, so every module collected after it fails to import real message
# types. Single-process whole-directory collection is therefore broken in this
# repo. Isolating per file reproduces what colcon test effectively does.
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

total_pass=0; total_fail=0; failed_files=()
for f in fc_core/test/test_*.py; do
    out=$(python3 -m pytest "$f" -q -p no:cacheprovider "$@" 2>&1 | tail -1) || true
    p=$(grep -oE '[0-9]+ passed' <<<"$out" | grep -oE '[0-9]+' || echo 0)
    fl=$(grep -oE '[0-9]+ (failed|error)' <<<"$out" | grep -oE '[0-9]+' | head -1 || echo 0)
    total_pass=$((total_pass + p)); total_fail=$((total_fail + fl))
    status="ok"; [ "$fl" != "0" ] && { status="FAIL"; failed_files+=("$f"); }
    printf '%-46s %-6s %s\n' "$f" "$status" "$out"
done

echo "-----------------------------------------------------------"
echo "TOTAL: ${total_pass} passed, ${total_fail} failed/errored"
[ ${#failed_files[@]} -gt 0 ] && printf 'failing files: %s\n' "${failed_files[*]}"
exit 0
