#!/usr/bin/env bash
# Phase 21 smoke — runs against the live runtime compose stack.
# CLAUDE.md rule: verify against /docker-compose.yml at repo root, not src/docker-compose.yml.
set -u
if [ ! -f docker-compose.yml ]; then
  echo "ERROR: run from repo root (docker-compose.yml not found here)" >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not on PATH" >&2
  exit 2
fi

BRIDGE_URL="${BRIDGE_URL:-http://localhost:8081}"
NOW_MS=$(date +%s%3N)
FROM_MS=$((NOW_MS - 86400000))

echo "== /health =="
HEALTH=$(curl -fsS "$BRIDGE_URL/health") || { echo "ERROR: /health unreachable" >&2; exit 1; }
echo "$HEALTH" | python3 -m json.tool
echo "$HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("snapshots_last_24h:", d.get("snapshots_last_24h", "[not exposed yet]")); print("oldest_snapshot_at:", d.get("oldest_snapshot_at", "[not exposed yet]"))'

echo "== /camera/history (last 24h) =="
HIST=$(curl -fsS "$BRIDGE_URL/camera/history?from=${FROM_MS}&to=${NOW_MS}") || { echo "NOTE: /camera/history not yet available (pre-Plan-03)"; HIST=""; }
if [ -n "$HIST" ]; then
  echo "$HIST" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("count:", d.get("count")); print("has_more:", d.get("has_more"))'
fi

echo "== snapshots table =="
docker compose exec -T timescale psql -U postgres -c "\d+ snapshots" 2>&1 | head -20 || echo "snapshots table not yet created"
docker compose exec -T timescale psql -U postgres -t -c "SELECT count(*) FROM snapshots;" 2>/dev/null || echo "(row count unavailable)"

echo "== smoke OK =="
