# Phase 1: Pi Integration & Environment - Context

**Gathered:** 2026-03-28
**Status:** Partial — Pi current state discussion deferred (will SSH to Pi next session)

<domain>
## Phase Boundary

Get developer access to FC-1 Pi, deploy the ROS2 stack natively, wire the MOSFET with gate pull-down resistor, and confirm DHT22 reads correctly on real hardware.

This phase is done when: SSH works, ROS2 stack runs on Pi and is visible on ROS domain from workstation, MOSFET is wired, DHT22 reads via `ros2 topic echo fc/humidity`.

</domain>

<decisions>
## Implementation Decisions

### Hardware

- **D-01:** FC-1 runs on **Raspberry Pi 4** (not Pi 5). RPi.GPIO library is compatible — no migration to rpi-lgpio needed.
- **D-02:** OS target: **Ubuntu 24.04 (Noble)**. Flash fresh if needed. ROS2 Jazzy installs natively on Ubuntu 24.04. User is comfortable with Ubuntu.

### Deployment Method

- **D-03:** **Native ROS2 installation** on Pi (not Docker). Docker is not used on the Pi.
- **D-04:** Code deployment workflow: **rsync or git pull** from workstation → **colcon rebuild on Pi**.
- **D-05:** Node runtime: **systemd service** — ROS2 launch runs as a systemd unit (auto-restart on failure, survives reboot).

### Network / VPN

- **D-06:** Pi gets a **static IP** on the LAN (192.168.88.x range). Initial SSH access is via this static IP.
- **D-07:** **LAN-first approach**: Phase 1 succeeds over LAN SSH. WireGuard VPN config (`wg0.conf.template`) is prepared and documented, but VPN verification is NOT a Phase 1 blocker — VPN connects "when server is reachable."
- **D-08:** A WireGuard server already exists but may be intermittently inaccessible from the workstation. Plan 01-01 should fill the template and document the connection steps without blocking on server availability.

### Claude's Discretion

- Pi current state (fresh vs partially set up, whether SSH keys need to be added) — to be determined next session when user boots Pi and attempts SSH.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Specs
- `.planning/REQUIREMENTS.md` — All v1 requirements; Phase 1 covers INFRA-01–04, HW-01–03, SENS-01
- `.planning/ROADMAP.md` §Phase 1 — Success criteria and plan breakdown

### Existing Code
- `src/chambers/fc-core/config/fc_config.yaml` — `simulation_mode: true` must be flipped to `false` for real hardware
- `wg0.conf.template` — WireGuard peer config template; `${WG_PRIVATE_KEY}`, `${WG_SERVER_PUBLIC_KEY}`, `${WG_SERVER_ENDPOINT}` must be filled

### Codebase Analysis
- `.planning/codebase/CONCERNS.md` — GPIO library deprecation notes, RPi.GPIO status

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `wg0.conf.template` — WireGuard peer config already in repo; plan 01-01 fills variables and deploys to Pi
- `src/chambers/fc-core/Dockerfile` — NOT used for Pi deployment (native install chosen), but useful as reference for what Python packages are needed
- `src/chambers/fc-core/launch/fc.launch.py` — the launch file that becomes the systemd service entrypoint

### Established Patterns
- `fc_config.yaml` is the single config source — `simulation_mode`, GPIO pins, all parameters go here
- `ROS_DOMAIN_ID=69` — must be set on Pi for cross-machine topic visibility

### Integration Points
- Pi must be on same ROS domain (ID=69) as workstation for `ros2 topic list` to work across machines
- systemd service must source `/opt/ros/jazzy/setup.bash` and workspace `install/setup.bash` before launching

</code_context>

<specifics>
## Specific Notes

- User uses Linux Mint on workstations, comfortable with Ubuntu, has used Raspbian before
- 10.68.19.x subnet is a VFX network — unrelated to mushroom farm Pi setup
- Pi's static IP will be on 192.168.88.x (local LAN, same subnet as workstation/booko)
- Pi current state unknown — will assess next session when Pi is booted

</specifics>

<deferred>
## Deferred Ideas

- Pi current state assessment deferred to next session — user will boot Pi and attempt SSH before discussion continues

</deferred>

---

*Phase: 01-pi-integration-environment*
*Context gathered: 2026-03-28 (partial)*
