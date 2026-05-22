---
phase: 44-event-gate-durable-signal-outbound-tenant-aware
plan: 06
subsystem: alerter / deploy
tags: [tenant-config, secrets-handling, docker-compose, foray-alpha]
provides:
  - tenants/mossrock/{config.yaml, strains.yaml, secrets.env.example}
  - tenants/example/config.yaml
  - layered config.js loader (tenant YAML -> env -> default)
  - docker-compose env_file path for alerter secrets
requires:
  - Plan 44-00 (gitignore rule for tenants/*/secrets.env, yaml dep)
affects:
  - downstream Plan 44-02 (signal_outbound consumes config.tenantId)
  - downstream Plan 44-04 (event-gate consumes config.eventGateConvoMode + config.anthropicApiKey)
key-files:
  created:
    - tenants/mossrock/config.yaml
    - tenants/mossrock/strains.yaml
    - tenants/mossrock/secrets.env.example
    - tenants/example/config.yaml
  modified:
    - src/agents/alerter/src/config.js
    - src/agents/alerter/test/config.test.js
    - docker-compose.override.yml
decisions:
  - "Path B (env_file: tenants/mossrock/secrets.env) chosen for alerter; root .env retains shared secrets for bridge + farmos-agent until v1.9 cleanup"
  - "env_file uses required:false so docker compose config parses on fresh clones; alerter fail-fasts via mustEnv() if secrets are absent at boot"
  - "Removed three explicit environment: lines (ANTHROPIC_API_KEY, FARMOS_PASSWORD, SIGNAL_SENDER) from alerter block — compose environment: shadows env_file: so they had to go for tenant secrets to win"
metrics:
  duration_min: ~25 (Task 6.3 only; Tasks 6.1 + 6.2 were prior sessions)
  tasks_completed: 3/3
  completed: 2026-05-22
---

# Phase 44 Plan 06: Tenant Config Tree + Alerter Secrets Migration Summary

One-liner: shipped the `tenants/<tenant_id>/` config tree, refactored
`config.js` to a layered tenant-YAML -> env -> default loader, and migrated the
alerter container's three secrets (`ANTHROPIC_API_KEY`, `FARMOS_PASSWORD`,
`SIGNAL_SENDER`) onto a gitignored `tenants/mossrock/secrets.env` consumed via
docker-compose `env_file`.

## Tasks

| Task | Commit | Description |
|------|--------|-------------|
| 6.1 | `7fcaf82` | Seeded tenants/mossrock/{config.yaml, strains.yaml, secrets.env.example} + tenants/example/config.yaml |
| 6.2 | `c4518d4` | Refactored config.js to layered tenant-aware loader (pick + mustEnv); 9 behavior tests + B4 field-surface test |
| 6.3 | `9de16b1` | docker-compose.override.yml: env_file: tenants/mossrock/secrets.env on alerter; removed three shadowing environment: lines |

## Secrets Deploy Path (Task 6.3 — operator decision)

**Chosen path: B** — promote secrets to `tenants/mossrock/secrets.env`,
consumed via docker-compose `env_file` directive on the alerter service.

### Implementation

`docker-compose.override.yml` alerter block now declares:

```yaml
env_file:
  - path: tenants/mossrock/secrets.env
    required: false
```

Three explicit `environment:` lines were removed from the alerter block:

- `- SIGNAL_SENDER=${SIGNAL_SENDER}` (line 75, removed — alerter now reads from env_file)
- `- ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}` (line 119, removed)
- `- FARMOS_PASSWORD=${FARMOS_PASSWORD}` (line 133, removed)

This removal was required: docker-compose `environment:` mappings override
`env_file:` values, so leaving the explicit lines would have shadowed the
tenant-scoped secrets with whatever happened to be (or not be) in repo-root
`.env`. See project memory `[[feedback_compose_env_passthrough_not_envfile]]`
for the canonical statement of this gotcha.

### What stays in root .env

`SIGNAL_SENDER` and `FARMOS_PASSWORD` remain in repo-root `.env` because they
are still consumed by **other** services:

- `bridge` reads `SIGNAL_SENDER` for `/heartbeat-alert` dispatch
  (docker-compose.override.yml:19)
- `farmos-agent` reads `FARMOS_PASSWORD` (docker-compose.yml:57)

`ANTHROPIC_API_KEY` was alerter-only, so it can safely be removed from
repo-root `.env` after the operator provisions `tenants/mossrock/secrets.env`
on elder-plops. We did **not** mutate the live `.env` in this plan — operator
chooses when to redact.

### Operator deploy steps (elder-plops)

1. `scp tenants/mossrock/secrets.env.example ubuntu@elder-plops:/mnt/slime-kingdom/opt/mushy/tenants/mossrock/secrets.env` (or create via heredoc on the host)
2. Edit the file in place, filling in the three values (existing values are in `.env` today)
3. `chmod 600 tenants/mossrock/secrets.env`
4. `docker compose up -d alerter` to pick up the new env_file
5. (Optional, after validation) redact `ANTHROPIC_API_KEY=` from repo-root `.env` — alerter is the only consumer; bridge/farmos-agent never read it

### Functional validation performed

With a populated `tenants/mossrock/secrets.env` placed locally (then deleted),
`docker compose config` resolved:

```
alerter:
  ANTHROPIC_API_KEY: test-anthropic        (from secrets.env)
  FARMOS_PASSWORD:   test-farmos           (from secrets.env)
  SIGNAL_SENDER:     +10000000000          (from secrets.env)
bridge:
  SIGNAL_SENDER:     +59891840205          (from root .env, unchanged)
farmos-agent:
  FARMOS_PASSWORD:   ...                   (from root .env, unchanged)
```

The path B wiring works end-to-end without breaking bridge or farmos-agent.

### Pre-flight gate (Task 6.3 — passed)

| Check | Result |
|-------|--------|
| `git log --all --full-history -- "tenants/mossrock/secrets.env"` | empty (file never tracked) |
| `git check-ignore tenants/mossrock/secrets.env` | exit 0 (ignored by Plan-00 rule) |
| `git check-ignore tenants/mossrock/secrets.env.example` | exit 1 (NOT ignored — template is committed) |
| `docker compose config --quiet` (no local secrets.env present) | parses cleanly via `required: false` |

## v1.9 Cleanup Carryovers

Tracked deferrals; do **not** treat as bugs:

1. **Bridge + farmos-agent secrets still in root .env.** `SIGNAL_SENDER` and
   `FARMOS_PASSWORD` are duplicated between root `.env` (for bridge +
   farmos-agent) and `tenants/mossrock/secrets.env` (for alerter). The
   alerter's tenant-scoped copy is the authoritative path forward; bridge +
   farmos-agent should migrate to per-tenant env_file in v1.9 when those
   services join the Foray α tenant boundary. Until then, both files must
   carry the same value for consistency.

2. **`process.env.X` reads outside config.js (Foray v0.1 carryover).**
   Plan 6.2's acceptance criterion required `config.js` be the only file in
   `src/agents/alerter/src/` that reads `process.env` directly. Any
   pre-existing exceptions (e.g. dotenv at boot in `index.js`, or
   environment reads in capture/transcribe siblings) remain Foray v0.1
   carryover and are tracked for the v1.9 sweep that finishes the tenant
   boundary.

3. **`ANTHROPIC_API_KEY` redaction from root .env.** Operator-discretionary
   cleanup. The key is alerter-only; once the new env_file path is validated
   in production, the root `.env` line can be removed without breaking any
   other service. Deferred to operator's next deploy window.

## Path-Traversal Sanity Check

Implemented in `config.js` `loadTenantFile()` per Plan 6.2 (commit `c4518d4`)
and threat T-44-06-02: the resolved tenant path is verified to stay under the
`tenants/` base directory before YAML parsing. Path traversal via
`TENANT_ID='../etc/passwd'` is mitigated at the file-read boundary.

## Deviations from Plan

None. Plan 6.3 executed exactly as drafted in `44-secrets-deploy-confirmation.md`
once the operator selected path B.

## Self-Check: PASSED

- `tenants/mossrock/config.yaml`: FOUND
- `tenants/mossrock/strains.yaml`: FOUND
- `tenants/mossrock/secrets.env.example`: FOUND
- `tenants/example/config.yaml`: FOUND
- `src/agents/alerter/src/config.js`: FOUND (modified)
- `docker-compose.override.yml`: FOUND (modified)
- commit `7fcaf82` (Task 6.1): FOUND
- commit `c4518d4` (Task 6.2): FOUND
- commit `9de16b1` (Task 6.3): FOUND
- `docker compose config --quiet`: exit 0
- `git log --all --full-history -- "tenants/mossrock/secrets.env"`: empty
