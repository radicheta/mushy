# Farm Connectivity Plan

**Date:** 2026-04-04
**Status:** Pre-implementation — needed before Phase 5 soak test

## Topology

```
  FARM                          INTERNET              OFFICE
  ────                          ────────              ──────
  fc1 Pi ──► phone hotspot ──► carrier NAT ──► vpn.mossrock.space:51820
                                                      │
                                                  pfSense WG
                                                      │
                                                  elder-plops
                                                  (OpenMCT + rosbridge)
```

All ROS traffic flows over WireGuard. Nothing unencrypted over the internet.

## fc1 Internet Access

Phone hotspot at the farm. Pi connects to hotspot WiFi or USB tethering.

## WireGuard Tunnel (fc1 → pfSense)

fc1 sits behind carrier NAT — can't receive inbound connections. Standard NAT traversal:

1. **DNS:** Point `vpn.mossrock.space` at pfSense's WAN IP. If WAN IP is dynamic, set up DDNS on pfSense.
2. **Port forward:** UDP 51820 from upstream modem to pfSense LAN IP (skip if pfSense is directly on WAN).
3. **fc1 WireGuard config:**
   ```ini
   [Peer]
   Endpoint = vpn.mossrock.space:51820
   PersistentKeepalive = 25
   ```
4. **pfSense side:** fc1's peer has no fixed endpoint — pfSense learns it from the handshake (roaming peer).

Keepalive every 25 seconds holds the NAT mapping open.

**Fallback:** If carrier blocks UDP 51820, run WireGuard on 443/UDP on pfSense (looks like QUIC to the carrier).

## Farmer Dashboard Access

**Decision:** WireGuard app + browser (Option A).

The farmer's stack per device:
1. Install WireGuard app (iOS/Android/desktop)
2. Scan QR code generated from pfSense peer config
3. Browse to elder-plops WG IP:8080 for OpenMCT dashboard

Each new device = add peer on pfSense + generate QR. ~2 minutes per device. Works from anywhere with internet — not tied to farm network.

## Checklist Before Soak Test

- [ ] Point `vpn.mossrock.space` → pfSense WAN IP (DNS A record or DDNS)
- [ ] Port forward UDP 51820 to pfSense (if behind modem)
- [ ] Update fc1 `/etc/wireguard/wg0.conf` with `Endpoint = vpn.mossrock.space:51820`
- [ ] Test tunnel from phone hotspot: `wg show` on fc1, `ping` across tunnel
- [ ] Verify ROS topics visible on elder-plops: `ros2 topic echo /fc/humidity --once`
- [ ] Verify OpenMCT dashboard loads from elder-plops browser
- [ ] Create farmer WireGuard peer on pfSense, generate QR
- [ ] Test farmer device: WireGuard connect → browse to OpenMCT
