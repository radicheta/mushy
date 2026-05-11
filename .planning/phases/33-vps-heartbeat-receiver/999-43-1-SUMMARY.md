# Phase 999.43.1 — ntfy.sh Tier 2 out-of-band channel — SUMMARY

**Status:** SHIPPED 2026-05-11 (immediately after Phase 33).
**Closes:** the actual mitigation gap of `project_2026_05_07_fc1_reboot_unrecoverable`. Phase 33 only handled in-band Signal alerts; this closes the case where home network itself is dead.

## What shipped

`vps/heartbeat-receiver/index.js` `dispatchAlertTier2()` is no longer a placeholder. When Tier 1 (Signal via bridge) fails — including the case where the bridge or home network is unreachable from the VPS — the receiver now POSTs to ntfy.sh.

Channel: `https://ntfy.sh/mushy-alerts-7f3a9c2b8e` (operator-only topic, kept out of git, lives on VPS at `/etc/mushy-heartbeat/ntfy.env` mode 640 root:mushy). Configured via systemd `EnvironmentFile=-/etc/mushy-heartbeat/ntfy.env` (optional with leading `-`, so the receiver still starts in deployments without Tier 2).

ntfy headers used: `Title: mushy: <source> silent`, `Priority: urgent`, `Tags: rotating_light,mushroom`. Body is the same human-readable message as Tier 1.

## Acceptance — full E2E proven

| # | Test | Result |
|---|------|--------|
| 1 | Direct curl POST to ntfy.sh topic delivers to operator phone | PASS — operator confirmed at 21:25 |
| 2 | Receiver picks up `NTFY_URL` from `EnvironmentFile` at boot | PASS — startup log: `Tier 2 alert path: ntfy https://ntfy.sh/<redacted>` |
| 3 | Inducing a Tier 1 failure (drop-in override `BRIDGE_URL=http://10.66.0.99:9999`, an unreachable peer), then stopping fc1 timer for >3min, fires ntfy | PASS — log shows `alert_fired` at 00:29:50 → `tier2_dispatched` at 00:29:51 (Tier 1 failed fast on unreachable peer, fallthrough succeeded) |
| 4 | Operator receives ntfy push with correct title + body | PASS — confirmed by operator |
| 5 | Override removed, normal operation restored | PASS — BRIDGE_URL back to `10.66.0.12:8081`, fc1 timer running |

## Failure-mode analysis (what's still NOT covered)

- **ntfy.sh itself is down at the same moment** — Tier 2 fails too. Receiver falls through to existing `OUT_OF_BAND_ALERT_MISSED` log entry, but the operator still wouldn't see it in real time. Mitigation: a Tier 3 channel (Twilio SMS, Pushover, or a second ntfy host like a self-hosted ntfy on a different region VPS). Defer until ntfy.sh demonstrates a reliability problem; in 5 years of public ntfy operation it's been exceptionally reliable.
- **Topic guessability** — `mushy-alerts-7f3a9c2b8e` is unguessable but anyone who learns it can spam the channel. ntfy supports access tokens for self-hosted setups; for the hosted free tier, topic obscurity is the only auth. If we ever get spam, rotate to a new random topic, update both `/etc/mushy-heartbeat/ntfy.env` and the operator phone subscription.
- **Operator phone offline** — if your phone is dead/airplane mode/etc., ntfy queues the push for delivery on next reconnect. Not a structural gap.

## Files

```
MODIFIED:
  vps/heartbeat-receiver/index.js                              dispatchAlertTier2 wired to ntfy
  vps/heartbeat-receiver/mushy-heartbeat-receiver.service      + EnvironmentFile=-/etc/mushy-heartbeat/ntfy.env

DEPLOYED (NOT in repo):
  VPS:
    /opt/mushy-heartbeat-receiver/index.js                     (replaced)
    /etc/systemd/system/mushy-heartbeat-receiver.service       (replaced)
    /etc/mushy-heartbeat/ntfy.env                              (NTFY_URL=https://ntfy.sh/<topic>; root:mushy 640)
```

The topic value is intentionally NOT in repo — operator secret. To re-deploy on a fresh VPS: install Phase 33 first, then create `/etc/mushy-heartbeat/ntfy.env` with the topic URL on the operator phone's ntfy subscription.

## Operational reference

- **Test ntfy from anywhere:** `curl -X POST https://ntfy.sh/<topic> -d "test message"`
- **Verify receiver loaded NTFY_URL:** `ssh mushy@178.105.84.13 'sudo journalctl -u mushy-heartbeat-receiver -n 50 --no-pager | grep "Tier 2"'`
- **Force Tier 2 fallback test (without breaking production):** drop in `/etc/systemd/system/mushy-heartbeat-receiver.service.d/99-test.conf` with `[Service]\nEnvironment=BRIDGE_URL=http://10.66.0.99:9999`, restart receiver, stop fc1 timer for 4min. Remove drop-in + restart receiver after.
