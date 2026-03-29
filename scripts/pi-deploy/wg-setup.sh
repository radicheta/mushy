#!/usr/bin/env bash
# wg-setup.sh — Deploy WireGuard config to FC-1 Pi from template
#
# Usage:
#   WG_PRIVATE_KEY=<key> \
#   WG_SERVER_PUBLIC_KEY=<key> \
#   WG_SERVER_ENDPOINT=<ip-or-host> \
#   WG_IP=<172.16.10.x> \
#   bash scripts/pi-deploy/wg-setup.sh
#
# Requires: envsubst (gettext-base package), sudo access on the Pi
# Template: wg0.conf.template in repo root

set -euo pipefail

# Determine repo root (script is at scripts/pi-deploy/wg-setup.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/wg0.conf.template"
OUTPUT="/etc/wireguard/wg0.conf"

# Validate required environment variables
MISSING=()
[[ -z "${WG_PRIVATE_KEY:-}" ]] && MISSING+=("WG_PRIVATE_KEY")
[[ -z "${WG_SERVER_PUBLIC_KEY:-}" ]] && MISSING+=("WG_SERVER_PUBLIC_KEY")
[[ -z "${WG_SERVER_ENDPOINT:-}" ]] && MISSING+=("WG_SERVER_ENDPOINT")
[[ -z "${WG_IP:-}" ]] && MISSING+=("WG_IP")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "ERROR: The following required environment variables are not set:" >&2
  for var in "${MISSING[@]}"; do
    echo "  - ${var}" >&2
  done
  echo "" >&2
  echo "Usage:" >&2
  echo "  WG_PRIVATE_KEY=<key> \\" >&2
  echo "  WG_SERVER_PUBLIC_KEY=<key> \\" >&2
  echo "  WG_SERVER_ENDPOINT=<ip-or-host> \\" >&2
  echo "  WG_IP=<172.16.10.x> \\" >&2
  echo "  bash ${BASH_SOURCE[0]}" >&2
  exit 1
fi

# Check template exists
if [[ ! -f "${TEMPLATE}" ]]; then
  echo "ERROR: Template not found at ${TEMPLATE}" >&2
  echo "Run this script from the repo root or ensure wg0.conf.template is present." >&2
  exit 1
fi

# Check envsubst is available
if ! command -v envsubst &>/dev/null; then
  echo "ERROR: envsubst not found. Install gettext-base:" >&2
  echo "  sudo apt install gettext-base" >&2
  exit 1
fi

echo "==> Filling WireGuard config template..."
FILLED=$(envsubst < "${TEMPLATE}")

echo "==> Writing config to ${OUTPUT} (requires sudo)..."
echo "${FILLED}" | sudo tee "${OUTPUT}" > /dev/null
sudo chmod 600 "${OUTPUT}"

echo "==> Enabling wg-quick@wg0 service..."
sudo systemctl enable wg-quick@wg0

echo "==> Starting wg-quick@wg0 service..."
sudo systemctl start wg-quick@wg0

echo ""
echo "==> WireGuard status:"
sudo wg show

echo ""
echo "Done. If 'wg show' shows a peer with a recent handshake, the tunnel is up."
echo "If no handshake yet, the server may be temporarily unreachable — this is normal per D-08."
echo "Phase 1 proceeds over LAN SSH regardless of VPN status."
