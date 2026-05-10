# Phase 33 — VPS heartbeat receiver + outage-alert relay — CONTEXT

**Status:** scaffolded 2026-05-10/11 overnight, autonomous run continuing from Phase 32 ship.
**Source:** ROADMAP backlog 999.43 (filed 2026-05-10) + DECISION-6 workload #3 + memory `project_2026_05_07_fc1_reboot_unrecoverable` (the 11h-blind incident this directly mitigates).

## The problem

On 2026-05-07 fc1 went offline for 11 hours after a remote reboot (memory `project_2026_05_07_fc1_reboot_unrecoverable`). Nobody noticed because the in-house alerter on elder-plops was also dead — same home-network blackout took down both the chamber and the thing that's supposed to scream when the chamber goes silent. The only system that *could* have screamed was independent of the home network: the VPS we just provisioned in Phase 32.

This phase wires that.

## Architecture (locked tonight)

**Receiver:** single-file Node.js service on the VPS (`mushy-heartbeat-receiver`), systemd unit, listens on `127.0.0.1:9000` AND on `10.66.0.1:9000` (WG hub interface). Public internet does NOT see this endpoint — peers reach it through the WG tunnel they already have. UFW continues to block port 9000 from the public side; only the wg-hub interface forwards in.

**Senders:** lightweight POST clients on each monitored source. Two delivery paths:
- **Hosts** (fc1, elder-plops): systemd timer (or cron) every 60s, calls `curl http://10.66.0.1:9000/heartbeat -d {source,...}`. Total bandwidth: ~1KB/source/min = trivial.
- **Containers** (bridge, alerter, signal-cli, openmct, farmer-app): defer to follow-up — host heartbeats already cover the dominant failure mode (host down → all containers down → no heartbeat). Container-level granularity is nice-to-have, not blocker.

**Detection:** receiver runs an internal 30-second timer. For each known source, computes `time_since_last_seen`; if exceeds per-source threshold, fires alert. Per-source thresholds (locked):
- `fc1`: 3 minutes (chamber control critical)
- `elder-plops`: 3 minutes (bridge + alerter + DB host)
- (others added later)

**Alert delivery:** two-tier (locked tonight, ntfy tier deferred to 999.43.1):
- **Tier 1 — Signal via existing alerter signal-cli** (in-band): receiver POSTs to elder-plops bridge over wg-hub: `http://10.66.0.12:8081/heartbeat-alert` (NEW endpoint; bridge then dispatches via existing signal-cli docker network reach). Works when home network is reachable. Same delivery path the alerter uses for chamber alarms.
- **Tier 2 — out-of-band push** (deferred to 999.43.1): when home network is DOWN, Tier 1 is unreachable. Need an independent path: ntfy.sh push notification (free, no account needed beyond installing the ntfy app on the operator phone + subscribing to a unique topic). Can also do Twilio SMS if budget available. **Tonight scope:** receiver code is structured to allow plugging Tier 2 in later; placeholder logs `[OUT-OF-BAND ALERT MISSED — install ntfy or wire Twilio]` to local file when Tier 1 fails.
- **Self-pathology guard:** receiver also dedupes alerts (don't fire same alert every 30s — first fire, then exponential backoff: 1m, 5m, 15m, 60m).

**Storage:** `last_seen.json` flat file, written atomically. No SQLite, no Postgres, no migration story. ~10 sources × 100 bytes = 1KB; updated every 60s. `last_seen` survives restart; reset is `rm last_seen.json`.

## Decisions (locked)

| ID | Decision | Source |
|----|----------|--------|
| D-01 | Receiver implementation: single-file Node.js (no framework, just `http`), systemd unit, runs as `mushy` user on VPS | Simplicity over rigor; ~150 LOC max |
| D-02 | Sender implementation: bash + curl, scheduled by systemd timer (preferred) or cron (fallback if systemd timer unavailable) | Already on every Linux host, zero deps |
| D-03 | Heartbeat interval: 60s (all hosts) | Balance: fast enough to catch outages within 3min threshold; slow enough to be cheap |
| D-04 | Detection threshold: 3min staleness for all hosts (fc1, elder-plops) | 3× heartbeat interval = clear distinction between transient blip and real outage |
| D-05 | Alert dedupe: 1m → 5m → 15m → 60m exponential backoff per (source, type); reset on next successful heartbeat | Avoid alert storms; 11h-blind incident produced ZERO alerts because alerter was dead, not because of dedupe; this is for future double-alerting |
| D-06 | Alert delivery: Tier 1 = Signal via existing alerter→signal-cli path (NEW bridge endpoint `/heartbeat-alert`); Tier 2 = OUT-OF-BAND push (DEFERRED to 999.43.1, requires ntfy install or Twilio account) | DECISION-6 + tonight's autonomous-scope reality |
| D-07 | Receiver port: 9000/tcp, bound to `127.0.0.1` AND `10.66.0.1` (wg-hub iface only). UFW blocks 9000 from public internet (reuse Phase 32 UFW posture). | Defense in depth — receiver is not internet-facing |
| D-08 | Receiver auth: HMAC SHA-256 of body using a shared secret in `/etc/wireguard/heartbeat.secret` (mode 600, root-owned). Senders include `X-Heartbeat-HMAC` header. Receiver rejects mismatch. | Only WG peers can reach the endpoint, but defense in depth — if a peer is compromised, attacker still can't fake heartbeats from a different source. |
| D-09 | Bridge `/heartbeat-alert` endpoint: POST `{ source, message }`, dispatches via existing signal-cli docker network. Mirrors the receive-loop dispatch pattern from Phase 31. | Reuse Phase 31's signal-cli docker network access |
| D-10 | NOT in scope tonight: ntfy.sh out-of-band channel; container-level (vs host-level) heartbeats; web dashboard; metrics export to TimescaleDB | Each is its own phase / follow-up |
| D-11 | NOT in scope tonight: TLS for the receiver endpoint (would need cert; WG already encrypts) | WG handles transport encryption |
| D-12 | Restart-from-clean-state: receiver loads `last_seen.json` if present; if absent, starts fresh and won't fire alerts until each source has been seen at least once (no false positives at boot) | Operational safety |

## Acceptance (tonight)

1. ✓ Receiver service `mushy-heartbeat-receiver` running on VPS as systemd unit, listening on 127.0.0.1:9000 + 10.66.0.1:9000
2. ✓ POSTing a fake heartbeat from fc1 (`curl http://10.66.0.1:9000/heartbeat -d ...`) returns 200 + last_seen.json updates
3. ✓ Stopping a sender for >3min triggers an entry in `/var/log/mushy-heartbeat/alerts.log` on VPS
4. ✓ Bridge `/heartbeat-alert` endpoint exists, accepts POST, dispatches Signal via signal-cli (using the same docker-network reach pattern as Phase 31's receive-loop dispatch)
5. ✓ End-to-end smoke test: stop fc1's sender → VPS detects 3min later → Tier 1 fires → Signal alert lands on operator phone
6. ✓ Sender deployed on fc1 (systemd timer) and elder-plops (systemd timer or cron)
7. ✓ Documented out-of-band gap (D-06 Tier 2) in SUMMARY for user follow-up
8. ✓ All committed + pushed to mushy main + fc1/prod

## What's NOT in scope tonight (Phase 999.43.1 / 999.43.2 candidates)

- ntfy.sh integration (out-of-band push when home network is down)
- Twilio SMS fallback
- Container-level heartbeats (currently only host-level: fc1, elder-plops)
- Web dashboard for status
- Metrics export to TimescaleDB or Grafana
- Multi-tenant (multiple chambers)
- Alert escalation chain (e.g. "if no ack in 30min, page secondary contact")

## Composition with existing memories

- `project_2026_05_07_fc1_reboot_unrecoverable` — this is the incident-class this phase mitigates (Tier 1 will work; Tier 2 closes the 11h-blind gap fully)
- `project_phase32_vps_hub_shipped` — depends on the WG hub being up (it is)
- `feedback_alerter_env_convention_bridge_http_url` — bridge `/heartbeat-alert` endpoint must be reachable from VPS; uses same wg-hub IP as farmer-app (10.66.0.12:8081)
- `project_phase31_shipped` — the bridge-side dispatch pattern (`control_experiment.js` calling signal-cli) is the template for `/heartbeat-alert`
- `project_alerter_watchdog_quiet_topic_bug` (999.42) — composes naturally; the heartbeat receiver IS the right home for "controller liveness" once we add fc-core as a per-process source (vs just the host)
