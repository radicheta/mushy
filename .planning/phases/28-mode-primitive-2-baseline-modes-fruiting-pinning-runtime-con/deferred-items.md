# Phase 28 deferred items

- [28-05] burn_bar.test.js — 2 pre-existing test failures (jimp/font rendering); unrelated to plan 28-05 scope. Caught during full-suite regression check.

- [28-07] **RESOLVED 2026-05-08 — was misdiagnosed.** Original report: `ros2 service call /set_mode` from non-interactive SSH fails with `rcl node's context is invalid`. Actual root cause: 28-07 executor used wrong field name (`{mode: pinning}`) — `SetMode.srv` request is `string name`, not `string mode`. The error they saw was `Failed to populate field: 'SetMode_Request' object has no attribute 'mode'`, which they apparently misread. Re-tested 2026-05-08 with correct `{name: pinning}`: full roundtrip success from non-interactive SSH (`success=True`, mode swapped, `source='service_call'`). No DDS discovery race exists. MODE-03 service path now demonstrably works via SSH CLI as well as the param-set path.
