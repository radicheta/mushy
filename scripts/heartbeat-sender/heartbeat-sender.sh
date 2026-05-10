#!/usr/bin/env bash
# heartbeat-sender — Phase 33
# POST a heartbeat to the VPS receiver. Wraps `curl` with HMAC signing.
#
# Usage (from systemd timer or cron):
#   heartbeat-sender.sh <source-name>
#
# Reads HMAC secret from /etc/mushy-heartbeat/secret (mode 600, root:root).
# Receiver URL defaults to http://10.66.0.1:9000/heartbeat (wg-hub).
set -euo pipefail

SOURCE="${1:?usage: heartbeat-sender.sh <source-name>}"
RECEIVER_URL="${HEARTBEAT_RECEIVER_URL:-http://10.66.0.1:9000/heartbeat}"
SECRET_FILE="${HEARTBEAT_SECRET_FILE:-/etc/mushy-heartbeat/secret}"

[ -f "$SECRET_FILE" ] || { echo "ERROR: secret file not found at $SECRET_FILE" >&2; exit 1; }
SECRET=$(cat "$SECRET_FILE")
[ -n "$SECRET" ] || { echo "ERROR: empty secret" >&2; exit 1; }

NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOAD_AVG=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo "")
UPTIME_SEC=$(cut -d' ' -f1 /proc/uptime 2>/dev/null || echo "")

# Compose JSON body
BODY=$(printf '{"source":"%s","ts":"%s","extras":{"load1":%s,"uptime_sec":%s}}' \
  "$SOURCE" "$NOW_ISO" "${LOAD_AVG:-null}" "${UPTIME_SEC:-null}")

# HMAC-SHA256 of the body
HMAC=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $NF}')

# POST (timeout 5s; quiet on success; log on failure)
RESP=$(curl -sS --max-time 5 \
  -H 'Content-Type: application/json' \
  -H "X-Heartbeat-HMAC: $HMAC" \
  -d "$BODY" \
  "$RECEIVER_URL" 2>&1) || {
  # Don't crash systemd timer — log and exit non-zero
  echo "$(date -Is) heartbeat-sender failed for $SOURCE: $RESP" >&2
  exit 1
}

# Optional: log success at debug level (uncomment if you want noisy logs)
# echo "$(date -Is) sent: $RESP"
