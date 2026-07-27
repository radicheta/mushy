# wg-hub-watchdog (MUSHY-29)

Self-heals fc1's `wg-hub` tunnel to the Hetzner VPS hub when its WireGuard
handshake goes stale, so a silent CGNAT drop no longer produces ~26h of false
`🚨 fc1 silent` heartbeat alerts (2026-07-11 incident).

**Scope guarantee:** only ever restarts `wg-quick@wg-hub`. It never touches
`wg0` (DDS telemetry → bridge → Mission Control) or the LAN SSH path. Bouncing
`wg-hub` is the exact manual mitigation that resolved the incident.

## How it works

`mushy-wg-hub-watchdog.timer` runs `wg-hub-watchdog.sh` every 2 min. The script
reads the newest peer handshake from `wg show wg-hub latest-handshakes`; if it is
`0` (never) or older than `WG_HUB_STALE_SEC` (default 180s), it runs
`systemctl restart wg-quick@wg-hub`. 180s > `persistent-keepalive` (25s), so a
healthy or just-restarted link never trips it.

## Install on fc1 (run on the box, needs sudo)

```bash
# from the repo checkout on fc1
sudo install -m 0755 scripts/wg-hub-watchdog/wg-hub-watchdog.sh /usr/local/bin/wg-hub-watchdog.sh
sudo install -m 0644 scripts/wg-hub-watchdog/mushy-wg-hub-watchdog.service /etc/systemd/system/
sudo install -m 0644 scripts/wg-hub-watchdog/mushy-wg-hub-watchdog.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mushy-wg-hub-watchdog.timer
```

## Verify

```bash
systemctl status mushy-wg-hub-watchdog.timer
systemctl list-timers mushy-wg-hub-watchdog.timer
# force a run and watch the decision:
sudo systemctl start mushy-wg-hub-watchdog.service
journalctl -u mushy-wg-hub-watchdog.service -n 20 --no-pager
# a stale link logs "bouncing wg-quick@wg-hub"; a healthy link logs nothing.
```

## Tuning

Override the staleness threshold via a systemd drop-in if 180s proves too tight
or too loose for the CGNAT path:

```bash
sudo systemctl edit mushy-wg-hub-watchdog.service
# [Service]
# Environment=WG_HUB_STALE_SEC=300
```
