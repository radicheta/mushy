---
phase: 08-pi-camera-feed-in-mission-control
plan: "04"
subsystem: ui
tags: [openmct, mjpeg, camera, docker, ros2]

requires:
  - phase: 08-03
    provides: Camera type, object provider, and view provider wired into OpenMCT plugin

provides:
  - Camera object named 'Camera' (not 'FC-1 Camera') in Mission Control tree
  - Production host URLs (10.68.155.50:8081) wired into FruitingChamberPlugin() in index.html
  - fc_config.yaml with camera_simulation_mode: false (ready to deploy to Pi)
  - openmct container rebuilt and serving updated plugin.js and index.html

affects:
  - 08-human-uat
  - production deployment

tech-stack:
  added: []
  patterns:
    - "FruitingChamberPlugin accepts options object with bridgeUrl, historyUrl, cameraUrl"
    - "Production URLs hardcoded to 10.68.155.50 (pfSense DHCP reservation — static)"

key-files:
  created: []
  modified:
    - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
    - src/mission-control/frontend/index.html
    - src/chambers/fc-core/config/fc_config.yaml

key-decisions:
  - "Hardcode 10.68.155.50 in index.html — acceptable per threat model T-08-11: IP is static via pfSense DHCP reservation"
  - "docker-compose v1 ContainerConfig bug worked around by removing stale container and using docker run directly"
  - "Pi deployment committed but not executed — fc1 (10.68.155.53) was unreachable (host down); deploy.sh ready to run when Pi is online"

patterns-established:
  - "FruitingChamberPlugin options pattern: pass { bridgeUrl, historyUrl, cameraUrl } for LAN deployments"

requirements-completed: [CAM-01, CAM-02, CAM-05]

duration: 15min
completed: 2026-04-09
---

# Phase 08 Plan 04: Gap Closure — Camera Name Fix, Production URLs, Simulation Disable Summary

**Camera renamed to 'Camera', production bridge URLs wired into index.html, and camera_simulation_mode disabled in fc_config.yaml — openmct container rebuilt and serving; Pi deploy pending fc1 coming back online**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-09T22:30:00Z
- **Completed:** 2026-04-09T22:45:00Z
- **Tasks:** 2 of 3 fully executed (Task 3 is human-verify checkpoint)
- **Files modified:** 3

## Accomplishments

- Fixed camera object name from 'FC-1 Camera' to 'Camera' in plugin.js — matches sensor naming convention
- Wired production host URLs (ws://10.68.155.50:8081, http://10.68.155.50:8081/history, http://10.68.155.50:8081/camera/mjpeg) into FruitingChamberPlugin() call in index.html — feed now reachable from any LAN machine
- Set camera_simulation_mode: false in fc_config.yaml — fc_camera will capture from real USB webcam on next deploy
- Rebuilt and restarted openmct container serving updated files (verified via curl)

## Task Commits

1. **Task 1: Fix camera name and wire production URLs into plugin** - `8255d37` (feat)
2. **Task 2: Disable camera simulation mode on Pi and redeploy** - `3b813d7` (chore)
3. **Task 3: Human verify camera feed in Mission Control** - checkpoint (awaiting human)

## Files Created/Modified

- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` - Camera object name changed from 'FC-1 Camera' to 'Camera'
- `src/mission-control/frontend/index.html` - FruitingChamberPlugin() now passes production host URLs for all three connection points
- `src/chambers/fc-core/config/fc_config.yaml` - camera_simulation_mode set to false (ready for Pi deploy)

## Decisions Made

- Hardcoded 10.68.155.50 directly in index.html rather than a config file — acceptable per threat model T-08-11 (IP is static via pfSense DHCP reservation, no public exposure)
- docker-compose v1 has a ContainerConfig compatibility bug with newer Docker Engine; worked around by removing the stale container state and using `docker run` directly with the same image/network/port settings

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] docker-compose v1 ContainerConfig bug prevented container restart**
- **Found during:** Task 1 (rebuilding openmct container)
- **Issue:** `docker-compose up -d openmct` failed with `KeyError: 'ContainerConfig'` — a known incompatibility between docker-compose v1.29.2 and newer Docker Engine when recreating containers built with a newer image format
- **Fix:** Removed the stale container (`docker rm`) and started fresh with `docker run -d --name src_openmct_1 -p 8080:8080 --network src_frontend-net src_openmct:latest`
- **Files modified:** none (runtime operation)
- **Verification:** `docker ps | grep openmct` shows container running; `curl http://localhost:8080/` returns index.html with correct FruitingChamberPlugin URLs
- **Committed in:** 8255d37 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Workaround transparent to end result — container is up serving updated files. No scope creep.

## Issues Encountered

- **Pi unreachable during Task 2:** fc1 (10.68.155.53) returned "Destination Host Unreachable" — likely powered off or disconnected from LAN at time of execution. Config change (camera_simulation_mode: false) is committed and correct. Deploy must be run manually when Pi is back online:
  ```bash
  cd /mnt/slime-kingdom/opt/mushy && ./scripts/pi-deploy/deploy.sh
  ```
  After deploy, verify with:
  ```bash
  ssh fc1 "journalctl -u fc-core --since '3 minutes ago' -n 50 --no-pager | grep -i camera"
  ```

## User Setup Required

**Pi deployment is pending.** When fc1 is back online:

1. Run the deploy script from elder-plops:
   ```bash
   cd /mnt/slime-kingdom/opt/mushy && ./scripts/pi-deploy/deploy.sh
   ```
2. Verify fc_camera is capturing from hardware (not simulation):
   ```bash
   ssh fc1 "journalctl -u fc-core --since '3 minutes ago' -n 50 --no-pager | grep -i camera"
   ```
   Look for `Opened /dev/video0` or `Publishing frame` — NOT `Simulation mode`.
3. Check bridge health endpoint:
   ```bash
   curl -s http://10.68.155.50:8081/health | python3 -m json.tool | grep -A2 '"camera"'
   ```
   `camera.lastFrame` must not be null.
4. Open Mission Control at http://10.68.155.50:8080 and verify:
   - Camera appears in tree as "Camera" (not "FC-1 Camera")
   - Clicking Camera shows live video pixels (not black screen)

## Next Phase Readiness

- openmct container is rebuilt and serving correct plugin.js and index.html
- Camera name and URL fixes are complete and verified via curl
- Remaining gate: Pi deploy + human visual verification of live feed
- Task 3 (human-verify checkpoint) documents exactly what to check

---
*Phase: 08-pi-camera-feed-in-mission-control*
*Completed: 2026-04-09*
