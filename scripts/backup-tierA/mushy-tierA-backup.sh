#!/usr/bin/env bash
# Mushy Tier A backup — small, irreplaceable bits, age-encrypted, pushed to VPS.
#
# What's in scope: secrets and operator-set knobs whose loss would force
# painful reconstruction (env vars, tuning knobs, HMAC/notification
# secrets). NOT in scope (Tier B/C): Timescale data, snapshots, captured
# media — those are bulky and replaceable.
#
# Restore:  age -d -i ~/.ssh/id_ed25519 <YYYYMMDD-HHMM>.tar.age | tar -xv
#
# Run via systemd timer (mushy-tierA-backup.timer). Failures POST to the
# bridge /heartbeat-alert so we hear about them through the same Phase 33
# Tier 1 / 999.43.1 Tier 2 chain that handles outages.
set -uo pipefail

# Config (env-overridable for testing)
VPS_HOST="${VPS_HOST:-mushy@178.105.84.13}"
VPS_REPO="${VPS_REPO:-/var/backups/mushy-tierA}"
VPS_FARMOS_REPO="${VPS_FARMOS_REPO:-/var/backups/farmos-db}"
FARMOS_BACKUP_DIR="${FARMOS_BACKUP_DIR:-/mnt/slime-kingdom/backups/farmos}"
RECIPIENT_PUB="${RECIPIENT_PUB:-/etc/mushy/tierA-recipients.txt}"
BRIDGE_HEARTBEAT_URL="${BRIDGE_HEARTBEAT_URL:-http://localhost:8081/heartbeat-alert}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
REPO_SCRIPT="${REPO_SCRIPT:-/mnt/slime-kingdom/opt/mushy/scripts/backup-tierA/mushy-tierA-backup.sh}"

STAMP=$(date -u +%Y%m%d-%H%M)
WORK=$(mktemp -d -t mushy-tierA-XXXXXX)
trap 'rm -rf "$WORK"' EXIT

log() { echo "$(date -Is) [tierA] $*"; }

fail() {
  local msg="$*"
  log "FAIL: $msg"
  curl -sS --max-time 10 -X POST "$BRIDGE_HEARTBEAT_URL" \
    -H 'Content-Type: application/json' \
    -d "$(printf '{"source":"backup-tierA","message":"⚠️ Tier A backup FAILED: %s"}' "$msg")" \
    > /dev/null 2>&1 || true
  exit 1
}

# MUSHY-45: warn if the deployed copy has drifted from the repo copy.
# This script ran for weeks without the signal-cli staging block below because
# the repo version was edited and never re-installed, and nothing noticed. A
# warning is deliberate rather than a hard fail: a drifted backup that still
# runs beats no backup at all. Install with scripts/backup-tierA/install.sh.
if [ -r "$REPO_SCRIPT" ] && ! cmp -s "$0" "$REPO_SCRIPT"; then
  log "WARNING: deployed $0 differs from repo $REPO_SCRIPT -- re-run install.sh"
  curl -sS --max-time 10 -X POST "$BRIDGE_HEARTBEAT_URL" \
    -H 'Content-Type: application/json' \
    -d '{"source":"backup-tierA","message":"\u26a0\ufe0f Tier A backup script has drifted from the repo copy -- re-run install.sh"}' \
    > /dev/null 2>&1 || true
fi

# 1. Stage source files into WORK/payload/
mkdir -p "$WORK/payload/elder-plops" "$WORK/payload/fc1" "$WORK/payload/vps"

# elder-plops .env files
for src in /mnt/slime-kingdom/opt/mushy/.env /mnt/slime-kingdom/shared/farmos/.env; do
  if [ -r "$src" ]; then
    install -m 0600 "$src" "$WORK/payload/elder-plops/$(basename "$(dirname "$src")")-$(basename "$src")" \
      || fail "stage $src"
    log "  staged $src"
  else
    log "  skip (missing/unreadable): $src"
  fi
done

# 999.52: signal-cli docker volume — losing this forces full re-registration
# + re-link of all farmer Signal trust (multi-hour reconstruction). Bundled
# via a transient alpine container so we don't need sudo to read the volume's
# _data directory.
#
# MUSHY-45: ./attachments is EXCLUDED. It is ~96% of the volume (227 MB vs
# 9 MB without it) and is farmer media, which is replaceable and explicitly
# Tier B/C per this script's own header — Tier A is "small, irreplaceable
# bits". The identity (data/accounts.json + data/<id>.d/account.db) is what
# makes this backup exist, and it is tiny. Do not re-add attachments here
# without also rethinking the nightly upload cost to the VPS.
if docker volume inspect mushy_signal-cli-data >/dev/null 2>&1; then
  docker run --rm \
    -v mushy_signal-cli-data:/data:ro \
    -v "$WORK/payload/elder-plops":/out \
    alpine:3 sh -c 'tar -czf /out/signal-cli-data.tar.gz -C /data --exclude=./attachments .' \
    || fail "tar mushy_signal-cli-data"
  log "  staged docker volume mushy_signal-cli-data ($(stat -c%s "$WORK/payload/elder-plops/signal-cli-data.tar.gz") bytes)"
  # MUSHY-45: the identity is the single point of failure for ALL farmer
  # alerting -- losing it means full re-registration and re-linking every
  # farmer's trust. If the volume exists, a staged tarball is not optional;
  # a silent skip here is exactly how it went missing for weeks.
  SIGNAL_TAR="$WORK/payload/elder-plops/signal-cli-data.tar.gz"
  [ -s "$SIGNAL_TAR" ] || fail "signal-cli identity not staged (tarball missing or empty)"
  if [ "$(stat -c%s "$SIGNAL_TAR")" -lt 1024 ]; then
    fail "signal-cli identity tarball implausibly small ($(stat -c%s "$SIGNAL_TAR") bytes)"
  fi
else
  log "  skip: mushy_signal-cli-data volume not present"
fi

# fc1 — runtime_overrides.yaml + heartbeat unit drift (not in pi-deploy yet)
ssh -o BatchMode=yes -o ConnectTimeout=10 fc1 'cat /var/lib/fc-core/runtime_overrides.yaml' \
  > "$WORK/payload/fc1/runtime_overrides.yaml" 2>/dev/null || fail "pull fc1 runtime_overrides.yaml"
log "  staged fc1:/var/lib/fc-core/runtime_overrides.yaml ($(stat -c%s "$WORK/payload/fc1/runtime_overrides.yaml") bytes)"

ssh -o BatchMode=yes -o ConnectTimeout=10 fc1 'sudo -n cat /etc/systemd/system/mushy-heartbeat.service /etc/systemd/system/mushy-heartbeat.timer 2>/dev/null' \
  > "$WORK/payload/fc1/heartbeat-systemd-units.txt" 2>/dev/null || true

# VPS — heartbeat secret + ntfy.env (it's on the same box that's our backup
# target, but we want them in the encrypted bundle too so a bare-VPS rebuild
# can decrypt+restore from someone else's copy of the bundle)
ssh -o BatchMode=yes -o ConnectTimeout=10 "$VPS_HOST" \
  'sudo -n cat /etc/mushy-heartbeat/secret 2>/dev/null; echo ---SEPARATOR---; sudo -n cat /etc/mushy-heartbeat/ntfy.env 2>/dev/null' \
  > "$WORK/payload/vps/heartbeat-secrets.txt" 2>/dev/null || fail "pull VPS heartbeat secrets"
log "  staged VPS:/etc/mushy-heartbeat/{secret,ntfy.env}"

# 2. Manifest (so restore-time has a clear picture of what's inside)
{
  echo "Mushy Tier A backup — $STAMP UTC"
  echo "Generated by $(hostname) at $(date -Is)"
  echo
  find "$WORK/payload" -type f -printf '%P  %s bytes\n' | sort
} > "$WORK/MANIFEST.txt"

# 3. Tar + age-encrypt + push to VPS
[ -r "$RECIPIENT_PUB" ] || fail "missing age recipient pubkey at $RECIPIENT_PUB"

OUT_LOCAL="$WORK/$STAMP.tar.age"
( cd "$WORK" && tar -cf - MANIFEST.txt payload ) \
  | age -R "$RECIPIENT_PUB" -o "$OUT_LOCAL" \
  || fail "tar | age failed"
SIZE=$(stat -c%s "$OUT_LOCAL")
log "encrypted bundle: $SIZE bytes"

scp -B -o ConnectTimeout=15 "$OUT_LOCAL" "$VPS_HOST:$VPS_REPO/$STAMP.tar.age" >/dev/null \
  || fail "scp to $VPS_HOST:$VPS_REPO"
log "pushed to $VPS_HOST:$VPS_REPO/$STAMP.tar.age"

# 4. Push latest farmOS DB dump to VPS
LATEST_DUMP=$(ls -t "$FARMOS_BACKUP_DIR"/farm-*.dump.gz 2>/dev/null | head -1)
if [ -n "$LATEST_DUMP" ]; then
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$VPS_HOST" "mkdir -p $VPS_FARMOS_REPO" \
    || fail "ensure $VPS_FARMOS_REPO on VPS"
  scp -B -o ConnectTimeout=30 "$LATEST_DUMP" "$VPS_HOST:$VPS_FARMOS_REPO/$(basename "$LATEST_DUMP")" >/dev/null \
    || fail "scp farmos dump to $VPS_HOST:$VPS_FARMOS_REPO"
  DUMP_SIZE=$(stat -c%s "$LATEST_DUMP")
  log "pushed farmos dump $(basename "$LATEST_DUMP") ($DUMP_SIZE bytes) to VPS"
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$VPS_HOST" \
    "find $VPS_FARMOS_REPO -maxdepth 1 -type f -name 'farm-*.dump.gz' -mtime +$RETENTION_DAYS -print -delete" \
    > /dev/null 2>&1 || log "farmos dump prune skipped (non-fatal)"
else
  log "no farmos dump found in $FARMOS_BACKUP_DIR — skipping"
fi

# 5. Retention prune on VPS
ssh -o BatchMode=yes -o ConnectTimeout=10 "$VPS_HOST" \
  "find $VPS_REPO -maxdepth 1 -type f -name '*.tar.age' -mtime +$RETENTION_DAYS -print -delete" \
  > "$WORK/pruned.txt" 2>/dev/null || log "prune skipped (non-fatal)"
PRUNED=$(wc -l < "$WORK/pruned.txt" 2>/dev/null || echo 0)
[ "$PRUNED" -gt 0 ] && log "pruned $PRUNED snapshots older than ${RETENTION_DAYS}d"

log "OK ($SIZE bytes, $STAMP)"
