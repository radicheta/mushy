# Requirements: Mushroom Farm — v1.3 Alerts & Unified Farmer Dashboard

**Defined:** 2026-04-18
**Core Value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers. v1.3 extends this by proactively alerting the operator when something is wrong and giving the grower a single webpage view of chamber + production data.

## v1.3 Requirements

Requirements for milestone v1.3: Alerts & Unified Farmer Dashboard. Each maps to roadmap phases. Architecture settled by research (see `.planning/research/SUMMARY.md`): alerter.js inside bridge, farmer dashboard as static HTML served by bridge, FarmOS via bridge proxy, signal-cli-rest-api as new Docker service.

### Alerts

- [ ] **ALRT-01**: bbernhard/signal-cli-rest-api Docker service running on elder-plops with Signal registered as primary account on the 4G router SIM (pre-phase gate: verify the router exposes incoming SMS for the one-time verification code)
- [ ] **ALRT-02**: Four alert types fire with PROBLEM message, auto-generate RECOVERY on state clear: (1) Pi offline (no ROS traffic / Tailscale unreachable), (2) sensor ERROR persisting past grace, (3) RH out-of-band for N minutes, (4) humidifier stuck (commanded state mismatches observed). Every PROBLEM produces exactly one RECOVERY.
- [ ] **ALRT-03**: Deduplication + throttle (debounce flap bounces, require N≥5 consecutive out-of-band readings before firing), severity tiers (WARN/CRITICAL with different repeat cadences), state persistence across bridge restart (in-memory map initially; Timescale `alerts` table if restart-spam proves noisy)
- [ ] **ALRT-04**: Daily heartbeat message ("FC-1 watchdog alive — [summary]") — serves dual purpose as liveness indicator AND Signal linked-device keepalive (though we're using primary registration, heartbeat still detects a silently-dead alerter)
- [ ] **ALRT-05**: Grace-period suppression: no alerts fire during the fc_controller 20s sensor warm-up window (consume `/fc1/sensor_health` WARN state)
- [ ] **ALRT-06**: All thresholds and cadences configurable via env vars (SIGNAL_API_URL, SIGNAL_RECIPIENT, ALERT_RH_TARGET, ALERT_RH_BAND, ALERT_COOLDOWN_MIN, ALERT_HUMIDIFIER_STUCK_MIN, etc.) — no hardcoded thresholds
- [ ] **ALRT-07**: Snooze-per-alert-type via bidirectional Signal reply (farmer replies "snooze rh 4h" to mute RH alerts for 4 hours). Requires signal-cli receive-loop; snooze state persists in the same store as cooldowns.
- [ ] **ALRT-08**: Every alert message body includes a link to the farmer dashboard (`http://elder-plops-ts:8081/farmer`) so farmer can jump to context in one tap

### Dashboard

- [ ] **DASH-01**: `/farmer` page served by the existing bridge (new static route via `express.static`). Vanilla HTML/CSS/JS — no framework, no build step. Mobile-first layout (single-column, ≥16px font, ≥44px touch targets). Bookmarkable URL on farmer's phone over Tailscale.
- [ ] **DASH-02**: Current readings displayed with sensor provenance — e.g. "81.3% RH (SCD41, ±6%)" not bare "81.3% RH". Every number carries its source + accuracy spec. Addresses the #1 lesson from 2026-04-11 field notes (40 min of calibration against the wrong sensor).
- [ ] **DASH-03**: Service health strip — consumes the six signals from Phase 16 (Sensors, Camera feed, Humidifier, Bridge, Pi reachable, Grace) via existing `/health` + `sensor_health` WS. Reuses Phase 14 `makeStatusLight` primitive.
- [ ] **DASH-04**: Last camera frame displayed (60s poll of `/camera/latest.jpg` as a thumbnail; full panel handled by DASH-09)
- [ ] **DASH-05**: Server-computed `_age_sec` fields on all time-sensitive values. Staleness banner appears on any reading older than `2 × publish_interval`. Continues the v1.2.1 pattern (`/health`'s camera.last_frame_age_sec).
- [ ] **DASH-06**: sensor_health replay-on-connect works correctly — WS client consumes the bridge's `lastSensorHealthBroadcast` on open (regression check for Phase 16.1 behavior). Verified by hard-refresh test.
- [ ] **DASH-07**: Times displayed in local farm timezone using browser `Intl.DateTimeFormat`. UTC on hover.
- [ ] **DASH-08**: "What's unusual" anomaly callout at top of page. Per-metric rule (NOT blanket 2σ — temperature swings too much for σ to be useful). Recommended: RH/CO2 = >2σ from 24h mean; temperature = absolute delta >3°C in 1h (finalize during phase planning).
- [ ] **DASH-09**: Full camera panel in dashboard — larger tile with live-subscribed MJPEG stream when the panel is visible. Bumps 4G usage while open; relies on subscriber-aware camera (Phase 12) to idle when no one's watching.

### FarmOS

- [ ] **FMOS-04**: `GET /farmos/summary` bridge proxy route — server-to-server call using existing FARMOS_* env vars from Phase 13; 60s cache; returns `[]` (not error) on FarmOS downtime. Dashboard consumes this for the FarmOS observations section.
- [ ] **FMOS-05**: v1.2 carryover — FC-1 exists as a structure asset in FarmOS with correct location, and farmos_agent has the FarmOS-side permissions to write observation logs without manual intervention. Completes the 999.2 beachhead.

### Carryover

- [ ] **CARRY-01**: Phase 12 subscriber-aware camera hardware UAT — carried from v1.2. Verify on real hardware (not dev) that idle→active transitions are instant from farmer's perspective and 4G usage matches the ~35 MB/day target when no one's watching.

## Future Requirements

Deferred to future milestones. Tracked but not in v1.3 roadmap.

### Dashboard enhancements (v1.4 candidates)

- **DASH-FUT-01**: 6h inline sparklines for RH + CO2 (farmer's #1 field-notes wish — calibration ergonomics)
- **DASH-FUT-02**: Annotated event timeline (restarts, DWELL-BLOCK events, threshold crossings) — requires fc_controller to emit structured events
- **DASH-FUT-03**: "Compare two timestamps" view (this cycle vs yesterday's cycle)
- **DASH-FUT-04**: Parameter-change UI (setpoint, tolerance, dwell with predicted-effect banner) — its own milestone

### Alert enhancements

- **ALRT-FUT-01**: Quiet hours for WARN alerts (configurable window, CRITICAL still fires)
- **ALRT-FUT-02**: Chart snapshot attachment in alert messages ("here's the last hour of RH")
- **ALRT-FUT-03**: Acknowledgement workflow (ack alert, suppress until resolved+recovery fires)

### Multi-chamber

- **MCHAM-FUT-01**: Second chamber via Pi Zero remote I/O. Blocked on hardware decision (original Pi Zero W is armv6 and cannot run ROS2 Jazzy — swap to Pi Zero 2 W vs stick with MQTT dumb-publisher is a v1.4 decision).

## Out of Scope

Explicitly excluded from v1.3. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Native mobile app | Webpage + Signal covers operator needs; native adds OS overhead without commensurate value |
| Authentication on /farmer | Single operator on a Tailscale-private network; auth is ceremony here |
| Full frontend framework (React/Vue) | 200 lines of vanilla JS suffices; build step would dwarf the feature |
| FarmOS page iframe embed | Cookie/SameSite collisions with Drupal; bridge proxy is the right pattern |
| Live MJPEG in alert messages | signal-cli attachment size limits + 4G cost; link-to-dashboard (ALRT-08) instead |
| Multi-chamber navigation in dashboard | Deferred with multi-chamber itself (MCHAM-FUT-01) |
| More than 2 alert severity tiers | info/warn/critical triage fatigue; WARN/CRITICAL is sufficient |
| 6h sparklines | Deferred to v1.4 per user 2026-04-18; easy to add back if priorities shift |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ALRT-01 | TBD | Pending |
| ALRT-02 | TBD | Pending |
| ALRT-03 | TBD | Pending |
| ALRT-04 | TBD | Pending |
| ALRT-05 | TBD | Pending |
| ALRT-06 | TBD | Pending |
| ALRT-07 | TBD | Pending |
| ALRT-08 | TBD | Pending |
| DASH-01 | TBD | Pending |
| DASH-02 | TBD | Pending |
| DASH-03 | TBD | Pending |
| DASH-04 | TBD | Pending |
| DASH-05 | TBD | Pending |
| DASH-06 | TBD | Pending |
| DASH-07 | TBD | Pending |
| DASH-08 | TBD | Pending |
| DASH-09 | TBD | Pending |
| FMOS-04 | TBD | Pending |
| FMOS-05 | TBD | Pending |
| CARRY-01 | TBD | Pending |

**Coverage:**
- v1.3 requirements: 20 total (8 alerts, 9 dashboard, 2 FarmOS carryover, 1 Phase 12 UAT)
- Mapped to phases: 0 (roadmap not yet created)
- Unmapped: 20

---
*Requirements defined: 2026-04-18*
*Last updated: 2026-04-18 — milestone v1.3 scope defined*
