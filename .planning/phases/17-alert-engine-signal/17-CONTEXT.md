# Phase 17: Alert Engine + Signal - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the first standalone **elder-plops agent** — a Signal alerter that:
1. Fires Signal PROBLEM/RECOVERY messages for the four fault conditions (Pi offline, sensor ERROR past grace, RH out-of-band, humidifier stuck)
2. Sends a daily watchdog heartbeat
3. Supports bidirectional snooze via Signal reply
4. Is env-var configured end-to-end

Runs on elder-plops as a sibling service to `bridge`. Nothing in this phase touches fc1. Threshold tuning happens in Phase 20 after ≥1 week of live behavior.

</domain>

<decisions>
## Implementation Decisions

### Architectural pattern (Shape A — locked for v1.3 and beyond)
- **D-01:** Bridge remains the single ROS↔outside-world gateway. It does not grow alerter logic. Agents are independent containers that consume bridge WS/REST.
- **D-02:** Alerter is the **reference implementation** for the future agent pattern. Weather poller (999.12), maturity detector (999.5), farmer-app backend (999.11), and any future autonomous agents follow the same shape.
- **D-03:** Each agent = its own compose service, its own process, its own crash domain, its own volume. Bridge crash = every agent sees "offline" (which for alerter is the correct Pi-offline signal path — bridge is the vantage point).

### Deployment topology
- **D-04:** Alerter runs as a standalone compose service on elder-plops named `alerter` (sibling to `bridge`, `timescale`, `openmct`, `signal-cli`).
- **D-05:** Telemetry ingress: alerter is a **WS client** of bridge (`ws://bridge:8081`). No rclnodejs/CycloneDDS in the alerter image. Alerter relies on bridge's replay-on-connect for `sensor_health` and `humidifier` state.
- **D-06:** Signal egress: alerter POSTs to `http://signal-cli:8080` on the compose internal network.
- **D-07:** Alerter state (cooldown timers, snooze windows, active-alert map) starts **in-memory**. Promote to a Timescale `alerts` table only if restart-spam proves noisy in soak (per ALRT-03).

### Code layout
- **D-08:** New top-level directory: **`src/agents/`** — home for all elder-plops-side autonomous services. Signals a clean separation from `src/mission-control/` (HMI stack: OpenMCT + bridge) and `src/chambers/` (Pi-side ROS packages).
- **D-09:** Phase 17 creates `src/agents/alerter/` with its own `package.json`, `Dockerfile`, and entrypoint. Deps: `ws`, `pg` (for eventual Timescale promotion), a Signal REST client (axios/fetch).
- **D-10:** No shared code with bridge in this phase. If duplication appears later (e.g. reconnect/backoff logic), extract to `src/agents/_shared/` — not a Phase 17 concern.

### Signal service
- **D-11:** `signal-cli-rest-api` (bbernhard) declared in **`docker-compose.override.yml`** alongside the existing bridge tailscale/CycloneDDS override — keeps production-only / farm-only concerns out of the main compose file.
- **D-12:** Account state in a **named Docker volume** (`signal-cli-data`). Survives container recreation. Backed up with the rest of the stack volumes; exact backup plan is out of scope for Phase 17.
- **D-13:** signal-cli-rest-api is **internal-only** on the compose network — not published to host, not Tailscale-served. Only `alerter` talks to it. Keeps attack surface minimal; manual debugging goes through `docker exec` + curl during registration.

### Claude's Discretion (researcher/planner to propose, no user preference locked)
- Fault detection rules: what exactly defines "Pi offline" (stale ROS heartbeat timeout, Tailscale ping, or both) and "humidifier stuck" (commanded-vs-observed mismatch, RH trajectory post-ON, duration)
- Initial cadences: WARN vs CRITICAL repeat intervals, per-alert cooldown, `ALERT_HUMIDIFIER_STUCK_MIN`, heartbeat time-of-day (farmer TZ)
- Signal message body template: severity prefix, value formatting, timestamp, link wording
- Snooze grammar: strict `snooze <type> <duration>` vs fuzzy vs menu
- Whether `ALERT_RH_TARGET`/`ALERT_RH_BAND` are independent env vars or read from `fc_config.yaml` — researcher to recommend
- Which signal-cli-rest-api mode (`normal`/`json-rpc`/`native`) and exact container image tag

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/ROADMAP.md` §"Phase 17: Alert Engine + Signal" — goal, success criteria, opening checks, pre-phase gates
- `.planning/REQUIREMENTS.md` — ALRT-01 through ALRT-08 (full locked spec for Signal service, 4 alert types, dedup/throttle, heartbeat, warm-up suppression, env-var config, snooze, dashboard link)

### Existing code to pattern-match and consume
- `src/mission-control/bridge/src/index.js` — bridge WS server that alerter will client into; see §humidifier subscribe (line 390+), §sensor_health subscribe (line 404+, replay-on-connect at 293+), §/health route (line 161+)
- `src/mission-control/bridge/package.json` — reference deps (`ws@^8.16.0`, `pg@^8.20.0`, `express@^5.2.1`) and Node container conventions
- `docker-compose.yml` + `docker-compose.override.yml` — service declaration style, network config, volume pattern
- `.env` conventions at repo root (CORS_ORIGIN, TIMESCALE_PASSWORD) — new alerter env vars follow the same flat pattern

### System behavior alerter must respect
- Phase 15 sensor warm-up: alerter must consume `sensor_health` WARN state and suppress alerts during the 20s grace (ALRT-05). See `src/chambers/fc-core/fc_core/fc_controller.py` sensor warm-up logic and Phase 15 CONTEXT at `.planning/milestones/v1.2.1-phases/15-sensor-warmup-grace-period/15-CONTEXT.md`.
- Phase 16 `sensor_health` broadcast shape: flattened KeyValue object on bridge WS. See `.planning/milestones/v1.2.1-phases/16-system-health-panel/16-CONTEXT.md`.
- Phase 14 stall recovery behavior — informs what Pi-offline debounce should tolerate (~9s recovery).

### Research inputs
- `.planning/research/ARCHITECTURE.md`, `.planning/research/STACK.md`, `.planning/research/PITFALLS.md`
- `.planning/research/SUMMARY.md` — v1.3 research synthesis

### External (researcher to fetch, not pre-cached)
- bbernhard/signal-cli-rest-api README + API spec (`/v2/send`, `/v1/receive`, registration flow)
- signal-cli primary-account registration flow over SMS (4G router gate)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Bridge WS broadcast + replay-on-connect** (`bridge/src/index.js:293+`): alerter gets initial humidifier + sensor_health state on connect without polling ROS.
- **Bridge `/health` REST** (`bridge/src/index.js:161+`): alerter can poll this as a secondary liveness signal (e.g. detect bridge itself wedged but still WS-connected).
- **Timescale pool (`pg`)**: pattern ready if Phase 17 soak forces the alerts table upgrade.
- **docker-compose.override.yml**: established home for farm-specific config (tailscale CycloneDDS already lives here).

### Established Patterns
- **Single-file Node services**: bridge is 450 LOC in one `index.js`. Alerter should stay similarly compact — a second file only when it earns one.
- **Env-var config, no config files** in the Node side (contrast with fc_core YAML on Pi). ALRT-06 is already aligned.
- **git → fc-system-sync → prod**: elder-plops deploys via `docker compose up -d --build`. No code lands on fc1 in Phase 17.
- **farmos_agent precedent**: a separate ROS2 lifecycle node already exists as a standalone agent on the Pi side — alerter is its elder-plops analog.

### Integration Points
- **Inbound telemetry**: `ws://bridge:8081` messages `{humidity, temperature, co2, humidifier, sensor_health, timestamp}` (shapes defined in bridge index.js).
- **Outbound Signal**: HTTP to `http://signal-cli:8080/v2/send` (internal compose DNS).
- **Receive loop**: signal-cli-rest-api `/v1/receive` or JSON-RPC mode — researcher to decide.
- **Dashboard link**: Phase 18 will serve `/farmer` from bridge on `http://elder-plops-ts:8081/farmer`. Phase 17 hardcodes this URL (env var) per ALRT-08, even though dashboard doesn't exist yet — link will 404 until Phase 18 lands, which is acceptable (both phases ship in v1.3).

</code_context>

<specifics>
## Specific Ideas

- Framing: alerter is "mr robot at the farm" — groundwork for a lineage of autonomous agents, not a one-off. Every design choice should be evaluated against "does this pattern extend to weather/maturity/farmer-app agents?"
- `src/agents/` as a top-level directory is a deliberate semantic signal: **"Mission Control" = HMI for humans**, **"agents" = autonomous services that act on chamber state**. The two are siblings, not nested.
- Bridge is a nervous system, not a server. Keep it boring. Agents are where intelligence accumulates.

</specifics>

<deferred>
## Deferred Ideas

- **Timescale `alerts` table** — promote from in-memory only if restart-spam is observed during Phase 17 soak (per ALRT-03). Don't pre-build.
- **Shared agent utilities (`src/agents/_shared/`)** — extract reconnect/backoff/signal-client only when the second agent (weather or maturity) lands. Premature today.
- **MJPEG/image attachments in Signal messages** — explicitly out per REQUIREMENTS.md non-goals; dashboard link is the vehicle.
- **Multi-recipient routing / on-call rotation** — single farmer recipient for v1.3. Revisit when farm scales beyond one operator.
- **Backup strategy for `signal-cli-data` volume** — Phase 17 just creates the volume; formal backup plan is separate ops work.
- **Extracting bridge `/farmer` static serving into its own agent** — interesting thought for later; Phase 18 serves from bridge as scoped.

</deferred>

---

*Phase: 17-alert-engine-signal*
*Context gathered: 2026-04-18*
