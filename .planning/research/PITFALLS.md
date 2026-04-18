# Domain Pitfalls: v1.3 Alerts + Unified Farmer Dashboard

**Domain:** Signal alerting bot + multi-source farm ops dashboard (ROS2 + FarmOS Drupal)
**Researched:** 2026-04-18
**Project:** Mushroom Farm — v1.3 milestone planning input
**Confidence:** HIGH for project-specific items (drawn from lived v1.0–v1.2.1 history); MEDIUM for Signal-specific constraints (signal-cli GitHub issues + Signal support docs)

---

## Part 1 — Signal / Chat Alert Pitfalls

### CRITICAL: Flap-storm (alert flood on sensor bounce)

**What goes wrong:** The SCD41 humidity reading can jitter by ±0.5–1% around the ±1% operating band edge. Without debounce, a single sensor bounce can fire "RH out-of-band" and "RH recovered" alternately 10–20 times before the value settles. The farmer mutes the Signal group after the third alert and misses the next real excursion.

**Why it happens:** A naive alert checks `current_value > threshold` on every sensor publish interval (currently ~5 s). The operating band is ±1% by empirical choice; the SCD41 reports at ±1.8% humidity accuracy (nominal ±6% from manufacturer, tighter in practice). The threshold and sensor noise floor are uncomfortably close.

**Prevention:**
- Require N consecutive out-of-band readings before firing (minimum 3, suggest 5 — covers ~25 s of consecutive out-of-band at 5 s publish rate).
- Suppress the `RH recovered` message if the alert fired fewer than 60 s ago (avoids rapid on/off spam).
- Store the last-alerted state so alerts only fire on transitions, not on each tick while already in an alerted state.
- Log suppressed alerts to TimescaleDB so the record isn't lost — silent suppression is fine for Signal, but the data must exist for later review.

**Warning signs during development:** In simulation or soak test you see multiple identical alerts within a 30 s window. If you see it in dev, the farmer will see it in prod.

**Phase:** Alert threshold + debounce logic must be spec'd and tested in the signal-alert implementation phase before any real threshold firing is enabled on fc1.

---

### CRITICAL: Missing recovery notification

**What goes wrong:** "RH out-of-band" fires at 02:00. The humidifier recovers by 02:03. If there is no "RH recovered" message, the farmer wakes at 07:00, sees the alert, and doesn't know if the chamber is still broken or has been fine for five hours. They can't sleep through alerts if recovery is silent — so they either check every alert manually (alert fatigue) or disable all alerts (worse).

**Prevention:**
- Every alert type that fires a PROBLEM message must have a corresponding RECOVERY message.
- Recovery message must include duration: "RH out-of-band RESOLVED — was out of band for 3 min 07 s."
- Test the recovery path explicitly: fire a synthetic threshold crossing, verify PROBLEM fires, correct the value, verify RECOVERY fires.

**Warning signs during development:** Alert tests that only verify the PROBLEM path and not the RECOVERY path.

**Phase:** Implement recovery messages in the same phase as the PROBLEM messages. Never ship PROBLEM without RECOVERY.

---

### CRITICAL: Bootstrap chicken-and-egg (Pi-offline alert from the offline Pi)

**What goes wrong:** The desired alert is "fc1 is unreachable." fc1 going offline is exactly the condition that prevents fc1 from sending the alert. A bot running on fc1 cannot alert on its own absence.

**Why it happens:** It's easy to scope alert logic as "add to fc_core" or "add to bridge" and not notice the liveness problem until the Pi actually goes offline.

**Prevention:**
- The Pi-offline alert must originate from a process that is NOT on fc1. Elder-plops is the natural home — it already runs the bridge that talks to fc1 over Tailscale.
- Implementation: elder-plops pings fc1's Tailscale IP (100.96.239.75) or polls the bridge's `/health` endpoint at a configurable interval. If N consecutive checks fail, Signal alert fires.
- The alert process on elder-plops must itself have a watchdog (see next pitfall).
- Do not implement this as a ROS2 node on fc1. It will not fire when fc1 is down.

**Warning signs during development:** Alert logic lives in a Python node under `fc_core`, or in a systemd service on the Pi, or triggered by a ROS2 topic from the Pi.

**Phase:** Must be a deliberate architecture decision at the start of the alert phase. Wrong placement here requires a rewrite.

---

### CRITICAL: Alert bot dies silently (no liveness / heartbeat)

**What goes wrong:** The Python alerting daemon crashes on a Monday afternoon due to an unhandled exception (e.g., Signal API timeout, JSON parse error). Nothing is monitoring the monitor. The farmer receives zero alerts for two weeks until they notice something feels off and manually check. This is the worst failure mode — the system appears healthy because it's quiet.

**Why it happens:** Alerting code is "background infrastructure" — it doesn't have a visible output that anyone checks. Service restarts may mask recurring crashes that consume all retry budget before the first real alert fires.

**Prevention:**
- Daily heartbeat message: the alert bot sends a Signal message every 24h (e.g., "Farm watchdog: fc1 up 4d 3h, RH 79.8%, last alert: none in 48h"). The farmer expects this. If it doesn't arrive, that IS the alert.
- The heartbeat must come from the same code path as real alerts — not a separate script. If the heartbeat doesn't arrive, the alert path is broken.
- Systemd `Restart=always` + `RestartSec=30` for the alerting service. Log restart count. Alert if `NRestarts > 3` within an hour.
- Use `Type=notify` or a watchdog ping in systemd if the alert daemon supports it. At minimum, write a PID file and have a cron-based liveness check.

**Warning signs during development:** The alert daemon has no heartbeat mechanism. Crash handling is `try/except: pass`. No restart policy in the service unit.

**Phase:** Heartbeat implementation is not optional — ship it in the same phase as the alert bot, not deferred.

---

### Signal-specific: Linked device session expiry

**What goes wrong:** signal-cli is registered as a linked device against the farmer's phone number. Signal's protocol expires linked devices after 45 days of inactivity (confirmed in Signal support docs). If the bot has been quiet (no alerts, no heartbeat), the linked device de-registers silently. The next time an alert condition occurs, signal-cli returns an error and no message is sent.

**Why it happens:** Linked devices that don't communicate regularly lose their session. The primary device (farmer's phone) is not notified of the de-registration.

**Prevention:**
- The daily heartbeat message (see above) also serves as an inactivity prevention mechanism — 24h heartbeat keeps the session alive well within the 45-day window.
- Add explicit error handling for signal-cli exit code / stderr indicating de-registration. Log and escalate (email/syslog) if message sending fails, since Signal itself can't be used to report the failure.
- Consider registering the bot on a dedicated SIM/number rather than as a linked device. A primary account on a cheap SIM is not subject to linked-device expiry. Trade-off: requires physical SIM and periodic SMS verification (~every 120 days per Signal account expiry policy).
- Test re-registration procedure. Document it in OPERATIONS.md. You will need it.

**Confidence:** MEDIUM — 45-day inactivity expiry confirmed via Signal support docs and signal-cli GitHub issues. Exact de-registration error messages vary by signal-cli version.

**Phase:** Registration decision (linked device vs dedicated number) must be made before implementing the alerting phase. It affects operational runbook.

---

### Signal-specific: Rate limiting on burst sends

**What goes wrong:** After a flap-storm (if debounce is not implemented), signal-cli hits Signal's server rate limit (HTTP 413). The limit is undocumented but practically observed at roughly 10–20 messages in quick succession. After hitting the limit, messages are queued and delayed, or dropped entirely depending on signal-cli version. Solving the CAPTCHA challenge that rate-limiting triggers requires manual intervention.

**Prevention:**
- Debounce (see flap-storm pitfall) prevents the underlying cause.
- Add a send-rate limiter in the alert code: maximum N messages per hour from the bot. Queue or drop excess with a log entry.
- Never send attachments (e.g., camera snapshots) in alert messages unless explicitly needed. Attachments increase the risk of triggering size or rate limits and have a ~100MB upload limit per Signal message.

**Warning signs during development:** Alert code calls signal-cli in a tight loop without backoff or deduplication.

**Phase:** Rate-limit wrapper should be part of the initial alert implementation, not retrofitted.

---

### Alert fatigue (operator mutes after false positive)

**What goes wrong:** One false-positive alert (e.g., sensor warm-up spike firing "RH critical" during fc-core restart) causes the farmer to mute the Signal group. All subsequent real alerts are missed silently.

**Why it happens here specifically:** The v1.2.1 sensor warm-up grace period (20s WARN→OK on `/fc1/sensor_health`) was added specifically because early-boot spikes were causing misleading state. If the alert bot does not respect the `grace` light from the sensor_health topic, it will fire on every fc-core restart.

**Prevention:**
- The alert bot must consume `/fc1/sensor_health` (or the WS broadcast equivalent) and suppress threshold alerts during the grace window.
- Test: restart fc-core, verify no alerts fire during the 20s grace period, verify alerts resume after grace.
- Alert level tuning: start with only the highest-severity alerts active (Pi offline, sensor ERROR for >5 min). Add lower-severity alerts after the farmer has lived with the system for a week and confirmed signal/noise ratio is acceptable.
- Provide a simple per-alert-type enable/disable in config, without requiring a redeploy.

**Phase:** Alert suppression during grace period must be verified in the same test suite as alert firing. It is a correctness requirement, not a nice-to-have.

---

### Out-of-band threshold config (hardcoded values require redeploy to change)

**What goes wrong:** Alert thresholds (RH out-of-band, CO2 high, temperature warning) are hardcoded in the Python alerting script. The farmer wants to tighten the RH alert threshold after observing the chamber for a week. This requires a code edit, commit, push, and service restart — same friction as any code change. The farmer doesn't do it and lives with a miscalibrated alert indefinitely.

**Prevention:**
- Store alert thresholds in `fc_config.yaml` alongside control parameters. The alerting service reads the same config file as fc-core.
- This also means a config push via `git push fc1/prod` (or the elder-plops equivalent) is sufficient to update thresholds without a code change.
- Document which config keys control which alerts in OPERATIONS.md.

**Phase:** Config-driven thresholds should be designed in from the start, not retrofitted.

---

## Part 2 — Dashboard Pitfalls

### CRITICAL: Stale WebSocket connection looks live

**What goes wrong:** The farmer's browser tab has been open for 6 hours. The WebSocket to the bridge reconnected silently after an elder-plops bridge restart, but the reconnect landed before the next sensor publish. The chart shows data from 30 minutes ago. There is no loading indicator, no stale banner, no last-updated timestamp. The farmer makes a decision based on 30-minute-old RH data.

**Why it happens here specifically:** The bridge's WS broadcasts are event-driven (on sensor message arrival). If a reconnect happens between sensor messages, the client may sit with stale in-memory values for up to the sensor publish interval (5s normally, potentially longer during bridge restarts). This is worse on the farmer dashboard than on Mission Control because it's designed to be glanced at, not scrutinized.

**Prevention:**
- Display last-updated timestamps on every live value, computed as `(now - last_message_ts)`. Use bridge-computed `_age_sec` fields (the v1.2.1 pattern from HFIX-03) rather than client-computed ages to avoid clock skew.
- Show a "stale" banner (yellow or grey) when any value has not updated in more than `2 * publish_interval` (10s for a 5s interval). This was the lesson behind `feedback_gap_over_noise.md` — gap over noise, honest grey over green.
- The farmer dashboard must replicate the sensor_health replay-on-connect pattern (Phase 16.1 shim) so the status panel is not grey on cold open. If a new dashboard is built without this, it will regress the UX that the farmer already attested.

**Warning signs during development:** Timestamps shown as "just now" or not shown at all. No staleness detection. Dashboard code uses client `Date.now()` to interpret server-sent timestamps.

**Phase:** Staleness display and sensor_health replay must be verified in the first iteration of the farmer dashboard, before any user testing.

---

### Sensor offline vs sensor reads zero — no distinction

**What goes wrong:** The humidity sensor returns 0.0% RH (or the bridge shows `null`). The dashboard displays "0%" in a number widget. The farmer sees 0% and initially thinks the mushrooms are in a desert. More subtle: the humidifier starts running continuously trying to reach setpoint, causing hardware wear and water overflow, because the controller reads 0 as "way below setpoint."

**Why it happens here specifically:** This already bit the project during the SHT30/SCD41 transition (see FARMER-APP-NOTES). The dashboard showed numbers without provenance. The farmer spent 40 minutes on calibration before realizing the sensor was offline.

**Prevention:**
- The farmer dashboard must reflect sensor_health state visually on every number that depends on a sensor. If sensor_health is ERROR, the number should be greyed out or replaced with "OFFLINE" rather than "0" or the last reading.
- Never show the last known value as if it were live when the sensor is in ERROR state. Show a gap or an explicit "last seen: T ago" with a distinct visual style.
- Design principle from FARMER-APP-NOTES: "81.3% RH (SCD41, ±6%)" — source provenance travels with every number.

**Phase:** Sensor health integration is mandatory in the farmer dashboard MVP. Not a polish step.

---

### Browser clock skew interpreting server timestamps

**What goes wrong:** The farmer dashboard receives a timestamp from the bridge (e.g., `{ humidity: 81.3, timestamp: 1713456789123 }`). The browser subtracts `Date.now()` to compute age. If the browser clock is ahead or behind by even 30s (common on mobile devices that haven't synced), the computed age is wrong. "5 minutes ago" becomes "4:30 ago" or "5:30 ago." More critically, a clock skew of >30s can flip a staleness check from "fresh" to "stale" incorrectly.

**Lesson already learned:** v1.2.1 HFIX-03 explicitly moved to server-computed `last_frame_age_sec` for this reason, per bridge comments and RETROSPECTIVE. This pattern must be carried forward to the new farmer dashboard — not re-learned.

**Prevention:**
- Use server-computed `_age_sec` fields from the bridge `/health` endpoint and WS broadcasts wherever age matters.
- Never do `Date.now() - server_timestamp` in the browser for anything that drives a UI state decision (stale/fresh, ok/warn).
- For the farmer dashboard, the bridge should expose `humidity_age_sec`, `co2_age_sec` etc. as explicit computed fields alongside the raw values.

**Phase:** Establish this as a convention in the bridge API spec before building the farmer dashboard frontend.

---

### Timezone displayed in UTC when farmer is in farm-local time

**What goes wrong:** The dashboard shows "last updated: 2026-04-18T02:31:00Z". The farmer is on Pacific time (UTC-7). The "2:31 AM" means nothing without conversion. This is worse for alert timestamps: "alert fired at 14:22:07Z" requires mental arithmetic the farmer won't do at 7am.

**Why it happens here specifically:** The Mission Control (OpenMCT) timezone plugin exists (`src/mission-control/frontend/plugins/timezone/plugin.js`) and is already part of the stack. The farmer dashboard, if built separately, will not inherit this automatically.

**Prevention:**
- Use the browser's `Intl.DateTimeFormat` with `timeZone: undefined` (resolves to local browser timezone) for all human-readable timestamp rendering. Do not hardcode UTC.
- Show UTC on hover/detail view for the operator, but default to farm-local for grower-facing displays.
- If the timezone plugin can be extracted from the OpenMCT plugin and reused, use it. Otherwise replicate the pattern.

**Phase:** Include timezone handling in the initial farmer dashboard spec. It is a one-line fix if planned in; a tedious grep-and-replace if retrofitted.

---

### Mobile screen real estate — charts unreadable on phone

**What goes wrong:** The farmer is in the fruiting chamber (40m from main infra, on their phone) and opens the dashboard. All widgets are desktop-sized. Charts require horizontal scrolling. Number readouts are 11px. The farmer gives up and uses Mission Control instead (which is even more desktop-heavy), or just checks nothing.

**Why it happens here specifically:** Mission Control (OpenMCT) is explicitly desktop-heavy per FARMER-APP-NOTES. The farmer dashboard is the first surface designed for phone-in-humid-chamber use. If it's built with desktop assumptions, the use case is lost.

**Prevention:**
- Phone-first layout from the start: single-column stacking, min touch target 44px, high contrast for humid/bright-light environments.
- Sparklines (small 48–72px trend lines) over full charts on the primary view. Full charts on tap/expand only.
- Defer chart rendering until user taps "expand" — reduces bandwidth on 4G.
- Test on an actual phone screen (or browser devtools mobile emulation) before any user testing.

**Phase:** Layout responsiveness must be a constraint from the first farmer dashboard implementation iteration, not a polish pass.

---

### Over-engineering the farmer dashboard frontend

**What goes wrong:** The dashboard is built with React + Redux + a charting library + a component framework, taking 3 phases to ship. The farmer gets a complex SPA that breaks when the CDN is unreachable from the farm, requires a build step to change a threshold color, and adds 200KB of JS to load on 4G.

**Why it happens here specifically:** v1.3 is scoping the farmer dashboard as a "HUD-only MVP." The FARMER-APP-NOTES explicitly state "stories, not tables" but the spec is a heads-up display, not an interactive app. A single HTML file with vanilla JS and inline CSS would cover this scope. The temptation to "build it properly" often means "build it later" in a project with production pressure.

**Prevention:**
- v1.3 scope: one HTML file served from elder-plops (nginx or the bridge itself), consuming the existing bridge WS and `/health` endpoint. No build step. No framework.
- If the file exceeds 400 lines of JS, that is a smell that scope crept.
- React, Vue, etc. are appropriate for v1.3+ when the farmer app gains interactive knobs and a story timeline. Not for a status HUD.

**Phase:** State this constraint explicitly in the farmer dashboard design phase. Reject any plan that proposes a frontend framework for the HUD MVP.

---

## Part 3 — Multi-Source Dashboard Pitfalls

### One source down silently hangs the page

**What goes wrong:** The farmer dashboard renders widgets from two sources: the Mission Control bridge (WS on port 8081) and FarmOS Drupal (API or embedded widgets). FarmOS is on a shared farm instance and occasionally responds slowly during Drupal cron runs or backups. The farmer dashboard waits for FarmOS data before rendering, so the entire page hangs. The farmer can't see fc1 chamber status because FarmOS is slow.

**Prevention:**
- Treat each data source as independent and failure-isolated. Render what is available; show a "FarmOS unavailable" stub for FarmOS widgets, and real data for bridge widgets.
- Set explicit timeouts on all FarmOS fetch calls (5s recommended). Do not allow one source to block the render of another.
- Load bridge data first (it's the primary ops surface), FarmOS data second (production records, less time-critical for a glance dashboard).

**Phase:** Source isolation and independent loading must be part of the initial dashboard architecture, not an afterthought.

---

### Re-auth storm (FarmOS session expires mid-day)

**What goes wrong:** The farmer opens the dashboard at 09:00. FarmOS API tokens (if using OAuth) expire after some TTL. At 14:00 the token expires. The next time FarmOS widgets try to refresh, they get a 401. If the error handling redirects the whole page to FarmOS login, the farmer loses their Mission Control view in the middle of a session. If the error is silent, FarmOS data goes stale without indication.

**Prevention:**
- Token refresh must happen transparently in the background, never by redirecting the whole page.
- If a FarmOS token cannot be refreshed (user session fully expired), show a "FarmOS: re-login required" stub in the FarmOS widget area only. The Mission Control portion of the dashboard continues working.
- Test with an intentionally short-lived token to verify the re-auth path before go-live.

**Phase:** Auth error handling must be specified and tested in the FarmOS integration phase, not discovered in production.

---

### CORS misconfiguration when browser talks to two origins

**What goes wrong:** The farmer dashboard page is served from elder-plops on port X. It makes a WS connection to the bridge on port 8081 (same host, different port — different origin). It also fetches from FarmOS on its own host. The browser enforces CORS and the bridge's `CORS_ALLOWED` env var (already an allowlist in index.js) does not include the farmer dashboard origin. Connections are silently blocked.

**Why it happens here specifically:** The bridge already has CORS handling with an explicit allowlist (`CORS_ALLOWED`). Adding a new origin for the farmer dashboard requires updating `CORS_ORIGIN` in the docker-compose `.env`. If this isn't done before the first test of the new dashboard, it will look like the bridge is broken when the new dashboard is the unconfigured consumer.

**Prevention:**
- Before building the farmer dashboard frontend, determine its serving origin (port, hostname) and add it to `CORS_ORIGIN` in `.env`.
- Test the bridge WS connection from the farmer dashboard origin explicitly as a first step — before implementing any UI logic.
- FarmOS CORS: FarmOS Drupal needs to allow requests from the farmer dashboard origin if fetching FarmOS APIs directly from the browser. If FarmOS API calls go server-side through the bridge, CORS is not an issue but adds latency.

**Phase:** CORS configuration must be verified at the start of the farmer dashboard phase, as a pre-condition check before any frontend work.

---

### FarmOS Drupal session cookies colliding with bridge session on embed

**What goes wrong:** If FarmOS widgets are embedded via iframe (or if the farmer dashboard includes FarmOS content inline), the browser's third-party cookie restrictions (Chrome/Safari SameSite=Lax default) prevent the FarmOS session cookie from being sent inside the iframe. The embedded FarmOS view shows a login wall. More subtly, if both the farmer dashboard and FarmOS set cookies on similar paths, session collision can log the farmer out of FarmOS when they open the dashboard.

**Prevention:**
- For v1.3 HUD MVP: do not use iframes. Fetch FarmOS data via API from the bridge (server-side proxy) and render it in your own widgets. Eliminates cookie collision entirely.
- If iframes are ever used later: FarmOS must be served from the same domain as the farmer dashboard (or a subdomain), and cookies must be `SameSite=None; Secure`.
- Practical v1.3 approach: the farmos_agent already has FarmOS API access patterns. Expose a `/farmos/summary` endpoint on the bridge that the farmer dashboard fetches, keeping all FarmOS auth server-side.

**Phase:** iframe embed should be explicitly ruled out in the v1.3 design. API proxy through the bridge is the safe path for this milestone.

---

## Part 4 — Integration-with-Existing-System Pitfalls

### Duplicating health logic between Mission Control plugin and farmer dashboard

**What goes wrong:** Mission Control (OpenMCT plugin.js) already interprets `sensor_health.level` and `camera.last_frame_age_sec` to drive the six-light status panel. If the farmer dashboard re-implements this logic independently, it will drift. Alert thresholds (e.g., "age > 10s means stale") become inconsistent between the two views. A farmer switching between views sees contradictory status colors for the same sensor.

**Prevention:**
- Extract the threshold constants and state-machine logic into a shared module or configuration value that both the Mission Control plugin and the farmer dashboard import.
- Alternatively: the farmer dashboard consumes the bridge `/health` endpoint directly and trusts the server-computed state — the bridge becomes the single source of truth for computed health state, and both dashboards just render it.
- Do not copy-paste health logic. If you find yourself doing so, stop and extract.

**Phase:** Identify the canonical health logic location before writing the farmer dashboard. Budget 30 minutes to extract it if it's currently inline in plugin.js.

---

### sensor_health replay pattern not carried to new dashboard

**What goes wrong:** Phase 16.1 added a `lastSensorHealthBroadcast` replay shim to the bridge: new WS clients receive the last sensor_health state immediately on connect, before the next fc_controller state transition. The farmer UAT that prompted this fix specifically involved hard-refresh showing grey lights for up to 60s on cold open.

If the new farmer dashboard subscribes to the same WS but does not handle the replayed `sensor_health` message on connect, the grey-on-cold-open problem re-emerges for the farmer dashboard even though it was fixed in Mission Control.

**Prevention:**
- The farmer dashboard WS client must handle `sensor_health` messages on connect (same as Mission Control does). The bridge already sends it; the dashboard must consume it.
- Add a cold-open test to the farmer dashboard verification: hard-reload the page after fc_controller has published at least one sensor_health update. Verify status lights are not grey.
- This is not a new feature request — it is a regression check. The bridge already does the right thing; the client just needs to listen.

**Phase:** Include explicit cold-open verification step in the farmer dashboard phase checklist. This is the exact failure mode that generated Phase 16.1 — do not repeat it.

---

### Shipping alerts without verifying delivery on the real Signal account

**What goes wrong:** Alert logic is tested in dev against a signal-cli instance with a test number. It works. The production deployment uses the farmer's real Signal number (or a linked device from it). On first real alert condition, signal-cli fails silently because: (a) the device is not linked, (b) the linked device session expired during the dev/test gap, (c) the CAPTCHA challenge flow was never completed for this number, or (d) the signal-cli version on elder-plops differs from dev.

**Why it happens here specifically:** The project has been burned by "but it worked in dev" before (compose-file drift in v1.0, bridge image cache in v1.0, warm-reconnect vs cold-open in v1.2.1). Signal delivery is an end-to-end path that cannot be verified without actually sending a message to the real recipient.

**Prevention:**
- Mandatory end-to-end delivery test before Phase complete: trigger a real test alert to the farmer's Signal number from the production elder-plops host and have the farmer confirm receipt. Not a signal-cli exit-code 0 test — a human reads the message on their phone.
- This test must be run on the same elder-plops service account / user that the production alerting daemon runs under. Permission issues or missing signal-cli data directories will surface here.
- Add delivery verification to the phase VERIFICATION.md as a hard human-attestation gate (not "human_needed" status that gets deferred — an explicit REQUIRED BEFORE MERGE gate).

**Phase:** End-to-end delivery test is a gate on the alerting phase, not a post-ship verification.

---

### Humidifier replay parity gap (carried from v1.2.1)

**What goes wrong:** The v1.2.1 RETROSPECTIVE notes: "Humidifier replay parity not shipped. sensor_health got a replay shim (16.1); humidifier state still relies only on ROS-level TRANSIENT_LOCAL replay to the bridge." On a cold-open of the farmer dashboard, the Humidifier light may still show grey if the bridge reconnects to ROS after the last TRANSIENT_LOCAL publish window.

**Why it matters for v1.3:** If the farmer dashboard is built with higher stakes for cold-open UX (it's the farmer's primary glance view, not a secondary ops surface), this gap will be more visible than it was in Mission Control.

**Prevention:**
- When implementing the farmer dashboard, audit which bridge WS fields have replay-on-connect coverage and which do not. Budget a follow-up task if the Humidifier state needs a replay shim for the new surface.
- Alternatively: poll `/health` once on page load to get `humidifier.last_msg_ts` and use it to render initial state, then switch to WS for live updates. This avoids the replay gap entirely for the farmer dashboard.

**Phase:** Audit bridge replay coverage as a pre-task in the farmer dashboard phase.

---

## Phase Assignment Summary

| Pitfall | Phase to Address |
|---------|-----------------|
| Flap-storm debounce | Signal alert implementation phase |
| Missing recovery notifications | Signal alert implementation phase (same PR as PROBLEM alerts) |
| Pi-offline bootstrap architecture | Alert architecture decision — first task of alert phase |
| Alert bot heartbeat / liveness | Signal alert implementation phase (ship with bot, not deferred) |
| Linked device expiry | Registration decision before alert phase begins |
| Signal rate limiting | Alert implementation phase (rate-limit wrapper) |
| Alert fatigue / grace suppression | Alert implementation phase (must test restart→no-alert path) |
| Out-of-band threshold config | Alert implementation phase (fc_config.yaml, not hardcoded) |
| Stale WS + sensor_health replay | First farmer dashboard phase (mandatory verification step) |
| Sensor offline vs reads zero | First farmer dashboard phase (MVP requirement) |
| Browser clock skew | Bridge API spec phase (before dashboard frontend) |
| Timezone handling | First farmer dashboard phase |
| Mobile layout | First farmer dashboard phase (constraint from start) |
| Over-engineering frontend | Design decision — state explicitly before dashboard phase |
| Source isolation (FarmOS down) | Multi-source dashboard phase |
| Re-auth storm | FarmOS integration phase |
| CORS misconfiguration | Pre-condition check at start of farmer dashboard phase |
| FarmOS cookie collision | Design decision — use bridge proxy, not iframe |
| Duplicate health logic | Identify canonical location before dashboard phase |
| sensor_health replay not carried forward | Farmer dashboard phase verification checklist |
| Shipping alerts without real delivery test | Hard gate on alert phase completion |
| Humidifier replay parity gap | Audit task at start of farmer dashboard phase |

---

## Sources

- v1.2.1 RETROSPECTIVE: cold-open vs warm-reconnect lesson, replay shim origin, humidifier parity gap
- v1.0 RETROSPECTIVE: "but it worked in dev" pattern (compose drift, image cache)
- FARMER-APP-NOTES-2026-04-11: sensor provenance principle, timezone wish, mobile use case, SHT30 offline blind-spot
- bridge/src/index.js: existing replay shim, CORS allowlist, server-computed age fields, health endpoint
- Signal support docs (support.signal.org): linked device 45-day inactivity expiry, account 120-day expiry
- signal-cli GitHub issues #1911, #1603, #1823: rate limiting behavior (HTTP 413, CAPTCHA challenge)
- Memory: `feedback_gap_over_noise.md`, `project_signal_alerts.md`, `project_phase12_camera_stall.md`
