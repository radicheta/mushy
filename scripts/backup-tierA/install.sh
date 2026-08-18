#!/usr/bin/env bash
# MUSHY-45: install the Tier A backup script + systemd units from the repo.
#
# This exists because the deployed /usr/local/bin/mushy-tierA-backup.sh silently
# drifted from the repo copy: the signal-cli staging block was added to the repo
# on 999.52 and never re-installed, so for weeks the nightly encrypted bundle did
# NOT contain the Signal identity -- the one secret whose loss takes all farmer
# alerting down until a multi-hour re-registration is done by hand.
#
# Idempotent. Run after ANY edit to mushy-tierA-backup.sh or the unit files.
#
#   sudo scripts/backup-tierA/install.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DST=/usr/local/bin/mushy-tierA-backup.sh
UNIT_DIR=/etc/systemd/system

[ "$(id -u)" -eq 0 ] || { echo "must run as root (sudo $0)" >&2; exit 1; }

install -m 0755 -o root -g root "$HERE/mushy-tierA-backup.sh" "$BIN_DST"
echo "installed $BIN_DST"

for unit in mushy-tierA-backup.service mushy-tierA-backup.timer; do
  install -m 0644 -o root -g root "$HERE/$unit" "$UNIT_DIR/$unit"
  echo "installed $UNIT_DIR/$unit"
done

systemctl daemon-reload
systemctl enable --now mushy-tierA-backup.timer
echo "enabled mushy-tierA-backup.timer"

# Verify: deployed must now be byte-identical to the repo copy, and must
# contain the staging block whose absence caused this ticket.
if ! cmp -s "$BIN_DST" "$HERE/mushy-tierA-backup.sh"; then
  echo "VERIFY FAILED: $BIN_DST still differs from the repo copy" >&2
  exit 1
fi
if ! grep -q 'mushy_signal-cli-data' "$BIN_DST"; then
  echo "VERIFY FAILED: $BIN_DST has no signal-cli staging block" >&2
  exit 1
fi
echo "verified: deployed copy matches repo and stages the Signal identity"
systemctl list-timers mushy-tierA-backup.timer --no-pager || true
