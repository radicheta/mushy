#!/usr/bin/env bash
exec env PI_HOST=172.16.10.6 BRANCH=fc2/prod UNIT_DIR=scripts/pi-deploy/fc2 UNITS=fc2-core.service PACKAGES=fc2_core SERVICE=fc2-core "$(dirname "$0")/../deploy.sh"
