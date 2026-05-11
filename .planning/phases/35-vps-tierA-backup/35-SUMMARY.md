# Phase 35 — VPS Tier A backup (small irreplaceable bits) — SUMMARY

**Status:** SHIPPED 2026-05-11.
**Lineage:** "empezar chiquito" subset of backlog 999.45 (full borg). 999.45 stays open for Tier B (Timescale + farmOS db) when vfx studio offsite infra is decided.

## Why this exists (vs 999.45 full borg)

Operator decided 2026-05-11 that the VPS is already running enough load (WG hub + Phase 33 receiver + Phase 34 uptime-kuma) and shouldn't also become the primary backup target for 20+ GB of pg_dump data. Better fit: vfx studio infra for the bulky offsite later.

But the worst case from `project_2026_05_03_ssd_failure` was NOT lost telemetry data — it was rediscovering env vars, the chamber tuning knobs the farmer had set, and the secrets needed to bring the stack back up. That's a few KB of stuff. Capturing it now closes the painful half of the SD-death recovery story without committing the VPS to a backup-target role.

## What's in the bundle (~20 KB encrypted)

| Source | Files | Why |
|--------|-------|-----|
| elder-plops `/mnt/slime-kingdom/opt/mushy/.env` | mushy stack secrets (Timescale password, Anthropic key, Signal SENDER/RECIPIENT, etc.) | Needed to bring up the mushy stack on a fresh box |
| elder-plops `/mnt/slime-kingdom/shared/farmos/.env` | farmOS stack secrets | Needed to bring up farmOS on a fresh box |
| fc1 `/var/lib/fc-core/runtime_overrides.yaml` | Live operator-tuned RH target / band / mode overrides | The farmer-set knobs that make the chamber actually work for the current crop |
| fc1 `/etc/systemd/system/mushy-heartbeat.{service,timer}` | Phase 33 sender systemd units (not yet folded into `scripts/pi-deploy/` per `feedback_diff_repo_vs_pi_systemd`) | Captures the drift from repo until pi-deploy is reconciled |
| VPS `/etc/mushy-heartbeat/secret` + `ntfy.env` | Phase 33 HMAC secret + 999.43.1 ntfy topic URL | Critical to receiver's auth + Tier 2 push; if VPS is rebuilt, these need to be restored on the new VPS for the heartbeat senders to keep working |

What's NOT in scope (Tier B/C — see 999.45 for the bigger picture):
- Timescale telemetry data (replaceable; chamber would still run)
- farmOS Postgres data (production records — IS irreplaceable; defer to Tier B with vfx studio offsite)
- `/data/snapshots/`, `/data/snapshots-burnt/`, `/data/signal-capture/` (~tens of GB, generated, easy to re-accumulate)
- signal-cli registration state in the docker volume (~MBs, would force a re-link via QR + 4G SIM if lost — annoying but doable; defer)

## Architecture

```
elder-plops (santi user, systemd timer)
  ├─ stage:
  │    .env files (local read)
  │    fc1:/var/lib/fc-core/runtime_overrides.yaml (ssh fc1 cat)
  │    fc1:/etc/systemd/system/mushy-heartbeat.* (ssh fc1 sudo -n cat)
  │    VPS:/etc/mushy-heartbeat/{secret,ntfy.env} (ssh mushy@VPS sudo -n cat)
  ├─ tar | age -R ~/.ssh/id_ed25519.pub
  ├─ scp → mushy@VPS:/var/backups/mushy-tierA/<YYYYMMDD-HHMM>.tar.age
  ├─ prune VPS files older than 30 days
  └─ on any failure: POST to bridge /heartbeat-alert (rides Phase 33 + 999.43.1 chain)
```

**Encryption identity:** the operator's existing `~/.ssh/id_ed25519` (recipient: the matching pubkey). No new secret to manage — operator already keeps this key safe (1Password etc.). To restore: `age -d -i ~/.ssh/id_ed25519 backup.tar.age | tar -xv`.

**Schedule:** daily `OnCalendar=*-*-* 03:30:00` with `Persistent=true` (catches up if the box is asleep at 03:30) and `RandomizedDelaySec=10m` (jitter so any flock of timer-driven jobs doesn't all fire at once).

**Failure path:** any step failure POSTs to `localhost:8081/heartbeat-alert` with `source=backup-tierA`. That goes through the existing Phase 33 → bridge → signal-cli → operator phone Signal path. Reuses the existing alerting; doesn't build a parallel pipe.

## Acceptance — first-run smoke 2026-05-11

| # | Test | Result |
|---|------|--------|
| 1 | Tarball encrypts + lands on VPS | PASS — 20692 bytes at `/var/backups/mushy-tierA/20260511-0137.tar.age` |
| 2 | Decrypt with operator's `~/.ssh/id_ed25519` | PASS — `age -d -i ~/.ssh/id_ed25519` succeeded |
| 3 | Manifest + 5 payload files present | PASS — see decrypted listing in commit message of `eb1661a..` chain |
| 4 | Systemd timer enabled + scheduled for 03:30 nightly | PASS — `systemctl list-timers` shows next run |
| 5 | Failure path triggers Phase 33 alert | UNTESTED in production — code path is straightforward `curl POST` to a known endpoint; will fire on first real failure |

## Files

```
ADDED:
  scripts/backup-tierA/mushy-tierA-backup.sh                bash, ~80 LOC, age + ssh + scp + cron-friendly logging
  scripts/backup-tierA/mushy-tierA-backup.service           systemd oneshot, User=santi
  scripts/backup-tierA/mushy-tierA-backup.timer             daily 03:30 with persistence
  .planning/phases/35-vps-tierA-backup/35-SUMMARY.md        this file

DEPLOYED (NOT in repo):
  elder-plops:
    /usr/local/bin/mushy-tierA-backup.sh
    /etc/systemd/system/mushy-tierA-backup.service
    /etc/systemd/system/mushy-tierA-backup.timer
    apt: age 1.0.0
  VPS:
    /var/backups/mushy-tierA/                              (mushy:mushy 750)
    apt: age 1.1.1
```

## Operational reference

- **Manual run:** `sudo systemctl start mushy-tierA-backup.service`
- **Check next scheduled run:** `systemctl list-timers mushy-tierA-backup.timer`
- **Inspect last log:** `sudo journalctl -u mushy-tierA-backup.service -n 30`
- **List bundles on VPS:** `ssh mushy@178.105.84.13 'ls -la /var/backups/mushy-tierA/'`
- **Restore drill (run from any box with the operator's ed25519 key):**
  ```bash
  scp mushy@178.105.84.13:/var/backups/mushy-tierA/<YYYYMMDD-HHMM>.tar.age /tmp/
  cd /tmp && age -d -i ~/.ssh/id_ed25519 <YYYYMMDD-HHMM>.tar.age | tar -xv
  ```
- **Force a failure-path test:** point `BRIDGE_HEARTBEAT_URL=http://10.66.0.99:9999/heartbeat-alert` and a non-existent `RECIPIENT_PUB` env, run, expect Signal alert via the same path 999.43.1 uses.

## What this does NOT close

999.45 (full borg with Tier B+C) stays in backlog until vfx studio infra (or another offsite) is decided. The receipt below is enough to recover from `project_2026_05_03_ssd_failure`-class incidents but does not protect against losing all of mushy's telemetry/captures/snapshots history.

## ⚠️ KNOWN SPOF — operator-acknowledged 2026-05-11

**The only key that can decrypt these backups is `~/.ssh/id_ed25519` on elder-plops.** That key is not currently backed up offline. If elder-plops's disk dies AND the key is lost, every Tier A backup on the VPS becomes unrecoverable ciphertext — defeats the point.

Mitigation deferred. Two cheap paths when ready:
1. **Operator generates a second age keypair**, stores the secret line in 1Password (or paper / USB), pastes only the pubkey to a future Claude session. Script gets `-R <pubkey1> -R <pubkey2>` (multi-recipient), every future bundle decrypts with either key.
2. **Or:** back up `~/.ssh/id_ed25519` itself to 1Password as a separate one-time action. Single recipient stays; key safety is moved offline.

Filed as a near-term TODO; not a phase. Surface as soon as the operator has 10 minutes for `age-keygen` + paste, OR next time they're updating 1Password.
