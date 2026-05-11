---
phase: 36-signal-pre-gate
plan: 01
captured_utc: 2026-05-11
deviceId_observed: 2 (linked-secondary, local install) + 1 (Signal-server-side primary, location unknown)
tarball_size: 99M
phase35_coverage: GAP — filed as 999.52
---

# Plan 36-01 — Pre-flight Snapshot

Captured **before** any signal-cli re-registration. This artifact is the abort path for Plan 36-02. Until 36-02 verifies a successful round-trip on the new primary, this snapshot is the rollback material.

## Snapshot Captured

| Item | Value |
|------|-------|
| Capture timestamp (UTC) | 2026-05-11 |
| Host | elder-plops |
| Docker volume name | `mushy_signal-cli-data` |
| Tarball path | `/mnt/slime-kingdom/mushy-backups/signal-cli-data-20260511.tar.gz` |
| Tarball size | 99M |
| Entry count | 140 |
| Account state present | YES — `./data/270761`, `./data/270761.d/account.db`, `./data/accounts.json` confirmed in `tar -tzf` |
| Avatars + attachments included | YES (avatars/profile-* + attachments/) |

**Path deviation from plan:** Plan 36-01 specified `/opt/mushy-backups/...`. That path requires `sudo` to create; operator was unavailable for the sudo step at capture time. Used `/mnt/slime-kingdom/mushy-backups/...` (RAID-backed, writable, no sudo gate) instead. The directory is durable and protected by the same RAID array as `/data/`. Operator may post-hoc `sudo ln -s /mnt/slime-kingdom/mushy-backups /opt/mushy-backups` if scripts elsewhere assume `/opt`; nothing in this repo currently does.

### Redacted state JSON

| Path | Contents |
|------|----------|
| `.planning/phases/36-signal-pre-gate/snapshots/devices-20260511.json` | 2 devices: id=1 (Signal-server primary, name="") + id=2 (`mushy-alerter`, local linked-secondary) |
| `.planning/phases/36-signal-pre-gate/snapshots/identities-20260511.json` | 5 identities (bot self + 4 farmer contacts) — E.164 numbers and UUIDs redacted |

### Note on device list — NOT abort

Plan 36-01 Task 1 says "If `.id == 1` already appears, ABORT — Phase 36 is already done." That ABORT condition was based on a simpler model. The reality observed today:

- `/v1/devices/+<BOT>` returns the **Signal-server-side device list** for the bot account — it includes ALL devices on the account, not just the local install.
- Two devices present: `id=1` (name empty, the server-side primary, location unknown — likely the device that originally registered the bot) and `id=2` (name `mushy-alerter`, our local elder-plops install, linked-secondary).
- The receive-400 symptom from Phase 25 is consistent with the local install operating as `id=2`. Only `id=1` can `/v1/receive` on this account.
- Re-registration via SMS (Plan 36-02) will: verify ownership of the number, invalidate the existing `id=1` device on Signal's server, and make the local install the new `id=1` with a rotated identity key. After 36-02 success, the redacted `devices-*.json` should show **a single entry with `id=1` and a new `creation_timestamp` matching the re-reg moment.**

→ Phase 36 is NOT already done. Proceeding to Plan 36-02 is correct.

## Phase 35 Tier A Coverage Verdict

**GAP.** Phase 35 Tier A backup (`scripts/backup-tierA/mushy-tierA-backup.sh`) bundles only:
- elder-plops `.env` files (mushy + farmos)
- fc1 `runtime_overrides.yaml` + heartbeat systemd units
- VPS heartbeat secrets + ntfy.env

→ **The signal-cli Docker volume is NOT in Tier A.** Loss of `mushy_signal-cli-data` would force full re-registration + re-link of all farmer trust — a multi-hour painful reconstruction.

Filed as `999.52 — Phase 35 Tier A missing signal-cli account state` (see STATE.md deferred items). Until 999.52 lands, the local tarball captured by this plan is the ONLY rollback path for the signal-cli volume.

## Restore Recipe (abort path for Plan 36-02)

Use this if Plan 36-02 SMS verification fails or the new primary lands in a bad state. Restores the pre-reg deviceId=2 linked-secondary (degraded — still HTTP 400 on `/v1/receive`, but otherwise functional).

```bash
# 1. Stop alerter + signal-cli
cd /mnt/slime-kingdom/opt/mushy
docker compose stop alerter signal-cli

# 2. Wipe the live volume
docker volume rm mushy_signal-cli-data
docker volume create mushy_signal-cli-data

# 3. Restore from local tarball
docker run --rm \
  -v mushy_signal-cli-data:/dst \
  -v /mnt/slime-kingdom/mushy-backups:/src \
  alpine tar -xzf /src/signal-cli-data-20260511.tar.gz -C /dst

# 4. Bring services back
docker compose up -d signal-cli alerter

# 5. Verify
BOT=$(grep -E '^SIGNAL_SENDER=' /mnt/slime-kingdom/opt/mushy/.env | cut -d= -f2)
curl -sS "http://127.0.0.1:8085/v1/devices/${BOT}" | jq '.[] | .id'
# Expected: 1 and 2 (server-side primary + local linked-secondary, restored)
```

If restore succeeds the system returns to the Phase 25 broken-but-non-destructive state. From there, retry Plan 36-02 after diagnosing the SMS verify failure.

## Pre-Flight Checklist for Plan 36-02

Gates that MUST be cleared before running primary re-registration:

- [x] Local tarball exists at `/mnt/slime-kingdom/mushy-backups/signal-cli-data-20260511.tar.gz` and `tar -tzf` lists 140 entries including `./data/accounts.json`
- [x] Device JSON snapshot captured (`devices-20260511.json`) showing local install at `id=2`
- [x] Identity DB snapshot captured (`identities-20260511.json`) — 5 identities including 4 farmer contacts (redacted)
- [x] Phase 35 verdict reviewed → GAP filed as 999.52; this tarball is the only rollback path
- [ ] **Farmer #1 coordinated for 30–60 min reachability window** (operator to confirm before Plan 36-02 Task 2)
- [ ] **4G router has SIM in slot + powered up** (operator action — in progress per session note)
- [ ] **gumbald is reachable** from elder-plops via `ssh gumbald` (alias → `santi@10.68.155.55`)
- [ ] **gumbald has the 4G router's WiFi credentials** (to receive SMS captcha)
- [ ] **Plan 36-02 runbook is written and reviewed** (Plan 36-02 Task 1 — must come before Task 2 live execution)

## References

- Plan: `36-01-PLAN.md`
- Context: `36-CONTEXT.md` (D-01..D-05 → this artifact; D-03 verdict here)
- Memory: `project_signal_cli_primary_reregister_path.md`, `project_phase35_tierA_backup.md`, `project_signal_cli_link_gotchas.md`
- Backlog filed: `STATE.md` deferred items → 999.52
