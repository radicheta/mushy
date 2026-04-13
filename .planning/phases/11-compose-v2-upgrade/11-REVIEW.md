---
phase: 11-compose-v2-upgrade
reviewed: 2026-04-12T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - docker-compose.yml
  - docker-compose.override.yml
  - CLAUDE.md
  - docs/OPERATIONS.md
  - docs/pi-setup/tailscale-setup.md
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-04-12
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

These files constitute the compose v2 upgrade artifacts: the live compose stack (root `docker-compose.yml` + `docker-compose.override.yml`), the project CLAUDE.md, and two operations/setup docs. The compose files themselves are structurally sound for compose v2 usage. The critical issue is a hardcoded plaintext database password committed directly to `.env` in the repository — a credential exposure risk. Three warnings cover a mutable `timescale/timescaledb:latest-pg14` image tag (upgrade risk on redeploy), a doc/code mismatch between the override file and the tailscale-setup guide, and an undocumented manual host precondition for the snapshot directory. Info items cover a stale comment in the deprecated compose, a doc inconsistency in OPERATIONS.md, and commented-out code in the deprecated compose.

---

## Critical Issues

### CR-01: Plaintext database credential committed to repository

**File:** `.env:1`
**Issue:** `TIMESCALE_PASSWORD` is committed to `.env` with a real 32-character password in plaintext. If this repository is or ever becomes public, or is pushed to a hosted remote, this credential is permanently exposed in git history. Even in a private repo, committing secrets is a security anti-pattern because git history is not rotated when the secret is.
**Fix:**
1. Add `.env` to `.gitignore` immediately.
2. Rotate the `TIMESCALE_PASSWORD` on the running TimescaleDB instance.
3. Provide `.env.example` with placeholder values instead:
```bash
# .env.example (safe to commit)
TIMESCALE_PASSWORD=CHANGE_ME
CORS_ORIGIN=http://localhost:8080
```
4. Document in CLAUDE.md that operators must create `.env` from `.env.example` before first deploy.

---

## Warnings

### WR-01: Mutable image tag on timescale service — silent upgrade risk

**File:** `docker-compose.yml:30`
**Issue:** `image: timescale/timescaledb:latest-pg14` uses a floating tag. Every `docker compose pull` or fresh deployment will pull whatever TimescaleDB version is current at that moment. A minor TimescaleDB release can change binary data formats or require `pg_upgrade`, silently breaking the persistent `timescale-data` volume on the next redeploy. This is a correctness risk, not merely a style issue — data may become inaccessible.
**Fix:** Pin to a specific digest or version tag:
```yaml
image: timescale/timescaledb:2.14.2-pg14
```
Check the current running version with `docker exec mushy-timescale-1 psql -U postgres -c 'SELECT version();'` and pin to that exact tag before the next planned upgrade cycle.

### WR-02: Doc/code mismatch — tailscale-setup.md references `docker-compose.override.yml` as editable, but current override hardcodes Tailscale config

**File:** `docs/pi-setup/tailscale-setup.md:46-59`
**Issue:** The guide instructs the operator to edit `docker-compose.override.yml` to switch between WireGuard and Tailscale CycloneDDS configs. However, the current `docker-compose.override.yml` (line 14-15) already hardcodes the Tailscale config:
```yaml
- CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml
volumes:
  - /home/santi/.config/cyclonedds-tailscale.xml:/etc/cyclonedds-tailscale.xml:ro
```
A WireGuard-mode snippet is shown in the guide but does not exist in the file. An operator following the guide would find the override already in Tailscale mode and the WireGuard snippet absent. If the intent is to always use Tailscale from elder-plops, the guide needs to be updated to reflect that the override is static. If WireGuard switching is still needed, the override needs an explicit note or a two-file approach.
**Fix:** Either update the doc to say "the override is currently set to Tailscale; to switch to WireGuard, replace lines 14-15 with..." or add a comment to `docker-compose.override.yml` noting the current mode:
```yaml
# Currently: Tailscale mode. To switch to WireGuard, change URI and volume below.
- CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml
```

### WR-03: Snapshot directory host precondition is undocumented in the live stack

**File:** `docker-compose.yml:27`
**Issue:** The bridge service mounts `/data/snapshots` from the host. If this directory does not exist on the host, Docker will create it as root-owned, which can silently break the bridge's ability to write snapshots. The deprecated `src/docker-compose.yml` has an inline comment (line 97) noting that `mkdir -p /data/snapshots/fc1` must be run on elder-plops before starting. That comment was not carried over to the live compose file or to OPERATIONS.md.
**Fix:** Add a comment to `docker-compose.yml` and a setup step to OPERATIONS.md:
```yaml
volumes:
  # Precondition: mkdir -p /data/snapshots/fc1 on elder-plops host
  - /data/snapshots:/data/snapshots
```
And add to OPERATIONS.md deploy procedure (step 0):
```bash
mkdir -p /data/snapshots/fc1
```

---

## Info

### IN-01: Deprecated `src/docker-compose.yml` mixes live and dead service definitions

**File:** `src/docker-compose.yml:66-109`
**Issue:** The deprecated file contains `openmct`, `bridge`, and `timescale` service definitions that shadow the canonical definitions in the repo root. These are dead code — CLAUDE.md explicitly says not to deploy from this file. However, they have diverged from the root compose (e.g., the deprecated bridge mounts `./mission-control/bridge/cyclonedds.xml` directly, not the host `~/.config` path; the deprecated timescale lacks `restart: always`). Keeping diverged shadow definitions increases the chance that a future operator deploys from the wrong file.
**Fix:** Remove the `openmct`, `bridge`, and `timescale` blocks from `src/docker-compose.yml`, keeping only the sim-specific services (`ros-core`, `ls-core`, `ic-core`, `simulation`) that aren't defined anywhere else.

### IN-02: OPERATIONS.md section numbering skips to 5.x without prior sections

**File:** `docs/OPERATIONS.md:77`
**Issue:** The Recovery Procedures section labels subsections as "5.1", "5.2", etc., but there are no preceding sections numbered 1–4. This is a minor doc quality issue that could confuse operators searching for a specific numbered section.
**Fix:** Either remove the numeric prefixes and use heading text only, or add the missing top-level numbered sections (Overview=1, Architecture=2, Configuration=3, Deploy Procedure=4, Recovery Procedures=5).

### IN-03: `CLAUDE.md` architecture overview lists `ros-net` / `frontend-net` Docker networks that no longer exist in the live compose

**File:** `CLAUDE.md:120-123`
**Issue:** The Architecture Overview section documents `ros-net` and `frontend-net` Docker bridge networks. These networks exist only in the deprecated `src/docker-compose.yml`. The live stack uses `network_mode: host` for all services (via the override), so no named Docker networks are created at all. A developer reading CLAUDE.md would have an incorrect mental model of the network topology.
**Fix:** Update the Docker networks section to reflect host networking:
```
Docker networking:
- All services use host networking (network_mode: host via override)
- No Docker bridge networks are created; services communicate via localhost
```

---

_Reviewed: 2026-04-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
