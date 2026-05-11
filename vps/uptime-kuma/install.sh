#!/usr/bin/env bash
# Install docker + uptime-kuma on the VPS.
# Run as: ssh mushy@178.105.84.13 'sudo bash -s' < install.sh
#
# Idempotent. Safe to re-run.
set -euo pipefail

INSTALL_DIR=/opt/uptime-kuma

# 1. Install docker engine + compose plugin if missing.
if ! command -v docker >/dev/null; then
  echo "==> installing docker engine"
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
docker --version
docker compose version

# 2. Drop the compose file in place.
mkdir -p "$INSTALL_DIR"
[ -f /tmp/uptime-kuma-compose.yml ] || { echo "ERROR: /tmp/uptime-kuma-compose.yml missing — caller should have scp'd it"; exit 1; }
cp /tmp/uptime-kuma-compose.yml "$INSTALL_DIR/docker-compose.yml"

# 3. Open UFW for port 3001 on wg-hub interface only.
if command -v ufw >/dev/null; then
  ufw allow in on wg-hub to any port 3001 proto tcp comment "Phase 34 uptime-kuma dashboard (wg-hub peers only)" || true
fi

# 4. Bring up the stack.
cd "$INSTALL_DIR"
docker compose pull
docker compose up -d

# 5. Verify.
sleep 4
echo "---"
echo "container state:"
docker compose ps
echo "listening:"
ss -tlnp 2>/dev/null | grep ':3001' | head -3
echo
echo "---installed---"
echo "Open http://10.66.0.1:3001/ from any wg-hub peer (fc1, elder-plops, your laptop if it's a peer)"
echo "First visit: set up admin user. Then add HTTP/ping monitors per 34-CONTEXT.md."
