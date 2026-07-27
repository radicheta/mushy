# Phase 56: Foundation - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 16 new files (greenfield `src/farm-agent/` skeleton)
**Analogs found:** 14 / 16

---

## File Classification

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `src/farm-agent/pyproject.toml` | config | N/A | `src/farmos-agent/setup.py` | role-match (deliberately departs: uv vs ament_python) |
| `src/farm-agent/Dockerfile` | config | N/A | `src/farmos-agent/Dockerfile` | role-match (deliberately departs: `python:3.12-slim` vs `ros:jazzy-ros-core`, uv vs apt) |
| `src/farm-agent/farm_agent/__init__.py` | config | N/A | `src/farmos-agent/farmos_agent/__init__.py` | exact (empty init stub) |
| `src/farm-agent/farm_agent/__main__.py` | utility | request-response | `src/farmos-agent/entrypoint.sh` | partial (same purpose: start the module; Python form instead of shell) |
| `src/farm-agent/farm_agent/boot.py` | utility | event-driven | `src/farmos-agent/farmos_agent/farmos_agent_node.py` | partial (asyncio event loop vs ROS lifecycle node) |
| `src/farm-agent/farm_agent/tenancy/tenant.py` | utility | request-response | `src/agents/alerter/src/config.js` | role-match (port target; layered config loader) |
| `src/farm-agent/farm_agent/persistence/pool.py` | service | request-response | `src/farmos-agent/farmos_agent/farmos_client.py` | partial (psycopg pattern; async pool vs sync session) |
| `src/farm-agent/farm_agent/persistence/migrations.py` | utility | batch | `src/agents/alerter/src/capture-db.js` | exact (idempotent CREATE TABLE IF NOT EXISTS pattern) |
| `src/farm-agent/farm_agent/extraction/schemas/seeding.py` | model | transform | `src/agents/alerter/src/extraction/schemas/seeding.js` | exact (port target) |
| `src/farm-agent/farm_agent/extraction/schemas/activity.py` | model | transform | `src/agents/alerter/src/extraction/schemas/activity.js` | exact (port target) |
| `src/farm-agent/farm_agent/extraction/schemas/input.py` | model | transform | `src/agents/alerter/src/extraction/schemas/input.js` | exact (port target) |
| `src/farm-agent/farm_agent/extraction/schemas/observation.py` | model | transform | `src/agents/alerter/src/extraction/schemas/observation.js` | exact (port target) |
| `src/farm-agent/farm_agent/extraction/schemas/harvest.py` | model | transform | `src/agents/alerter/src/extraction/schemas/harvest.js` | exact (port target) |
| `src/farm-agent/farm_agent/extraction/schemas/seeding_session.py` | model | transform | `src/agents/alerter/src/extraction/schemas/seeding-session.js` | exact (port target) |
| `src/farm-agent/farm_agent/extraction/schemas/provenance.py` | model | transform | `src/agents/alerter/src/extraction/schemas/provenance.js` | exact (port target) |
| `src/farm-agent/farm_agent/extraction/schemas/submission.py` | model | transform | `src/agents/alerter/src/extraction/schemas/index.js` | exact (port target; emits SUBMISSION_JSON_SCHEMA) |
| `src/farm-agent/tests/conftest.py` | test | N/A | `src/farmos-agent/tests/conftest.py` | role-match (pytest fixture file; async pool fixture vs mock session) |
| `src/farm-agent/tests/test_schema_parity.py` | test | transform | `src/farmos-agent/tests/test_farmos_client.py` | partial (test file shape only; no analog for structural JSON diff) |
| `src/farm-agent/tests/test_foray_seam.py` | test | N/A | none | no analog |
| `src/farm-agent/fixtures/submission_json_schema.json` | config | N/A | none | no analog (generated once from live Node) |
| `docker-compose.override.yml` (modified) | config | N/A | existing `alerter:` block in same file | exact (copy the alerter service block shape) |
| `src/farm-agent/.lint-imports` | config | N/A | none | no analog |

---

## Pattern Assignments

### `src/farm-agent/pyproject.toml` (config)

**Analog:** `src/farmos-agent/setup.py` (lines 1-26) — understand what to depart from.

**Departure notes:** `setup.py` is ament_python (ROS-integrated). `pyproject.toml` is standalone uv. No `package.xml`, no `resource/`, no `ament_index` data_files. The ROS setup.py is shown here only to anchor the contrast:

```python
# src/farmos-agent/setup.py (lines 1-26) -- what we are NOT doing
from setuptools import setup

package_name = 'farmos_agent'
setup(
    name=package_name,
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    entry_points={
        'console_scripts': [
            'farmos_agent = farmos_agent.farmos_agent_node:main',
        ],
    },
)
```

**Pattern to write (from RESEARCH.md FND-01 shape):**

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
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

No analog exists in the repo for a uv pyproject.toml service. This is the authoritative shape from RESEARCH.md.

---

### `src/farm-agent/Dockerfile` (config)

**Analog:** `src/farmos-agent/Dockerfile` (lines 1-16) — understand what to depart from.

**farmos-agent Dockerfile (lines 1-17) -- the ROS shape we are NOT replicating:**

```dockerfile
FROM ros:jazzy-ros-core

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-rmw-cyclonedds-cpp \
    python3-requests \
    python3-psycopg2 \
    python3-apscheduler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
```

**Departures:** No ROS base image. No apt-installed Python packages (uv handles all deps via wheel). No entrypoint.sh shell wrapper. Psycopg[binary] bundles libpq so no `libpq-dev` apt install is needed on slim-bookworm.

**Pattern to write (uv-in-Docker, from RESEARCH.md FND-01):**

```dockerfile
FROM python:3.12-slim-bookworm
RUN pip install uv
WORKDIR /app
# Copy dependency spec first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev
COPY farm_agent/ ./farm_agent/
CMD ["uv", "run", "python", "-m", "farm_agent"]
```

Key: `uv sync --no-dev` creates `.venv/` inside `/app`. `uv run` uses that venv. If `uv run` is not desired at CMD runtime, use `.venv/bin/python -m farm_agent` instead.

---

### `src/farm-agent/farm_agent/__main__.py` (utility, request-response)

**Analog:** `src/farmos-agent/entrypoint.sh` (lines 1-5) — same purpose (start the module), different form.

```bash
# src/farmos-agent/entrypoint.sh (lines 1-5)
#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="/app:${PYTHONPATH}"
exec python3 -m farmos_agent.farmos_agent_node
```

**Pattern to write (Python module entry point):**

```python
# farm_agent/__main__.py
import asyncio
from farm_agent.boot import main

asyncio.run(main())
```

This is the `python -m farm_agent` entry point. Thin wrapper — all logic lives in `boot.py`.

---

### `src/farm-agent/farm_agent/boot.py` (utility, event-driven)

**Analog:** `src/farmos-agent/farmos_agent/farmos_agent_node.py` (partial match -- same "boot and wait" shape but ROS lifecycle vs asyncio SIGTERM).

**Pattern to write (asyncio signal-handling idle loop, from RESEARCH.md FND-01):**

```python
# farm_agent/boot.py
import asyncio
import logging
import os
import signal
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
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await pool.close()
```

**Critical constraint:** `boot.py` is the ONLY module allowed to import across Foray package boundaries (FND-05 enforcement). All other packages import only within their own package or from packages lower in the dependency graph.

---

### `src/farm-agent/farm_agent/tenancy/tenant.py` (utility, request-response)

**Analog:** `src/agents/alerter/src/config.js` (lines 1-265) — the port target.

**`mustEnv` pattern** (config.js lines 7-10):

```javascript
function mustEnv(env, key) {
  const v = env[key];
  if (!v) throw new Error(`[config] Required env var ${key} is missing`);
  return v;
}
```

**Layered `pick` pattern** (config.js lines 67-71):

```javascript
function pick(tenantConfig, env, key, def) {
  if (tenantConfig[key] !== undefined && tenantConfig[key] !== null) return tenantConfig[key];
  if (env[key] !== undefined) return env[key];
  return def;
}
```

**Path-traversal boundary check** (config.js lines 47-64):

```javascript
const TENANTS_BASE = path.resolve(__dirname, '..', '..', '..', '..', 'tenants');

function loadTenantFile(tenantId, filename) {
  const p = path.resolve(TENANTS_BASE, tenantId, filename);
  if (p !== TENANTS_BASE && !p.startsWith(TENANTS_BASE + path.sep)) return {};
  if (!fs.existsSync(p)) return {};
  try {
    const parsed = YAML.parse(fs.readFileSync(p, 'utf8'));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (e) {
    console.warn(`[config] ${p} parse failed: ${e.message}`);
    return {};
  }
}
```

**Farmer map parse** (config.js lines 31-41) -- also handles the YAML object form (config.js lines 75-84):

```javascript
function resolveFarmerMap(tenantConfig, env) {
  const fromTenant = tenantConfig.SIGNAL_FARMER_MAP;
  if (fromTenant && typeof fromTenant === 'object' && !Array.isArray(fromTenant)) {
    const m = new Map();
    for (const [phone, slug] of Object.entries(fromTenant)) {
      if (phone && slug) m.set(String(phone), String(slug));
    }
    return m;
  }
  return parseFarmerMap(env.SIGNAL_FARMER_MAP || '');
}
```

**Python pattern to write (from RESEARCH.md FND-02):**

```python
# tenancy/tenant.py
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from ruamel.yaml import YAML

TENANTS_BASE = Path(__file__).parent.parent.parent.parent / "tenants"

def _must_env(env: dict, key: str) -> str:
    v = env.get(key)
    if not v:
        raise RuntimeError(f"[config] Required env var {key} is missing")
    return v

def _load_tenant_file(tenant_id: str, filename: str) -> dict[str, Any]:
    p = (TENANTS_BASE / tenant_id / filename).resolve()
    if not str(p).startswith(str(TENANTS_BASE) + os.sep):
        return {}
    if not p.exists():
        return {}
    yaml = YAML()
    return yaml.load(p) or {}

def _pick(tenant_cfg: dict, env: dict, key: str, default: Any) -> Any:
    if tenant_cfg.get(key) is not None:
        return tenant_cfg[key]
    if env.get(key) is not None:
        return env[key]
    return default
```

**Layer order** (from config.js comments): `tenant YAML -> env -> hardcoded default`. Secrets (`ANTHROPIC_API_KEY`, `TIMESCALE_PASSWORD`, `SIGNAL_SENDER`, `FARMOS_PASSWORD`) resolved via `_must_env(env, key)` only -- never from YAML.

---

### `src/farm-agent/farm_agent/persistence/pool.py` (service, request-response)

**Analog:** `src/farmos-agent/farmos_agent/farmos_client.py` (lines 19-45) — psycopg connection idiom (sync), which we translate to async pool.

**farmos_client.py psycopg2 session pattern** (lines 19-45):

```python
def get_session(farmos_url: str, username: str, password: str) -> requests.Session:
    session = requests.Session()
    resp = session.post(
        f"{farmos_url}/user/login",
        params={'_format': 'json'},
        json={'name': username, 'pass': password},
        timeout=10,
    )
    resp.raise_for_status()
    csrf = resp.json()['csrf_token']
    session.headers.update({
        'X-CSRF-Token': csrf,
        'Content-Type': 'application/vnd.api+json',
        'Accept': 'application/vnd.api+json',
    })
    return session
```

This is the synchronous psycopg2-era pattern -- injected connection, explicit lifecycle. The pool.py translates the same "explicit lifecycle + caller injects connection" idiom to async:

**psycopg3 async pool pattern (from RESEARCH.md FND-03):**

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
        open=False,   # REQUIRED: defer open until event loop is running
    )
    await pool.open()
    return pool
```

**Critical:** `open=False` + `await pool.open()` is mandatory for async-safe init. Passing `open=True` (default) attempts synchronous connection creation in `__init__`, which is unsafe before the event loop runs.

`options=-c timezone=UTC` enforces UTC at the connection level -- prevents naive datetime bugs (per PITFALLS.md Pitfall 7).

---

### `src/farm-agent/farm_agent/persistence/migrations.py` (utility, batch)

**Analog:** `src/agents/alerter/src/capture-db.js` (lines 6-76) -- the exact idempotent CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS pattern to replicate.

**Core DDL pattern** (capture-db.js lines 6-32):

```javascript
async function initDb(pool) {
  await pool.query(`
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
  `);
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time ON signal_capture (sender, captured_at DESC)`);
  await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_capture_expired ON signal_capture (expired) WHERE expired = false`);
```

**Additive column pattern** (capture-db.js lines 29-58):

```javascript
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text`);
  // ... continues through all Phase 37/44/50/53 columns
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS corpus_context jsonb`);
```

**Python translation (psycopg3 async):**

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
    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time ON signal_capture (sender, captured_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_signal_capture_expired ON signal_capture (expired) WHERE expired = false",
        # Phase 37 ADD COLUMN IF NOT EXISTS:
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text",
        # 999.53:
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS input_tokens int",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS output_tokens int",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_creation_input_tokens int",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS cache_read_input_tokens int",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS model text",
        # Phase 44:
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS extraction_gate VARCHAR(32)",
        # Phase 50:
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS signal_msg_ts bigint",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS quote_msg_ts bigint",
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS quote_author_e164 text",
        # Phase 53:
        "ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS corpus_context jsonb",
    ]:
        await conn.execute(sql)
    # View (idempotent via CREATE OR REPLACE):
    await conn.execute("""
        CREATE OR REPLACE VIEW v_llm_cost_daily AS ...
    """)
```

**Additive-only constraint:** The migration runner MUST NOT issue `DROP TABLE`, `DROP COLUMN`, `DROP INDEX`, `TRUNCATE`, or `ALTER COLUMN ... TYPE` (except the safe `text -> text` no-op on `signal_outbound.related_capture_id` / `related_draft_id`). The Node alerter stack reads the same DB until Phase 65 cutover.

**`signal_outbound` requires:** `CREATE EXTENSION IF NOT EXISTS pgcrypto` (for `gen_random_uuid()`). Must be the first statement in `_run_outbound_migrations`.

**`signal_draft` partial unique index:** `CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_draft_in_flight_per_sender ON signal_draft (sender_e164) WHERE status IN ('pending','awaiting_farmer')` -- Postgres accepts string literals in partial index predicates; use the exact same string literals as the Node source.

---

### `src/farm-agent/farm_agent/extraction/schemas/seeding.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/seeding.js` (lines 1-31)

**Node source:**

```javascript
const BLOCK_NAME_RE = /^[0-9]{6}_[A-Z]{2,4}_[0-9]+$/;

const SeedingLog = z.object({
    type: z.literal('seeding'),
    species: z.string().min(1),
    block_name: z.string().regex(BLOCK_NAME_RE, 'B5 block_name'),
    qty: z.number().int().positive(),
    event_timestamp: z.string().datetime(),
    parent_batch_name: z.string().min(1).optional(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
}).strict();
```

**Pydantic translation:**

```python
# extraction/schemas/seeding.py
from pydantic import BaseModel, ConfigDict, Field, field_validator

BLOCK_NAME_RE = r'^[0-9]{6}_[A-Z]{2,4}_[0-9]+$'

class SeedingLog(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['seeding']
    species: str = Field(min_length=1)
    block_name: str = Field(pattern=BLOCK_NAME_RE)
    qty: int = Field(gt=0)
    event_timestamp: str          # str NOT datetime; see FND-04 Pitfall 1
    parent_batch_name: str | None = Field(default=None, min_length=1)
    notes: str | None = None
    confidence: dict[str, float]

    @field_validator('event_timestamp')
    @classmethod
    def validate_datetime_has_T(cls, v: str) -> str:
        if 'T' not in v:
            raise ValueError('event_timestamp must be ISO-8601 with T separator')
        return v
```

**Critical translation rules:**
- `z.number().int().positive()` -> `int = Field(gt=0)` (NOT `Field(ge=1)` which emits `minimum:1` vs zod's `exclusiveMinimum:0`)
- `z.string().datetime()` -> `str` + T-separator validator (bare date `2025-06-14` passes Python `datetime.fromisoformat` but would fail zod's `.datetime()`)
- `.strict()` -> `model_config = ConfigDict(extra='forbid')` on EVERY model including nested ones
- `z.record(z.string(), z.number().min(0).max(1))` -> `dict[str, float]`
- `z.string().min(1).optional()` -> `str | None = Field(default=None, min_length=1)`

---

### `src/farm-agent/farm_agent/extraction/schemas/activity.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/activity.js` (lines 1-23)

**Node source:**

```javascript
const ACTIVITY_NAMES = ['sterilize', 'sterilize_failed', 'water', 'relocate', 'cold_shock', 'archive_spent', 'contam'];

const ActivityLog = z.object({
    type: z.literal('activity'),
    name: z.enum(ACTIVITY_NAMES),
    asset_ref: z.string().min(1),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
}).strict();
```

**Pydantic translation:**

```python
class ActivityLog(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['activity']
    name: Literal['sterilize', 'sterilize_failed', 'water', 'relocate', 'cold_shock', 'archive_spent', 'contam']
    asset_ref: str = Field(min_length=1)
    event_timestamp: str   # str + T-validator (same as SeedingLog)
    notes: str | None = None
    confidence: dict[str, float]
```

`z.enum([...])` with no discriminator -> `Literal[..., ...]`. Do NOT use `enum.Enum` -- it changes the JSON Schema shape.

---

### `src/farm-agent/farm_agent/extraction/schemas/observation.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/observation.js` (lines 1-31)

**Node source -- two-export pattern (base vs refine):**

```javascript
const ObservationLogBase = z.object({
    type: z.literal('observation'),
    asset_ref: z.string().min(1),
    state: z.string().optional(),
    notes: z.string().optional(),
    event_timestamp: z.string().datetime(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
}).strict();

const ObservationLog = ObservationLogBase.refine(hasStateOrNotes, {
    message: 'observation requires state or notes',
    path: ['state'],
});
```

**Pydantic translation -- critical: discriminated union uses Base, standalone uses validator:**

```python
# extraction/schemas/observation.py
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

class ObservationLogBase(BaseModel):
    """Base shape -- used in discriminated union (no cross-field validator)."""
    model_config = ConfigDict(extra='forbid')
    type: Literal['observation']
    asset_ref: str = Field(min_length=1)
    state: str | None = None
    notes: str | None = None
    event_timestamp: str   # str + T-validator
    confidence: dict[str, float]

class ObservationLog(ObservationLogBase):
    """Standalone use -- adds cross-field validator replicating .refine()."""
    @model_validator(mode='after')
    def state_or_notes_required(self) -> 'ObservationLog':
        if not self.state and not self.notes:
            raise ValueError('observation requires state or notes')
        return self
```

The discriminated union in `submission.py` uses `ObservationLogBase` (no validator) to match zod's `discriminatedUnion` requirement for pure `z.object` inputs.

---

### `src/farm-agent/farm_agent/extraction/schemas/harvest.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/harvest.js` (lines 1-21)

**Node source:**

```javascript
const HarvestLog = z.object({
    type: z.literal('harvest'),
    harvest_batch_id: z.string().min(1),
    source_block_refs: z.array(z.string().min(1)).min(1),
    qty_g: z.number().positive(),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
}).strict();
```

**Pydantic translation:**

```python
class HarvestLog(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['harvest']
    harvest_batch_id: str = Field(min_length=1)
    source_block_refs: list[str] = Field(min_length=1)
    qty_g: float = Field(gt=0)   # z.number().positive() -> float Field(gt=0)
    event_timestamp: str
    notes: str | None = None
    confidence: dict[str, float]
```

`z.number().positive()` (non-integer) -> `float = Field(gt=0)`.

---

### `src/farm-agent/farm_agent/extraction/schemas/input.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/input.js` (lines 1-19)

**Node source:**

```javascript
const InputLog = z.object({
    type: z.literal('input'),
    recipe_lot: z.string().min(1),
    asset_ref: z.string().min(1),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
}).strict();
```

**Pydantic translation:**

```python
class InputLog(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['input']
    recipe_lot: str = Field(min_length=1)
    asset_ref: str = Field(min_length=1)
    event_timestamp: str
    notes: str | None = None
    confidence: dict[str, float]
```

---

### `src/farm-agent/farm_agent/extraction/schemas/provenance.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/provenance.js` (lines 1-38)

**Node source -- factory function shape:**

```javascript
const SOURCE_ENUM = z.enum(['audio', 'paper_log_photo', 'bag_label_photo', 'text', 'model_inference']);

function Provenanced(valueSchema) {
  return z.object({
    value: valueSchema,
    confidence: z.number().min(0).max(1),
    sources: z.array(SOURCE_ENUM).min(1),
  }).strict();
}
```

**Critical JSON Schema shape:** The Node `Provenanced(ParentRef)` emits as an **inline object** `{value, confidence, sources[]}` with `additionalProperties: false` -- NOT as a `$ref`. This must be replicated in pydantic via Generic.

**Pydantic translation:**

```python
# extraction/schemas/provenance.py
from pydantic import BaseModel, ConfigDict, Field
from typing import Generic, Literal, TypeVar

T = TypeVar('T')

SourceEnum = Literal['audio', 'paper_log_photo', 'bag_label_photo', 'text', 'model_inference']

class Provenanced(BaseModel, Generic[T]):
    model_config = ConfigDict(extra='forbid')
    value: T
    confidence: float = Field(ge=0, le=1)
    sources: list[SourceEnum] = Field(min_length=1)
```

The Generic[T] approach matches the factory function pattern. Each callsite in `seeding_session.py` uses e.g. `Provenanced[str]`, `Provenanced[int]`, `Provenanced[list[ChildBlockNameOrSentinel]]`.

---

### `src/farm-agent/farm_agent/extraction/schemas/seeding_session.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/seeding-session.js` (lines 1-91)

**Key nested structures (node source lines 40-83):**

```javascript
const SeedingSessionGroup = z.object({
    parent: Provenanced(ParentRef),
    species: Provenanced(z.string().regex(/^[A-Z]{2,4}$/)),
    qty: Provenanced(z.number().int().positive()),
    child_block_names: Provenanced(z.array(ChildBlockNameOrSentinel).min(1)),
}).strict();

const SeedingSession = z.object({
    type: z.literal('seeding_session'),
    event_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'YYYY-MM-DD'),
    groups: z.array(SeedingSessionGroup).min(1),
    needs_input: z.enum(['starting_seq']).optional(),
    conflicts: z.array(ConflictEntry).optional(),
    notes: z.string().optional(),
}).strict();
```

**Critical:** `event_date` uses a bare date regex (NOT `.datetime()`). Python: `str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')`.

**ChildBlockNameOrSentinel** (node lines 29-33):

```javascript
const ChildBlockNameOrSentinel = z.union([
    z.literal('NEEDS_SEQ'),
    z.string().regex(BLOCK_NAME_RE, 'B5 block_name'),
]);
```

Python: `Annotated[str, Field(pattern=BLOCK_NAME_RE)] | Literal['NEEDS_SEQ']` -- but the union order matters for JSON Schema shape. Put `Literal['NEEDS_SEQ']` first to match the anyOf member order.

---

### `src/farm-agent/farm_agent/extraction/schemas/submission.py` (model, transform)

**Analog:** `src/agents/alerter/src/extraction/schemas/index.js` (lines 1-102) -- the top-level assembly.

**Node source (lines 31-81):**

```javascript
const Draft = z.discriminatedUnion('type', [
    SeedingLog, ActivityLog, InputLog, ObservationLogBase, HarvestLog, SeedingSession,
]);

const DraftSubmission = z.object({
    draft: Draft,
    per_field_confidence: z.record(z.string(), z.number().min(0).max(1)),
}).strict();

const Submission = z.object({
    drafts: z.array(DraftSubmission).min(1),
    continuity: z.enum(['append', 'replace', 'start_new']),
    continuity_reason: z.string().min(1),
    capture_kind: CAPTURE_KIND_ENUM.nullable().optional(),
}).strict();

const SUBMISSION_JSON_SCHEMA = zodToJsonSchema(Submission, 'Submission');
```

**Pydantic translation:**

```python
# extraction/schemas/submission.py
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Literal, Union

DraftUnion = Annotated[
    Union[SeedingLog, ActivityLog, InputLog, ObservationLogBase, HarvestLog, SeedingSession],
    Field(discriminator='type')
]

class DraftSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    draft: DraftUnion
    per_field_confidence: dict[str, float]

CaptureKind = Literal['paper_log', 'physical_object_photo', 'voice_note', 'text']

class Submission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    drafts: list[DraftSubmission] = Field(min_length=1)
    continuity: Literal['append', 'replace', 'start_new']
    continuity_reason: str = Field(min_length=1)
    capture_kind: CaptureKind | None = None

SUBMISSION_JSON_SCHEMA = Submission.model_json_schema()
```

**FND-04 fixture note:** The committed fixture (`fixtures/submission_json_schema.json`) is the RAW Node `SUBMISSION_JSON_SCHEMA` output -- top-level `{"$ref": "#/definitions/Submission", "definitions": {...}, "$schema": "...draft-07..."}`. Pydantic emits `{"type": "object", ...}` at the root (no top-level `$ref`). The `normalize_schema()` function in the test reconciles `$defs` -> `definitions` and `#/$defs/` -> `#/definitions/` before the structural diff.

---

### `src/farm-agent/tests/conftest.py` (test)

**Analog:** `src/farmos-agent/tests/conftest.py` (lines 1-48)

**farmos-agent conftest shape** (lines 1-14):

```python
import pytest
from unittest.mock import MagicMock
import farmos_agent.farmos_client as _farmos_client_module

@pytest.fixture(autouse=True)
def clear_asset_uuid_cache():
    _farmos_client_module._asset_uuid_cache.clear()
    yield
    _farmos_client_module._asset_uuid_cache.clear()

@pytest.fixture
def mock_farmos_session():
    session = MagicMock(spec=requests.Session)
    ...
    return session
```

**Pattern to write (async pool fixture for integration tests):**

```python
# tests/conftest.py
import os
import pytest_asyncio
from farm_agent.tenancy.tenant import load as load_config
from farm_agent.persistence.pool import build_pool
from farm_agent.persistence.migrations import run_migrations

TEST_ENV = {
    "TENANT_ID": "test",
    "TIMESCALE_HOST": os.environ.get("TEST_TIMESCALE_HOST", "localhost"),
    "TIMESCALE_DB": os.environ.get("TEST_TIMESCALE_DB", "test_farm_agent"),
    "TIMESCALE_USER": os.environ.get("TEST_TIMESCALE_USER", "postgres"),
    "TIMESCALE_PASSWORD": os.environ.get("TEST_TIMESCALE_PASSWORD", "postgres"),
    "SIGNAL_SENDER": "+10000000000",  # placeholder -- never used in Phase 56 tests
    "ANTHROPIC_API_KEY": "test-key",
    "FARMOS_PASSWORD": "test-pass",
    # ... all other required fields with test defaults
}

@pytest_asyncio.fixture(scope="session")
async def pool():
    config = load_config(TEST_ENV)
    p = await build_pool(config)
    await run_migrations(p)
    yield p
    await p.close()
```

**Key departure from farmos-agent:** The pool fixture is `async` (pytest-asyncio) and session-scoped. farmos-agent uses synchronous `requests.Session` mocks. The farm-agent conftest wires a real async pool against the test TimescaleDB instance (port 5434 per RESEARCH.md Environment Availability section).

---

### `docker-compose.override.yml` (modified -- `alerter-py` service added)

**Analog:** Existing `alerter:` block in `docker-compose.override.yml` (lines 62-169).

**env_file string form** (lines 79-86 -- the hotfix pattern to copy exactly):

```yaml
env_file:
  # 2026-05-23 hotfix: simple string form for compose v2.40 — the object form
  # (`- path: ... required: false`) parses to env_file:None silently on this
  # version ...
  - tenants/mossrock/secrets.env
```

**Networks block** (lines 167-169):

```yaml
networks:
  - signal-net
  - default
```

**Pattern to write for `alerter-py`:**

```yaml
alerter-py:
  build:
    context: ./src/farm-agent
    dockerfile: Dockerfile
  restart: unless-stopped
  env_file:
    - tenants/mossrock/secrets.env   # STRING form -- NOT object form (compose v2.40 bug)
  environment:
    - TENANT_ID=mossrock
    - TIMESCALE_HOST=${TIMESCALE_HOST:-timescale}
    - TIMESCALE_DB=${TIMESCALE_DB:-postgres}
    - TIMESCALE_USER=${TIMESCALE_USER:-postgres}
    - TIMESCALE_PASSWORD=${TIMESCALE_PASSWORD}
    # ... mirror all env vars from the alerter: block above
  networks:
    - signal-net
    - default
```

**CRITICAL:** Use the string list form `- tenants/mossrock/secrets.env` (NOT `- path: ... required: false`). The object form silently drops on compose v2.40 (confirmed prod outage 2026-05-23; memory `feedback_compose_env_file_object_form_silently_drops`).

---

## Shared Patterns

### Idempotent DDL (additive-only guard)

**Source:** `src/agents/alerter/src/capture-db.js` lines 6-76 (also `outbound-db.js`, `extraction-db.js`, `commit-db.js`)
**Apply to:** `persistence/migrations.py`

```javascript
// The Node pattern every migration function follows:
await pool.query(`CREATE TABLE IF NOT EXISTS ...`);
await pool.query(`CREATE INDEX IF NOT EXISTS ...`);
await pool.query(`ALTER TABLE x ADD COLUMN IF NOT EXISTS col type`);
// Never: DROP, TRUNCATE, ALTER COLUMN TYPE (except text->text no-op)
```

Python translation: `await conn.execute(sql)` in a loop over additive-only SQL strings.

### `extra='forbid'` on every pydantic model

**Source:** `src/agents/alerter/src/extraction/schemas/seeding.js` line 29 (`.strict()`)
**Apply to:** Every class in `extraction/schemas/` including nested models inside `seeding_session.py` and `provenance.py`

```python
model_config = ConfigDict(extra='forbid')
```

This MUST appear on every `BaseModel` subclass, including `DraftSubmission`, `Submission`, `SeedingSessionGroup`, `ConflictEntry`, the `Provenanced` generic, and candidate nested classes. Missing `extra='forbid'` on any nested model will cause the FND-04 parity test to fail because pydantic won't emit `"additionalProperties": false` for that model.

### Secret isolation (no business module reads env directly)

**Source:** `src/agents/alerter/src/config.js` lines 7-10 (`mustEnv`) + FND-02 lock
**Apply to:** ALL modules in `farm_agent/` except `tenancy/tenant.py` and `boot.py`

The `_must_env` / `load_config` functions are the only code that calls `os.environ`. All other modules receive config via function argument injection. CI check to enforce: `grep -r "os.environ" farm_agent/ --include='*.py' | grep -v tenancy/tenant.py | grep -v boot.py` must return empty.

### T-separator datetime validation

**Source:** `src/agents/alerter/src/extraction/schemas/seeding.js` line 24 (`z.string().datetime()`)
**Apply to:** All pydantic models with `event_timestamp: str` fields (SeedingLog, ActivityLog, InputLog, ObservationLogBase, HarvestLog)

```python
@field_validator('event_timestamp')
@classmethod
def validate_datetime_has_T(cls, v: str) -> str:
    if 'T' not in v:
        raise ValueError('event_timestamp must be ISO-8601 with T separator')
    return v
```

Do NOT use `datetime` type -- bare dates like `2025-06-14` pass Python's `datetime.fromisoformat` but would fail zod's `.datetime()`. Keeping as `str` + T-check preserves schema parity (both emit `{"type": "string"}` without `"format": "date-time"`).

### Compose env_file string form

**Source:** `docker-compose.override.yml` lines 79-86
**Apply to:** `alerter-py` service block in `docker-compose.override.yml`

Always `- tenants/mossrock/secrets.env` (bare string), never the object form. Document the reason inline as the existing alerter block does.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/fixtures/submission_json_schema.json` | config | N/A | Generated once via Node script; no existing committed JSON fixture pattern in the repo |
| `tests/test_foray_seam.py` | test | N/A | No existing seam-enforcement tests; novel for this project |
| `src/farm-agent/.lint-imports` | config | N/A | No import-linter config exists in repo; optional in Phase 56 (grep gate is primary) |

---

## Deliberate Departures from Analogs

| Analog Pattern | Phase 56 Departure | Reason |
|----------------|-------------------|--------|
| `FROM ros:jazzy-ros-core` (farmos-agent Dockerfile line 1) | `FROM python:3.12-slim-bookworm` | alerter has zero ROS dependency; standalone daemon |
| `python3-psycopg2` apt package (farmos-agent Dockerfile line 6) | `psycopg[binary]>=3.3` via uv | psycopg3 is native async; psycopg2 requires thread wrappers for asyncio |
| `setup.py` + ament_python (farmos-agent) | `pyproject.toml` + uv | not a ROS package; uv gives deterministic lockfile + fast Docker layers |
| `entrypoint.sh` shell wrapper (farmos-agent) | `__main__.py` + `CMD ["uv", "run", ...]` | no ROS env to source; Python module entry point is cleaner |
| Synchronous psycopg2 `connect()` (farmos_client.py) | `AsyncConnectionPool(open=False)` + `await pool.open()` | asyncio daemon requires non-blocking DB; pool shared across all packages |
| Node `config.js` reads env directly everywhere | `tenancy/TenantConfig` is the sole env reader | FND-02 constraint; enforced via CI grep gate |
| No migration tool in Node alerter (inline DDL in `initDb`) | Same pattern ported to Python (no alembic) | D-02 lock; additive-only constraint makes idempotent CREATE IF NOT EXISTS sufficient |

---

## Metadata

**Analog search scope:** `src/farmos-agent/`, `src/agents/alerter/src/`, `docker-compose.override.yml`
**Files scanned:** 22 source files read in full
**Pattern extraction date:** 2026-06-15
