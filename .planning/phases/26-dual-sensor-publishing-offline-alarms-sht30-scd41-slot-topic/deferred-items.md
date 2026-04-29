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

## Process miss: slot-2 was contract-tested at the bridge but invisible to the farmer

**Surfaced:** UAT-8 attempt 2026-04-29.

**Symptom:** `/fc1/humidity_2` and `/fc1/temperature_2` were publishing on the Pi (Plan 26-01 ✓), the bridge was subscribing and writing to Timescale (Plan 26-02 ✓), and `/history/fc.humidity_2` would have worked — *except* that two pieces of plumbing tying it to the user-facing UI were never touched:

1. `src/mission-control/bridge/src/index.js` — `ALLOWED_TOPICS` allowlist for the history endpoint (line 346) listed only the original 4 keys; slot-2 history requests would 400.
2. `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` — `SENSORS` array (line 15) and `fieldToKey` map (line 265) advertised only the original 4 sensors; slot-2 had no telemetry object in the OpenMCT tree, so the farmer literally could not pull it onto a plot.

The farmer attempted UAT-8 and reported "I only see one humidity in MC" — that was the diagnostic that surfaced the miss. Patched same session (commit `2b5ae75`).

**Why this happened (process gap, not a code defect):** Plan 26-02 was scoped as "Bridge slot-2 forwarding (VOLATILE-QoS subs for `fc1/temperature_2` & `fc1/humidity_2` → WS broadcast + TimescaleDB)". The plan was completed exactly as written — the bridge does forward, broadcast, and persist. But the *demand* side — what makes the data appear in the farmer's UI — is split across:
- the bridge's own history endpoint allowlist (server-side gate), and
- the OpenMCT plugin's sensor/dispatch tables (client-side discovery).

Neither was named in any plan, because plan-26-03 was scoped to alerter changes, not UI plumbing.

**Lesson for future "expose new telemetry" phases:** the unit of work is not "publish + bridge + persist" — it's the full demand chain ending at the UI element the farmer interacts with. A plan that adds a new `/fc1/foo` topic should explicitly enumerate every gate between publisher and a click-able OpenMCT object: ROS publisher → bridge subscriber → DB write → bridge `ALLOWED_TOPICS` (history) → bridge WS broadcast field → OpenMCT plugin `SENSORS` entry → OpenMCT plugin `fieldToKey` entry → tree composition. Six of the eight were touched in 26-01/26-02; the two history+plugin steps weren't.

**Concrete suggestion:** the plan-template (or the plan-checker agent) for "new telemetry" phases should include a checklist verifying *every* gate is named in at least one plan task. Equally, a verification script that diffs `bridge ALLOWED_TOPICS` vs `Timescale topics with rows in last 1h` vs `OpenMCT plugin SENSORS keys` would have caught this in seconds.

**Why captured here, not as a backlog phase:** this is process/template work, not chamber feature work — belongs adjacent to GSD plan templates, not the product roadmap.
