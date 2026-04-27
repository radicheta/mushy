#!/usr/bin/env bash
set -euo pipefail
API="${SIGNAL_API_URL:-http://localhost:8080}"
NUM="${SIGNAL_SENDER:-+59891840205}"
FARMER="${SIGNAL_RECIPIENT:-+59892893012}"

echo "==> /v1/accounts"
DEV_ID=$(curl -fsS "$API/v1/accounts" | jq -r --arg n "$NUM" '.[] | select(.number==$n) | .device_id')
if [[ "$DEV_ID" != "1" ]]; then echo "FAIL: device_id=$DEV_ID (expected 1 — primary)"; exit 1; fi
echo "ok device_id=1"

echo "==> /v1/receive HTTP code"
CODE=$(curl -sS -o /tmp/wave0-recv.json -w "%{http_code}" "$API/v1/receive/$NUM?timeout=1")
if [[ "$CODE" != "200" ]]; then echo "FAIL: /v1/receive returned $CODE (expected 200; if 400 — MODE not flipped or still linked-secondary)"; exit 1; fi
echo "ok /v1/receive=200"

echo "==> /v2/send regression"
TS=$(curl -fsS -X POST "$API/v2/send" -H 'Content-Type: application/json' \
  -d "{\"message\":\"wave0-smoke\",\"number\":\"$NUM\",\"recipients\":[\"$FARMER\"]}" | jq -r '.timestamp')
if [[ -z "$TS" || "$TS" == "null" ]]; then echo "FAIL: /v2/send did not return timestamp"; exit 1; fi
echo "ok /v2/send timestamp=$TS"

echo "PASS"
