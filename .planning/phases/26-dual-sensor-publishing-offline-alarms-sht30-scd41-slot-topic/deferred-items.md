# Phase 26 — Deferred Items

Items observed during execution that are out-of-scope per the per-task scope-boundary rule. Each must NOT be fixed inline; logged here for future cleanup.

## Pre-existing test isolation: test_camera.py pollutes sys.modules

**Source:** `src/chambers/fc-core/fc_core/test/test_camera.py` (commit fd5b7f7, Phase 08-01).

**Symptom:** Running `pytest fc_core/test/` (or `colcon test --packages-select fc_core` on dev workstation) fails with:
```
ImportError: cannot import name 'Temperature' from 'sensor_msgs.msg' (unknown location)
```
during collection of `test_controller.py` or `test_sensors.py`, because `test_camera.py` installs MagicMock entries into `sys.modules['rclpy']`, `sys.modules['rclpy.node']`, `sys.modules['sensor_msgs']`, and `sys.modules['sensor_msgs.msg']` at module-import time (via module-level helper functions).

**Workaround in use:** Run explicit file lists or `--ignore=fc_core/test/test_camera.py`. Phase 26 verification used:
```
pytest fc_core/test/test_controller.py fc_core/test/test_sensors.py
```
which yields the green 38/38 expected.

**Root cause:** `test_camera.py` stubs ROS imports because the camera module imports `cv2` and the rest of rclpy at module-load time, and the test runner did not have ROS available at the time of authorship. The cleanest fix is to move the sys.modules patching inside a fixture/setUpClass with explicit teardown via `monkeypatch` or `unittest.mock.patch.dict(sys.modules, ...)`.

**Why deferred:** Pre-existing (4+ months old), affects only dev-loop pytest. The colcon-pytest production invocation runs each file in its own pytest process via the entrypoint hook, so CI is unaffected. Phase 26 does not introduce or worsen this issue.

**Suggested fix (future):** Refactor `test_camera.py` to use `pytest.fixture(autouse=False)` for sys.modules injection, scoped to test_camera tests only. Tracked under future tech-debt cleanup.
