---
status: partial
phase: 12-subscriber-aware-camera
source: [12-VERIFICATION.md]
started: 2026-04-13T04:30:00-03:00
updated: 2026-04-13T04:30:00-03:00
---

## Current Test

[awaiting human testing]

## Tests

### 1. Idle rate on Pi
expected: `ros2 topic hz /fc1/camera/compressed` shows ~0.000278 Hz with no MC viewers open; health endpoint returns `subscribed:false`
result: [pending]

### 2. LIVE badge on MC open
expected: Badge transitions to teal LIVE within 5s of opening Mission Control; `ros2 topic hz` jumps to ~1 Hz; health endpoint returns `subscribed:true`
result: [pending]

### 3. Grace period / idle after tab close
expected: Rate drops back to idle after 6+ seconds of no viewers; seamless ramp-up on re-open with no stutter
result: [pending]

### 4. No cycling on page refresh within 5s
expected: Quick tab close + reopen (within 5s) preserves subscription — no rate dip
result: [pending]

### 5. pytest confirmation
expected: `python3 -m pytest src/chambers/fc-core/fc_core/test/test_camera.py -v` passes all tests in pyenv environment
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
