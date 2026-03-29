# FC-1 Pi WireGuard VPN Setup

> **Note:** VPN is not required for Phase 1 to succeed. LAN SSH access (ssh fc1) is sufficient.
> WireGuard connects when the server is reachable. This is a preparation step only — per D-07.

## Prerequisites

- SSH access to FC-1 Pi (see `docs/pi-setup/ssh-setup.md`)
- WireGuard installed on Pi:
  ```
  sudo apt install wireguard
  ```
- WireGuard server public key: `FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0=` (tun_wg0 "mossrock" on pfSense)
- WireGuard server endpoint: pfSense LAN `10.68.155.1:51820` (or public WAN IP for remote access)
- Pi's assigned IP on the `172.16.10.0/24` mesh: **`172.16.10.5`** (next available — .2/.3/.4 in use)

## Generate Pi Keys

On the Pi, generate a key pair:

```bash
wg genkey | sudo tee /etc/wireguard/private.key | wg pubkey | sudo tee /etc/wireguard/public.key
sudo chmod 600 /etc/wireguard/private.key
```

Print the public key (share this with the WireGuard server admin to add FC-1 as a peer):

```bash
sudo cat /etc/wireguard/public.key
```

## Fill the Config Template

The repo contains `wg0.conf.template` in the project root. The following variables must be
substituted to produce a valid `/etc/wireguard/wg0.conf`:

| Variable              | Source                                    | Example                     |
|-----------------------|-------------------------------------------|-----------------------------|
| `${WG_PRIVATE_KEY}`   | Contents of `/etc/wireguard/private.key`  | `aBcD1234...` (base64)      |
| `${WG_SERVER_PUBLIC_KEY}` | `FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0=` (tun_wg0 mossrock) | —              |
| `${WG_SERVER_ENDPOINT}` | `10.68.155.1` (LAN) or pfSense WAN IP for remote | `10.68.155.1`  |
| `${WG_IP}`            | `172.16.10.5` (assigned to FC-1)          | `172.16.10.5`               |

The resulting config will look like:

```ini
[Interface]
PrivateKey = <WG_PRIVATE_KEY value>
Address = <WG_IP>/24
ListenPort = 51820

[Peer]
PublicKey = <WG_SERVER_PUBLIC_KEY value>
AllowedIPs = 172.16.10.0/24
Endpoint = <WG_SERVER_ENDPOINT>:51820
PersistentKeepalive = 25
```

## Deploy

Use the provided deployment script from your workstation (copies template, fills vars, deploys):

```bash
# Set environment variables
export WG_PRIVATE_KEY=$(ssh fc1 "sudo cat /etc/wireguard/private.key")
export WG_SERVER_PUBLIC_KEY="FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0="
export WG_SERVER_ENDPOINT="10.68.155.1"  # or pfSense WAN IP for remote access
export WG_IP="172.16.10.5"

# Run the deployment script on the Pi
# (script must be pushed to Pi first, or run inline)
bash scripts/pi-deploy/wg-setup.sh
```

Or manually on the Pi:

```bash
# On the Pi — fill variables and write config
sudo bash -c "
  WG_PRIVATE_KEY=\$(cat /etc/wireguard/private.key)
  WG_SERVER_PUBLIC_KEY='FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0='
  WG_SERVER_ENDPOINT='10.68.155.1'
  WG_IP='172.16.10.5'
  envsubst < /path/to/wg0.conf.template > /etc/wireguard/wg0.conf
  chmod 600 /etc/wireguard/wg0.conf
"

# Enable and start
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0
```

## Verify

```bash
sudo wg show
```

Expected output: lists the `wg0` interface, shows configured peer with last handshake time.

```bash
ping 172.16.10.1
```

Expected: replies from the WireGuard server (if server is running and reachable).

## Troubleshooting

**No handshake / tunnel not establishing:**
- Confirm server endpoint is reachable: `ping <WG_SERVER_ENDPOINT>` or `nc -zvu <WG_SERVER_ENDPOINT> 51820`
- Check that the Pi's public key has been added as a peer on the WireGuard server
- Check server-side firewall allows UDP port 51820 inbound
- Check Pi-side firewall: `sudo ufw status`

**Service fails to start:**
- Check config syntax: `sudo wg-quick strip wg0`
- View logs: `sudo journalctl -u wg-quick@wg0 --no-pager -n 50`
- Ensure `WireGuard` kernel module is loaded: `lsmod | grep wireguard`

**NAT traversal issues:**
- `PersistentKeepalive = 25` is already set in template — this helps with most NAT scenarios
- If still failing, confirm server has correct `AllowedIPs` for the Pi's WireGuard IP

**Intermittent server access:**
- Per D-08, the WireGuard server may be intermittently inaccessible — this is expected
- VPN is not required for Phase 1 work; proceed over LAN SSH as primary access method
