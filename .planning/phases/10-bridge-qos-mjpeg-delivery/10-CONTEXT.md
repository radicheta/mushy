# Phase 10: Bridge QoS & MJPEG Delivery - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix two v1.0 tech debt items in the Mission Control bridge and Pi-side
CycloneDDS configuration:

1. **TDEBT-01**: Bridge subscribes `fc1/actuators/humidifier` with
   `transient_local` durability so the last humidifier state replays on
   bridge restart (fc_controller already publishes with TRANSIENT_LOCAL).
2. **TDEBT-02**: Eliminate the phantom CycloneDDS peer at `192.168.1.193`
   that stalls live MJPEG delivery on the `/camera/mjpeg` endpoint.

Explicitly out of scope:
- Refactoring bridge architecture or fc_camera
- Dashboard/UI changes in Mission Control
- Any new telemetry topics or features
- Temperature control, CO2 features, multi-chamber

</domain>

<decisions>
## Implementation Decisions

### Bridge QoS Fix (TDEBT-01)

- **D-01:** Add explicit `transient_local` durability QoS to ONLY the
  `/fc1/actuators/humidifier` subscription in `src/mission-control/bridge/src/index.js`.
  The other subscriptions (humidity, temperature, co2, camera) use sensor
  data that is transient by nature — no need to replay stale sensor values
  on bridge restart. Keep them on default QoS.
- **D-02:** Use rclnodejs `QoS` profile object passed as the 4th argument
  to `node.createSubscription()`. The profile must match the publisher:
  `depth: 1, durability: TRANSIENT_LOCAL, reliability: RELIABLE,
  history: KEEP_LAST`. Consult rclnodejs docs for exact API.
- **D-03:** The fix is bridge-side only. No changes to fc_controller.py
  or any Python code. Deploy via `docker compose up -d --build bridge`
  at the repo root.

### Phantom Peer Cleanup (TDEBT-02)

- **D-04:** The `192.168.1.193` peer is NOT in any repo-tracked CycloneDDS
  XML config. The bridge-side `cyclonedds.xml` lists only Tailscale IPs
  (100.96.10.66, 100.96.239.75). The Pi-side `scripts/pi-deploy/cyclonedds.xml`
  lists only WireGuard IPs (172.16.10.3, 172.16.10.5). The phantom peer
  is a stale DDS discovery artifact on the Pi — likely from an old
  LAN-connected session before VPN was set up.
- **D-05:** Fix approach: verify the live `/etc/cyclonedds.xml` (or
  whatever path `CYCLONEDDS_URI` points to) on the Pi does NOT contain
  `192.168.1.193`. If it does, remove it. If it doesn't, the stale peer
  is coming from DDS discovery cache — restart fc-core after confirming
  the config is clean, and verify the write-retry errors stop.
- **D-06:** If the phantom peer persists after config cleanup and restart,
  add explicit CycloneDDS tuning to shorten peer expiry / lease duration
  so unresponsive peers are dropped faster. This is a fallback, not the
  first approach.
- **D-07:** The Pi-side fix deploys via `fc1/prod` branch + `deploy.sh`
  per project convention (memory: `feedback_deploy_method.md`).

### Deploy Sequence

- **D-08:** The two fixes are independent and can ship separately. Bridge
  QoS fix (D-01–D-03) deploys from elder-plops via docker compose. Phantom
  peer cleanup (D-04–D-07) deploys to the Pi via fc1/prod. No ordering
  dependency between them.
- **D-09:** Bridge QoS fix should be verified FIRST because it can be
  tested entirely from elder-plops (restart bridge, check Mission Control
  humidifier chart). Phantom peer fix requires Pi access (Phase 09 must
  be complete).

### Verification Strategy

- **D-10:** TDEBT-01 verification: `docker compose restart bridge` on
  elder-plops, then check Mission Control humidifier-state chart shows
  correct last-known state immediately — no blank gap. This matches
  success criterion 1 from ROADMAP.md.
- **D-11:** TDEBT-02 verification: after deploying the Pi-side fix, check
  `journalctl -u fc-core.service` for absence of `192.168.1.193`
  write-retry errors (success criterion 3), and confirm `/camera/mjpeg`
  delivers continuous frames for 60+ seconds (success criterion 2).
- **D-12:** Pi must be reachable over Tailscale for TDEBT-02 verification.
  Phase 09 (4G hotspot + boot stability) must be complete first. This
  matches the `Depends on: Phase 09` in ROADMAP.md.

### Claude's Discretion

- Exact rclnodejs QoS API usage (constructor, constants import)
- Whether to add a brief log line on bridge startup confirming QoS profile
- DDS lease duration tuning values if the fallback (D-06) is needed
- Whether to add a smoke test script for the bridge restart scenario
- Order of committing bridge vs Pi-side changes within the phase plans

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — TDEBT-01, TDEBT-02 definitions for v1.1
- `.planning/ROADMAP.md` §Phase 10 — Goal, success criteria, dependencies

### Bridge Source (TDEBT-01 target)
- `src/mission-control/bridge/src/index.js` — Lines 311-319: humidifier
  subscription with default QoS. Lines 279-330: all subscriptions. This
  is the file to modify.
- `src/mission-control/bridge/package.json` — rclnodejs ^1.9.0 pinned;
  check rclnodejs docs for QoS API

### fc_controller Publisher (reference for QoS match)
- `src/chambers/fc-core/fc_core/fc_controller.py` — Lines 90-98:
  TRANSIENT_LOCAL publisher QoS profile. Bridge subscription must match
  this exactly.

### CycloneDDS Configs (TDEBT-02 target)
- `src/mission-control/bridge/cyclonedds.xml` — Bridge-side Tailscale
  unicast config. No phantom peer here.
- `scripts/pi-deploy/cyclonedds.xml` — Pi-side WireGuard unicast config.
  No phantom peer here either. Live Pi config at `/etc/cyclonedds.xml`
  may differ — must be checked on the Pi itself.

### Docker Compose (bridge deploy)
- `docker-compose.yml` — Live compose at repo root. Bridge rebuild:
  `docker compose up -d --build bridge`

### v1.0 Audit (failure documentation)
- `.planning/milestones/v1.0-MILESTONE-AUDIT.md` — `ACTR-03-qos-mismatch`
  and `CAM-03-stale-peer` entries document both failure modes in detail

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **rclnodejs QoS API** — rclnodejs ^1.9.0 supports QoS profiles on
  subscriptions. The `createSubscription` call accepts an options object
  with QoS settings. No additional npm packages needed.
- **fc_controller.py QoS profile** — Lines 91-96 define the exact QoS
  profile the bridge must match: depth=1, TRANSIENT_LOCAL, RELIABLE,
  KEEP_LAST. Use this as the source of truth.

### Established Patterns
- **Bridge subscriptions are all in one block** (index.js:279-330) —
  five `createSubscription` calls in sequence. The humidifier one at
  line 311 is the only one that needs QoS changes.
- **CycloneDDS unicast-only** — both bridge and Pi configs disable
  multicast and use explicit peer lists. No mDNS or multicast discovery.
- **Host networking for bridge container** — docker-compose.override.yml
  gives the bridge access to `tailscale0` directly.

### Integration Points
- **Bridge container rebuild** — `docker compose up -d --build bridge`
  at repo root. The override file mounts the CycloneDDS config.
- **Pi deploy path** — git push to `fc1/prod` + `deploy.sh`. Changes to
  `scripts/pi-deploy/cyclonedds.xml` land on Pi via this path.
- **fc-core.service on Pi** — restart after CycloneDDS config change
  needed to pick up the cleaned config.

</code_context>

<specifics>
## Specific Ideas

No specific requirements — user delegated all decisions to Claude ("go
ahead and do it as best you can"). All decisions above are based on
codebase evidence and the documented tech debt from the v1.0 milestone
audit.

</specifics>

<deferred>
## Deferred Ideas

None — analysis stayed within phase scope.

</deferred>

---

*Phase: 10-bridge-qos-mjpeg-delivery*
*Context gathered: 2026-04-12*
