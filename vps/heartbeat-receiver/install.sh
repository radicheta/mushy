#!/usr/bin/env bash
# Install mushy-heartbeat-receiver on the VPS.
# Run as: ssh mushy@178.105.84.13 'sudo bash -s' < install.sh
set -euo pipefail

INSTALL_DIR=/opt/mushy-heartbeat-receiver
DATA_DIR=/var/lib/mushy-heartbeat
SECRET_DIR=/etc/mushy-heartbeat

# 1. Ensure node is available
if ! command -v node >/dev/null; then
  echo "installing nodejs..."
  apt-get update -qq
  apt-get install -y -qq nodejs
fi
NODE_VER=$(node -v)
echo "node: $NODE_VER (need >=18 for built-in fetch)"

# 2. Create users + dirs
id mushy >/dev/null 2>&1 || { echo "ERROR: mushy user must already exist (Phase 32 prerequisite)"; exit 1; }
mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$SECRET_DIR"
chown mushy:mushy "$DATA_DIR"
# Secret dir: root-owned, group mushy, 750 so the service (User=mushy) can
# traverse and read the secret. 700 here blocked the service on first install.
chown root:mushy "$SECRET_DIR"
chmod 750 "$SECRET_DIR"

# 3. Generate HMAC secret if absent
if [ ! -f "$SECRET_DIR/secret" ]; then
  head -c 48 /dev/urandom | base64 > "$SECRET_DIR/secret"
  echo "generated new HMAC secret at $SECRET_DIR/secret"
else
  echo "HMAC secret already present at $SECRET_DIR/secret (preserving)"
fi
chown root:mushy "$SECRET_DIR/secret"
chmod 640 "$SECRET_DIR/secret"

# 4. Copy code (caller is expected to have placed index.js + service file in /tmp)
[ -f /tmp/heartbeat-index.js ] || { echo "ERROR: /tmp/heartbeat-index.js not found"; exit 1; }
[ -f /tmp/heartbeat.service ] || { echo "ERROR: /tmp/heartbeat.service not found"; exit 1; }
cp /tmp/heartbeat-index.js "$INSTALL_DIR/index.js"
chmod 755 "$INSTALL_DIR/index.js"
cp /tmp/heartbeat.service /etc/systemd/system/mushy-heartbeat-receiver.service

# 5. Enable and start
systemctl daemon-reload
systemctl enable --now mushy-heartbeat-receiver

# 6. Verify
sleep 2
echo "---"
echo "service state:"
systemctl is-active mushy-heartbeat-receiver
echo "listening:"
ss -tlnp 2>/dev/null | grep ':9000' | head -3
echo "health probe:"
curl -sS http://127.0.0.1:9000/health | head -3
echo
echo "---installed---"
echo "Secret (share with senders): $(cat $SECRET_DIR/secret)"
