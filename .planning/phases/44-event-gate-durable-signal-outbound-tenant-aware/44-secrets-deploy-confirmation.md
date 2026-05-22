# 44-06 Task 6.3 — Operator checkpoint: secrets.env deploy path

**Status:** AWAITING OPERATOR CONFIRMATION
**Created:** 2026-05-22
**Blocks:** Plan 44-06 final completion + downstream Plans 44-02/44-04 (which consume `config.anthropicApiKey` + `config.signalSender` via the layered loader).

## What was built (Tasks 6.1 + 6.2 — committed)

| Task | Commit | Files |
|------|--------|-------|
| 6.1  | `7fcaf82` | tenants/mossrock/{config.yaml, strains.yaml, secrets.env.example}, tenants/example/config.yaml |
| 6.2  | `c4518d4` | src/agents/alerter/src/config.js, src/agents/alerter/test/config.test.js |

- `tenants/mossrock/config.yaml` committed; **no secrets** (verified: `grep -E "PASSWORD|API_KEY"` returns nothing).
- `tenants/mossrock/secrets.env.example` committed as a template listing the three required secrets (`ANTHROPIC_API_KEY`, `FARMOS_PASSWORD`, `SIGNAL_SENDER`) without values.
- `tenants/mossrock/secrets.env` is gitignored (Plan-00 rule `tenants/*/secrets.env`); verified via `git check-ignore` (exit 0).
- `tenants/mossrock/secrets.env.example` is **NOT** gitignored (only `secrets.env` is); verified via `git check-ignore` (exit 1).
- `config.js` refactored to layered loader: tenant YAML → env → default. Secrets enforced via `mustEnv()` (env-only). All 44 config tests green; full alerter suite 744 passed / 33 skipped.

## What operator must confirm

### 1. Secrets are not in git history

Run on operator's machine:

```bash
git log --all --full-history -- "tenants/mossrock/secrets.env"
git log --all --full-history -- "tenants/*/secrets.env"
```

**Expected:** empty output. If anything prints, secrets leaked — STOP and rotate the leaked secret (ANTHROPIC_API_KEY / FARMOS_PASSWORD / SIGNAL_SENDER) before continuing.

### 2. Production deploy path for `tenants/mossrock/secrets.env`

The alerter container must see the three secrets at boot. The layered loader uses `mustEnv(env, 'X')` for `ANTHROPIC_API_KEY`, `FARMOS_PASSWORD`, `SIGNAL_SENDER` — these must arrive as environment variables in the alerter process, **OR** be exported from a sourced `secrets.env` file before the alerter container starts.

Three candidate deploy paths (operator picks one):

| Option | Where secrets live in production | How alerter sees them | Action needed |
|--------|----------------------------------|-----------------------|---------------|
| **A** — keep current `.env` (legacy, NO-OP) | `/mnt/slime-kingdom/opt/mushy/.env` on elder-plops (already deployed) | docker-compose.override.yml `${VAR}` interpolation reads compose-level `.env` → forwarded to alerter env block | None. Phase 44 layered loader picks up env-arrived secrets exactly as before. `tenants/mossrock/secrets.env` is documentation/template only this phase. |
| **B** — promote to `tenants/mossrock/secrets.env` (clean Foray α) | `tenants/mossrock/secrets.env` on elder-plops; sourced by deploy script or compose `env_file` | docker-compose.override.yml `env_file: [tenants/mossrock/secrets.env]` on the alerter service | Add `env_file:` to override.yml alerter service AND `scp tenants/mossrock/secrets.env` to elder-plops AND remove the three keys from the root `.env`. |
| **C** — CI-driven (GitHub Actions secret → file on deploy) | GitHub repository secrets; runner writes `tenants/mossrock/secrets.env` on the elder-plops host during deploy | same as B (env_file mount) | Requires a deploy pipeline. Out of scope for current operator workflow (manual elder-plops compose). |

**Recommendation:** Option A for this phase (zero deploy risk; the existing `.env` mechanism keeps working as a fallback per RESEARCH "Runtime State Inventory"). Defer Option B to v1.9 when the CI deploy pipeline is in scope.

### 3. Resume signal

Reply in the planning chat with **one** of:

- `secrets path confirmed: A` — operator keeps the existing `.env` on elder-plops; no compose changes; tenants/mossrock/secrets.env stays a template only.
- `secrets path confirmed: B` — operator wants `env_file` migration this phase; attach the proposed `docker-compose.override.yml` diff or request executor to draft it.
- `secrets path confirmed: C` — operator wants CI deploy path (out of scope; file a v1.9 backlog item).
- `abort` — stop the phase; do not advance to Plan 44-02.

Once a reply is received, the executor resumes and writes the chosen path into `44-06-SUMMARY.md` (under "Secrets Deploy Path") and the plan is marked complete.
