#!/usr/bin/env bash
set -euo pipefail
API="${SIGNAL_API_URL:-http://localhost:8080}"
NUM="${SIGNAL_SENDER:-+59891840205}"
FARMER="${SIGNAL_RECIPIENT:-+59892893012}"

echo "==> /v1/accounts"
ACCOUNTS=$(curl -fsS "$API/v1/accounts")
if ! jq -e --arg n "$NUM" '. | index($n)' <<<"$ACCOUNTS" >/dev/null; then
  echo "FAIL: $NUM not in /v1/accounts response: $ACCOUNTS"; exit 1
fi
echo "ok account registered"

echo "==> /v1/devices/$NUM (primary check)"
DEV_ID=$(curl -fsS "$API/v1/devices/$NUM" | jq -r '[.[] | select(.id==1)] | length')
if [[ "$DEV_ID" != "1" ]]; then echo "FAIL: no device with id=1 (expected primary)"; exit 1; fi
echo "ok device_id=1 (primary)"

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
