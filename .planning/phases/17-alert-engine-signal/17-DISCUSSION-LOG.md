# Phase 17: Alert Engine + Signal - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 17-alert-engine-signal
**Areas discussed:** Service deployment shape (expanded into bridge architecture evolution)

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Fault detection rules | Pi-offline and humidifier-stuck definition | |
| Cadences & thresholds | WARN/CRITICAL repeats, cooldown, heartbeat time | |
| Message format & snooze grammar | Body template, snooze reply patterns | |
| Service deployment shape | Where alerter + signal-cli live | ✓ |

**User's choice:** Service deployment shape only. All other areas → Claude's discretion for researcher/planner.

---

## Service Deployment Shape

### Q1: Where should alerter logic live?
| Option | Description | Selected |
|--------|-------------|----------|
| Inside bridge process | alerter.js as bridge module | |
| Separate Node container | Standalone compose service | ↪ reframed |

**User's response:** *"why would we deploy it to fc1? i'm leaning towards separate entity (mr robot at the farm) but should be deployed in elder-plops, no?"*

**Clarification:** Both options were always elder-plops-side. Claude's initial phrasing ("one more container to ship to fc1") was incorrect and caused confusion. Neither alerter nor signal-cli ever runs on fc1.

### Q2 (reframed): Lock architectural pattern for v1.3 and future agents?
User pivoted to architectural conversation: "let's discuss bridge architecture and evolution roadmap. this signal thing is part of groundwork for future autonomous agents."

Claude presented two shapes:
- **Shape A:** Bridge as nervous system, agents as independent compose services consuming bridge WS/REST
- **Shape B:** Bridge grows, every agent becomes a bridge module

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — lock Shape A | alerter = reference impl for future agents; bridge stays ROS↔web gateway | ✓ |
| Shape A, shared image/repo with bridge | Same topology, less isolation | |
| Hybrid — Shape B now, extract later | Ship as bridge module, migrate later | |

### Q3: Repo layout for alerter
| Option | Description | Selected |
|--------|-------------|----------|
| src/mission-control/alerter/ | Sibling to bridge/ under mission-control | |
| src/agents/alerter/ | New top-level "agents" directory | ✓ |

**User's rationale:** clear semantic separation — Mission Control = HMI for humans, agents = autonomous services that act on chamber state. Siblings, not nested.

### Q4: Where does signal-cli-rest-api get declared?
| Option | Description | Selected |
|--------|-------------|----------|
| Main docker-compose.yml | Canonical stack | |
| docker-compose.override.yml | Production/farm-only concerns | ✓ |

### Q5: Signal account data persistence
| Option | Description | Selected |
|--------|-------------|----------|
| Named Docker volume | Opaque, managed by Docker | ✓ |
| Bind mount under repo | Filesystem-visible | |

### Q6: signal-cli-rest-api network exposure
| Option | Description | Selected |
|--------|-------------|----------|
| Internal only | Compose network, alerter-only access | ✓ |
| Bound to localhost | Also on 127.0.0.1 for debug | |

### Q7: Alerter telemetry source
| Option | Description | Selected |
|--------|-------------|----------|
| Bridge WS (ws://bridge:8081) | Reuse replay-on-connect, no rclnodejs | ✓ |
| Direct ROS subscriptions | rclnodejs in alerter image | |

---

## Claude's Discretion

Areas left open for researcher/planner to propose:
- Fault detection rules for Pi-offline and humidifier-stuck (timeouts, mismatch definitions)
- Initial WARN/CRITICAL repeat cadences and cooldown defaults
- Heartbeat time-of-day (farmer TZ)
- Signal message body template (severity prefix, value formatting, link wording)
- Snooze grammar (strict vs fuzzy vs menu)
- Whether RH thresholds read from fc_config.yaml or independent env vars
- Exact signal-cli-rest-api mode and image tag

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section — Timescale alerts table promotion, `src/agents/_shared/`, MJPEG attachments, multi-recipient, backup strategy, extracting `/farmer` from bridge.
