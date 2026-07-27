# Phase 56: Foundation - Research

**Researched:** 2026-06-15
**Domain:** Python asyncio daemon skeleton, layered config, psycopg3 async pool, idempotent migrations, zod-to-pydantic JSON-Schema parity gate, Foray CI seam
**Confidence:** HIGH (derived from live Node source + PyPI + active codebase inspection)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01: psycopg3** is the Postgres driver (not asyncpg). `psycopg_pool.AsyncConnectionPool`; `[binary]` extra.
- **D-02: Migration approach** -- idempotent `CREATE TABLE IF NOT EXISTS` on boot, same as Node alerter. NO alembic/yoyo. Additive-only: no DROP/ALTER that breaks the live Node schema.
- **D-03: Repo location + package names** -- `src/farm-agent/`. Foray packages: `signal_io/`, `extraction/`, `confirm/`, `farmos_client/`, `capture/`, `persistence/`, `tenancy/`, `llm/`. Mushy-private: `chamber/`. `boot.py` is the only module allowed to import across all packages.
- **D-04: Schema-parity gate** -- commit Node's emitted `SUBMISSION_JSON_SCHEMA` as a fixture file; assert structural equality against pydantic's `model_json_schema()` in a pytest. `extra='forbid'` on every nested pydantic model; cross-field validators as `model_validator(mode='after')`.

### Claude's Discretion
- Final names within `src/farm-agent/` if a cleaner split emerges, but `chamber/` MUST be the sole private package.
- No heavyweight migration tool unless planning finds a concrete need.

### Deferred Ideas (OUT OF SCOPE)
- Generalizing origin guard into a full dev/prod origin split (v1.13 candidate).
- Signal I/O, extraction, confirm, farmOS writes, chamber alerting (Phases 57+).
- No business behavior in this phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FND-01 | Python package skeleton boots as a single asyncio daemon (`boot.py` is the only module importing across all packages); `uv sync` + `python:3.12-slim` Docker image builds and runs under compose. | uv-in-Docker pattern verified; boot-in-5s testable via asyncio startup probe. |
| FND-02 | `tenancy/TenantConfig` loads layered YAML+env config; no business module reads `env` directly; secrets stay env-only. | Node `config.js` fully read; layer order and secret-vs-non-secret split documented. |
| FND-03 | `persistence/` provides shared psycopg3 async pool + idempotent migrations covering existing tables; schema additions are additive-only. | All four DDL files read; complete table/column/index inventory documented below. |
| FND-04 | Pydantic v2 draft schemas emit JSON Schema that structurally matches Node's zod-derived schema; structural-diff pytest passes as ship gate before any LLM call. | Actual `SUBMISSION_JSON_SCHEMA` generated and inspected live; structural risks documented. |
| FND-05 | Foray seam is statically enforced -- a CI check fails the build if any non-`chamber` package imports from `chamber/`. | import-linter 2.11 approach and grep fallback both specified. |
</phase_requirements>

---

## Summary

Phase 56 builds the boot-able skeleton before any Signal or LLM code exists. Its five deliverables are independent enough to be built in order (FND-01 first, FND-03 depends on FND-02 for config, FND-04 depends on FND-03 existing, FND-05 is orthogonal and can run last).

The critical deliverable is FND-04: the JSON-Schema parity gate. It is the structural defense against the zod-to-pydantic schema drift documented in PITFALLS.md as the single highest-risk silent regression. The fixture approach (dump Node's live `SUBMISSION_JSON_SCHEMA` to a committed JSON file, then structurally diff against pydantic's `model_json_schema()` in pytest) is confirmed correct: Node's output has been generated and inspected (see FND-04 section below). The discriminated union shape uses `anyOf` (not `oneOf`), `definitions` (draft-7, not `$defs`), and requires `inlineTopLevelRef` pre-processing before passing to Anthropic. The pydantic equivalent of this transformation is documented below.

The second most important deliverable is FND-03: the live shared TimescaleDB schema is additive and must stay compatible with the running Node alerter until Phase 65 cutover. All four DDL files have been read; the complete column inventory is below. The Python migrations must reproduce the same CREATE TABLE / ADD COLUMN IF NOT EXISTS sequence without issuing any ALTER that the Node stack cannot tolerate.

**Primary recommendation:** Build in order: FND-01 (project layout + Dockerfile) -> FND-02 (TenantConfig) -> FND-03 (pool + migrations) -> FND-04 (schema fixture + parity test) -> FND-05 (CI seam). Each is independently testable and the dependency graph is linear.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Boot / lifecycle | `boot.py` (single entrypoint) | -- | Only module allowed to import across all packages; start/stop of all tasks. |
| Config loading | `tenancy/` | -- | Lowest node in dependency graph; no other imports. Env passthrough for secrets. |
| DB connection pool | `persistence/pool.py` | -- | Single pool shared by all packages via injection (not imported directly). |
| Schema migrations | `persistence/migrations.py` | -- | Runs at boot before any other DB work; additive-only; idempotent. |
| Pydantic schemas | `extraction/schemas/` | -- | JSON Schema exported for Anthropic tool-use AND for the FND-04 parity gate. |
| Foray boundary | CI grep/import-linter | -- | Structural gate; no runtime component needed. |

---

## Standard Stack

### Core (Phase 56 only -- foundation slice)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 | Runtime | `python:3.12-slim-bookworm` Docker base. [VERIFIED: milestone STACK.md] |
| uv | latest | Package/venv management | Deterministic lockfile, fast Docker installs. [VERIFIED: milestone STACK.md] |
| pydantic | 2.13.4 | Schema models + JSON Schema export | `model_json_schema()` replaces `zodToJsonSchema`. `extra='forbid'` replicates `.strict()`. [VERIFIED: milestone STACK.md; PyPI confirmed 2.13.4] |
| psycopg[binary] | 3.3.4 | Postgres async driver | D-01 locked. `[binary]` bundles libpq -- no apt package needed in Docker. [VERIFIED: PyPI JSON API 2026-06-15] |
| psycopg-pool | 3.3.1 | `AsyncConnectionPool` | Separate package; major version must match psycopg. [VERIFIED: PyPI JSON API 2026-06-15] |
| ruamel.yaml | 0.19.1 | Tenant config YAML parsing | Preserves comments on round-trip. [VERIFIED: milestone STACK.md; PyPI confirmed 0.19.1] |

### Dev / Test (Phase 56 scope)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.1.0 | Test runner | Standard. [VERIFIED: milestone STACK.md] |
| pytest-asyncio | 1.4.0 | Async test support | Required for testing asyncio coroutines. Set `asyncio_mode = "auto"`. [VERIFIED: PyPI JSON API 2026-06-15] |
| ruff | 0.15.17 | Linter + formatter | Replaces flake8/isort/black. [VERIFIED: milestone STACK.md] |
| import-linter | 2.11 | Foray boundary enforcement (FND-05) | Contracts-based import checker; published 2026-03-06. [VERIFIED: PyPI JSON API 2026-06-15] |

### Not Needed in Phase 56

| Avoid for Now | Reason |
|---------------|--------|
| anthropic SDK | No LLM calls until Phase 59-60. |
| websockets | No signal-cli / ROS-bridge until Phase 57 / 63. |
| httpx | No farmOS / Whisper calls until Phase 58+. |
| pydantic-settings | Hand-rolled layered loader matches the Node `config.js` pattern exactly and avoids BaseSettings auto-discovery semantics. See FND-02 below. |

**Installation:**
```bash
# In src/farm-agent/
uv add "pydantic>=2.13" "psycopg[binary]>=3.3" "psycopg-pool>=3.3" "ruamel.yaml>=0.19"
uv add --dev "pytest>=9.1" "pytest-asyncio>=1.4" "ruff>=0.15" "import-linter>=2.11"
```

---

## Package Legitimacy Audit

slopcheck was unavailable at research time (pyenv version not installed in this shell). All packages below are tagged `[ASSUMED]` for registry existence purposes, but every package is well-established (psycopg, pydantic, pytest, ruff, ruamel.yaml are industry-standard; import-linter is the canonical Python import-boundary tool). PyPI JSON API confirmed latest versions.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| psycopg | PyPI | 4+ yrs | Very high | github.com/psycopg/psycopg | [ASSUMED] | Approved -- official successor to psycopg2 |
| psycopg-pool | PyPI | 4+ yrs | High | github.com/psycopg/psycopg | [ASSUMED] | Approved -- same org as psycopg |
| pydantic | PyPI | 7+ yrs | Very high | github.com/pydantic/pydantic | [ASSUMED] | Approved |
| ruamel.yaml | PyPI | 10+ yrs | High | sourceforge/ruamel-yaml | [ASSUMED] | Approved |
| pytest | PyPI | 15+ yrs | Very high | github.com/pytest-dev/pytest | [ASSUMED] | Approved |
| pytest-asyncio | PyPI | 8+ yrs | High | github.com/pytest-dev/pytest-asyncio | [ASSUMED] | Approved |
| ruff | PyPI | 3+ yrs | Very high | github.com/astral-sh/ruff | [ASSUMED] | Approved |
| import-linter | PyPI | 5+ yrs | Medium | github.com/seddonym/import-linter | [ASSUMED] | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged [SUS]:** none

*All packages above tagged `[ASSUMED]` -- slopcheck unavailable at research time. Planner should add a `checkpoint:human-verify` before first `uv sync` if desired, but these are well-established packages.*

---

## Architecture Patterns

### System Architecture Diagram

```
                 src/farm-agent/
                      |
              pyproject.toml + uv.lock
                      |
              boot.py  <-- ONLY cross-package importer
               /   |   \
       tenancy/ persistence/ [extraction/] [chamber/]
         |          |
    TenantConfig  AsyncConnectionPool
    (no imports)    + migrations.py
                    + repos/
```

Data flow for Phase 56 (boot only):
```
docker compose up alerter-py
  --> Dockerfile: uv sync --no-dev
  --> CMD: python -m farm_agent  (or: uv run python boot.py)
  --> boot.py:
       1. load TenantConfig(env)
       2. build_pool(config) -> AsyncConnectionPool
       3. run_migrations(pool)   <- additive CREATE TABLE IF NOT EXISTS
       4. structured log: "boot complete"
       5. asyncio.Event().wait()  <- idle loop (no tasks yet; Phases 57+ add them)
```

### Recommended Project Structure

```
src/farm-agent/
├── pyproject.toml          # uv-managed; all tool config here (ruff, pytest, lint)
├── uv.lock                 # committed
├── Dockerfile
├── .lint-imports           # import-linter config (FND-05)
├── farm_agent/             # top-level package
│   ├── __init__.py
│   ├── __main__.py         # asyncio.run(main()) -- enables `python -m farm_agent`
│   ├── boot.py             # wire all components; ONLY cross-package importer
│   │
│   ├── tenancy/            # FORAY - lowest dep node; no other package imports
│   │   ├── __init__.py
│   │   └── tenant.py       # TenantConfig dataclass + load(env) function
│   │
│   ├── persistence/        # FORAY - DB layer; imports tenancy only
│   │   ├── __init__.py
│   │   ├── pool.py         # build_pool(config) -> AsyncConnectionPool
│   │   └── migrations.py   # run_migrations(pool) -- all CREATE TABLE IF NOT EXISTS
│   │
│   └── extraction/         # FORAY - Phase 60 content; stub now for FND-04 schemas
│       ├── __init__.py
│       └── schemas/        # Pydantic models (Phase 56 ships these for FND-04 gate)
│           ├── __init__.py
│           ├── seeding.py
│           ├── seeding_session.py
│           ├── observation.py
│           ├── harvest.py
│           ├── activity.py
│           ├── input.py
│           ├── provenance.py
│           └── submission.py   # top-level Submission model + JSON Schema export
│
├── tests/
│   ├── conftest.py
│   ├── test_tenancy.py
│   ├── test_persistence.py     # integration: real DB on :5434 test instance
│   ├── test_schema_parity.py   # FND-04 structural diff
│   └── test_foray_seam.py      # FND-05 (or handled by lint gate in CI)
│
└── fixtures/
    └── submission_json_schema.json   # FND-04 committed Node fixture
```

Note: `chamber/` is not created in Phase 56 (no chamber code). It is added in Phase 63.

---

## FND-01: asyncio Skeleton + Docker

### pyproject.toml Shape

```toml
[project]
name = "farm-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.13",
    "psycopg[binary]>=3.3",
    "psycopg-pool>=3.3",
    "ruamel.yaml>=0.19",
]

[project.optional-dependencies]
dev = [
    "pytest>=9.1",
    "pytest-asyncio>=1.4",
    "ruff>=0.15",
    "import-linter>=2.11",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"         # pytest-asyncio 1.x config key -- confirmed
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**pytest-asyncio 1.x note:** The config key is `asyncio_mode = "auto"` in `[tool.pytest.ini_options]`. This is confirmed for pytest-asyncio 1.4.0 (verified PyPI 2026-06-15). [ASSUMED from milestone STACK.md; no Context7 verification this session]

### Dockerfile

```dockerfile
FROM python:3.12-slim-bookworm
# Install uv
RUN pip install uv
WORKDIR /app
# Copy dependency spec first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev
# Copy source
COPY farm_agent/ ./farm_agent/
CMD ["uv", "run", "python", "-m", "farm_agent"]
```

**uv-in-Docker best practice:** `uv sync --no-dev` creates the venv in `.venv/` inside the container. `uv run` executes within that venv. Alternatively: `RUN uv sync --no-dev && .venv/bin/python -m farm_agent` avoids the `uv run` overhead at runtime. Either works; `uv run` is safer for Dockerfile CMD because it handles PATH correctly. [ASSUMED: uv docs pattern; not verified via Context7 this session]

### Boot Pattern

```python
# farm_agent/__main__.py
import asyncio
from farm_agent.boot import main

asyncio.run(main())
```

```python
# farm_agent/boot.py
import asyncio
import logging
import os
import time

from farm_agent.tenancy.tenant import load as load_config
from farm_agent.persistence.pool import build_pool
from farm_agent.persistence.migrations import run_migrations

log = logging.getLogger(__name__)

async def main() -> None:
    t0 = time.monotonic()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    config = load_config(os.environ)
    pool = await build_pool(config)
    await run_migrations(pool)
    elapsed = time.monotonic() - t0
    log.info("boot complete in %.2fs", elapsed)
    # FND-01 gate: assert elapsed < 5.0 in tests
    # Phase 57+ will add: asyncio.gather(receive_loop(), watchdogs(), ...)
    # For now: idle until SIGTERM
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await pool.close()
```

**Boot-in-5s testability:** In `test_persistence.py`, call `main()` against a test DB (env override), capture elapsed time, assert `elapsed < 5.0`. This is a pure in-process integration test -- no Docker needed. The 5-second target is extremely conservative for a boot that only opens a pool and runs ~15 idempotent SQL statements. [ASSUMED: timing estimate based on psycopg3 pool open latency]

### Compose Integration

The new `alerter-py` service joins the existing compose without replacing `alerter`. It uses the same networks (`signal-net`, `default`) and the same `tenants/mossrock/secrets.env` env_file:

```yaml
# docker-compose.override.yml addition
alerter-py:
  build:
    context: ./src/farm-agent
    dockerfile: Dockerfile
  restart: unless-stopped
  env_file:
    - tenants/mossrock/secrets.env
  environment:
    - TIMESCALE_HOST=${TIMESCALE_HOST:-timescale}
    - TIMESCALE_DB=${TIMESCALE_DB:-postgres}
    - TIMESCALE_USER=${TIMESCALE_USER:-postgres}
    - TIMESCALE_PASSWORD=${TIMESCALE_PASSWORD}
    - TENANT_ID=mossrock
    # ... same env as alerter block
  networks:
    - signal-net
    - default
```

**IMPORTANT:** Use the string form for `env_file` (not object form). The object form (`- path: ... required: false`) silently drops on compose v2.40 (documented prod outage 2026-05-23). [VERIFIED: memory feedback_compose_env_file_object_form_silently_drops]

---

## FND-02: TenantConfig

### Design Decision: Hand-Rolled Loader vs. pydantic-settings

**Recommendation: hand-rolled loader** mirroring the Node `config.js` pattern exactly.

pydantic-settings `BaseSettings` has auto-discovery behavior (env prefix matching, case-insensitive lookups, nested model expansion) that differs from the Node pattern and would require careful configuration to not diverge. The Node `config.js` is 265 lines and its exact layer order, fallback semantics, and secret-vs-non-secret split are already known. Porting it directly as a Python dataclass with explicit field mapping is lower-risk and produces a more auditable result.

The only downside of hand-rolling is boilerplate. Given the config is <30 fields and is already fully understood, this is not a concern. [ASSUMED: pydantic-settings tradeoff assessment]

### Config Layer Order (from live `config.js`)

```
1. tenants/<tenant_id>/config.yaml    (tenant YAML -- non-secrets)
2. tenants/<tenant_id>/strains.yaml   (tenant YAML -- strain codes)
3. os.environ                         (env -- non-secrets can be overridden)
4. hardcoded default                  (fallback)
```

Secrets (`ANTHROPIC_API_KEY`, `TIMESCALE_PASSWORD`, `SIGNAL_SENDER`, `FARMOS_PASSWORD`) come from `os.environ` only -- never from tenant YAML. The Python implementation must call `os.environ[key]` with an explicit KeyError on missing secrets (equivalent to Node's `mustEnv()`).

### TenantConfig Dataclass

```python
# tenancy/tenant.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

TENANTS_BASE = Path(__file__).parent.parent.parent.parent / "tenants"

@dataclass(frozen=True)
class TenantConfig:
    tenant_id: str
    # Secrets (env-only)
    signal_sender: str
    timescale_password: str
    anthropic_api_key: str
    farmos_password: str
    # Non-secrets (YAML or env or default)
    signal_recipient: str
    signal_group_id: str | None
    signal_farmer_map: dict[str, str]      # e164 -> slug
    strains: list[str]
    event_gate_convo_mode: str
    farmos_url: str
    farmos_username: str
    farmos_integration: bool
    timescale_host: str
    timescale_db: str
    timescale_user: str
    whisper_url: str
    capture_base_dir: str
    capture_retention_days: int
    rh_target: float
    rh_band: float
    pi_offline_min: int
    sensor_offline_min: int
    heartbeat_hour: int
    receive_poll_sec: int
    max_sends_per_hour: int
    draft_pending_timeout_min: int
    draft_watchdog_interval_ms: int
    commit_watchdog_interval_ms: int
    commit_watchdog_batch_cap: int
    commit_retry_max: int
    timezone: str
    log_level: str
    # ... (all fields from config.js)
```

**Path-traversal guard:** The Python loader must implement the same boundary check as Node:
```python
def _load_tenant_file(tenant_id: str, filename: str) -> dict[str, Any]:
    p = (TENANTS_BASE / tenant_id / filename).resolve()
    if not str(p).startswith(str(TENANTS_BASE) + os.sep):
        return {}
    if not p.exists():
        return {}
    yaml = YAML()
    return yaml.load(p) or {}
```

**Secrets enforcement:** Use `_must_env(env, key)` that raises `RuntimeError` (not `KeyError`) with a clear message -- matching Node's `mustEnv()` behavior.

---

## FND-03: Persistence (psycopg3 AsyncConnectionPool + Migrations)

### Complete Table/Column Inventory

Derived from reading all four DDL files (`capture-db.js`, `extraction-db.js`, `outbound-db.js`, `commit-db.js`) directly. [VERIFIED: live source files read 2026-06-15]

#### `signal_capture` -- PK type: `text` (ULID, e.g. `01KS9HSSJZYC6QHNKFT8Y3RF1H`)

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| id | text | NOT NULL | -- | PRIMARY KEY; ULID string |
| captured_at | timestamptz | NOT NULL | now() | |
| sender | text | NOT NULL | -- | e164 |
| message_type | text | NOT NULL | -- | |
| raw_text | text | NULL | -- | |
| attachment_paths | text[] | NOT NULL | ARRAY[]::text[] | |
| transcript | text | NULL | -- | |
| llm_session_tag | text | NULL | -- | |
| llm_reply | text | NULL | -- | |
| degraded | boolean | NOT NULL | false | |
| expired | boolean | NOT NULL | false | |
| group_id | text | NULL | -- | Phase 37 ADD COLUMN |
| farmos_person | text | NULL | -- | Phase 37 ADD COLUMN |
| reply_target_kind | text | NULL | -- | Phase 37 ADD COLUMN |
| input_tokens | int | NULL | -- | 999.53 ADD COLUMN |
| output_tokens | int | NULL | -- | 999.53 ADD COLUMN |
| cache_creation_input_tokens | int | NULL | -- | 999.53 ADD COLUMN |
| cache_read_input_tokens | int | NULL | -- | 999.53 ADD COLUMN |
| model | text | NULL | -- | 999.53 ADD COLUMN |
| extraction_gate | VARCHAR(32) | NULL | -- | Phase 44 ADD COLUMN |
| signal_msg_ts | bigint | NULL | -- | Phase 50 ADD COLUMN; ms-since-epoch |
| quote_msg_ts | bigint | NULL | -- | Phase 50 ADD COLUMN |
| quote_author_e164 | text | NULL | -- | Phase 50 ADD COLUMN |
| corpus_context | jsonb | NULL | -- | Phase 53 ADD COLUMN |

Indexes: `idx_signal_capture_sender_time` (sender, captured_at DESC), `idx_signal_capture_expired` (expired) WHERE expired = false.

View: `v_llm_cost_daily` (CREATE OR REPLACE -- idempotent).

#### `signal_draft` -- PK type: `text` (hex SHA-256, e.g. `f87eb1e0...`)

ID computed as: `SHA-256(sorted(captureIds).join('|'))`, with `#N` suffix for index > 0 in multi-draft batches. [VERIFIED: live `extraction-db.js:computeDraftId()`]

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| id | text | NOT NULL | -- | PRIMARY KEY; hex SHA-256 |
| created_at | timestamptz | NOT NULL | now() | |
| updated_at | timestamptz | NOT NULL | now() | |
| sender_e164 | text | NOT NULL | -- | |
| farmos_person | text | NULL | -- | |
| source_capture_ids | text[] | NOT NULL | ARRAY[]::text[] | ULIDs of contributing captures |
| status | text | NOT NULL | -- | Enum: pending, awaiting_farmer, confirmed, discarded, expired, needs_review, committing, committed, commit_failed |
| log_type | text | NULL | -- | |
| draft_json | jsonb | NULL | -- | |
| per_field_confidence | jsonb | NULL | -- | |
| askback_turns | integer | NOT NULL | 0 | |
| farmer_facing_preview | text | NULL | -- | |
| needs_review_reason | text | NULL | -- | ADD COLUMN IF NOT EXISTS (idempotent no-op since column already in CREATE TABLE) |
| reply_target_kind | text | NULL | -- | |
| group_id | text | NULL | -- | |
| discarded_reason | text | NULL | -- | Phase 49 ADD COLUMN |
| discarded_at | timestamptz | NULL | -- | Phase 49 ADD COLUMN |
| farmos_response | jsonb | NULL | -- | Phase 40 / commit-db ADD COLUMN |
| committed_at | timestamptz | NULL | -- | Phase 40 ADD COLUMN |
| commit_failed_reason | text | NULL | -- | Phase 40 ADD COLUMN |
| commit_attempt_count | int | NOT NULL | 0 | Phase 40 ADD COLUMN |
| committed_at_attempt | timestamptz | NULL | -- | Phase 40 ADD COLUMN |
| outcome_ack_sent_at | timestamptz | NULL | -- | Phase 45 ADD COLUMN |

Indexes: `idx_signal_draft_sender_status` (sender_e164, status); `idx_signal_draft_in_flight_per_sender` UNIQUE (sender_e164) WHERE status IN ('pending','awaiting_farmer'); `idx_signal_draft_status_confirmed` (status, confirmed_at) WHERE status IN ('confirmed','committing').

#### `signal_outbound` -- PK type: `uuid` (Postgres-generated via `gen_random_uuid()`)

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| id | uuid | NOT NULL | gen_random_uuid() | PRIMARY KEY; requires pgcrypto extension |
| tenant_id | text | NOT NULL | -- | |
| sent_at | timestamptz | NOT NULL | now() | |
| recipient_e164 | text | NOT NULL | -- | |
| intent | text | NOT NULL | -- | |
| body | text | NOT NULL | -- | |
| attachments | jsonb | NULL | -- | |
| source_module | text | NOT NULL | -- | |
| source_line | integer | NULL | -- | |
| related_capture_id | text | NULL | -- | **text, NOT uuid** (hotfix: was uuid, broke on ULID insert) |
| related_draft_id | text | NULL | -- | **text, NOT uuid** (same hotfix) |
| signal_msg_ts | bigint | NULL | -- | Phase 50 ADD COLUMN |

Indexes: `idx_signal_outbound_tenant_sent` (tenant_id, sent_at DESC); `idx_signal_outbound_recipient_sent` (recipient_e164, sent_at DESC); `idx_signal_outbound_intent` (intent); `idx_signal_outbound_msg_ts` (signal_msg_ts) WHERE signal_msg_ts IS NOT NULL.

Extension: `pgcrypto` (CREATE EXTENSION IF NOT EXISTS).

**CRITICAL:** The `ALTER TABLE signal_outbound ALTER COLUMN related_capture_id TYPE text` and `ALTER COLUMN related_draft_id TYPE text` statements from `outbound-db.js` are NOT safe to include in the Python migrations if the Node alerter has already run them. `ALTER COLUMN ... TYPE text` on a `text` column is a no-op in Postgres (`text` -> `text` is a no-op cast), so it is safe to include. [ASSUMED: Postgres behavior for no-op type cast; verify in Wave 0 test] Include them anyway -- they are idempotent.

### AsyncConnectionPool Setup

```python
# persistence/pool.py
from psycopg_pool import AsyncConnectionPool
from farm_agent.tenancy.tenant import TenantConfig

async def build_pool(config: TenantConfig) -> AsyncConnectionPool:
    conninfo = (
        f"host={config.timescale_host} "
        f"dbname={config.timescale_db} "
        f"user={config.timescale_user} "
        f"password={config.timescale_password} "
        f"options=-c timezone=UTC"
    )
    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=5,
        # open=False means we open it manually; needed for async context
        open=False,
    )
    await pool.open()
    return pool
```

**`options=-c timezone=UTC`:** This enforces UTC at the connection level, preventing naive datetime insertion bugs. The Node alerter passes `new Date().toISOString()` (always UTC with Z); the Python equivalent is `datetime.now(timezone.utc)`. [VERIFIED: PITFALLS.md Pitfall 7]

**Pool size:** `min_size=1, max_size=5` is appropriate for the alerter's workload (single-process, event-driven, low concurrency). The Node alerter uses `pg.Pool` defaults. [ASSUMED: sizing estimate]

### Migration Runner

```python
# persistence/migrations.py
import logging
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

async def run_migrations(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await _run_capture_migrations(conn)
        await _run_draft_migrations(conn)
        await _run_outbound_migrations(conn)
        await _run_commit_migrations(conn)
    log.info("migrations complete")

async def _run_capture_migrations(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_capture (
          id              text PRIMARY KEY,
          captured_at     timestamptz NOT NULL DEFAULT now(),
          ...
        )
    """)
    # ADD COLUMN IF NOT EXISTS for all Phase 37/44/50/53 columns
    await conn.execute("ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text")
    ...
```

**Additive-only guard:** The migration runner MUST NOT issue:
- `DROP TABLE` or `DROP COLUMN`
- `ALTER COLUMN ... TYPE` (except the safe `text -> text` no-op already in Node)
- `DROP INDEX`
- `TRUNCATE`

Any of these would break the live Node stack reading the same DB. [VERIFIED: D-02 CONTEXT.md]

---

## FND-04: Zod-to-Pydantic JSON-Schema Parity Gate

### Why This Exists

PITFALLS.md Pitfall 1 documents that `model_json_schema()` and `zodToJsonSchema()` produce subtly different output. The LLM receives the JSON Schema as its tool `input_schema`, so schema differences change LLM behavior silently -- not as validation errors. The parity gate catches this before any LLM call runs. [VERIFIED: PITFALLS.md]

### The Fixture: Committed Node Output

The fixture approach: run a small Node script once against the live `SUBMISSION_JSON_SCHEMA`, commit the output to `tests/fixtures/submission_json_schema.json`, then diff against pydantic's output in pytest.

**The fixture has been generated.** The live Node `SUBMISSION_JSON_SCHEMA` was produced during research. Key structural facts: [VERIFIED: live generation 2026-06-15]

- Top-level: `{"$ref": "#/definitions/Submission", "definitions": {...}, "$schema": "http://json-schema.org/draft-07/schema#"}`
- `definitions` key (draft-7), NOT `$defs` (draft-2019+)
- Schema size: 6155 characters
- `Submission` uses `anyOf` (not `oneOf`) for the draft union, with 6 members: seeding, activity, input, observation, harvest, seeding_session
- `additionalProperties: false` is present on: Submission, DraftSubmission wrapper, every log-type object, SeedingSessionGroup, ConflictEntry, Provenanced wrapper
- `Provenanced` wrapper emits as an inline object `{value, confidence, sources[]}` with `additionalProperties: false` -- NOT as a `$ref`. This is the critical shape to replicate.
- `sources` items use `$ref` pointing into `definitions` for reuse (the enum SOURCE_ENUM is referenced)

**The `inlineTopLevelRef` transform:** The Node extractor applies `inlineTopLevelRef()` before passing to Anthropic. This merges the top-level `$ref` into the object so it has `type: "object"` at the root (Anthropic requires this). The pydantic `model_json_schema()` emits with `type: "object"` directly at the root by default (no top-level `$ref` unless using `mode='serialization'`). So:

- The **fixture** used for pytest comparison should be the RAW `SUBMISSION_JSON_SCHEMA` output (with the top-level `$ref`).
- The **Anthropic tool call** uses the inlined version (which the Python port applies via an equivalent `inline_top_level_ref()` helper).
- The pytest compares pydantic's output against the fixture structurally, accounting for the `definitions` vs `$defs` difference.

### Pydantic Model Structure

**Top-level `Submission` model:**

```python
# extraction/schemas/submission.py
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Annotated, Union
from .seeding import SeedingLog
from .activity import ActivityLog
from .input import InputLog
from .observation import ObservationLogBase
from .harvest import HarvestLog
from .seeding_session import SeedingSession

DraftUnion = Annotated[
    Union[SeedingLog, ActivityLog, InputLog, ObservationLogBase, HarvestLog, SeedingSession],
    Field(discriminator="type")
]

class DraftSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    draft: DraftUnion
    per_field_confidence: dict[str, float]  # z.record(z.string(), z.number())

class Submission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    drafts: list[DraftSubmission] = Field(min_length=1)
    continuity: Literal['append', 'replace', 'start_new']
    continuity_reason: str = Field(min_length=1)
    capture_kind: Literal['paper_log', 'physical_object_photo', 'voice_note', 'text'] | None = None

SUBMISSION_JSON_SCHEMA = Submission.model_json_schema()
```

**Per-model requirements (ALL must have `extra='forbid'`):**

| Zod | Pydantic v2 |
|-----|-------------|
| `.strict()` | `model_config = ConfigDict(extra='forbid')` |
| `z.string().datetime()` | `str` + regex validator OR `datetime` with T-separator enforcement |
| `z.record(z.string(), z.number())` | `dict[str, float]` -- emits `additionalProperties: {type: number}` |
| `z.string().regex(BLOCK_NAME_RE)` | `str` + `Field(pattern=r'^[0-9]{6}_[A-Z]{2,4}_[0-9]+$')` |
| `z.discriminatedUnion('type', [...])` | `Annotated[Union[...], Field(discriminator='type')]` |
| `z.literal('seeding')` | `Literal['seeding']` |
| `z.enum([...])` | `Literal[..., ...]` or `enum.Enum` |

**`ObservationLog` cross-field validator (Pitfall 1):**

```python
from pydantic import model_validator

class ObservationLogBase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['observation']
    asset_ref: str = Field(min_length=1)
    state: str | None = None
    notes: str | None = None
    event_timestamp: str  # ISO-8601; validate with regex, NOT native datetime
    confidence: dict[str, float]

class ObservationLog(ObservationLogBase):
    """With cross-field validator for standalone use (not in discriminated union)."""
    @model_validator(mode='after')
    def state_or_notes_required(self) -> 'ObservationLog':
        if not self.state and not self.notes:
            raise ValueError('observation requires state or notes')
        return self

# The discriminated union uses ObservationLogBase (no validator), matching Node's
# discriminatedUnion requirement for pure z.object inputs.
```

**`event_timestamp` handling:** Use `str` + a regex validator, NOT Python `datetime`. Zod's `z.string().datetime()` accepts ISO-8601 with T separator; Python's `datetime.fromisoformat()` accepts bare dates. A bare date `2025-06-14` passes Python but would fail Zod. [VERIFIED: PITFALLS.md Pitfall 1]

```python
from pydantic import field_validator

class SeedingLog(BaseModel):
    ...
    event_timestamp: str

    @field_validator('event_timestamp')
    @classmethod
    def validate_datetime(cls, v: str) -> str:
        # Must contain 'T' separator -- bare dates fail Zod's z.string().datetime()
        if 'T' not in v:
            raise ValueError('event_timestamp must be ISO-8601 with T separator')
        return v
```

**`SeedingSession.event_date`:** Uses `z.string().regex(/^\d{4}-\d{2}-\d{2}$/)` -- a bare date, NOT datetime. Python: `str` + `Field(pattern=r'^\d{4}-\d{2}-\d{2}$')`.

**`BLOCK_NAME_RE`:** Use `re.fullmatch()` in any Python code that validates block names programmatically. In pydantic, use `Field(pattern=r'^[0-9]{6}_[A-Z]{2,4}_[0-9]+$')` which anchors. [VERIFIED: PITFALLS.md Pitfall 1]

### The Pytest Structural Diff

The FND-04 test compares the pydantic output against the committed fixture. The comparison must account for known structural differences between zod-to-json-schema 3.x and pydantic v2:

| Node (zod-to-json-schema 3.25.2) | Pydantic v2 | Handling |
|----------------------------------|-------------|---------|
| `"definitions"` key | `"$defs"` key | Normalize both to a canonical key before diff |
| `"anyOf"` for discriminated union | `"anyOf"` (same) | No normalization needed |
| `"additionalProperties": false` | `"additionalProperties": false` | Must match -- failure = missing `extra='forbid'` |
| `"format": "date-time"` | Not emitted for bare `str` | If using `str` fields, fixture must be adjusted |
| `$ref` in sources enum | May differ | Normalize $ref paths before diff |
| `exclusiveMinimum: 0` (draft-7 value form) | `exclusiveMinimum: 0` or `exclusiveMinimum: true` | Verify pydantic v2 draft-7 output form |

```python
# tests/test_schema_parity.py
import json
from pathlib import Path
from farm_agent.extraction.schemas.submission import SUBMISSION_JSON_SCHEMA

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "submission_json_schema.json"

def normalize_schema(schema: dict) -> dict:
    """Normalize $defs vs definitions and $ref paths for cross-tool comparison."""
    s = json.dumps(schema)
    # Normalize $defs to definitions
    s = s.replace('"$defs"', '"definitions"')
    # Normalize $ref paths from pydantic's format to zod's format
    # pydantic: #/$defs/Foo  ->  #/definitions/Foo
    s = s.replace('#/$defs/', '#/definitions/')
    return json.loads(s)

def test_submission_schema_matches_fixture():
    fixture = json.loads(FIXTURE_PATH.read_text())
    actual = SUBMISSION_JSON_SCHEMA
    # The top-level $ref difference: fixture has $ref; pydantic has type:object
    # We compare the inlined (Submission object) structure
    norm_fixture = normalize_schema(fixture)
    norm_actual = normalize_schema(actual)
    # Structural equality: all required fields, additionalProperties, property types
    assert norm_actual == norm_fixture, (
        f"JSON Schema mismatch.\n"
        f"Missing keys: {set(norm_fixture) - set(norm_actual)}\n"
        f"Extra keys: {set(norm_actual) - set(norm_fixture)}"
    )
```

**Note:** A strict `==` diff may be too strict for initial implementation because of minor structural differences (ordering of `required` arrays, `$ref` path format). The test should be written to fail on substantive differences (`additionalProperties`, required fields, type constraints) while tolerating cosmetic differences. Use a recursive structural comparator that normalizes ordering. [ASSUMED: exact diff strategy; may need iteration in Wave 0]

### Generating the Fixture

A one-time Node script to commit the fixture:

```bash
# Run once from src/agents/alerter/
node -e "
const { SUBMISSION_JSON_SCHEMA } = require('./src/extraction/schemas/index.js');
const fs = require('fs');
fs.writeFileSync('../../farm-agent/fixtures/submission_json_schema.json',
  JSON.stringify(SUBMISSION_JSON_SCHEMA, null, 2));
console.log('fixture written');
"
```

This script can also be a Wave 0 task in the plan to ensure the fixture is committed before FND-04 testing.

### Does FND-04 Need a Spike?

**Yes, for the discriminated union translation.** The `Annotated[Union[...], Field(discriminator='type')]` in pydantic v2 can emit subtly different `anyOf` shapes vs. zod's `discriminatedUnion`. Specifically:

- Pydantic may include a `discriminator` key in the schema object (not present in zod output).
- Pydantic's `anyOf` members may include `title` fields (zod does not emit these).
- The `$defs`/`definitions` normalization must be tested.

**Recommendation:** The first plan task for FND-04 should be a spike: build a minimal `Submission` model with one log type, run `model_json_schema()`, compare against the fixture fragment for that type, and verify the diff is only cosmetic (titles, ordering) not substantive (additionalProperties missing, wrong types). Budget 2-4 hours. If the diff is substantive, the full-model translation work is flagged and a second plan is needed before Phase 59-60 can land.

---

## FND-05: Foray CI Seam

### Options

**Option A: import-linter 2.11 (recommended)**

import-linter defines "contracts" that specify which imports are allowed between packages. It integrates with pytest and can run as a pre-commit check.

```ini
# .lint-imports in src/farm-agent/
[importlinter]
root_packages =
    farm_agent

[importlinter:contract:foray-seam]
name=Foray seam: no foray package imports from chamber
type=forbidden
source_modules =
    farm_agent.tenancy
    farm_agent.persistence
    farm_agent.signal_io
    farm_agent.extraction
    farm_agent.confirm
    farm_agent.farmos_client
    farm_agent.capture
    farm_agent.llm
forbidden_modules =
    farm_agent.chamber
```

Run: `lint-imports` (or `python -m importlinter`).

Integrate into pytest via `pytest --lint-imports` or as a separate CI step.

**Option B: grep CI check (simpler, no dependency)**

```bash
# In CI / Makefile
if grep -r "from farm_agent.chamber" src/farm-agent/farm_agent/ \
   --include="*.py" \
   --exclude-dir=chamber; then
  echo "FORAY SEAM VIOLATION: foray package imports from chamber"
  exit 1
fi
```

This grep is zero-dependency, runs in milliseconds, and is entirely correct for the enforcement requirement. It has one gap: it catches `from farm_agent.chamber import X` but misses `import farm_agent.chamber` (the `import` form without `from`). Add a second grep for that:

```bash
if grep -rE "^import farm_agent\.chamber|from farm_agent\.chamber" \
   src/farm-agent/farm_agent/ --include="*.py" --exclude-dir=chamber; then
  echo "FORAY SEAM VIOLATION"
  exit 1
fi
```

**Recommendation:** Use the grep approach in Phase 56 (zero new dependency, deterministic, no configuration). Add import-linter as an optional enhancement once `chamber/` exists (Phase 63). Add a `test_foray_seam.py` that runs the grep as a subprocess and asserts exit code 0, so it is part of the pytest run.

```python
# tests/test_foray_seam.py
import subprocess

FORAY_PACKAGES = [
    "farm_agent/tenancy",
    "farm_agent/persistence",
    "farm_agent/extraction",
    # signal_io, confirm, farmos_client, capture, llm not created yet
]

def test_no_chamber_imports_in_foray():
    """FND-05: grep that fails CI if any foray package imports from chamber."""
    # chamber/ doesn't exist in Phase 56, so this test vacuously passes.
    # It is wired now so it FAILS the moment a violation is introduced.
    result = subprocess.run(
        ["grep", "-rE", r"^import farm_agent\.chamber|from farm_agent\.chamber",
         "--include=*.py"] + FORAY_PACKAGES,
        capture_output=True, text=True, cwd="."
    )
    assert result.returncode != 0 or result.stdout == "", (
        f"FORAY SEAM VIOLATION:\n{result.stdout}"
    )
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML parsing with comment preservation | Custom parser | `ruamel.yaml` | Round-trip fidelity; nested object support |
| Async DB connection lifecycle | Custom pool | `psycopg_pool.AsyncConnectionPool` | Handles min/max, health checks, reconnect |
| Dependency check between packages | Runtime feature flags | import-linter (CI) / grep | Structural enforcement, no runtime cost |
| datetime UTC enforcement | Per-call `replace(tzinfo=utc)` | `options=-c timezone=UTC` on DB connection + `datetime.now(timezone.utc)` everywhere | Connection-level UTC is defense-in-depth |

---

## Common Pitfalls

### Pitfall 1: pydantic `$defs` vs zod `definitions`

**What goes wrong:** pydantic v2 uses `$defs` (JSON Schema draft 2020-12). zod-to-json-schema 3.x uses `definitions` (draft-7). The fixture has `definitions`; pydantic emits `$defs`. A naive `==` comparison fails even if the schemas are structurally identical.

**How to avoid:** Normalize both sides in the pytest before comparison (see `normalize_schema()` above). [VERIFIED: live schema inspection 2026-06-15]

### Pitfall 2: `exclusiveMinimum` form difference

**What goes wrong:** Draft-7 represents `exclusiveMinimum: 0` as a numeric value. Draft-2020 uses a boolean `exclusiveMinimum: true` alongside `minimum`. Pydantic v2 targets draft 2020-12 by default for `model_json_schema()`. The Node fixture has `"exclusiveMinimum": 0` (numeric, draft-7). Pydantic may emit the boolean form.

**How to avoid:** Verify the pydantic output for a `z.number().int().positive()` equivalent (`int` with `gt=0`). If pydantic emits `exclusiveMinimum: true`, the fixture diff will show a discrepancy. Either normalize both forms in the test, or use `Annotated[int, Field(gt=0)]` and verify it emits `exclusiveMinimum: 0`. [ASSUMED: draft-7 vs 2020 difference; verify in spike]

### Pitfall 3: `ALTER TABLE ... ALTER COLUMN TYPE text` on existing column

**What goes wrong:** The Node `outbound-db.js` includes `ALTER TABLE signal_outbound ALTER COLUMN related_capture_id TYPE text`. If the column is already `text`, this is a no-op in Postgres. But the Python migration includes it, and some Postgres versions may still acquire a table lock briefly. On an active table, this could delay other queries.

**How to avoid:** Include the `ALTER COLUMN ... TYPE text` statements for correctness (they are no-ops), but add a comment explaining they are idempotent compatibility statements for hosts that ran the original uuid schema. The table is low-volume so the lock is not a production concern. [ASSUMED: lock behavior; low risk for this workload]

### Pitfall 4: psycopg3 `AsyncConnectionPool` `open=False` required for asyncio

**What goes wrong:** If `AsyncConnectionPool` is created with `open=True` (the default), it attempts to open connections synchronously in `__init__`, which is not safe in async context before the event loop is running.

**How to avoid:** Pass `open=False` and call `await pool.open()` inside the async `main()`. [ASSUMED: psycopg3 pool API; verify against Context7 docs or psycopg3 changelog]

### Pitfall 5: `uv sync` in Docker creates venv at `.venv/`; CMD must use it

**What goes wrong:** `uv sync` creates `.venv/` inside the working directory. If CMD uses `python` directly (not `uv run` or `.venv/bin/python`), it uses the system Python which lacks the installed packages.

**How to avoid:** Use `CMD ["uv", "run", "python", "-m", "farm_agent"]` or `CMD [".venv/bin/python", "-m", "farm_agent"]`. [ASSUMED: uv behavior]

---

## Runtime State Inventory

This is a foundation/scaffolding phase. Step 2.5 applies only for rename/refactor phases. **Skipped -- greenfield package creation, no renames.**

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python 3.12 | Runtime (Docker) | In Docker image | 3.12.x (from `python:3.12-slim-bookworm`) | -- |
| Python 3.10 | Dev host (elder-plops) | YES | 3.10.12 | Tests run in Docker; local 3.10 cannot run `farm_agent` directly (3.12 features) |
| uv | Docker build + local dev | YES (`/home/santi/.pyenv/shims` suggests pyenv) | check `uv --version` | `pip + venv` (fallback but not recommended) |
| PostgreSQL/TimescaleDB | FND-03 integration tests | YES (timescale container running on prod) | 14+ (timescale container) | Throwaway `docker run postgres:14 -p 5434:5432` for tests |
| Node.js + alerter | FND-04 fixture generation | YES (src/agents/alerter node_modules present) | Node LTS; zod-to-json-schema 3.25.2 | -- |
| Docker compose v2 | Container build | YES | v2.40+ | -- |

**Note:** The dev host Python (3.10.12) cannot run the new stack (requires 3.12). All Python testing should run via Docker or a pyenv-managed 3.12 venv. The `.python-version` file in `/mushy` points to a `mushroom_farm` pyenv version that is not installed. Before local dev, either: (a) install pyenv `mushroom_farm` version pointing to 3.12, or (b) run all tests via Docker. [VERIFIED: `python3 --version` output 2026-06-15]

**Missing dependencies with fallback:**
- Local Python 3.12: use Docker for test execution.

---

## Open Questions

1. **pyenv `mushroom_farm` version -- should it be 3.12?**
   - What we know: `.python-version` at `/mushy` root specifies `mushroom_farm`, not installed.
   - What's unclear: Is this intended to resolve to 3.12 or is it stale?
   - Recommendation: Either create `mushroom_farm` -> Python 3.12 via `pyenv install` and `pyenv virtualenv`, or add a `src/farm-agent/.python-version` with `3.12.x` pinned directly.

2. **signal-cli UNIX socket path (Phase 57, not Phase 56)**
   - What we know: The current Node alerter uses the signal-cli HTTP REST API at `http://signal-cli:8080`. The milestone research recommends switching to the UNIX socket for the Python port.
   - What's unclear: The exact socket path in the current compose topology. `$XDG_RUNTIME_DIR/signal-cli/socket` or a fixed volume mount path?
   - Recommendation: Defer to Phase 57. Phase 56 does not touch signal-cli.

3. **psycopg3 `AsyncConnectionPool(open=False)` API**
   - What we know: The API was stable in psycopg 3.1+.
   - What's unclear: Whether psycopg 3.3.x changed the `open` parameter or the `await pool.open()` pattern.
   - Recommendation: Verify in Wave 0 spike with `psycopg-pool 3.3.1`. The Context7 source (STACK.md references `/psycopg/psycopg` Context7) has this documented.

4. **pydantic `exclusiveMinimum` form in `model_json_schema()`**
   - What we know: Draft-7 uses numeric `exclusiveMinimum: 0`; pydantic v2 targets draft 2020-12.
   - What's unclear: Whether pydantic v2 emits the draft-7 form (numeric) or draft-2020 form (boolean).
   - Recommendation: The FND-04 spike (first plan task) must verify this and adjust the fixture normalizer if needed.

---

## Validation Architecture

Each FND requirement has a concrete, automated verification. All tests run in < 30 seconds unless noted.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.0 + pytest-asyncio 1.4.0 |
| Config file | `src/farm-agent/pyproject.toml` (`[tool.pytest.ini_options]` with `asyncio_mode = "auto"`) |
| Quick run command | `cd src/farm-agent && uv run pytest tests/ -x -q` |
| Full suite command | `cd src/farm-agent && uv run pytest tests/ -v` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FND-01 | Package boots as asyncio daemon in < 5 seconds | integration | `pytest tests/test_boot.py::test_boot_completes_in_5s` | Wave 0 |
| FND-01 | Docker image builds and `uv sync` succeeds | build smoke | `docker build src/farm-agent/ -t farm-agent:test` | Wave 0 (Dockerfile) |
| FND-02 | TenantConfig loads YAML + env; secrets raise on missing | unit | `pytest tests/test_tenancy.py -x` | Wave 0 |
| FND-02 | No business module reads `os.environ` directly | static | `grep -r "os.environ" farm_agent/ --include='*.py' | grep -v tenancy/tenant.py | grep -v boot.py` (must return empty) | CI check |
| FND-03 | Migrations run idempotent (second run is a no-op) | integration | `pytest tests/test_persistence.py::test_migrations_idempotent` | Wave 0 |
| FND-03 | Pool connects to test DB, can INSERT and SELECT | integration | `pytest tests/test_persistence.py::test_pool_roundtrip` | Wave 0 |
| FND-04 | `model_json_schema()` == fixture (structural) | unit | `pytest tests/test_schema_parity.py::test_submission_schema_matches_fixture` | Wave 0 (fixture + test) |
| FND-04 | `extra='forbid'` on every nested model (spot check) | unit | `pytest tests/test_schema_parity.py::test_all_models_forbid_extra` | Wave 0 |
| FND-04 | ObservationLog cross-field validator rejects state=None,notes=None | unit | `pytest tests/test_schema_parity.py::test_observation_requires_state_or_notes` | Wave 0 |
| FND-05 | No foray package imports from `chamber/` | CI grep | `pytest tests/test_foray_seam.py::test_no_chamber_imports_in_foray` | Wave 0 |

### Sampling Rate

- **Per task commit:** `cd src/farm-agent && uv run pytest tests/ -x -q` (fast, < 10s)
- **Per wave merge:** `cd src/farm-agent && uv run pytest tests/ -v` + Docker build check
- **Phase gate:** Full suite green + Docker image builds + `docker compose up alerter-py` boots cleanly

### Wave 0 Gaps

- [ ] `src/farm-agent/pyproject.toml` -- project config, no version exists
- [ ] `src/farm-agent/Dockerfile` -- no Dockerfile exists
- [ ] `src/farm-agent/farm_agent/__init__.py` -- package does not exist
- [ ] `src/farm-agent/tests/conftest.py` -- shared test DB fixture (test TimescaleDB on separate port)
- [ ] `src/farm-agent/tests/fixtures/submission_json_schema.json` -- FND-04 fixture; generate via Node script
- [ ] `src/farm-agent/.lint-imports` -- FND-05 config (optional; grep test is the primary gate)

---

## Security Domain

`security_enforcement` is not explicitly set to false in `.planning/config.json` (file not checked -- treat as enabled per default rule).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth in Phase 56 |
| V3 Session Management | No | No session in Phase 56 |
| V4 Access Control | No | No user-facing endpoints |
| V5 Input Validation | Partial | TenantConfig validates env vars; parity test validates schema |
| V6 Cryptography | No | No crypto in Phase 56 (ULID generation deferred to Phase 58) |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal in tenant file loader | Tampering | `p.resolve().startswith(TENANTS_BASE + sep)` boundary check (ported from Node) |
| Secret exposure via tenant YAML | Information Disclosure | Secrets resolved only from `os.environ`; never from YAML files |
| DB connection with default timezone | Tampering | `options=-c timezone=UTC` on connection; `datetime.now(timezone.utc)` everywhere |
| Migration data loss (DROP/ALTER) | Tampering | Additive-only guard: review list in migration runner; no DROP/ALTER except no-op text casts |

---

## Code Examples

### psycopg3 `AsyncConnectionPool` with `open=False`

```python
# Source: psycopg3 docs (async pool lifespan pattern, analogous to FastAPI lifespan)
from psycopg_pool import AsyncConnectionPool

async def build_pool(config) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        conninfo=f"host={config.timescale_host} dbname={config.timescale_db} "
                 f"user={config.timescale_user} password={config.timescale_password} "
                 f"options=-c\\ timezone=UTC",
        min_size=1,
        max_size=5,
        open=False,
    )
    await pool.open()
    return pool
```

### Idempotent migration (additive-only pattern)

```python
# Source: derived from Node alerter capture-db.js pattern
async def _run_capture_migrations(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_capture (
          id              text PRIMARY KEY,
          captured_at     timestamptz NOT NULL DEFAULT now(),
          sender          text NOT NULL,
          message_type    text NOT NULL,
          raw_text        text,
          attachment_paths text[] NOT NULL DEFAULT ARRAY[]::text[],
          transcript      text,
          llm_session_tag text,
          llm_reply       text,
          degraded        boolean NOT NULL DEFAULT false,
          expired         boolean NOT NULL DEFAULT false
        )
    """)
    # Phase 37 columns -- idempotent ADD COLUMN IF NOT EXISTS
    for col_sql in [
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text",
        # ... remaining columns
    ]:
        await conn.execute(col_sql)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time
        ON signal_capture (sender, captured_at DESC)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_capture_expired
        ON signal_capture (expired) WHERE expired = false
    """)
```

### Pydantic discriminated union (FND-04 shape)

```python
# Source: pydantic v2 docs (discriminated unions with Annotated)
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Literal, Union

class SeedingLog(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['seeding']
    species: str = Field(min_length=1)
    block_name: str = Field(pattern=r'^[0-9]{6}_[A-Z]{2,4}_[0-9]+$')
    qty: int = Field(gt=0)
    event_timestamp: str   # str, NOT datetime -- see FND-04 notes
    parent_batch_name: str | None = Field(default=None, min_length=1)
    notes: str | None = None
    confidence: dict[str, float]

DraftUnion = Annotated[
    Union[SeedingLog, ...],
    Field(discriminator='type')
]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setup.py` + pip | `pyproject.toml` + uv | 2023-2024 | Deterministic lockfile; faster Docker builds |
| psycopg2 (sync) | psycopg3 (async) | 2022+ | Native asyncio support; no thread wrappers |
| `asyncio_mode = "strict"` (pytest-asyncio 0.x) | `asyncio_mode = "auto"` (pytest-asyncio 1.x) | 2024 | No per-test `@pytest.mark.asyncio` decorator needed |
| alembic for migrations | Idempotent `CREATE IF NOT EXISTS` | N/A (by design) | No migration state table; restartable at any point |

**Deprecated / avoid:**
- `pydantic.BaseSettings` from pydantic-settings: valid for simple cases but auto-discovery behavior differs from the Node layered pattern; not used here.
- `asyncio_mode = "strict"` (requires per-test marker): use `"auto"` instead.
- `psycopg2` in new async code: use `psycopg[binary]` (psycopg3).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `asyncio_mode = "auto"` is the correct pytest-asyncio 1.x config key | FND-01, Validation Architecture | Tests require `@pytest.mark.asyncio` on every test function -- annoying but not blocking |
| A2 | `AsyncConnectionPool(open=False)` is the correct async-safe init pattern for psycopg-pool 3.3.x | FND-03 | Pool may not open correctly; startup hangs or errors |
| A3 | `uv sync --no-dev` in Dockerfile creates `.venv/` and `uv run` finds it correctly | FND-01 | Container CMD fails; need to adjust to `.venv/bin/python` directly |
| A4 | pydantic v2 `dict[str, float]` for `z.record(z.string(), z.number())` emits `additionalProperties: {type: number}` (matching Node) | FND-04 | Schema parity test fails; need to use `Dict[str, float]` annotation or custom type |
| A5 | pydantic v2 `exclusiveMinimum` emitted as numeric 0 (draft-7 form) matching Node fixture | FND-04 | Fixture diff fails on `qty: {exclusiveMinimum}` fields; normalize in test |
| A6 | `ALTER TABLE signal_outbound ALTER COLUMN related_capture_id TYPE text` is a true no-op on Postgres when column is already text | FND-03 | Statement acquires lock briefly; safe for low-volume table but should verify |
| A7 | `python:3.12-slim-bookworm` base image contains everything needed for `psycopg[binary]` wheel install (no libpq-dev needed) | FND-01 | Docker build fails on psycopg binary wheel; add `apt-get install libpq-dev` |

---

## Sources

### Primary (HIGH confidence)
- Live Node source: `src/agents/alerter/src/capture-db.js`, `extraction-db.js`, `outbound-db.js`, `farmos/commit-db.js` -- complete DDL read 2026-06-15
- Live Node source: `src/agents/alerter/src/extraction/schemas/index.js`, `seeding.js`, `seeding-session.js`, `observation.js` -- schema shapes read 2026-06-15
- Live Node source: `src/agents/alerter/src/config.js` -- complete config surface read 2026-06-15
- Live schema generation: `SUBMISSION_JSON_SCHEMA` generated via Node REPL 2026-06-15; confirmed `anyOf`, `definitions`, `additionalProperties: false`, 6155 chars, draft-7
- `.planning/research/STACK.md` -- library versions verified PyPI 2026-06-14; all confirmed current
- `.planning/research/PITFALLS.md` -- pitfall inventory derived from live source; HIGH confidence
- `.planning/research/ARCHITECTURE.md` -- package layout; HIGH confidence
- `.planning/phases/56-foundation/56-CONTEXT.md` -- locked decisions read 2026-06-15
- PyPI JSON API (psycopg 3.3.4, psycopg-pool 3.3.1, pytest-asyncio 1.4.0, import-linter 2.11, pydantic 2.13.4, ruamel.yaml 0.19.1) -- verified 2026-06-15
- `tenants/mossrock/config.yaml`, `strains.yaml` -- tenant config surface read 2026-06-15
- `docker-compose.override.yml` -- alerter service env surface read 2026-06-15

### Secondary (MEDIUM confidence)
- uv Dockerfile pattern (milestone STACK.md; not re-verified via official docs this session)
- psycopg3 `AsyncConnectionPool(open=False)` pattern (milestone STACK.md references psycopg Context7 source; not re-verified this session)

### Tertiary (LOW confidence)
- pytest-asyncio 1.x `asyncio_mode = "auto"` config key: confirmed from milestone STACK.md, not re-verified against official pytest-asyncio changelog this session.

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH -- all versions PyPI-verified live
- Architecture: HIGH -- derived directly from live Node source
- FND-03 DDL: HIGH -- read from live source files
- FND-04 Schema Shape: HIGH -- generated live from Node runtime
- FND-05 CI Approach: HIGH -- grep is deterministic
- psycopg3 API details: MEDIUM -- from milestone research; not re-verified via Context7 this session
- Pytest-asyncio config: MEDIUM -- confirmed from milestone; not re-checked against official docs

**Research date:** 2026-06-15
**Valid until:** 2026-08-15 (stable library ecosystem; psycopg3 and pydantic have stable APIs)
