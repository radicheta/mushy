# Phase 32 — VPS Hub Runbook

How to operate and extend the WireGuard hub that shipped 2026-05-10.

## Inventory pointer

- **VPS:** Hetzner CX22 Nuremberg, 178.105.84.13, hostname `ubuntu-4gb-nbg1-1`, OS Ubuntu 24.04.3 LTS
- **Admin user:** `mushy` (NOPASSWD sudo)
- **WG subnet:** `10.66.0.0/24`, hub IP `10.66.0.1`, port `51820/udp`
- **Hub pubkey:** `uk3YC2fiXg/Qgo0MUdv8UkJPo/9XnC7RZgN1JOnXtnc=`
- **Secrets/keys not in this file** — see gitignored `32-INVENTORY.md`

## Peer assignment policy

| IP range | Use |
|---|---|
| 10.66.0.1 | Hub |
| 10.66.0.10..19 | Infrastructure peers (laptops, servers) |
| 10.66.0.20..29 | Farmers / beta-testers |
| 10.66.0.30..49 | Future expansion (additional farms, sensors, etc.) |

When assigning a new IP, pick the lowest unused in the appropriate range and record in `32-INVENTORY.md`.

## Add a new mobile/laptop peer (most common case)

Run on the VPS as `mushy` with sudo:

```bash
NAME="alice"           # short identifier (alphanumeric)
IP="10.66.0.24"        # pick next unused in farmer range
OS="Android"           # for the audit comment line

sudo bash <<EOF
set -e
cd /etc/wireguard
umask 077
wg genkey | tee ${NAME}.key | wg pubkey > ${NAME}.pub
HUB_PUB=\$(cat hub.pub)
PRIV=\$(cat ${NAME}.key)
PUB=\$(cat ${NAME}.pub)

# Generate peer's config
cat > /tmp/${NAME}-mushy-vps.conf <<PEER
[Interface]
PrivateKey = \$PRIV
Address = ${IP}/32

[Peer]
PublicKey = \$HUB_PUB
Endpoint = 178.105.84.13:51820
AllowedIPs = 10.66.0.0/24
PersistentKeepalive = 25
PEER

# QR for phone scanning
qrencode -t png -s 8 -l M -o /tmp/${NAME}-mushy-vps.png < /tmp/${NAME}-mushy-vps.conf

# Add peer to hub config (live-reload)
cat >> /etc/wireguard/wg-hub.conf <<HUB

[Peer]
# ${NAME} (${OS}) — added \$(date -I)
PublicKey = \$PUB
AllowedIPs = ${IP}/32
HUB
wg syncconf wg-hub <(wg-quick strip wg-hub)
chmod 644 /tmp/${NAME}-mushy-vps.{conf,png}
EOF

# Pull artifacts back to your laptop for Signal delivery:
scp mushy@178.105.84.13:/tmp/${NAME}-mushy-vps.{conf,png} ~/Downloads/
```

Then Signal the PNG to the new peer with these instructions:

> 1. Install **WireGuard** from Play Store / App Store
> 2. Open app → tap `+` → "Create from QR code" → scan the PNG
> 3. Toggle the tunnel ON
> 4. Open browser → `http://10.66.0.12:8080/` → Mission Control

Update `32-INVENTORY.md` Peers table with the new entry.

## Revoke a peer

```bash
sudo bash <<'EOF'
NAME="alice"   # set to peer's name
# Delete the [Peer] block from /etc/wireguard/wg-hub.conf
# (manual edit recommended — find the "# ${NAME}" comment line and delete the block)
nano /etc/wireguard/wg-hub.conf
# After saving, live-reload:
wg syncconf wg-hub <(wg-quick strip wg-hub)
# Optionally remove keys
rm /etc/wireguard/${NAME}.{key,pub}
EOF
```

## Add an infrastructure peer (server / laptop with its own SSH access)

Same as mobile peer but generate the keypair on the peer machine, send pubkey to VPS, and write the wg-hub.conf locally on the peer. See `32-01-PLAN.md` T5 (elder-plops) for the pattern, and `/tmp/wg-hub-elder-plops-setup.sh` as a template script.

Key differences from mobile:
- Keypair stays on the peer (best practice)
- AllowedIPs on peer side = `10.66.0.0/24` (route the whole hub subnet through the tunnel; rest of internet stays untouched)
- If the peer already has another WireGuard tunnel (like fc1's wg0), **do not set `ListenPort`** on the new wg-hub.conf — let it pick an ephemeral port to avoid conflict
- Use systemd unit: `systemctl enable --now wg-quick@wg-hub`

## Common operations

```bash
# Show all peers + handshake state
ssh mushy@178.105.84.13 'sudo wg show wg-hub'

# Live-reload after editing /etc/wireguard/wg-hub.conf
ssh mushy@178.105.84.13 'sudo wg syncconf wg-hub <(sudo wg-quick strip wg-hub)'

# Restart cleanly (drops all sessions briefly)
ssh mushy@178.105.84.13 'sudo systemctl restart wg-quick@wg-hub'

# Tail hub logs
ssh mushy@178.105.84.13 'sudo journalctl -u wg-quick@wg-hub --since "10 min ago"'

# Tail UFW logs (rejected/forwarded traffic)
ssh mushy@178.105.84.13 'sudo journalctl -k --since "10 min ago" | grep UFW'

# fail2ban status
ssh mushy@178.105.84.13 'sudo fail2ban-client status sshd'
```

## Hardening tripwires

- **First-wins sshd_config**: Ubuntu 24 cloud-init drops `50-cloud-init.conf` which sets `PasswordAuthentication yes`. Our override is named `00-mushy-hardening.conf` so it loads first. Don't add a new dropin with a higher prefix without remembering this.
- **`sshd -t` outside systemd**: errors with "Missing privilege separation directory: /run/sshd" because the runtime dir doesn't exist when sshd isn't started by systemd. Workaround: `mkdir -p /run/sshd` before the test, or skip the test and let `systemctl reload ssh` validate.
- **UFW + WireGuard**: hub-and-spoke routing needs `ufw route allow in on wg-hub out on wg-hub` (allows forwarding within the WG interface). Without this, peer-to-peer through hub silently drops packets.

## Tripwires for connecting peers

- **CycloneDDS interface binding**: fc1's `/etc/cyclonedds.xml` binds to `wg0` only. When fc1 moves to farm 4G, wg0 dies and DDS must switch to `wg-hub`. Update cyclonedds.xml binding BEFORE the move OR list both interfaces.
- **Port 51820 conflict**: fc1's existing wg0 listens on `51820/udp`. When adding wg-hub on the same host, omit `ListenPort` (use ephemeral) — otherwise the second interface fails to start.
- **ssh-agent overflow**: peers with many keys in ssh-agent hit MaxAuthTries before reaching the right one. Fix on the peer: `~/.ssh/config` host stanza with `IdentitiesOnly yes` and explicit `IdentityFile`.
- **MC CORS**: `CORS_ORIGIN` env on the bridge must include every origin that loads MC. When farmer's browser opens `http://10.66.0.12:8080/`, bridge expects that origin in the allowlist. Edit `.env` and rebuild bridge.

## Peer-handshake debugging

If a peer's `wg show` doesn't show a handshake:

1. **Hub-side firewall**: `sudo ufw status` should show `51820/udp ALLOW IN`
2. **Hub-side WG running**: `sudo wg show wg-hub` should list the interface up
3. **Peer-side endpoint right**: peer's config must have `Endpoint = 178.105.84.13:51820` exactly
4. **Peer-side AllowedIPs**: include `10.66.0.0/24` to route through hub
5. **NAT/firewall on peer side blocking outbound 51820**: `PersistentKeepalive = 25` helps punch through, but some corporate networks block all UDP. Test from cellular instead.

## Architecture notes

- **Hub-and-spoke**, not full mesh. Each peer's AllowedIPs is `10.66.0.0/24` on its side; on the hub side, each peer's AllowedIPs is its own `/32`. This means all peer-to-peer traffic routes through the hub (slightly extra latency but simpler routing + better security: revoking a peer at the hub kills all its connectivity instantly).
- **Coexistence with existing wg0** (fc1↔elder-plops LAN tunnel): wg-hub uses interface name `wg-hub`, different subnet (`10.66.0.0/24` vs `172.16.10.0/24`), and on fc1 uses ephemeral port. Both tunnels run simultaneously. Memory `feedback_stopping_tailscaled_kills_pid` reminds: do not disturb the existing DDS transport.
- **240ms hop tax**: any traffic through the hub adds ~240ms RTT (Uruguay→Nuremberg). Fine for HTTPS / DDS at 1Hz / SSH / monitoring. Not fine for sub-100ms control loops.
- **NOT a chamber-control dependency**: VPS dying does not affect mushroom growing. fc1 keeps growing via wg0; only outside-in observability + beta-tester access goes dark.
