#!/usr/bin/env bash
# wg-hub-watchdog — MUSHY-29
# Bounce wg-quick@wg-hub when its WireGuard handshake goes stale, so the
# Phase 33 heartbeat link to the VPS self-heals instead of firing false
# "fc1 silent" alerts for a day.
#
# Incident (2026-07-11): fc1's wg-hub tunnel dropped silently (0 B received,
# latest-handshake=0) behind CGNAT; persistent-keepalive could not recover a
# stale source-port mapping. The VPS heartbeat-receiver fired hourly
# "fc1 silent for N min" alerts for ~26h. The chamber + Mission Control were
# unaffected the whole time (they ride wg0, a separate tunnel).
#
# This watchdog ONLY touches wg-hub. It never touches wg0 (DDS telemetry ->
# bridge -> Timescale -> MC) or the LAN SSH path. Restarting wg-quick@wg-hub
# is the exact manual mitigation that resolved the incident.
#
# Runs from the systemd timer mushy-wg-hub-watchdog.timer (every 2 min).
# Requires root: `wg show` and `systemctl restart` both need it.
set -euo pipefail

IFACE="wg-hub"
# Restart when the newest peer handshake is older than this many seconds, or
# never happened. 180s > persistent-keepalive (25s), so a healthy or
# just-restarted link never trips it.
STALE_SEC="${WG_HUB_STALE_SEC:-180}"

# Hard guard: refuse to operate on anything but wg-hub.
[ "$IFACE" = "wg-hub" ] || { echo "$(date -Is) wg-hub-watchdog: refusing to touch $IFACE" >&2; exit 1; }

# If wg-quick@wg-hub isn't up, there's nothing for this watchdog to heal.
if ! wg show "$IFACE" >/dev/null 2>&1; then
  echo "$(date -Is) wg-hub-watchdog: $IFACE not present; skipping" >&2
  exit 0
fi

# `wg show <if> latest-handshakes` prints "<pubkey>\t<epoch>" per peer; 0 = never.
# Take the most recent across all peers.
LAST=$(wg show "$IFACE" latest-handshakes | awk '{print $2}' | sort -rn | head -1)
LAST="${LAST:-0}"
NOW=$(date +%s)
AGE=$(( NOW - LAST ))

if [ "$LAST" -eq 0 ] || [ "$AGE" -gt "$STALE_SEC" ]; then
  echo "$(date -Is) wg-hub-watchdog: handshake stale (age=${AGE}s last=${LAST}s epoch); bouncing wg-quick@${IFACE}" >&2
  systemctl restart "wg-quick@${IFACE}"
  exit 0
fi

# Healthy — stay quiet.
exit 0
