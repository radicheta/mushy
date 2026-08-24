#!/usr/bin/env bash
# test-with-db.sh -- run the farm-agent suite with the DB-backed lane actually enabled.
#
# MUSHY-47: without a test DB the suite skips ~61 DB-backed tests and still
# reports green, so the skip count lies about coverage. This starts a throwaway
# postgres on :5434, runs the suite with REQUIRE_TEST_DB=1 (which turns "no DB"
# from a silent skip into a failure), and tears the container down again.
#
# Usage:   scripts/test-with-db.sh [extra pytest args...]
# Example: scripts/test-with-db.sh -k confirm_repo -v
set -euo pipefail

cd "$(dirname "$0")/.."

CONTAINER=fa-testdb
PORT=5434
DB=test_farm_agent

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

cleanup
docker run -d --name "$CONTAINER" -p "127.0.0.1:${PORT}:5432" \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB="$DB" postgres:14 >/dev/null

# NOTE: pg_isready goes true before initdb has created POSTGRES_DB, so polling it
# yields 'database "test_farm_agent" does not exist'. Poll for the database itself.
for _ in $(seq 1 60); do
  if docker exec "$CONTAINER" psql -U postgres -d "$DB" -tAc 'select 1' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$CONTAINER" psql -U postgres -d "$DB" -tAc 'select 1' >/dev/null

REQUIRE_TEST_DB=1 .venv/bin/python -m pytest "$@"
