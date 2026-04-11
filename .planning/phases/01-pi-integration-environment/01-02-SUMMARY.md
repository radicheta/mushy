---
phase: 01-pi-integration-environment
plan: 02
subsystem: infra
tags: [ros2, raspberry-pi, systemd, rsync, colcon, deploy]

# Dependency graph
requires:
  - phase: 01-pi-integration-environment
    provides: SSH key-based access to fc1 (Pi at 10.68.155.53, user ubuntu)
provides:
  - One-command deploy workflow (rsync + colcon rebuild + service restart) from workstation to Pi
  - systemd service file for ROS2 launch with correct env vars (ROS_DOMAIN_ID=69, ROS_LOCALHOST_ONLY=0)
  - Developer workflow documentation for Pi setup, deploy cycle, log observation
affects: [02-safety-hardening, 03-closed-loop-control, 04-observability-integration, 05-production-deployment]

# Tech tracking
tech-stack:
  added: [systemd service unit, rsync deploy pattern]
  patterns: [rsync-colcon-rebuild deploy cycle, systemd for ROS2 node lifecycle]

key-files:
  created:
    - scripts/pi-deploy/deploy.sh
    - scripts/pi-deploy/fc-core.service
    - docs/pi-setup/dev-workflow.md
  modified: []

key-decisions:
  - "Deploy pattern is rsync to Pi + colcon rebuild on Pi (not Docker, not git pull) per D-04"
  - "ROS2 stack runs as systemd service with Restart=on-failure and 5s delay per D-05"
  - "ROS_DOMAIN_ID=69 and ROS_LOCALHOST_ONLY=0 set in systemd unit for cross-machine topic visibility"

patterns-established:
  - "Deploy: ./scripts/pi-deploy/deploy.sh from repo root — wraps rsync + remote colcon + systemctl restart"
  - "Service: ExecStart sources /opt/ros/jazzy/setup.bash then workspace setup.bash before ros2 launch"

requirements-completed: [INFRA-03, INFRA-04]

# Metrics
duration: 1min
completed: 2026-03-29
---

# Phase 01 Plan 02: Deploy Workflow & Systemd Service Summary

**rsync-based one-command deploy (workstation to Pi) with systemd service for ROS2 auto-start on reboot**

## Performance

- **Duration:** ~1 min (Task 1 only; Task 2 at checkpoint awaiting hardware verification)
- **Started:** 2026-03-29T15:38:38Z
- **Completed:** 2026-03-29T15:39:40Z (partial — Task 1 of 2)
- **Tasks:** 1/2 (Task 2 is a checkpoint:human-verify gate)
- **Files modified:** 3

## Accomplishments

- Created `scripts/pi-deploy/deploy.sh` — executable, passes `bash -n` syntax check, handles rsync exclusions for git/build/cache dirs
- Created `scripts/pi-deploy/fc-core.service` — systemd unit with correct ROS env vars, sources both setup.bash files before launch
- Created `docs/pi-setup/dev-workflow.md` — covers ROS2 install, service install, deploy cycle, log observation, cross-machine topic monitoring

## Task Commits

1. **Task 1: Create deploy script, systemd service, and workflow documentation** - `ad89efc` (feat)

## Files Created/Modified

- `scripts/pi-deploy/deploy.sh` - rsync source, rsync config, remote colcon build, systemctl restart fc-core
- `scripts/pi-deploy/fc-core.service` - systemd unit: ROS_DOMAIN_ID=69, ROS_LOCALHOST_ONLY=0, Restart=on-failure
- `docs/pi-setup/dev-workflow.md` - ROS2 install steps, service install, deploy cycle, log/topic observation

## Decisions Made

- Service sources `/opt/ros/jazzy/setup.bash` and workspace `install/setup.bash` inside a single `ExecStart` bash -c command, as systemd `Environment=` only sets variables and cannot source shell files
- Deploy script step 2 (config rsync) is technically redundant since step 1 syncs all of `src/` including config — kept as explicit step for clarity and to ensure config is always current even if only config changed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Checkpoint Status

Task 2 (`checkpoint:human-verify`) reached. Physical verification required:

1. Install systemd service on Pi
2. Run first deploy: `./scripts/pi-deploy/deploy.sh`
3. Verify `ssh fc1 "sudo systemctl status fc-core"` shows active (running)
4. Verify `ros2 topic list` on workstation (with ROS_DOMAIN_ID=69) shows `/fc/humidity`
5. Verify service survives `ssh fc1 "sudo reboot"`

## Next Phase Readiness

After Task 2 checkpoint clears:
- INFRA-03 and INFRA-04 fully satisfied
- Phase 1 Plan 3 (hardware wiring / MOSFET) can proceed
- All subsequent phases can use `./scripts/pi-deploy/deploy.sh` for code iteration

---
*Phase: 01-pi-integration-environment*
*Completed: 2026-03-29 (partial — at checkpoint)*
