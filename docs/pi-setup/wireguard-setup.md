# FC-1 Pi WireGuard VPN Setup

## Current State

| Setting | Value |
|---------|-------|
| Pi VPN IP | `172.16.10.5` |
| Server endpoint | `10.68.155.1:51820` (pfSense LAN — remote access deferred) |
| pfSense server public key | `FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0=` |
| VPN subnet | `172.16.10.0/24` (split-tunnel — only mesh traffic through VPN) |
| Service | `wg-quick@wg0` (systemd, enabled, auto-starts on boot) |

> **Note on remote access:** The endpoint is `10.68.155.1` (pfSense LAN IP). This works when the Pi
> and pfSense are on the same LAN. Remote access via a public DNS endpoint is out of scope for the
> current phase — it requires an ISP router port forward and is deferred to a later phase.

## Prerequisites

- SSH access to FC-1 Pi (see `docs/pi-setup/ssh-setup.md`)
- WireGuard kernel module present on Pi (confirmed: Ubuntu 24.04 / kernel 6.8.0-1047-raspi)
- Sudo access on Pi (`ubuntu` user, passwordless sudo)

## Deploy (Primary Method)

Use the automated deploy script — it installs wireguard-tools, generates a keypair if needed,
writes the config, and starts the service. Run it on the Pi via SSH:

```bash
# From your workstation
scp scripts/pi-deploy/wg-setup.sh fc1:/tmp/wg-setup.sh
ssh fc1 "sudo bash /tmp/wg-setup.sh"
```

The script is idempotent — safe to re-run. It will skip key generation if a keypair already exists.

At the end, the script prints the Pi's public key for pfSense peer registration:

```
=== Pi WireGuard public key (add to pfSense as FC-1 peer) ===
<base64 public key>
===
```

## pfSense Peer Registration

After running the deploy script, add the Pi as a peer in pfSense WebGUI:

```
VPN > WireGuard > Peers > + Add Peer
  Tunnel:           tun_wg0 (mossrock)
  Description:      FC-1 Pi
  Public Key:       <paste output of: ssh fc1 "sudo cat /etc/wireguard/public.key">
  Allowed IPs:      172.16.10.5/32
  Dynamic Endpoint: checked
> Save > Apply Changes
```

> The tunnel handshake will NOT succeed until the peer is added in pfSense.

## Verify

Check WireGuard status on the Pi:

```bash
ssh fc1 "sudo wg show wg0"
```

Expected output shows the interface with the pfSense peer configured. After pfSense peer registration:

```bash
# Ping the pfSense WireGuard gateway
ssh fc1 "ping -c 3 172.16.10.1"

# Ping elder-plops workstation on VPN
ssh fc1 "ping -c 3 172.16.10.3"
```

Check service is running:

```bash
ssh fc1 "systemctl is-active wg-quick@wg0"
# Expected: active
```

## Manual Key Operations

View the Pi's public key (for pfSense peer entry):

```bash
ssh fc1 "sudo cat /etc/wireguard/public.key"
```

## Troubleshooting

**No handshake / tunnel not establishing:**
- Confirm Pi public key is registered in pfSense: VPN > WireGuard > Peers
- Confirm server endpoint is reachable: `ssh fc1 "ping -c 2 10.68.155.1"`
- Check server-side firewall allows UDP port 51820 inbound
- Check Pi-side firewall: `ssh fc1 "sudo ufw status"`

**Service fails to start:**
- Check config syntax: `ssh fc1 "sudo wg-quick strip wg0"`
- View logs: `ssh fc1 "sudo journalctl -u wg-quick@wg0 --no-pager -n 50"`
- Ensure WireGuard kernel module is loaded: `ssh fc1 "lsmod | grep wireguard"`

**NAT traversal issues:**
- `PersistentKeepalive = 25` is set in the config — handles most NAT scenarios
- If still failing, confirm pfSense has `AllowedIPs = 172.16.10.5/32` for the Pi peer

**Service starts but no handshake after 30+ seconds:**
- Likely cause: Pi public key not yet added to pfSense peer list
- See pfSense Peer Registration section above
