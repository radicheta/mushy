---
phase: 14
plan: 02
subsystem: fc_camera
tags: [hotfix, camera, rclpy, dds, subscriber-detection, tdd]
dependency_graph:
  requires: [14-01]
  provides: [HFIX-01, HFIX-02]
  affects: [fc_camera.py, test_camera.py]
tech_stack:
  added: []
  patterns: [1Hz polling timer, node-level graph introspection via count_subscribers()]
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_camera.py
    - src/chambers/fc-core/fc_core/test/test_camera.py
decisions:
  - "Path A confirmed (per orchestrator context): node.count_subscribers() polls a different cache than publisher.get_subscription_count()"
  - "1 Hz graph-poll timer added alongside existing idle/active cam timer — purely additive, does not replace Phase 12 logic"
  - "capture_and_publish ORs both caches: writer_count if writer_count > 0 else graph_count"
  - "_ramp_up log now reports both writer= and graph= counts for post-mortem diagnostics"
metrics:
  duration_minutes: 26
  completed: "2026-04-18T00:26:24Z"
  tasks_completed: 3
  files_modified: 2
---

# Phase 14 Plan 02: fc_camera idle-stall fix + regression tests Summary

1Hz graph-poll fallback via `node.count_subscribers()` closes the Phase 12 stall where writer-local DDS cache drifted to 0 while the bridge subscription remained live on the graph.

## What Was Built

### fc_camera.py patch (~53 lines added)

- `self._camera_topic = 'fc1/camera/compressed'` — single string constant used by publisher and both poll paths, eliminating string drift.
- `self._graph_poll_timer = self.create_timer(1.0, self._graph_poll)` — 1 Hz timer created alongside the existing capture timer.
- `_graph_poll()` method — checks `self.count_subscribers(self._camera_topic)`; if non-zero and node is idle, calls `_ramp_up()`. Returns immediately if already active. Wraps the rclpy call in try/except so no introspection hiccup can crash the node.
- `capture_and_publish()` updated — now ORs `writer_count` (publisher-local cache) with `graph_count` (node-level cache). Happy path unchanged; stale-writer path now recovers.
- `_ramp_up()` log updated — now emits `writer=N graph=M subscriber(s)` to make post-mortem diagnosis trivial.
- `destroy_node()` updated — cleans up `_graph_poll_timer` alongside existing grace timer cleanup.

### test_camera.py additions (~88 lines added)

`FakeNode` extended:
- `self._node_sub_count = {}` — instance dict simulating node-level graph cache, independently mutable from `FakePublisher._sub_count`.
- `count_subscribers(topic)` — returns `self._node_sub_count.get(topic, 0)`.
- `count_publishers(topic)` — stub returning 1 (satisfies any future call).

`TestIdleToActiveRecovery` class (3 tests):
- `test_node_level_sub_count_drives_ramp_up` — writer cache = 0, graph cache = 1 → graph-poll fires → active. This is the canonical Phase 12 stall reproduced in the harness.
- `test_long_idle_then_graph_sees_sub_ramps_up` — 10 idle ticks with both caches at 0, then graph cache flips to 1, graph-poll fires → active.
- `test_happy_path_both_caches_agree` — both caches at 1 → ramp up via capture_and_publish; both at 0 → grace timer starts. Phase 12 behaviour preserved.

## Test Run Output

```
============================= test session starts ==============================
platform linux -- Python 3.11.12, pytest-9.0.2
collected 15 items

TestCameraSimMode::test_camera_sim_mode PASSED
TestCameraUnavailable::test_camera_unavailable PASSED
TestCameraPublishesCompressedImage::test_camera_publishes_compressed_image PASSED
TestCameraParametersDeclared::test_camera_parameters_declared PASSED
TestSubscriberAwareCamera::test_new_params_declared PASSED
TestSubscriberAwareCamera::test_ramp_up_on_subscriber PASSED
TestSubscriberAwareCamera::test_starts_idle PASSED
TestSubscriberAwareCamera::test_stays_active_while_subscribed PASSED
TestSubscriberGracePeriod::test_destroy_node_cleans_grace PASSED
TestSubscriberGracePeriod::test_grace_expires_drops_to_idle PASSED
TestSubscriberGracePeriod::test_grace_starts_on_unsub PASSED
TestSubscriberGracePeriod::test_resub_cancels_grace PASSED
TestIdleToActiveRecovery::test_happy_path_both_caches_agree PASSED
TestIdleToActiveRecovery::test_long_idle_then_graph_sees_sub_ramps_up PASSED
TestIdleToActiveRecovery::test_node_level_sub_count_drives_ramp_up PASSED

============================== 15 passed in 0.03s ==============================
```

RED phase confirmed 2/3 new tests failing (no graph-poll timer existed). GREEN phase: all 15 pass.

colcon test not run in this sandbox (no ROS2 Jazzy environment; pyenv `mushroom_farm` not present on this worktree). Will be validated on fc1 during plan 14-05 deploy + soak.

## Commit

- `3e7d65c` — `fix(14): add 1Hz graph-poll fallback for fc_camera idle-stall`
  - Files: `fc_camera.py` (+53 lines), `test_camera.py` (+88 lines)
  - No Co-Authored-By trailer.

## Deviations from Plan

None — plan executed exactly as written.

The only minor note: `_ramp_up` calls `self.count_subscribers(self._camera_topic)` in the log line, so `count_subscribers` appears 4 times total (not 2). The plan said "used in both _graph_poll and capture_and_publish" — it is also in `_ramp_up`'s log line. This is an additive improvement, not a deviation.

## Timer Interaction with Other fc_core Nodes

`_graph_poll_timer` runs at 1 Hz within `FcCamera`'s executor. `fc_controller`, `fc_sensors`, and `fc_display` are independent ROS2 nodes running their own timer callbacks — they are not affected. The graph-poll callback is a single `count_subscribers()` call with no publish and no state mutation beyond `_ramp_up()` (which is idempotent when `_is_active` is already `True`). No interaction risk.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced. `count_subscribers()` is a read-only local rclpy call.

## Self-Check: PASSED

- `src/chambers/fc-core/fc_core/fc_camera.py` — exists, contains `self.count_subscribers(` (4 occurrences).
- `src/chambers/fc-core/fc_core/test/test_camera.py` — exists, contains `class TestIdleToActiveRecovery`.
- Commit `3e7d65c` — present in git log.
- No Co-Authored-By trailer in commit.
