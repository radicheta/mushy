# Phase 999.45 — VPS offsite backups — RESEARCH

**Status:** RESEARCH (pre-discuss). Filed in ROADMAP 2026-05-10. Mitigates `project_2026_05_03_ssd_failure` (SD card death → full rebuild from scratch).
**Target:** Hetzner CX22 (Nuremberg), wg-hub `10.66.0.1`, mushy user has sudo, ~20 GB free disk.
**Date:** 2026-05-10.

---

## Recommendation: borgbackup (1.4.x from upstream, NOT borg2 beta)

Pick **borg**. Reasons in priority order:

1. **Compression matters here.** Our payload is ~95% Postgres dumps + JSON + YAML — highly compressible text. Borg's zstd cuts ~50% on top of dedup; restic has no compression below 0.14 and even now compression is opt-in/auto-detected with weaker results on already-deduped chunks. On a 20 GB VPS budget this is the difference between 60+ days vs 30 days of retention.
2. **Append-only over SSH is a first-class primitive.** Borg's server-side `borg serve --append-only` plus a restricted SSH `command=` lockdown means a compromised elder-plops cannot delete VPS-side history. Restic's append-only via REST server requires running an extra daemon.
3. **Single-host repo is the right shape.** Restic's killer feature (multi-host dedup in one repo) doesn't apply — we have exactly one source (elder-plops) shipping data. Restic's advantage evaporates.
4. **Apt-current on both ends.** Ubuntu 24.04 ships `borgbackup 1.2.8`; elder-plops (Mint 21.2 / jammy) has `1.2.0`. Both wire-compatible (1.2 client ↔ 1.2 server is supported). Restic in jammy is `0.12.1` (Aug 2021, four years stale) — would force pinning a binary from GitHub releases. Borg avoids that drift.
5. **FUSE mount for restore browsing.** `borg mount repo::archive /mnt` is the difference between a 5-minute restore drill and a 45-minute one. Restic has `restic mount` too but slower in practice on large repos.

What we give up:
- **No native S3/B2.** Future S3 optionality (DECISION-6 nice-to-have) needs `rclone serve sftp` or borgmatic; not free. Acceptable — VPS-only is the design point for now.
- **borg2 beta is tempting** (better compression, multi-host repos) but explicitly "DO NOT USE FOR PRODUCTION." Stay on 1.4.x stable (1.4.4 released 2026-03-19 — actively maintained).

| | borg 1.4 | restic 0.18 |
|---|---|---|
| Latest release | 1.4.4 (2026-03-19) | 0.18.1 (2025-09-21) |
| Ubuntu 24.04 apt | 1.2.8 | 0.16.4 |
| Mint 21.2 / jammy apt | 1.2.0 | 0.12.1 (stale) |
| Compression | zstd/lz4/zlib/lzma | zstd (weaker on this workload) |
| Push/pull | push (SSH) or pull (server initiates) | push only |
| S3/B2 native | no (rclone) | yes |
| Encryption | repokey-blake2 (default) | AES-256 + Poly1305 |
| Append-only | `borg serve --append-only` | REST server flag |
| Restore single file | `borg extract` or FUSE mount | `restic restore` or mount |
| Single-source dedup | excellent | excellent |

**Decision posture:** borg is final unless pre-discuss surfaces a hard requirement for S3 in the next 6 months.

---

## What gets backed up

| Source | Include nightly? | Approach | Retention | Approx size |
|---|---|---|---|---|
| Timescale (`mushy-timescale-1`, db `postgres`) | **Yes** | `pg_dump -Fc` piped into borg via `--stdin` (no temp file). Custom format = parallelizable restore. | 14 daily / 8 weekly / 12 monthly | ~1.2 GB raw → ~200 MB compressed; daily delta after dedup ~30-80 MB |
| farmOS Postgres (separate stack at `/mnt/slime-kingdom/shared/farmos/`) | **Yes** | Same `pg_dump -Fc \| borg create --stdin` from the farmOS db container | 14 / 8 / 12 | unknown, expect <500 MB compressed |
| `bridge-state/buffer-replay.state.json` | **Yes** | Raw file include in nightly archive | matches db retention | <1 KB |
| fc1 `/var/lib/fc-core/runtime_overrides.yaml` | **Yes** | Pulled to elder-plops via existing SSH (`ssh fc1 cat ...` into staging dir), then borg | matches | <10 KB |
| `/data/snapshots/` (camera frames, raw) | **No** | Too large (tens of GB), already on RAID, low recovery value vs cost. Nightly skip. | n/a | tens of GB |
| `/data/snapshots-burnt/` (with overlays) | **No** | Same reasoning. Re-derivable from raw + Phase 22 sidecar. | n/a | tens of GB |
| `/data/snapshots/INDEX` or equivalent metadata file (if exists) | **Yes** if cheap | Include only the index/manifest, not the JPEGs | matches | small |
| `/data/signal-capture/` | **Yes** | Raw file include (text/audio metadata; small) | 14 / 8 / 12 | <100 MB |
| `.env` files at repo root + farmOS root | **Yes** | Critical secrets; restore would need them | matches | <10 KB |
| `docker-compose.override.yml`, `docker-compose.yml` | No (in git) | Skip — git is the source of truth | — | — |

**Snapshots opt-out is the load-bearing call.** If the farmer ever asks "can we restore last March's photos?" the answer is no; this is a deliberate scope cut and should be flagged in the SUMMARY for farmer attestation.

**Retention math:** worst case (14 + 8 + 12) × ~250 MB compressed ≈ 8.5 GB. Comfortably inside the 20 GB VPS budget with room for farmOS + signal-capture growth.

---

## Deployment shape

```
elder-plops (sender)              VPS 10.66.0.1 (receiver)
─────────────────────             ───────────────────────────
/etc/systemd/system/              /var/lib/mushy-backup/borg-repo/
  mushy-backup.service              (append-only, mode 700,
  mushy-backup.timer                 owner mushy:mushy)
                                  ~mushy/.ssh/authorized_keys
/usr/local/bin/                     command="borg serve
  mushy-backup.sh                    --append-only
                                     --restrict-to-repository ..."
~/.ssh/mushy-backup-id_ed25519     SSH key (separate from
  (root-owned, mode 600)             ops keys)
```

- **Script lives on elder-plops** at `/usr/local/bin/mushy-backup.sh` (push model). VPS only runs `borg serve` invoked via SSH `command=`. No cron on VPS for backup.
- **Schedule:** systemd timer (`OnCalendar=*-*-* 03:30:00`, `RandomizedDelaySec=20m`, `Persistent=true` so it catches up after elder-plops downtime). Matches the Phase 33 pattern.
- **Credentials:**
  - Borg passphrase: stored in `/etc/mushy-backup/passphrase` on elder-plops (root:root, mode 600); script `export BORG_PASSCOMMAND="cat /etc/mushy-backup/passphrase"`. Passphrase ALSO printed-and-stored in 1Password / sealed envelope in farm physical office — without it the VPS data is opaque even with full disk access.
  - SSH key: dedicated keypair (not the existing ops key), public half pinned in VPS `authorized_keys` with `command=` restriction + `no-pty,no-agent-forwarding,no-X11-forwarding,no-port-forwarding`.
  - Postgres password: already in elder-plops `.env` as `TIMESCALE_PASSWORD`; script sources it.
- **Pruning:** `borg prune --keep-daily 14 --keep-weekly 8 --keep-monthly 12` runs at end of script. Append-only mode means prune from elder-plops is a *request* — needs a periodic `borg compact` on the VPS to actually reclaim space. Add a weekly VPS-side systemd timer (`mushy-backup-compact.timer`, Sunday 04:00) that runs `borg compact /var/lib/mushy-backup/borg-repo`.
- **Logging + alerting:** `mushy-backup.service` writes JSON line to `/var/log/mushy-backup.log` on each run. On failure, exit non-zero → systemd `OnFailure=mushy-backup-alert.service` POSTs to bridge `/heartbeat-alert` (reuse Phase 33 endpoint). Two consecutive failures = Signal alert.
- **Heartbeat integration:** add a successful-backup marker — script touches `/var/lib/mushy-backup/last_success` and elder-plops `mushy-heartbeat-sender.sh` includes the timestamp in heartbeat payload. Receiver flags "last backup >36h ago" as a Tier 1 alert. Cheap addition; closes the "backups silently stopped" failure mode.

---

## Restore drill (quarterly)

**Frequency:** first Sunday of each quarter (Jan/Apr/Jul/Oct), set as recurring calendar item; also gate before any major upgrade.

**Procedure** (~15 min, runs from elder-plops or any box with the passphrase + SSH key):

```
# 1. List available archives
borg list ssh://mushy@10.66.0.1/~/borg-repo

# 2. Pick yesterday's archive
ARCH=$(borg list --short ssh://mushy@10.66.0.1/~/borg-repo | tail -1)

# 3. Mount it FUSE
mkdir /tmp/restore-drill && borg mount ssh://mushy@10.66.0.1/~/borg-repo::$ARCH /tmp/restore-drill

# 4. Bring up a sandbox Postgres on a throwaway port
docker run -d --name restore-drill-pg -p 5433:5432 \
  -e POSTGRES_PASSWORD=drill timescale/timescaledb:latest-pg16

# 5. Restore the dump
pg_restore -h localhost -p 5433 -U postgres -d postgres \
  /tmp/restore-drill/timescale.dump

# 6. Verify: query a recent telemetry row
psql -h localhost -p 5433 -U postgres -c \
  "SELECT max(time) FROM telemetry WHERE topic = 'fc1/humidity';"

# 7. Tear down
docker rm -f restore-drill-pg && borg umount /tmp/restore-drill
```

**Success criterion (single, falsifiable):** step 6 returns a timestamp within the last 30 hours of the archive's creation time. If yes, drill PASS. If no, drill FAIL → file incident, don't archive milestone until resolved.

Drill output (PASS/FAIL + timestamp) appended to `/var/log/mushy-backup-drill.log` and noted in next session's status.

---

## Out of scope for 999.45 (file as backlog if needed)

| Out-of-scope item | Why deferred |
|---|---|
| **Camera snapshot backup** | Tens of GB, low recovery value. If farmer needs historical photos, file new phase to ship `/data/snapshots/` to a B2/Backblaze bucket directly (different cost profile than 999.45). |
| **Off-site #2 (S3 / B2 / Wasabi)** | Single-site (VPS only) is fine for the SD-failure incident class. Geographic diversification is a separate tier-2 problem; would need rclone or borg2's S3 native support. |
| **fc1-side backups** (other than `runtime_overrides.yaml`) | fc1 is reproducible from git + Pi deploy script; only runtime state needs preserving. If we add more on-Pi state later, expand the elder-plops collection step. |
| **Encrypted backup of the borg passphrase itself** | Out-of-band, manual: 1Password + paper. Don't try to automate this — it's a recovery-time problem, not a runtime problem. |
| **Bare-metal elder-plops restore** | Elder-plops OS itself is not in scope; Docker compose + git checkout + restore the dbs from VPS = recovery path. If we want OS-level snapshots, that's a separate phase. |
| **Multi-tenant / multi-chamber** | Single chamber for now. When chamber #2 ships, repo can stay one (borg dedups across archives within one repo) but archive naming convention will need a chamber prefix. |
| **PITR (point-in-time recovery) for Timescale** | Nightly `pg_dump` loses up to 24h. PITR via WAL shipping is an order of magnitude more complex; not justified at v1.5 farm scale. |
| **Automated restore drill (in CI)** | Quarterly manual drill is sufficient. Automating it is a future hardening phase. |

---

## Composition with existing memories

- `project_2026_05_03_ssd_failure` — this phase is the direct mitigation. SD died → full rebuild → if Timescale had been on the SD (or fc1 had had local persisted state we cared about), data was unrecoverable. Backups = recovery in hours not days.
- `project_phase32_vps_hub_shipped` — backup repo lives on the VPS, reachable over wg-hub at `10.66.0.1`. SSH path is `mushy@10.66.0.1` (already provisioned).
- `project_phase33_vps_heartbeat_receiver` (33-SUMMARY) — reuse the bridge `/heartbeat-alert` endpoint for backup-failure notifications and the heartbeat payload for "last successful backup" surfacing. Avoid building a parallel notification path.
- `feedback_no_farmer_bookkeeping_tax` — restore drill is operator/Claude work, not farmer work. Quarterly drill = no farmer touch.
- `project_data_path_on_raid` — `/data` is a symlink to `/mnt/slime-kingdom/data`; backup script must dereference (`borg create --files-cache=ctime,size` should be fine; verify that borg follows the symlink at the include path level).
- `feedback_diff_repo_vs_pi_systemd` — fc1 systemd drift means the runtime_overrides.yaml backup needs to actually `ssh fc1 cat`, not assume the file is reproducible from git.

---

## Open questions for discuss-phase

1. Snapshot retention bands above (14 / 8 / 12) are a guess; farmer may want more aggressive monthly retention for end-of-cycle reconstruction.
2. farmOS db backup — does Zoy want to own this on the farmOS side, or do we just back up their Postgres container from elder-plops? (CLAUDE-SYNC.md crosspost candidate.)
3. Backup passphrase escrow — paper-in-office only, or also a copy at the farmer's house?
4. Should snapshot directory's *index* (not JPEGs) be in the backup so post-restore we can detect what's missing?

---

## Sources

- [Borg releases (1.4.4 — 2026-03-19)](https://github.com/borgbackup/borg/releases)
- [Borg release series page](https://www.borgbackup.org/releases/)
- [Restic 0.18.1 release (2025-09-21)](https://restic.net/blog/2025-09-21/restic-0.18.1-released/)
- [Restic releases on GitHub](https://github.com/restic/restic/releases)
- [Borg vs Restic comparison — servercrate 2026](https://servercrate.net/restic-vs-borg/)
- [Restic vs BorgBackup vs Kopia on VPS in 2025 — onidel](https://onidel.com/blog/restic-vs-borgbackup-vs-kopia-2025)
- [borgbackup Noble 24.04 (1.2.8) — Launchpad](https://launchpad.net/ubuntu/noble/+package/borgbackup)
- [restic Noble 24.04 (0.16.4) — Launchpad](https://launchpad.net/ubuntu/noble/+source/restic)
