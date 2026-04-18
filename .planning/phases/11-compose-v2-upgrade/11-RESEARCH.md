# Phase 11: Compose v2 Upgrade - Research

**Researched:** 2026-04-12
**Domain:** Docker Compose v1 → v2 migration on Ubuntu 22.04 (Linux Mint 21.2)
**Confidence:** HIGH

## Summary

elder-plops currently runs docker-compose 1.29.2 (Python-based standalone binary installed via the Ubuntu `docker-compose` package). The `docker-compose-v2` package (version 2.40.3) is available in `jammy-updates` and installs a Go binary as a Docker CLI plugin at `/usr/libexec/docker/cli-plugins/docker-compose`. After installation, `docker compose` (v2) works immediately; the old `docker-compose` v1 Python binary at `/usr/bin/docker-compose` remains in place until explicitly removed.

The critical migration issue is container renaming: Compose v1 named containers with underscores (`mushy_bridge_1`), v2 uses hyphens (`mushy-bridge-1`). A full audit of the codebase found that **no production code** references hardcoded container names — the bridge's `index.js` uses service DNS names, not container names. The only files that reference v1 underscore names are two documentation files (`docs/OPERATIONS.md` and `docs/pi-setup/tailscale-setup.md`). Those docs need updating but are not execution-blockers.

Running `docker compose up -d` with v2 on this project will stop the existing v1-named containers and create new v2-named ones — this is the expected migration cutover. The `timescale-data` volume is named (not anonymous), so TimescaleDB data survives the recreation.

**Primary recommendation:** Install `docker-compose-v2` via apt, purge `docker-compose` v1, remove the deprecated `version:` field from compose files, run `docker compose up -d --build bridge` to recreate all containers under v2 naming, then update docs to reflect new container names.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-01 | elder-plops runs docker compose v2 (`docker compose` plugin) instead of docker-compose v1 | `docker-compose-v2` package v2.40.3 available in `jammy-updates`; installs as CLI plugin; old v1 binary can be purged |
| INFRA-02 | All existing services (bridge, openmct, timescale) start correctly under compose v2 | Compose files use standard features (host networking, volumes, env vars) with no v1-only syntax; named volume `timescale-data` survives recreation |
| INFRA-03 | Container name format change (underscores → hyphens) accounted for — no hardcoded references break | Full codebase audit: only docs contain v1 names; bridge code uses service DNS, not container names |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| docker-compose-v2 (apt) | 2.40.3 | Docker Compose v2 as CLI plugin | Ubuntu 22.04 native package; no Docker Hub account needed; installs to `/usr/libexec/docker/cli-plugins/` which is in Docker's plugin discovery path |

**No new application dependencies.** This phase is a host-level tooling upgrade only.

### What Changes
| Component | Before | After |
|-----------|--------|-------|
| Compose binary | `/usr/bin/docker-compose` (Python 1.29.2) | `/usr/libexec/docker/cli-plugins/docker-compose` (Go 2.40.3) |
| Invocation | `docker-compose up -d` | `docker compose up -d` |
| Container names | `mushy_bridge_1`, `mushy_openmct_1`, `mushy_timescale_1` | `mushy-bridge-1`, `mushy-openmct-1`, `mushy-timescale-1` |
| Compose file `version:` field | `version: '3.8'` (used) | Deprecated/removed (v2 ignores it) |

**Installation:**
```bash
sudo apt install docker-compose-v2
sudo apt purge docker-compose   # remove v1 Python binary
```

**Version verification:** [VERIFIED: apt-cache show docker-compose-v2]
```
docker-compose-v2: 2.40.3+ds1-0ubuntu1~22.04.1 (available in jammy-updates)
docker-compose:    1.29.2-1 (currently installed, to be removed)
Docker Engine:     28.2.2 (already installed)
```

## Architecture Patterns

### Package Install Path
`docker-compose-v2` installs the binary to `/usr/libexec/docker/cli-plugins/docker-compose`. [VERIFIED: dpkg-deb -c on downloaded package]

Docker Engine 28.x automatically discovers CLI plugins from these directories:
- `~/.docker/cli-plugins`
- `/usr/local/lib/docker/cli-plugins`
- `/usr/local/libexec/docker/cli-plugins`
- `/usr/lib/docker/cli-plugins`
- `/usr/libexec/docker/cli-plugins` ← where the package installs

No additional PATH or config changes needed after `apt install docker-compose-v2`.

### Coexistence During Install

After `apt install docker-compose-v2` (before purging v1):
- `docker compose version` → v2.40.3 (the plugin)
- `docker-compose version` → v1.29.2 (the Python binary, still at `/usr/bin/`)

The packages do NOT conflict: `docker-compose-v2` provides `docker-compose` (virtual package) but does not `Conflicts:` or `Replaces:` the `docker-compose` package. [VERIFIED: apt-cache show docker-compose-v2]

This means v1 must be explicitly purged to prevent accidental use of the old binary.

### Container Recreation During Migration

When `docker compose up -d` is first run with v2 against this project:
1. v2 computes expected container names as `mushy-bridge-1`, `mushy-openmct-1`, `mushy-timescale-1`
2. It sees `mushy_bridge_1`, `mushy_openmct_1`, `mushy_timescale_1` as **orphan containers** (old names)
3. It prints a warning about orphans and creates new containers with hyphen names
4. The old underscore-named containers are left stopped but not removed (until `docker compose down` or manual removal)

**Key:** The named volume `timescale-data` is not bound to the container name — it persists across recreation. All telemetry data survives. [VERIFIED: docker-compose.yml inspection]

### Compose File Changes Needed

The `version:` top-level field is deprecated in Compose v2 spec. [CITED: docs.docker.com/compose/migrate]
- v2 ignores it silently (no error), but may print a WARN message
- Best practice: remove the field entirely when migrating

Both `docker-compose.yml` and `docker-compose.override.yml` currently have `version: '3.8'` — remove from both.

The deprecated `src/docker-compose.yml` should also have the field removed for hygiene, though it is not deployed.

### Anti-Patterns to Avoid

- **Using `--compatibility` flag as the solution:** The `COMPOSE_COMPATIBILITY` env var or `--compatibility` flag makes v2 use v1 underscore naming — but this is a crutch. Since no code depends on the container names, use proper v2 naming from the start.
- **Keeping docker-compose v1 installed:** After migration, the old `/usr/bin/docker-compose` binary is a footgun. Any script or muscle memory that uses `docker-compose` will silently run v1 against the v2-managed stack. Purge it.
- **Not passing `--build` when recreating bridge:** The CLAUDE.md explicitly notes: "When rebuilding bridge, always pass `--build` — the compose file pins the build context but not the image tag, and `up -d` alone will reuse the cached image."

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Compose v2 availability | Manual binary download to `/usr/local/bin` | `apt install docker-compose-v2` | Ubuntu package is on 2.40.3 in jammy-updates; apt manages upgrades; no Docker Hub credentials needed |
| Keeping v1 names | COMPOSE_COMPATIBILITY=1 globally | Proper v2 migration | No code depends on underscore names; just update two doc files |

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `timescale-data` named Docker volume — TimescaleDB data | None — named volumes survive container recreation |
| Live service config | 3 running containers with v1 names (`mushy_bridge_1`, `mushy_openmct_1`, `mushy_timescale_1`) | `docker compose up -d --build bridge` recreates with v2 names; old containers stop |
| OS-registered state | None — no systemd units or cron jobs reference container names by name | None |
| Secrets/env vars | `.env` at repo root: `TIMESCALE_PASSWORD`, `CORS_ORIGIN` — these are env var names, not container names | None — unchanged |
| Build artifacts | Bridge and openmct Docker images (tagged by compose project) | Rebuild bridge with `--build`; openmct image rebuilds automatically |

**Other projects on this host also use v1 naming:**
The host runs `farmos` (3 containers) and `webserver-sombrero` (many containers) with v1 underscore names. These projects are NOT managed by the mushy repo. Installing `docker-compose-v2` does not affect their running containers — it only changes what tool is used for future `docker compose` commands in those projects. No scripts in those projects were found that call `docker-compose` directly. [VERIFIED: grep across /mnt/slime-kingdom/webserver-sombrero/ and /mnt/slime-kingdom/shared/farmos/]

## Common Pitfalls

### Pitfall 1: Orphan Containers After Migration
**What goes wrong:** After `docker compose up -d` with v2, both `mushy_bridge_1` (stopped v1) and `mushy-bridge-1` (running v2) exist. `docker ps -a` shows double entries. Monitoring scripts or mental models that check for "mushy_bridge_1" would see it as stopped.
**Why it happens:** v2 creates new containers without removing old ones; it just warns about orphans.
**How to avoid:** After verifying v2 stack is healthy, run `docker compose down --remove-orphans` or manually `docker rm` the old v1-named stopped containers.
**Warning signs:** `docker ps -a | grep mushy` shows 6 entries instead of 3.

### Pitfall 2: docker-compose v1 Still on PATH
**What goes wrong:** `docker-compose` (v1) still resolves after `apt install docker-compose-v2`. A developer types `docker-compose ps` and gets v1 output, which shows the old stopped containers with underscore names as if they're still current.
**Why it happens:** The packages don't conflict; v1 binary remains at `/usr/bin/docker-compose`.
**How to avoid:** `sudo apt purge docker-compose` immediately after confirming v2 works.
**Warning signs:** `which docker-compose` returns `/usr/bin/docker-compose`.

### Pitfall 3: bridge Starts with Stale Image
**What goes wrong:** `docker compose up -d` recreates bridge container but uses cached image — new code changes not picked up.
**Why it happens:** compose `up -d` without `--build` reuses the existing image if it exists.
**How to avoid:** Always use `docker compose up -d --build bridge` when recreating the bridge.
**Warning signs:** Container starts but old behavior observed; `docker inspect mushy-bridge-1` shows old image hash.

### Pitfall 4: `version:` Field Warning Noise
**What goes wrong:** Every `docker compose` invocation prints `WARN[0000] ... 'version' is obsolete and will be ignored`.
**Why it happens:** The `version: '3.8'` field in both compose files is deprecated in the Compose v2 spec.
**How to avoid:** Remove the `version:` line from `docker-compose.yml` and `docker-compose.override.yml` as part of this migration.
**Warning signs:** Warning printed on every command after v2 is installed.

### Pitfall 5: Docs Confuse Future Operators
**What goes wrong:** `docs/OPERATIONS.md` recovery procedures say to check for `mushy_openmct_1` and `mushy_bridge_1`. After migration, `docker ps | grep mushy` shows `mushy-openmct-1` and `mushy-bridge-1`. Operator thinks the containers aren't running.
**Why it happens:** Docs written against v1 naming convention.
**How to avoid:** Update both doc files as part of this migration — specifically the architecture diagram and the recovery section in OPERATIONS.md, and the `docker exec` command in tailscale-setup.md.
**Warning signs:** Doc says `mushy_bridge_1`; `docker ps` shows `mushy-bridge-1`.

## Code Examples

### Check Current Compose Status
```bash
# Before migration — verify current state
docker-compose version        # should show 1.29.2
docker ps --format "{{.Names}}" | grep mushy
# mushy_bridge_1  mushy_openmct_1  mushy_timescale_1
```

### Install v2 Plugin
```bash
# [VERIFIED: apt-cache show docker-compose-v2 on elder-plops]
sudo apt update
sudo apt install docker-compose-v2
docker compose version        # should show v2.40.3
docker-compose version        # still shows 1.29.2 (not yet purged)
```

### Purge v1
```bash
sudo apt purge docker-compose
which docker-compose          # should return nothing (or error)
```

### Recreate Stack Under v2
```bash
cd /mnt/slime-kingdom/opt/mushy   # or wherever the repo lives on elder-plops
docker compose down               # stop + remove old containers (if using v2 first time, these are v1 names)
docker compose up -d --build bridge
docker compose ps                 # expect: mushy-bridge-1, mushy-openmct-1, mushy-timescale-1
```

### Verify Telemetry End-to-End
```bash
# Wait ~30s for bridge to connect to ROS2
curl http://localhost:8080        # OpenMCT UI responds
# Open Mission Control in browser, verify humidity/CO2/humidifier state shows live values
```

### Remove v1 Orphan Containers (after verifying v2 is healthy)
```bash
docker compose up -d --remove-orphans
# or manually:
docker rm mushy_bridge_1 mushy_openmct_1 mushy_timescale_1 2>/dev/null
```

## Hardcoded Container Name Audit

**Files with v1 container names:** [VERIFIED: grep across all .py, .sh, .js, .ts, .yml, .md files]

| File | Line | v1 Name | Action |
|------|------|---------|--------|
| `docs/OPERATIONS.md` | 19 | `mushy_openmct_1` | Update to `mushy-openmct-1` |
| `docs/OPERATIONS.md` | 20 | `mushy_bridge_1` | Update to `mushy-bridge-1` |
| `docs/OPERATIONS.md` | 137 | `mushy_openmct_1`, `mushy_bridge_1` | Update both |
| `docs/pi-setup/tailscale-setup.md` | 94 | `mushy_bridge_1` | Update to `mushy-bridge-1` |

**Files with NO container name references (confirmed clean):**
- `src/mission-control/bridge/src/index.js` — uses `localhost` for DB, not container names
- `scripts/pi-deploy/deploy.sh` — no docker references
- `scripts/workstation-setup/install-ros2-jazzy.sh` — no mushy container references
- All ROS2 Python packages in `src/chambers/` — no docker references

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `docker-compose` (Python standalone binary) | `docker compose` (Go CLI plugin) | Compose v2 GA ~2022; v1 EOL Jan 2024 | Faster, actively maintained, DNS-valid container names |
| `version:` field required in compose YAML | `version:` field deprecated/removed | Compose v2 spec | Remove the field; v2 determines feature availability from Docker Engine version |

**Deprecated/outdated:**
- docker-compose v1: EOL since January 2024. [CITED: docker.com/blog/announcing-compose-v2-general-availability]
- `version: '3.8'` at top of compose files: deprecated in v2 spec, produces warnings.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | farmos and sombrero projects on this host have no shell scripts calling `docker-compose` directly | Runtime State Inventory | Low — even if they do, those projects still work; they just get v1 behavior until their operators migrate |
| A2 | Docker Engine 28.2.2 discovers plugins from `/usr/libexec/docker/cli-plugins/` without additional config | Architecture Patterns | Medium — if not discovered, `docker compose` would still say "not installed"; would need to add to PATH or symlink |

**Note on A2:** Docker's official CLI plugin discovery path includes `/usr/libexec/docker/cli-plugins` for system-wide installs. The package installs there. This is the expected behavior for Ubuntu. [CITED: docs.docker.com/compose/install/linux]

## Open Questions

1. **elder-plops working directory when running compose**
   - What we know: The compose files are at `/mnt/slime-kingdom/opt/mushy/` — the project name inferred from the directory is `mushy` (matching the running containers)
   - What's unclear: Confirm this is the working directory used in practice (e.g., in cron, systemd, or shell aliases)
   - Recommendation: Verify with `docker inspect mushy_bridge_1 | grep working_dir` — already confirmed: `"com.docker.compose.project.working_dir": "/mnt/slime-kingdom/opt/mushy"`

2. **Does elder-plops use docker compose commands in any aliases or systemd units?**
   - What we know: No systemd units in this repo reference docker-compose; the Mission Control stack is manually started
   - What's unclear: Whether there are system-level aliases or cron jobs not in this repo
   - Recommendation: Run `grep -r docker-compose /etc/systemd/ /etc/cron* ~/.bashrc ~/.zshrc 2>/dev/null` before cutting over

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| docker-compose-v2 (apt) | INFRA-01 | In apt cache | 2.40.3 | — |
| docker-compose v1 (to remove) | n/a | ✓ installed | 1.29.2 | — |
| Docker Engine | All services | ✓ | 28.2.2 | — |
| `.env` at repo root | Bridge + timescale | ✓ | — | — |
| `timescale-data` volume | TimescaleDB persistence | ✓ (active) | — | — |
| CycloneDDS config | bridge Tailscale routing | ✓ `/home/santi/.config/cyclonedds-tailscale.xml` | — | — |

**Missing dependencies with no fallback:** None.

**Note on elder-plops as dev+prod:** All changes take effect immediately in production. There is no staging environment. The brief downtime during `docker compose up -d` (containers stopping and restarting) is the production cutover.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Manual smoke test (no automated tests for compose infrastructure) |
| Config file | none |
| Quick run command | `docker compose ps && curl -s -o /dev/null -w "%{http_code}" http://localhost:8080` |
| Full suite command | Manual UAT: open Mission Control in browser, verify live telemetry |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | `docker compose version` prints v2.x | smoke | `docker compose version \| grep "^Docker Compose version v2"` | ❌ Wave 0 (one-liner, no file needed) |
| INFRA-01 | `docker-compose` v1 binary no longer active | smoke | `! which docker-compose` | ❌ Wave 0 |
| INFRA-02 | All 3 services running under v2 | smoke | `docker compose ps --format json \| python3 -c "import sys,json; data=json.load(sys.stdin); ..."` | ❌ Wave 0 |
| INFRA-02 | TimescaleDB data intact | integration | `docker compose exec timescale psql -U postgres -c "SELECT count(*) FROM telemetry;"` (or equivalent) | ❌ Wave 0 |
| INFRA-03 | No v1 underscore names in `docker ps` output | smoke | `! docker ps --format "{{.Names}}" \| grep "mushy_"` | ❌ Wave 0 |
| INFRA-03 | Mission Control shows live telemetry | e2e / manual | Open browser to http://localhost:8080 | manual-only |

### Sampling Rate
- **Per task:** Run the relevant smoke command from the task's verification step
- **Phase gate:** All 3 services healthy + live telemetry confirmed in browser before `/gsd:verify-work`

### Wave 0 Gaps
- No test files needed — all validations are CLI one-liners run interactively during task execution
- No test framework install required

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | no | — |
| V6 Cryptography | no | — |

This phase is a host-level tooling upgrade. No new network endpoints, authentication surfaces, or data processing paths are introduced. The security posture is unchanged.

**Existing controls preserved:**
- TimescaleDB bound to `127.0.0.1:5432` (not exposed to LAN) — unchanged
- Bridge uses host networking with CycloneDDS Tailscale config — unchanged
- `TIMESCALE_PASSWORD` sourced from `.env` (gitignored) — unchanged

## Sources

### Primary (HIGH confidence)
- [VERIFIED: dpkg-deb -c on docker-compose-v2_2.40.3 deb] — confirmed binary installs to `/usr/libexec/docker/cli-plugins/docker-compose`
- [VERIFIED: apt-cache show docker-compose-v2] — version 2.40.3, Provides: docker-compose, no Conflicts
- [VERIFIED: apt-get install -s docker-compose-v2] — does not remove docker-compose v1
- [VERIFIED: docker-compose version on elder-plops] — 1.29.2 currently installed
- [VERIFIED: docker compose version on elder-plops] — plugin NOT installed (yet)
- [VERIFIED: grep across all source files] — only docs reference v1 container names
- [VERIFIED: docker inspect mushy_bridge_1] — project working dir confirmed at `/mnt/slime-kingdom/opt/mushy`, project name `mushy`
- [VERIFIED: docker ps -a] — current running containers use v1 underscore naming

### Secondary (MEDIUM confidence)
- [CITED: liudonghua123.github.io/docker-docs/compose/migrate] — v1→v2 migration differences, container naming change, --compatibility flag

### Tertiary (LOW confidence)
- [ASSUMED] Docker Engine 28.2.2 discovers `/usr/libexec/docker/cli-plugins/` automatically (standard behavior, not verified in this session by actually running `docker compose` post-install)

## Metadata

**Confidence breakdown:**
- Package availability: HIGH — verified via apt-cache and deb inspection on target host
- Container naming change: HIGH — verified from official migration docs and confirmed against running containers
- Hardcoded name audit: HIGH — comprehensive grep across all source file types confirmed
- Architecture patterns: HIGH — verified by inspecting actual binary install path from deb
- Pitfalls: HIGH — derived from direct system inspection and migration docs

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (stable tooling; package version may update but migration steps remain identical)
