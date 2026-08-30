#!/usr/bin/env bash
# MUSHY-138: install the self-tune runner + timer. Idempotent.
#
#   sudo scripts/self-tune/install.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DST=/usr/local/bin/mushy-self-tune.sh
UNIT_DIR=/etc/systemd/system

[ "$(id -u)" -eq 0 ] || { echo "must run as root (sudo $0)" >&2; exit 1; }

install -m 0755 -o root -g root "$HERE/mushy-self-tune.sh" "$BIN_DST"
echo "installed $BIN_DST"

for unit in mushy-self-tune.service mushy-self-tune.timer; do
  install -m 0644 -o root -g root "$HERE/$unit" "$UNIT_DIR/$unit"
  echo "installed $UNIT_DIR/$unit"
done

systemctl daemon-reload
systemctl enable --now mushy-self-tune.timer
echo "enabled mushy-self-tune.timer"

# Verify: deployed must now be byte-identical to the repo copy.
if ! cmp -s "$BIN_DST" "$HERE/mushy-self-tune.sh"; then
  echo "VERIFY FAILED: $BIN_DST still differs from the repo copy" >&2
  exit 1
fi
echo "verified: deployed copy matches repo"
systemctl list-timers mushy-self-tune.timer --no-pager || true
