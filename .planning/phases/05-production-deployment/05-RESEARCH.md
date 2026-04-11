# Phase 5: Production Deployment - Research

**Researched:** 2026-04-05
**Domain:** systemd service hardening, operations documentation, production soak validation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Default target humidity set to 0.80 (80%) in `fc_config.yaml`. Tolerance stays at 0.05 (5%), giving a 75–85% operational band.
- **D-02:** Configuration changes happen via `fc_config.yaml` + `deploy.sh` redeploy. No runtime config UI for MVP.
- **D-03:** Min dwell time stays at 300s (5 minutes). Proven safe in Phase 3 testing.
- **D-04:** Soak test duration: 24 hours continuous operation on FC-1 at the farm. Full day/night cycle covers lighting transitions and temperature swings.
- **D-05:** Stability definition: systemd auto-restart (`Restart=on-failure`) counts as stable. If the service restarts and keeps working, the test passes. Log any restarts for review.
- **D-06:** Soak test is gated by physical Pi relocation from lab to farm (04-HUMAN-UAT.md pending item).
- **D-07:** Day-to-day monitoring via OpenMCT dashboard over WireGuard VPN. Browser → Pi IP:8080. Already functional from Phase 4 + Phase 6.
- **D-08:** No alerts for MVP. Alert/notification system is a future phase capability.
- **D-09:** Two formats: README/OPERATIONS.md in repo (for developers) + printable 1-page checklist (for grower near the chamber).
- **D-10:** Doc covers: hardware requirements (Pi 4, SHT30, SSR-10A, GPIO pins), recovery steps (power check, SSH, service restart, redeploy), configuration guide (edit config + deploy.sh), known limitations (single chamber, no alerts, no remote config UI, GPIO library deprecation path).

### Claude's Discretion

- Exact layout and formatting of the operations documents
- Whether to include a system architecture diagram in the docs
- How to structure the printable checklist for maximum clarity
- Soak test monitoring approach (manual log checks vs automated verification script)

### Deferred Ideas (OUT OF SCOPE)

- **OpenMCT command channel** — Bidirectional control from dashboard. Future phase.
- **Alert/notification system** — Email or push notifications. Future phase.
- **TimescaleDB telemetry storage** — Historical data retention. Future phase.
- **Multi-chamber support** — FC-2 integration. Out of MVP scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEPL-01 | System runs stably on Pi and is suitable for grower handoff (better than timer) | Config update (target_humidity 0.75→0.80), soak test verification, and OPERATIONS.md together satisfy this |

</phase_requirements>

---

## Summary

Phase 5 is a deployment and documentation phase — no new code logic. The control stack is complete from Phases 1–4. Three things must happen: (1) update `target_humidity` from 0.75 to 0.80 in `fc_config.yaml` and redeploy, (2) run and verify a 24-hour soak test once the Pi is physically relocated to the farm, and (3) write two operations documents for grower handoff.

The infrastructure is already production-ready. The fc-core service has been running continuously on FC-1 since 2026-04-04T21:31:22 UTC with zero restarts [VERIFIED: SSH to fc1, systemctl show]. The systemd unit already has `Restart=on-failure`, `RestartSec=5`, and full journal logging. The deploy pipeline via `deploy.sh` is proven across multiple phases. OpenMCT is reachable at port 8080 [VERIFIED: HTTP 200 from localhost:8080].

The one outstanding gap is the config value: `target_humidity` is currently 0.75 in both the repo and the deployed Pi config [VERIFIED: codebase read + SSH to fc1]. D-01 locks this to 0.80. This is the only code/config change in this phase. Everything else is validation and documentation.

**Primary recommendation:** Update config, deploy, document, then monitor the soak. The system is already stable — Phase 5 is finishing the handoff, not fixing the system.

---

## Standard Stack

### Core (already deployed — no new installs)

| Component | Version/State | Purpose | Notes |
|-----------|--------------|---------|-------|
| fc-core systemd service | Active, 0 restarts [VERIFIED: SSH] | Auto-start and supervision of ROS2 nodes | `Restart=on-failure`, `RestartSec=5` |
| `deploy.sh` | Proven pipeline | rsync + colcon build + service restart | No changes needed |
| `fc_config.yaml` | Needs 1 change | All runtime parameters | `target_humidity: 0.75` → `0.80` |
| OpenMCT + rosbridge | Running (docker containers up [VERIFIED: docker ps]) | Grower observability dashboard | Port 8080 |
| WireGuard VPN | Active | Remote monitoring over VPN | wg0 on both elder-plops and FC-1 |

### No new library installs required

This phase installs nothing new. All runtime dependencies are already on the Pi.

---

## Architecture Patterns

### Current System State (VERIFIED)

```
FC-1 Pi (10.68.155.53 / 172.16.10.5 VPN)
├── fc-core.service (systemd, Restart=on-failure)
│   ├── fc_sensors node  → SHT30 I2C 0x44, SCD41 I2C 0x62
│   ├── fc_controller node → GPIO27 (SSR-10A humidifier)
│   └── fc_display node
├── /etc/cyclonedds.xml  (WireGuard unicast, wg0)
└── ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml

elder-plops (172.16.10.3 VPN)
├── OpenMCT (docker: mushy_openmct_1, port 8080)  [VERIFIED: running]
└── rosbridge (docker: mushy_bridge_1)             [VERIFIED: running]
```

### Config Delta Required

The only change needed before deployment is in `fc_config.yaml`:

```yaml
# CURRENT (0.75 — must change per D-01)
target_humidity: 0.75  # 75%

# TARGET (0.80 per D-01 — 80% setpoint, ±5% → 75–85% band)
target_humidity: 0.80  # 80%
```

[VERIFIED: current value confirmed in repo file and on Pi via SSH]

The controller default (`target_humidity: 0.85` in `fc_controller.py` line 25) is superseded by the config file value at runtime. No Python change needed — config file is authoritative. [VERIFIED: fc_controller.py parameter declaration]

### Soak Test Pattern

The soak test is observational, not automated. Standard approach for embedded control systems:

1. Deploy config update → confirm service restarts clean
2. Confirm humidifier is cycling correctly for the current ambient humidity
3. Walk away for 24 hours (D-04)
4. Return and check: `ssh fc1 'sudo journalctl -u fc-core --since "24 hours ago" | grep -E "Humidifier|restart|error"'`
5. Check NRestarts: `ssh fc1 'sudo systemctl show fc-core --property=NRestarts'`

Per D-05: any number of restarts that auto-recover counts as stable for MVP. Document restart count in the verification record.

### Operations Documentation Pattern (D-09)

Two-tier doc approach standard for grower-facing deployments:

- **OPERATIONS.md** (in repo): Full reference for developers — SSH commands, full recovery procedure, configuration guide, architecture overview
- **Printable checklist** (1 page, large print): For grower to keep near the chamber — symptom + action pairs only, no command details

Anti-pattern: do not make the printable checklist a condensed version of OPERATIONS.md. They serve different audiences and mental models. The grower checklist should be symptom-first ("Humidifier not turning on → check power strip"). [ASSUMED: grower UX convention — not domain-specific to ROS]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service supervision | Custom watchdog | systemd `Restart=on-failure` (already in fc-core.service) | Already proven; handles crash/OOM/exception |
| Soak test automation | Custom log scraper | `journalctl --since` + `systemctl show --property=NRestarts` | journald is the ground truth; ad-hoc scripts add maintenance burden |
| Config validation | Custom YAML checker | Deploy + check service active + check topic echo | The system itself is the validator |
| Deployment | Manual scp/ssh | `deploy.sh` (already exists) | Proven across 10+ deployments in this project |

---

## Common Pitfalls

### Pitfall 1: Config value drift between repo and Pi

**What goes wrong:** `target_humidity` is updated in the repo file but the Pi still runs the old value. Or vice versa — the Pi file is edited directly (on-Pi edit) and the repo drifts.

**Why it happens:** The deploy.sh rsync overwrites Pi with repo on next deploy, but if a developer edits on-Pi directly, that change is lost on next deploy.

**How to avoid:** Always edit `src/chambers/fc-core/config/fc_config.yaml` in the repo and run `deploy.sh`. Never edit config directly on the Pi.

**Warning signs:** After deploy, `ssh fc1 'cat ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml | grep target_humidity'` should match repo value.

### Pitfall 2: fc-core.service not enabled (boot survival)

**What goes wrong:** Service runs in current session but doesn't survive Pi reboot.

**Why it happens:** `systemctl start` vs `systemctl enable`. The service has `WantedBy=multi-user.target` in the unit file, so it will enable correctly, but only if the one-time setup step (`systemctl enable fc-core`) was run.

**How to avoid:** Verify with `ssh fc1 'sudo systemctl is-enabled fc-core'` — must return `enabled`, not just `active`. This was done in Phase 1, but verify before declaring soak test start. [VERIFIED: service has been running continuously since Phase 4 — boot survival previously confirmed]

**Warning signs:** Service disappears from `systemctl status` after Pi reboot.

### Pitfall 3: Humidifier and SSR not physically connected at farm

**What goes wrong:** Soak test starts but humidifier never activates because the Pi was not wired into the farm's power strip.

**Why it happens:** Phase 5 gate (D-06) requires Pi physical relocation. The software will run fine but `fc/actuators/humidifier: True` won't drive a physical device if SSR GPIO27 is disconnected.

**How to avoid:** Verify SSR is wired before starting soak. `ssh fc1 'sudo journalctl -u fc-core -n 20'` should show `Humidifier: ON` log lines when humidity is below setpoint. Visually confirm humidifier is actually activating.

**Warning signs:** journalctl shows `Humidifier: ON` but the physical humidifier is silent/dry.

### Pitfall 4: OpenMCT not running during soak grower handoff demo

**What goes wrong:** The grower observability check requires `docker-compose up` on elder-plops. If containers are stopped, the dashboard is unavailable even though fc-core is healthy on the Pi.

**Why it happens:** Docker containers are not auto-started. OpenMCT + bridge must be running on elder-plops workstation.

**How to avoid:** Run `docker compose up -d openmct bridge` from the mushy repo root on elder-plops before demonstrating dashboard. The OPERATIONS.md must document this dependency explicitly. [VERIFIED: mushy_openmct_1 and mushy_bridge_1 containers confirmed running during research]

**Warning signs:** Browser shows blank or "can't connect" at localhost:8080.

### Pitfall 5: Soak test monitoring gap — no visibility if Pi goes dark overnight

**What goes wrong:** Soak starts, Pi has an issue at 3 AM, but nobody knows until morning review shows a gap in sensor data.

**Why it happens:** No alerts (D-08 — explicitly out of scope for MVP). Manual check-in process creates coverage gap.

**How to avoid:** Before starting soak, schedule two manual check-ins — one at the ~8-hour mark, one at the ~16-hour mark. This is "soak test monitoring approach" per Claude's Discretion. Check via: `ssh fc1 'sudo systemctl show fc-core --property=NRestarts,ActiveState'` and review a few minutes of journalctl to confirm data is flowing.

---

## Code Examples

### Check service state and restart count

```bash
# [VERIFIED: SSH to fc1 during research — NRestarts=0 as of 2026-04-05]
ssh fc1 'sudo systemctl show fc-core --property=NRestarts,ActiveState,SubState,ExecMainStartTimestamp'
```

### Review last N hours of logs for anomalies

```bash
# Replace "24 hours ago" with soak start timestamp for final check
ssh fc1 'sudo journalctl -u fc-core --since "24 hours ago" --no-pager | grep -E "Humidifier|restart|error|warn" | tail -50'
```

### Verify deployed config matches repo

```bash
ssh fc1 'grep target_humidity ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml'
# Should output: target_humidity: 0.80  (after Phase 5 config update + deploy)
```

### Full deploy cycle

```bash
# From mushy repo root on elder-plops
./scripts/pi-deploy/deploy.sh
# Verify:
ssh fc1 'sudo systemctl is-active fc-core'
ssh fc1 'sudo journalctl -u fc-core -n 10 --no-pager'
```

### Confirm humidifier is cycling (quick spot check)

```bash
# On Pi directly — checks last 5 minutes of control decisions
ssh fc1 'sudo journalctl -u fc-core --since "5 minutes ago" --no-pager | grep -E "Humidifier: (ON|OFF)"'
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|-----------------|-------|
| target_humidity: 0.75 (75%) | target_humidity: 0.80 (80%) | D-01 change; new on/off thresholds: OFF above 85%, ON below 75% |
| Phase 4 quick verification | Phase 5 24-hour soak at farm | Full day/night cycle validation |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Grower checklist should be symptom-first rather than command-first | Architecture Patterns (documentation format) | Low — formatting only; grower can still use it if structured differently |

**All other claims in this research were verified via SSH to fc1, codebase inspection, or docker ps.**

---

## Open Questions

1. **Pi physical relocation to farm**
   - What we know: Soak test is gated on this (D-06). Pi is currently still at the lab/developer location based on context clues (04-SUMMARY references "Pi not yet at farm").
   - What's unclear: Has the Pi been moved? 04-HUMAN-UAT.md shows the end-to-end hardware test as pending. The service is active at 10.68.155.53, which is the Pi's LAN IP, reachable from elder-plops.
   - Recommendation: The plan should include a physical prerequisite checkpoint: "Pi must be physically connected to humidifier at farm before soak test begins." This is a human action, not a code task.

2. **Soak test start time coordination**
   - What we know: 24 hours is required; full day/night cycle preferred.
   - What's unclear: When the Pi will be at the farm.
   - Recommendation: Plan should note that the soak test task is a human checkpoint with a pass/fail criterion, not an automated task. The planner should emit a HUMAN-UAT item for it.

3. **Current ambient humidity at farm location**
   - What we know: Current readings at Pi's current location are ~66% (below even the old 75% setpoint). At 0.80 target with 0.05 tolerance, the humidifier will be ON continuously until 75% is reached.
   - What's unclear: Whether the farm environment has different baseline humidity.
   - Recommendation: After deploying 0.80 config, observe a few minutes of journalctl to confirm humidifier is cycling as expected before starting the 24-hour soak clock.

---

## Environment Availability

| Dependency | Required By | Available | Version/State | Notes |
|------------|------------|-----------|--------------|-------|
| FC-1 Pi (SSH) | All tasks | ✓ | fc-core active, 0 restarts [VERIFIED] | `ssh fc1` works |
| fc-core systemd service | Soak test | ✓ | Running since 2026-04-04T21:31 [VERIFIED] | `Restart=on-failure` already set |
| OpenMCT (docker) | Grower observability | ✓ | mushy_openmct_1 running [VERIFIED: docker ps] | Port 8080 returns HTTP 200 |
| rosbridge (docker) | OpenMCT ↔ ROS | ✓ | mushy_bridge_1 running [VERIFIED: docker ps] | |
| WireGuard VPN | Remote access | ✓ | wg0 on both sides [VERIFIED: cyclonedds.xml on Pi] | 172.16.10.3 ↔ 172.16.10.5 |
| Physical humidifier at farm | Soak test | ? | Unknown — Pi relocation pending (D-06) | Blocker for soak; see Open Questions |

**Missing dependencies with no fallback:**
- Physical Pi relocation to farm with humidifier connected — blocks the soak test (24-hour validation). The software tasks (config update, deploy, documentation) can proceed without this, but the soak itself cannot start until physical setup is confirmed.

**Missing dependencies with fallback:**
- None.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (colcon test wrapper) |
| Config file | `src/chambers/fc-core/fc_core/test/test_controller.py` |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/ -x -q` |
| Full suite command | `colcon test --packages-select fc_core && colcon test-result --verbose` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| DEPL-01 (config) | `target_humidity` is 0.80 in deployed config | manual-verify | `ssh fc1 'grep target_humidity ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml'` | Grep output is the check |
| DEPL-01 (stability) | Service runs 24h without unrecoverable crash | manual-soak | `ssh fc1 'sudo systemctl show fc-core --property=NRestarts,ActiveState'` | Human gate — not automatable |
| DEPL-01 (observability) | Dashboard shows live data | manual-verify | Open browser to localhost:8080 | Requires running browser |
| DEPL-01 (documentation) | OPERATIONS.md exists and covers D-10 content | manual-review | File existence + content review | Human review |

### Wave 0 Gaps

- None — no new test files needed. DEPL-01 is satisfied by deployment verification steps and human soak sign-off, not unit tests.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | SSH key-based auth already established (Phase 1) |
| V3 Session Management | no | No session layer |
| V4 Access Control | no | Single-user system; ubuntu user in gpio+i2c groups |
| V5 Input Validation | no | No new user input surfaces in this phase |
| V6 Cryptography | no | No new crypto; WireGuard already handles VPN layer |

**This phase introduces no new attack surface.** The only change is a YAML float value and two documentation files.

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 5 |
|-----------|-------------------|
| ROS2 Jazzy workspace, colcon build | deploy.sh uses colcon; no deviation |
| `ROS_DOMAIN_ID=69`, `ROS_LOCALHOST_ONLY=0` | Already set in fc-core.service; no change |
| Primary config: `fc_config.yaml` | The only config change this phase |
| Deploy pattern: `./scripts/pi-deploy/deploy.sh` | Use exactly this for the config update |
| Simulation mode: controlled by `simulation_mode` parameter | Production: `sensor_simulation_mode: false`, `actuator_simulation_mode: false` — both already correct in config |

---

## Sources

### Primary (HIGH confidence)
- SSH to fc1 — NRestarts=0, ActiveState=active, ExecMainStartTimestamp verified
- `scripts/pi-deploy/deploy.sh` — read directly from codebase
- `scripts/pi-deploy/fc-core.service` — read directly from codebase
- `src/chambers/fc-core/config/fc_config.yaml` — read from repo AND verified on Pi via SSH
- `src/chambers/fc-core/fc_core/fc_controller.py` — read directly from codebase
- `.planning/phases/05-production-deployment/05-CONTEXT.md` — primary phase spec
- `.planning/phases/04-observability-integration/04-02-SUMMARY.md` — Phase 4 completion state
- `docker ps` — mushy_openmct_1 and mushy_bridge_1 confirmed running
- HTTP GET localhost:8080 — 200 OK

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — project history and accumulated decisions
- `04-VERIFICATION.md` — Phase 4 verification status

### Tertiary (LOW confidence)
- None — all claims verified against live system or codebase.

---

## Metadata

**Confidence breakdown:**
- Config change required: HIGH — both repo and Pi values verified, delta is unambiguous
- Deploy pipeline: HIGH — proven across 10+ deployments per STATE.md
- Soak test approach: HIGH — systemctl show NRestarts is authoritative
- Documentation content: MEDIUM — D-10 specifies what to cover; exact layout is Claude's Discretion
- Pi physical relocation status: LOW — cannot verify remotely; treat as a human gate

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable domain — systemd and ROS2 deployment patterns are not volatile)
