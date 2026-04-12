# Phase 10: Bridge QoS & MJPEG Delivery - Research

**Researched:** 2026-04-12
**Domain:** rclnodejs QoS API, CycloneDDS peer lifecycle, ROS2 TRANSIENT_LOCAL durability
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Add explicit `transient_local` durability QoS to ONLY the `/fc1/actuators/humidifier`
  subscription in `src/mission-control/bridge/src/index.js`. Other subscriptions (humidity,
  temperature, co2, camera) keep default QoS — no stale sensor value replay needed.
- **D-02:** Use rclnodejs `QoS` profile object passed as the `options` 3rd argument to
  `node.createSubscription()`. Profile must match the publisher: `depth=1,
  durability=TRANSIENT_LOCAL, reliability=RELIABLE, history=KEEP_LAST`.
- **D-03:** Bridge-side fix only. No changes to `fc_controller.py` or any Python code.
  Deploy via `docker compose up -d --build bridge` at repo root.
- **D-04:** `192.168.1.193` is NOT in any repo-tracked CycloneDDS XML. The phantom peer is a
  stale DDS discovery artifact on the Pi — not a config file problem.
- **D-05:** Verify live `/etc/cyclonedds.xml` on Pi does not contain `192.168.1.193`. If
  absent, restart fc-core after confirming config is clean; verify errors stop.
- **D-06:** If phantom peer persists, tune CycloneDDS `LeaseDuration` / `InitialLocatorPruneDelay`
  to shorten peer expiry. Fallback only, not first approach.
- **D-07:** Pi-side fix deploys via `fc1/prod` branch + `deploy.sh`.
- **D-08:** The two fixes are independent and can ship in separate plans.
- **D-09:** Bridge QoS fix (TDEBT-01) verified first from elder-plops; phantom peer fix
  (TDEBT-02) requires Pi access and Phase 09 being complete.
- **D-10:** TDEBT-01 verification: `docker compose restart bridge`, check Mission Control
  humidifier chart shows correct last-known state immediately with no blank gap.
- **D-11:** TDEBT-02 verification: after Pi-side deploy, check `journalctl -u fc-core.service`
  for absence of `192.168.1.193` write-retry errors; confirm `/camera/mjpeg` delivers
  continuous frames for 60+ seconds.
- **D-12:** Phase 09 must be complete before TDEBT-02 can be verified.

### Claude's Discretion

- Exact rclnodejs QoS API usage (constructor, constants import)
- Whether to add a brief log line on bridge startup confirming QoS profile
- DDS lease duration tuning values if fallback (D-06) is needed
- Whether to add a smoke test script for the bridge restart scenario
- Order of committing bridge vs Pi-side changes within the phase plans

### Deferred Ideas (OUT OF SCOPE)

- Refactoring bridge architecture or fc_camera
- Dashboard/UI changes in Mission Control
- New telemetry topics or features
- Temperature control, CO2 features, multi-chamber
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TDEBT-01 | Mission Control bridge subscribes `fc1/actuators/humidifier` with `durability: transient_local` QoS so last-state replays on bridge restart | rclnodejs 1.9.0 QoS API verified; constructor signature and enum values confirmed; exact code pattern documented below |
| TDEBT-02 | Live MJPEG stream at `/camera/mjpeg` delivers continuous frames — no stalls from phantom CycloneDDS peer at `192.168.1.193` | CycloneDDS peer lifecycle documented; repo-tracked configs confirmed clean; Pi live config must be inspected; lease duration fallback values researched |
</phase_requirements>

---

## Summary

Phase 10 closes two isolated v1.0 tech debt items. Neither requires architectural change — both are targeted single-file (or single-config) edits with clear verification paths.

**TDEBT-01** is a QoS mismatch between the fc_controller publisher (TRANSIENT_LOCAL) and the bridge subscription (VOLATILE default). ROS2's transient_local durability requires both sides to opt in; when only the publisher opts in, a late-joining subscriber never receives the cached last value. The fix is a one-line change to the `createSubscription` call at index.js:311, passing a `QoS` options object. The rclnodejs 1.9.0 API for this is verified and documented below.

**TDEBT-02** is a CycloneDDS phantom peer: the Pi logs `ddsi_udp_conn_write to udp/192.168.1.193:24670 failed with retcode -1` every ~8 seconds. This write-retry storm consumes delivery bandwidth and correlates with intermittent MJPEG frame drops. Neither repo-tracked CycloneDDS config contains this IP. The stale peer likely came from a pre-VPN LAN session. First step is inspecting the live `/etc/cyclonedds.xml` on the Pi; if clean, restarting fc-core.service clears the in-memory DDS state. The fallback is a `LeaseDuration` reduction in the Pi-side XML.

**Primary recommendation:** Ship TDEBT-01 as Plan 01 (no Pi required), ship TDEBT-02 as Plan 02 (Pi must be online via Phase 09). Commit both to `fc1/prod` for the Pi side; bridge fix goes via docker compose rebuild.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rclnodejs | ^1.9.0 (pinned in package.json) | ROS2 Node.js client — createSubscription with QoS | Already in use; 1.9.0 is current latest [VERIFIED: npm view rclnodejs] |
| rmw_cyclonedds_cpp | ros-jazzy-rmw-cyclonedds-cpp | RMW implementation for DDS transport | Already deployed on bridge and Pi; no change needed |

No new packages needed for either fix. [VERIFIED: codebase inspection]

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| QoS constructor with enum constants | Predefined profile string (e.g., `'transient_local'`) | rclnodejs 1.9 does not expose a built-in `transient_local` named profile; must construct manually |
| Restarting fc-core.service to clear DDS state | Modifying `/etc/cyclonedds.xml` to remove phantom entry | Config files don't contain the phantom — restart is the correct first action |

---

## Architecture Patterns

### Pattern 1: rclnodejs QoS on createSubscription (TDEBT-01)

**What:** Pass a `QoS` object inside an `options` object as the 3rd argument to `createSubscription`. The callback moves to the 4th argument.

**When to use:** Any subscription that must match a TRANSIENT_LOCAL publisher.

**Verified API (rclnodejs 1.9.0):** [CITED: https://robotwebtools.github.io/rclnodejs/docs/1.9.0/QoS.html]

The `QoS` constructor signature:
```
new QoS(history, depth, reliability, durability, avoidRosNameSpaceConventions)
```

Enum values (from type definitions): [CITED: https://app.unpkg.com/rclnodejs@0.21.2/files/types/qos.d.ts]
- `QoS.HistoryPolicy.RMW_QOS_POLICY_HISTORY_KEEP_LAST`
- `QoS.ReliabilityPolicy.RMW_QOS_POLICY_RELIABILITY_RELIABLE`
- `QoS.DurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL`

The `createSubscription` options overload:
```javascript
node.createSubscription(typeClass, topic, { qos: qosObject }, callback)
```

**Code example:**
```javascript
// Source: rclnodejs 1.9.0 API docs + type definitions
const { QoS } = rclnodejs;

const humidifierQos = new QoS(
    QoS.HistoryPolicy.RMW_QOS_POLICY_HISTORY_KEEP_LAST,
    1,
    QoS.ReliabilityPolicy.RMW_QOS_POLICY_RELIABILITY_RELIABLE,
    QoS.DurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL,
    false
);

// Subscribe: fc1/actuators/humidifier -> fc.humidifier  (TRANSIENT_LOCAL — matches publisher)
node.createSubscription(
    'std_msgs/msg/Bool',
    '/fc1/actuators/humidifier',
    { qos: humidifierQos },
    async (msg) => {
        const value = msg.data ? 1 : 0;
        broadcast({ humidifier: value, timestamp: Date.now() });
        await insertTelemetry('fc.humidifier', value);
    }
);
```

**Caveat:** The `QoS` class import path must be confirmed at runtime. `rclnodejs` exports it at the top level. If `rclnodejs.QoS` is undefined, the alternative is `require('rclnodejs').QoS` or checking the rclnodejs init call pattern already in index.js. [ASSUMED — verify destructuring at runtime if build fails]

### Pattern 2: fc_controller.py QoS (reference — do not change)

```python
# Source: src/chambers/fc-core/fc_core/fc_controller.py lines 91-96 [VERIFIED: codebase]
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
```

The bridge QoS must match this profile exactly.

### Pattern 3: CycloneDDS LeaseDuration Fallback (TDEBT-02 D-06)

**What:** If the phantom peer persists after restarting fc-core.service, shorten the DDS lease duration so the Pi drops unresponsive peers faster.

**CycloneDDS XML path:** `//CycloneDDS/Domain/Discovery/LeaseDuration` [CITED: https://cyclonedds.io/docs/cyclonedds/latest/config/config_file_reference.html]

**Default:** `10 s`
**Recommended fallback value:** `5 s` (halves the time before a silent peer is evicted)

```xml
<CycloneDDS ...>
    <Domain Id="any">
        <Discovery>
            <LeaseDuration>5 s</LeaseDuration>
            <Peers>
                <Peer address="100.96.10.66"/>
                <Peer address="100.96.239.75"/>
            </Peers>
        </Discovery>
    </Domain>
</CycloneDDS>
```

Related element if needed: `InitialLocatorPruneDelay` (default 30 s) controls how long unresponsive configured peer locators are pinged before pruning. Reducing to `10 s` would be a more aggressive option if LeaseDuration alone is insufficient. [CITED: https://cyclonedds.io/docs/cyclonedds/latest/config/config_file_reference.html]

### Anti-Patterns to Avoid

- **Changing other subscriptions to TRANSIENT_LOCAL:** Only the humidifier topic publishes with this profile. Applying it to sensor topics would cause undefined behavior (policy incompatibility — sensor topics publish VOLATILE). D-01 is explicit: only the humidifier subscription changes.
- **Adding `192.168.1.193` as an explicit exclusion in XML:** CycloneDDS XML has no deny-list mechanism. The correct approach is clearing in-memory DDS state by restarting fc-core.service.
- **`docker compose up -d` without `--build`:** The cached bridge image will not pick up the QoS change. Always use `docker compose up -d --build bridge`. [VERIFIED: project memory `feedback_verify_docker.md`]
- **Editing `src/docker-compose.yml` instead of repo root:** Live stack runs from `/docker-compose.yml` at repo root. [VERIFIED: project memory `feedback_verify_runtime_compose.md`]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| QoS profile for TRANSIENT_LOCAL | Custom durability logic in bridge JS | `new QoS(...)` with rclnodejs enum constants | rclnodejs exposes the full RMW QoS surface; hand-rolling would bypass RMW and break DDS negotiation |
| Peer cleanup | Script to kill DDS processes | Restart fc-core.service + optionally tune `LeaseDuration` | DDS peer state lives inside rmw_cyclonedds process; killing it from outside can leave dangling file descriptors |

---

## Common Pitfalls

### Pitfall 1: QoS Incompatibility at Runtime

**What goes wrong:** Bridge starts but never receives the last-known humidifier state after restart, even with the QoS fix applied.
**Why it happens:** ROS2 QoS incompatibility is silent — if reliability or history don't match, DDS silently refuses to connect the subscription to the publisher. The bridge will log nothing obvious.
**How to avoid:** Match ALL four fields (history, depth, reliability, durability) exactly to the publisher. The fc_controller.py profile (lines 91-96) is the source of truth.
**Warning signs:** `ros2 topic echo /fc1/actuators/humidifier` on the Pi side shows messages but the bridge doesn't receive them after restart.

### Pitfall 2: QoS Class Import Location

**What goes wrong:** `ReferenceError: QoS is not defined` at bridge startup.
**Why it happens:** rclnodejs 1.x changed how QoS is exported across minor versions. In some versions it's `rclnodejs.QoS`; in others it must be destructured after init.
**How to avoid:** Check `Object.keys(rclnodejs)` at the top of index.js in a test print, or look for how rclnodejs is already imported in the file. If `const rclnodejs = require('rclnodejs')` is already there, `rclnodejs.QoS` should work — but verify with a test build.
**Warning signs:** Bridge container exits immediately with a ReferenceError in `docker compose logs bridge`.

### Pitfall 3: Phantom Peer Returns After fc-core Restart

**What goes wrong:** Restarting fc-core.service clears the peer from logs, but it reappears after Pi reconnects to the LAN at the farm (if the 4G hotspot also bridges to the LAN).
**Why it happens:** If the Pi has both a 4G path and a LAN path simultaneously, CycloneDDS (using `wg0` interface only) should not rediscover LAN peers — but misconfiguration could allow it.
**How to avoid:** Confirm `CYCLONEDDS_URI` on the Pi points to a config that restricts DDS to the WireGuard/Tailscale interface only (no multicast, no LAN interface). The Pi-side `scripts/pi-deploy/cyclonedds.xml` already does this; verify the live file matches.
**Warning signs:** `192.168.1.193` errors reappear in journalctl within minutes of clearing them.

### Pitfall 4: Bridge Rebuild with Wrong Compose Context

**What goes wrong:** Bridge rebuild succeeds but runs from a stale image.
**Why it happens:** Running `docker compose up -d` without `--build` from repo root, or running from `src/` instead of repo root.
**How to avoid:** Always run `docker compose up -d --build bridge` from `/mnt/slime-kingdom/opt/mushy/` (repo root). Confirm with `docker compose ps` that the bridge container shows a new `Created` timestamp.
**Warning signs:** `docker compose logs bridge` shows old log lines without the new QoS startup log message.

---

## Code Examples

### Current humidifier subscription (before fix)

```javascript
// Source: src/mission-control/bridge/src/index.js:311-320 [VERIFIED: codebase]
// Subscribe: fc1/actuators/humidifier -> fc.humidifier
node.createSubscription(
    'std_msgs/msg/Bool',
    '/fc1/actuators/humidifier',
    async (msg) => {
        const value = msg.data ? 1 : 0;
        broadcast({ humidifier: value, timestamp: Date.now() });
        await insertTelemetry('fc.humidifier', value);
    }
);
```

### After fix (TRANSIENT_LOCAL QoS)

```javascript
// Construct QoS to match fc_controller.py publisher profile
const humidifierQos = new rclnodejs.QoS(
    rclnodejs.QoS.HistoryPolicy.RMW_QOS_POLICY_HISTORY_KEEP_LAST,
    1,
    rclnodejs.QoS.ReliabilityPolicy.RMW_QOS_POLICY_RELIABILITY_RELIABLE,
    rclnodejs.QoS.DurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL,
    false
);

// Subscribe: fc1/actuators/humidifier -> fc.humidifier  (TRANSIENT_LOCAL — replays on restart)
node.createSubscription(
    'std_msgs/msg/Bool',
    '/fc1/actuators/humidifier',
    { qos: humidifierQos },
    async (msg) => {
        const value = msg.data ? 1 : 0;
        broadcast({ humidifier: value, timestamp: Date.now() });
        await insertTelemetry('fc.humidifier', value);
    }
);
```

### Verifying QoS effect (from elder-plops)

```bash
# 1. Restart bridge
docker compose restart bridge

# 2. Watch bridge logs — should see humidifier value within ~1s of startup
docker compose logs -f bridge | grep humidifier

# 3. Check Mission Control humidifier chart shows value immediately (no gap)
# Navigate to OpenMCT at http://10.68.155.50:8080
```

### Pi phantom peer investigation

```bash
# On Pi via Tailscale SSH (requires Phase 09 complete):

# Check live CycloneDDS config path
echo $CYCLONEDDS_URI
cat /etc/cyclonedds.xml   # or whatever path CYCLONEDDS_URI points to

# Check current error rate
journalctl -u fc-core.service --since "5 minutes ago" | grep 192.168.1.193

# Restart fc-core to clear DDS state
sudo systemctl restart fc-core.service

# Verify errors are gone
journalctl -u fc-core.service -f | grep -E "(192.168.1.193|error|ERROR)"
```

---

## Runtime State Inventory

This is a targeted bug-fix phase, not a rename/refactor. No runtime state migration is required. The sections below confirm what was checked.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | TimescaleDB telemetry table — no schema change | None |
| Live service config | Bridge container QoS is in-memory (set at startup via code) | Rebuild bridge container |
| OS-registered state | fc-core.service on Pi — needs restart after config cleanup | `sudo systemctl restart fc-core.service` |
| Secrets/env vars | No env var changes needed | None |
| Build artifacts | Bridge Docker image cached — rebuild required | `docker compose up -d --build bridge` |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker + compose v2 | Bridge rebuild | ✓ | `docker compose` on elder-plops | — |
| `/home/santi/.config/cyclonedds-tailscale.xml` | Bridge container mount | ✓ (confirmed live) | N/A | — |
| Pi reachable over Tailscale | TDEBT-02 verification | ✗ (pending Phase 09) | — | Skip TDEBT-02 verify until Phase 09 done |
| `journalctl` on Pi | TDEBT-02 error check | ✓ (once Pi is reachable) | — | — |

**Missing dependencies with no fallback:**
- Pi Tailscale reachability for TDEBT-02 verification — blocked on Phase 09. TDEBT-01 can be verified independently.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Manual verification (no automated test suite for bridge JS) |
| Config file | None detected |
| Quick run command | `docker compose logs bridge \| grep humidifier` |
| Full suite command | `docker compose restart bridge && docker compose logs -f bridge` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TDEBT-01 | Humidifier state replays immediately on bridge restart | manual smoke | `docker compose restart bridge; docker compose logs --tail=20 bridge` | N/A |
| TDEBT-02 | No `192.168.1.193` errors in fc-core journalctl after cleanup | manual smoke | `journalctl -u fc-core.service --since "1 min ago" \| grep 192.168.1` | N/A — requires Pi SSH |
| TDEBT-02 | MJPEG continuous for 60+ seconds | manual smoke | `curl -s http://elder-plops-ip:8081/camera/mjpeg --max-time 65 -o /dev/null -w "%{size_download}"` | N/A |

### Sampling Rate

- **Per task commit:** `docker compose logs --tail=30 bridge` to confirm no startup errors
- **Per wave merge:** Full manual smoke per D-10/D-11 verification criteria
- **Phase gate:** Both TDEBT-01 and TDEBT-02 success criteria met before `/gsd:verify-work`

### Wave 0 Gaps

None — no new test files are needed. Verification is observational (log inspection + Mission Control UI check + curl timing).

---

## Security Domain

This phase modifies a QoS field on a DDS subscription and potentially edits a CycloneDDS XML config. Neither change introduces new attack surface.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | no | Internal ROS message, not user input |
| V6 Cryptography | no | — |

No security controls are affected by either fix.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `rclnodejs.QoS` is accessible directly on the top-level `rclnodejs` require result | Code Examples | Build failure — need to check rclnodejs 1.9 module exports; fix: destructure or check `rclnodejs.QoS` at startup |
| A2 | CycloneDDS `LeaseDuration` default is 10 s for ros-jazzy rmw_cyclonedds_cpp | Architecture Patterns (fallback) | Fallback tuning may be less effective; actual default can be confirmed via `cyclonedds_tool` or rmw logs |
| A3 | Phantom peer at `192.168.1.193` is NOT in the live Pi `/etc/cyclonedds.xml` — it is DDS discovery cache only | Common Pitfalls | If IP IS in live Pi XML (a config drift from repo), the fix is simply removing it from that file |

---

## Open Questions

1. **Does the live Pi `/etc/cyclonedds.xml` contain `192.168.1.193`?**
   - What we know: Repo-tracked `scripts/pi-deploy/cyclonedds.xml` does not contain it
   - What's unclear: The Pi's live file may have diverged (project memory documents that Pi systemd units drift)
   - Recommendation: First task of TDEBT-02 plan is SSH to Pi and `cat /etc/cyclonedds.xml` — the answer drives the fix branch

2. **Is `rclnodejs.QoS` the correct import path in v1.9.0?**
   - What we know: Type definitions export `QoS` as a top-level class; `rclnodejs` is already `require`d at line 4 of index.js
   - What's unclear: Whether 1.9.0 exports `QoS` directly on the module object or requires additional destructuring
   - Recommendation: Add a one-line guard in the bridge task: `console.log('QoS available:', typeof rclnodejs.QoS)` — if `undefined`, use `const { QoS } = rclnodejs` pattern

---

## Sources

### Primary (HIGH confidence)

- rclnodejs npm registry — `npm view rclnodejs version` → `1.9.0` confirmed [VERIFIED: npm registry]
- `src/mission-control/bridge/src/index.js` — subscription block lines 279-330 [VERIFIED: codebase]
- `src/chambers/fc-core/fc_core/fc_controller.py` — publisher QoS lines 90-98 [VERIFIED: codebase]
- `src/mission-control/bridge/cyclonedds.xml` — no phantom peer [VERIFIED: codebase]
- `scripts/pi-deploy/cyclonedds.xml` — no phantom peer [VERIFIED: codebase]
- `/home/santi/.config/cyclonedds-tailscale.xml` — live elder-plops bridge config confirmed [VERIFIED: filesystem]
- `docker-compose.yml` + `docker-compose.override.yml` — bridge service definition confirmed [VERIFIED: codebase]
- `.planning/milestones/v1.0-MILESTONE-AUDIT.md` — ACTR-03 and CAM-03 failure documentation [VERIFIED: codebase]

### Secondary (MEDIUM confidence)

- rclnodejs 1.9.0 QoS constructor signature — [CITED: https://robotwebtools.github.io/rclnodejs/docs/1.9.0/QoS.html]
- rclnodejs QoS enum constants — [CITED: https://app.unpkg.com/rclnodejs@0.21.2/files/types/qos.d.ts]
- rclnodejs `createSubscription` options overload — [CITED: https://app.unpkg.com/rclnodejs@1.9.0/files/types/node.d.ts]
- CycloneDDS `LeaseDuration` and `InitialLocatorPruneDelay` — [CITED: https://cyclonedds.io/docs/cyclonedds/latest/config/config_file_reference.html]

### Tertiary (LOW confidence)

- A1 (`rclnodejs.QoS` import path) — inferred from type definitions, not directly tested

---

## Metadata

**Confidence breakdown:**
- TDEBT-01 implementation: HIGH — publisher QoS verified in codebase; subscriber API verified in rclnodejs 1.9 docs; exact code pattern ready
- TDEBT-02 diagnosis: HIGH — audit documentation confirms the phantom peer and its origin; repo configs confirmed clean
- TDEBT-02 fallback tuning: MEDIUM — CycloneDDS lease duration values from official docs; real-world effect depends on rmw_cyclonedds version on Pi
- rclnodejs QoS import path (A1): LOW — requires a test build to confirm

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (stable stack; rclnodejs 1.9.0 is current latest)
