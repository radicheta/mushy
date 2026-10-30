#!/usr/bin/env bash
# One-time host setup for FC-2. Run ON the Pi with sudo, from the repo checkout:
#   sudo bash scripts/pi-deploy/fc2/bootstrap.sh
# Idempotent.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

install -m 644 -o root -g root "${HERE}/cyclonedds.xml" /etc/cyclonedds.xml

# Hardware watchdog: reboots the Pi if systemd itself hangs.
install -d -m 755 /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=15\n' > /etc/systemd/system.conf.d/fc2-watchdog.conf

install -d -o ubuntu -g ubuntu -m 0755 /var/lib/fc2-core

echo "FC-2 bootstrap done. Reboot (or 'systemctl daemon-reexec') to arm the watchdog."
