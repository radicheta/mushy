# Phase 5: Production Deployment - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 05-production-deployment
**Areas discussed:** Humidity target tuning, Soak test criteria, Grower observability, Known constraints doc

---

## Humidity Target Tuning

| Option | Description | Selected |
|--------|-------------|----------|
| 85-95% | target_humidity: 0.90, tolerance: 0.05. Standard fruiting range. | |
| 80-90% | target_humidity: 0.85, tolerance: 0.05. Lower condensation risk. | |
| Keep 70-80% | Leave config as-is for initial testing. | |

**User's choice:** Custom — "should be set from mission control and stored as a configuration. default can be 80%"
**Notes:** User initially wanted OpenMCT command channel for runtime config. After discussing scope, agreed to fc_config.yaml + redeploy for MVP. Default 80%.

### Dwell Time

| Option | Description | Selected |
|--------|-------------|----------|
| Keep 5 min | Conservative default, proven safe in Phase 3. | ✓ |
| Increase to 10 min | More conservative for ultrasonic humidifiers. | |
| You decide | Claude picks based on humidifier type. | |

### Config Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| fc_config.yaml + redeploy | Edit config, run deploy.sh. Simple, proven. | ✓ |
| ROS2 param set via SSH | CLI command, no code changes. Requires terminal comfort. | |
| OpenMCT command channel | Bidirectional dashboard. Significant new feature. | |

**User's choice:** fc_config.yaml + redeploy (Recommended)

---

## Soak Test Criteria

| Option | Description | Selected |
|--------|-------------|----------|
| 24 hours stable | Full day/night cycle. Proves handling of transitions. | ✓ |
| 4 hours stable | Faster validation. Multiple humidifier cycles. | |
| 1 week stable | High confidence, long-term reliability. | |

### Crash Recovery

| Option | Description | Selected |
|--------|-------------|----------|
| systemd auto-restart is enough | If it restarts and keeps working, counts as stable. | ✓ |
| Any crash fails the test | Strict — investigate root cause first. | |
| You decide | Claude picks reasonable criteria. | |

---

## Grower Observability

| Option | Description | Selected |
|--------|-------------|----------|
| OpenMCT over VPN | Browser to Pi IP:8080 over WireGuard. Already works. | ✓ |
| journalctl on Pi via SSH | Minimal, requires terminal comfort. | |
| Both + status script | OpenMCT + simple SSH status script. | |

### Alerts

| Option | Description | Selected |
|--------|-------------|----------|
| No alerts for MVP | Just monitoring. Alerts deferred to future phase. | ✓ |
| Simple email/push alert | Notify if humidity outside range >30 min. | |
| Log-based alerting | Write alert events to journal. | |

---

## Known Constraints Doc

### Format

| Option | Description | Selected |
|--------|-------------|----------|
| README section in repo | OPERATIONS.md stays with code. | |
| Printed checklist | 1-page doc near the chamber. | |
| Both | README + printable checklist. | ✓ |

### Content (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Hardware requirements | Pi 4, SHT30, SSR-10A, GPIO pins, power supply. | ✓ |
| Recovery steps | Power check, SSH, restart service, redeploy. | ✓ |
| Configuration guide | Change humidity target, dwell time. Edit config + deploy. | ✓ |
| Known limitations | Single chamber, no alerts, GPIO deprecation path. | ✓ |

---

## Claude's Discretion

- Operations doc layout and formatting
- System architecture diagram inclusion
- Printable checklist structure
- Soak test monitoring approach

## Deferred Ideas

- OpenMCT command channel (bidirectional config from dashboard)
- Alert/notification system
- TimescaleDB telemetry storage
- Multi-chamber support
