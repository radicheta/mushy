#!/usr/bin/env bash
# wg-setup.sh — Idempotent WireGuard setup script for FC-1 Pi
#
# Run ON the Pi (not from the workstation):
#   scp scripts/pi-deploy/wg-setup.sh fc1:/tmp/wg-setup.sh
#   ssh fc1 "sudo bash /tmp/wg-setup.sh"
#
# What this does:
#   1. Installs wireguard-tools if not already installed
#   2. Generates a WireGuard keypair if not already present
#   3. Writes /etc/wireguard/wg0.conf with hardcoded LAN endpoint (10.68.155.1:51820)
#   4. Enables and starts the wg-quick@wg0 systemd service
#   5. Prints the public key for pfSense peer registration
#
# VPN mesh: 172.16.10.0/24
#   pfSense server (igb5): 172.16.10.1
#   FC-1 Pi (this device):  172.16.10.5
#   elder-plops workstation: 172.16.10.3
#
# NOTE: Endpoint is 10.68.155.1 (pfSense LAN IP).
#   Remote access via mossrock.space DNS is deferred to a later phase.
#   This setup works when Pi and pfSense are on the same LAN (10.68.155.0/24).

set -euo pipefail

WG_SERVER_PUBLIC_KEY="FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0="
WG_SERVER_ENDPOINT="10.68.155.1"
WG_IP="172.16.10.5"
WG_CONF="/etc/wireguard/wg0.conf"
WG_PRIVKEY="/etc/wireguard/private.key"
WG_PUBKEY="/etc/wireguard/public.key"

# Step 1: Install wireguard-tools if not present
if ! dpkg -l wireguard-tools 2>/dev/null | grep -q '^ii'; then
    echo "==> Installing wireguard-tools..."
    apt-get update -q
    apt-get install -y wireguard
else
    echo "==> wireguard-tools already installed — skipping"
fi

# Step 2: Generate keypair if not already present
if [ ! -f "${WG_PRIVKEY}" ]; then
    echo "==> Generating WireGuard keypair..."
    mkdir -p /etc/wireguard
    wg genkey | tee "${WG_PRIVKEY}" | wg pubkey | tee "${WG_PUBKEY}"
    chmod 600 "${WG_PRIVKEY}"
    echo "==> Keypair generated"
else
    echo "==> WireGuard keypair already present — skipping key generation"
    # Ensure public key exists even if it was somehow lost
    if [ ! -f "${WG_PUBKEY}" ]; then
        echo "==> Public key missing — regenerating from private key..."
        wg pubkey < "${WG_PRIVKEY}" | tee "${WG_PUBKEY}"
    fi
fi

# Step 3: Write wg0.conf (always overwrite to ensure correct values)
echo "==> Writing ${WG_CONF}..."
WG_PRIVATE_KEY=$(cat "${WG_PRIVKEY}")
cat > "${WG_CONF}" <<EOF
[Interface]
PrivateKey = ${WG_PRIVATE_KEY}
Address = ${WG_IP}/24
ListenPort = 51820

[Peer]
PublicKey = ${WG_SERVER_PUBLIC_KEY}
AllowedIPs = 172.16.10.0/24
Endpoint = ${WG_SERVER_ENDPOINT}:51820
PersistentKeepalive = 25
EOF
chmod 600 "${WG_CONF}"
echo "==> wg0.conf written with correct LAN endpoint"

# Step 4: Enable and start wg-quick@wg0
echo "==> Enabling and starting wg-quick@wg0..."
systemctl enable --now wg-quick@wg0
echo "==> Service status: $(systemctl is-active wg-quick@wg0)"

# Step 5: Print public key for pfSense peer registration
echo ""
echo "=== Pi WireGuard public key (add to pfSense as FC-1 peer) ==="
cat "${WG_PUBKEY}"
echo "==="
echo ""
echo "pfSense peer registration (VPN > WireGuard > Peers > Add):"
echo "  Tunnel:           tun_wg0 (mossrock)"
echo "  Description:      FC-1 Pi"
echo "  Public Key:       $(cat ${WG_PUBKEY})"
echo "  Allowed IPs:      ${WG_IP}/32"
echo "  Dynamic Endpoint: checked"
echo ""
echo "NOTE: Tunnel handshake will not succeed until pfSense peer is added (Plan 02)."
echo "Done."
