---
phase: 56-foundation
verified: 2026-06-15T17:00:00Z
reverified: 2026-06-21T15:05:00Z
status: passed
score: 5/5
overrides_applied: 0
human_verification:
  - test: "Run `docker compose up alerter-py` on elder-plops and confirm the container logs 'boot complete in' within 5s with the live Node alerter still responding"
    expected: "alerter-py container starts, logs 'boot complete in X.XXs', stays running; the existing Node alerter service continues processing normally"
    why_human: "Requires the real host's compose environment, host-networking, shared TimescaleDB reachability, and secrets.env file -- cannot be verified from the verifier environment without starting infrastructure"
    result: "DONE 2026-06-21 on elder-plops. First build FAILED — Dockerfile ran `uv sync` before copying farm_agent/, so hatchling had no source to build the project wheel (a real bug, never previously caught because host-uv tests and `docker compose config` never exercise the image build). Fixed in commit 13e71e9 (--no-install-project deps layer, then post-COPY sync). Rebuild succeeded; alerter-py logged 'boot complete in 0.07s', migrations ran, no secrets in log; mushy-alerter-1 (Node) stayed healthy throughout; container stopped cleanly (exit 0)."
gaps: []
resolved_gaps:
  - truth: "pytest tests/ passes (Success Criterion 3)"
    status: resolved
    reason: "ROADMAP SC3 reads `uv run pytest tests/` (not `tests/unit/`); the original 'partial' was a wording mismatch against a stale literal. Re-run 2026-06-21: `uv run pytest tests/` = 127 passed, 10 skipped (DB-gated), 0 failed. No source-of-truth change needed; ROADMAP already correct."
---

# Phase 56: Foundation Verification Report

**Phase Goal:** The Python package boots as a testable asyncio daemon with layered config, async DB pool, idempotent migrations, and a statically-enforced Foray boundary -- before any Signal or LLM code runs.
**Verified:** 2026-06-15T17:00:00Z
**Re-verified:** 2026-06-21T15:05:00Z
**Status:** passed (5/5)
**Re-verification:** Yes -- 2026-06-21 closed the human-verification boot check + SC3 wording gap (see addendum below)

> ## Re-Verification Addendum — 2026-06-21
>
> Both outstanding items from the 2026-06-15 `human_needed` report are now closed.
> The original report below is preserved verbatim as the historical record.
>
> **1. Human boot check (truth #1) — PASSED, and found+fixed a real bug.**
> Running the deferred check on elder-plops surfaced that `alerter-py` had never
> actually built in Docker: the Dockerfile ran `uv sync` before `COPY farm_agent/`,
> so hatchling had no source to build the project wheel and the build failed. This
> was invisible to the 2026-06-15 verification because the automated proxy
> (`test_boot_completes_in_5s`) runs via host `uv`, and `docker compose config`
> validates YAML without building. Fixed in **commit 13e71e9** (split into a
> `--no-install-project` deps layer, then a post-`COPY` `uv sync`). Rebuild
> succeeded; the container logged **`boot complete in 0.07s`**, migrations ran, no
> secrets appeared in the log, `mushy-alerter-1` (Node) stayed healthy throughout,
> and the container stopped cleanly (exit 0). Reinforces the standing lesson that
> host-green ≠ container-boots.
>
> **2. SC3 `tests/unit/` gap — moot.** ROADMAP SC3 reads `uv run pytest tests/`
> (not `tests/unit/`); the original "partial" was a mismatch against a stale
> literal. Re-run 2026-06-21: `uv run pytest tests/` = **127 passed, 10 skipped
> (DB-gated), 0 failed**. No source-of-truth change required.
>
> **Score: 4/5 → 5/5. Status: human_needed → passed.**

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `uv sync && docker compose up alerter-py` starts without error; daemon logs "boot complete" within 5s | VERIFIED (automated proxy) / HUMAN (full host) | `test_boot_completes_in_5s` PASSES with ephemeral test DB (42/42 suite green); `docker compose config` validates; full host boot deferred to human check below |
| 2 | `run_migrations()` against blank test DB produces all expected tables with correct column types; re-running is a no-op | VERIFIED | `test_migrations_create_expected_tables` PASSES: signal_capture/signal_draft/signal_outbound + pgcrypto + v_llm_cost_daily confirmed; column types spot-checked (signal_capture.id=text, signal_draft.id=text, signal_outbound.id=uuid, related_capture_id=text, signal_msg_ts=bigint); `test_migrations_idempotent` PASSES (second run is no-op) |
| 3 | `pytest tests/unit/` passes; structural diff of pydantic schema vs Node fixture shows zero discrepancies; `extra='forbid'` on every nested model | PARTIAL | All 4 parity tests PASS (test_submission_schema_matches_fixture, test_seeding_fragment_parity, test_all_models_forbid_extra, test_observation_requires_state_or_notes); 15 `extra='forbid'` declarations verified; fixture byte-unchanged in git. BUT `pytest tests/unit/` exits code 4 -- tests/unit/ dir does not exist; tests land in tests/ directly (Plan 01 set testpaths=["tests"]) |
| 4 | CI fails if any non-`chamber/` package imports from chamber (Foray seam enforced statically) | VERIFIED | test_no_chamber_imports_in_foray PASSES; test_seam_trips_on_violation PASSES (armed, not vacuous); test_seam_trips_on_bare_import_form PASSES. Note: ROADMAP SC4 cites `from alerter.chamber` (old Node namespace); implementation correctly guards `from farm_agent.chamber` -- deviation documented in test file comment |
| 5 | No business module imports os.environ directly; all config flows through TenantConfig | VERIFIED | test_no_other_module_reads_os_environ PASSES; grep confirms os.environ appears only in tenancy/tenant.py and boot.py; boot.py passes `os.environ` as a dict argument to `load_config()` rather than reading individual keys (correct adapter pattern; test explicitly excludes both files) |

**Score:** 4/5 truths fully verified; 1 partial (naming deviation in tests directory structure)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/farm-agent/pyproject.toml` | uv project + asyncio_mode=auto | VERIFIED | asyncio_mode="auto", testpaths=["tests"], Python 3.12 |
| `src/farm-agent/Dockerfile` | python:3.12-slim, uv sync --no-dev | VERIFIED | FROM python:3.12-slim-bookworm; CMD uv run python -m farm_agent |
| `src/farm-agent/uv.lock` | Committed lock | VERIFIED | Committed at commit 07513cb |
| `src/farm-agent/farm_agent/tenancy/tenant.py` | Frozen TenantConfig dataclass, sole os.environ reader | VERIFIED | 34-field frozen dataclass; _must_env for secrets; layered YAML+env+default; path-traversal guard |
| `src/farm-agent/farm_agent/persistence/pool.py` | psycopg3 AsyncConnectionPool, open=False+await, UTC | VERIFIED | build_pool() uses open=False; options=-c timezone=UTC; host:port split for test ports |
| `src/farm-agent/farm_agent/persistence/migrations.py` | Idempotent additive-only migrations, 3 tables | VERIFIED | signal_capture + signal_draft + signal_outbound + commit cols; all IF NOT EXISTS; two whitelisted text->text ALTERs |
| `src/farm-agent/farm_agent/extraction/schemas/submission.py` | SUBMISSION_JSON_SCHEMA exported, all models extra='forbid' | VERIFIED | 9 schema modules; 15 extra='forbid' declarations; SUBMISSION_JSON_SCHEMA exported |
| `src/farm-agent/tests/fixtures/submission_json_schema.json` | Committed Node zod fixture, byte-unchanged | VERIFIED | Committed dc2e3aa; git diff HEAD returns empty; 19431 chars |
| `src/farm-agent/tests/test_schema_parity.py` | Parity gate with normalize_schema | VERIFIED | 4 tests all PASS; normalize_schema handles $defs/$ref/title/description/required-sort |
| `src/farm-agent/tests/test_foray_seam.py` | 3 armed grep tests | VERIFIED | 3 tests PASS; armed-not-vacuous proven by synthetic violation |
| `src/farm-agent/farm_agent/boot.py` | Single asyncio entrypoint, "boot complete" log | VERIFIED | Sole cross-package importer; SIGTERM/SIGINT idle loop; logs "boot complete in %.2fs"; config never logged |
| `src/farm-agent/farm_agent/__main__.py` | asyncio.run(main()) entry | VERIFIED | Single line: asyncio.run(main()) |
| `docker-compose.override.yml` alerter-py block | New service, coexists with Node alerter | VERIFIED | env_file bare string form; mirrors alerter: env vars; networks signal-net+default; live Node alerter block untouched |
| `src/farm-agent/.lint-imports` | import-linter contract for Phase 63 | VERIFIED | Committed; not active yet (no chamber/ in Phase 56) |
| `tests/unit/` directory | ROADMAP SC3 expects this path | MISSING | Plan 01 used testpaths=["tests"]; all tests in tests/; pytest tests/unit/ exits 4 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| boot.py | tenancy.tenant.load | import + load_config(os.environ) | VERIFIED | Line 29+49 |
| boot.py | persistence.pool.build_pool | import + await build_pool(config) | VERIFIED | Line 30+53 |
| boot.py | persistence.migrations.run_migrations | import + await run_migrations(pool) | VERIFIED | Line 31+55 |
| TenantConfig | psycopg3 AsyncConnectionPool | build_pool(config) extracts timescale_host/db/user/password | VERIFIED | pool.py lines 14-46 |
| AsyncConnectionPool | run_migrations | pool.connection() -> conn.execute() DDL | VERIFIED | migrations.py run_migrations() |
| SUBMISSION_JSON_SCHEMA | submission_json_schema.json fixture | normalize_schema() structural diff in test_schema_parity.py | VERIFIED | 4 parity tests green |
| test_foray_seam grep gate | farm_agent/{tenancy,persistence,extraction}/ | subprocess grep -rE "from farm_agent.chamber" | VERIFIED | Armed and passing |

### Data-Flow Trace (Level 4)

Not applicable -- Phase 56 is a foundation phase with no user-facing data rendering; all outputs are log lines and DB schema. The boot sequence is verified via test_boot_completes_in_5s.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite (42 tests) with live test DB | `pytest -v` with postgres:14 on :5434 | 42 passed in 10.31s | PASS |
| Migrations idempotent (second run) | test_migrations_idempotent with DB | PASSED | PASS |
| All 3 live tables + correct column types | test_migrations_create_expected_tables | PASSED | PASS |
| Additive-only guard (no DROP/TRUNCATE) | test_migrations_additive_only (DB-independent) | PASSED | PASS |
| Boot daemon reaches idle phase within 5s | test_boot_completes_in_5s with test DB | PASSED | PASS |
| No secrets logged at boot | test_boot_logs_no_secrets | PASSED | PASS |
| os.environ only in tenant.py + boot.py | test_no_other_module_reads_os_environ (grep) | PASSED | PASS |
| Foray seam catches from + import forms | test_seam_trips_on_violation + bare form | PASSED | PASS |
| pytest tests/unit/ (SC3 literal) | `pytest tests/unit/` | exit 4, no tests ran | FAIL |
| `docker compose config` validates | `docker compose config --quiet` | exit 0 | PASS |

### Probe Execution

No probe scripts declared for this phase.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| FND-01 | Python package boots as asyncio daemon; uv sync + Docker | VERIFIED | boot.py wired; test_boot_completes_in_5s PASSES; Dockerfile verified; compose service added |
| FND-02 | TenantConfig layered YAML+env; no direct os.environ in business modules; secrets env-only | VERIFIED | 28-test suite in test_tenancy.py; grep gate test_no_other_module_reads_os_environ PASSES |
| FND-03 | psycopg3 async pool + idempotent migrations; additive-only schema | VERIFIED | 4 migration tests PASS (3 DB-dependent + 1 source guard); column types verified |
| FND-04 | pydantic JSON Schema structurally matches zod fixture; extra='forbid' on all nested models | VERIFIED | test_submission_schema_matches_fixture PASSES; test_all_models_forbid_extra PASSES; 15 declarations; fixture byte-unchanged |
| FND-05 | Foray seam: non-chamber packages cannot import from chamber/ | VERIFIED | 3 tests PASS; .lint-imports contract committed for Phase 63 |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| None in src/farm-agent/farm_agent/ | -- | -- | No debt markers, no stubs, no hardcoded empty data in rendering paths found in production code |

All anti-pattern grep results (TBD/FIXME/XXX) are inside `.venv/` (third-party packages) -- not in phase-authored code.

**Scope check:** No signal-cli, LLM, farmOS client, or chamber implementation leaked into Phase 56 code. The only references to farmos/anthropic in farm_agent/ are TenantConfig field names (config holder), not implementation code. migrations.py references `llm_session_tag` and `llm_reply` as DDL column names ported verbatim from capture-db.js -- not LLM client code.

### Human Verification Required

#### 1. Full alerter-py boot on elder-plops host

**Test:** On elder-plops, run `docker compose up alerter-py` (or `docker compose up alerter-py --build` for first-time image build) and watch the container logs.
**Expected:** Within 5 seconds of the container starting, a log line matching `"boot complete in X.XXs"` appears; the container remains running (not crash-looping); `docker compose logs alerter` confirms the live Node alerter is still processing normally.
**Why human:** Requires the real host's compose environment with `tenants/mossrock/secrets.env` present, host-networking to the shared TimescaleDB, and the live Node alerter running -- none of these can be safely reproduced from a test environment. The automated proxy `test_boot_completes_in_5s` (which PASSES) validates the same code path against an ephemeral Postgres, providing high confidence. This check is for production readiness only.

### Gaps Summary

One gap blocks strict SC3 literal compliance: `tests/unit/` does not exist. The command `pytest tests/unit/` exits 4. All 42 tests (which cover every FND-01 through FND-05 requirement) pass when run as `pytest tests/` or `pytest`. The deviation was introduced silently in Plan 01: the PLAN explicitly set `testpaths = ["tests"]` in pyproject.toml and no PLAN/SUMMARY noted the divergence from ROADMAP SC3.

**Remediation options (choose one):**
1. Create `src/farm-agent/tests/unit/` as a directory and move the DB-independent tests there (rename: test_foray_seam.py, test_schema_parity.py, test_tenancy.py, test_scaffold.py -> tests/unit/; keep DB-dependent tests in tests/ or tests/integration/). This matches the ROADMAP SC3 wording exactly.
2. Accept the flat `tests/` structure (the VALIDATION.md spec predated the final layout) and update ROADMAP SC3 to say `pytest tests/` or `pytest`. This is a 1-line doc fix.

Option 2 is lower risk (no test file moves, no import path changes).

**SC4 namespace note:** ROADMAP SC4 says `from alerter.chamber` (old Node namespace). The implementation correctly uses `from farm_agent.chamber`. The test documents this divergence explicitly. This is not a gap -- the guard enforces the correct Python package namespace.

---

_Verified: 2026-06-15T17:00:00Z_
_Verifier: Claude (gsd-verifier)_
