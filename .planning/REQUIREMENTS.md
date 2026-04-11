# Requirements: Mushroom Farm — v1.1 Tech Debt & Connectivity

**Defined:** 2026-04-11
**Core Value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.

## v1.1 Requirements

Bugfix + infra milestone closing v1.0 tech debt and establishing reliable farm connectivity to fc1.

### Tech Debt (TDEBT)

- [ ] **TDEBT-01**: Mission Control bridge subscribes `fc1/actuators/humidifier` with `durability: transient_local` QoS so last-state replays on bridge restart (closes ACTR-03 carried over from v1.0 Phase 04).
- [ ] **TDEBT-02**: Live MJPEG stream at `/camera/mjpeg` delivers continuous frames during normal operation — no stalls caused by a phantom CycloneDDS peer at `192.168.1.193` (closes CAM-03 carried over from v1.0 Phase 08).
- [ ] **TDEBT-03**: `fc-core.service` starts cleanly on Pi cold boot without restart loops waiting for the `tailscale0` interface — zero automatic restarts expected on a healthy boot.

### Connectivity (CONN)

- [ ] **CONN-01**: fc1 Pi maintains reliable internet at the farm via a 4G hotspot path — ROS topics and Mission Control are reachable from elder-plops across the Tailscale mesh, and the Pi auto-recovers from WAN blips without manual intervention.

## Deferred to Future Milestone

Acknowledged but not in v1.1 scope.

### Sensor Redundancy

- **SHT30-01**: Physically reinstall SHT30 on I2C 0x44 so the primary humidity sensor is live again (currently on SCD41 fallback). Deferred because SCD41 fallback works; redundancy is nice-to-have.

### CO2 Capabilities

- CO2 alerts, trend reports, CO2-triggered ventilation control. Routed to a dedicated `/gsd:explore` session for v2.0 themes — the farmer's unexpected favorite feature deserves deliberate scoping.

### Backlog Promotion Candidates (Phase 999.x)

- Edge buffering (local telemetry store-and-forward)
- Signal alerts
- Fan/light telemetry

## Out of Scope

Explicitly excluded from v1.1.

| Feature | Reason |
|---------|--------|
| Temperature control loop | Still deferred from v1.0 — v1.1 is tech debt only |
| Multi-chamber / FC-2 | Still single-chamber until v2.0+ |
| OpenMCT UI enhancements | v1.1 does not touch dashboards beyond fixing the MJPEG delivery bug |
| Refactor of fc_camera or bridge architecture | Target the specific bugs, do not restructure |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONN-01 | Phase 09 | Pending |
| TDEBT-03 | Phase 09 | Pending |
| TDEBT-01 | Phase 10 | Pending |
| TDEBT-02 | Phase 10 | Pending |

**Coverage:**
- v1.1 requirements: 4 total
- Mapped to phases: 4 (100%)
- Unmapped: 0

---
*Requirements defined: 2026-04-11*
*Last updated: 2026-04-11 — traceability populated by roadmapper*
