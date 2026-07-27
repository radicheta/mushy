# Phase 56: Foundation - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

The Python asyncio skeleton for the alerter port — the wiring harness everything else builds on. Delivers: the package layout (Foray-island packages + `chamber/` as the only mushy-private package), the `tenancy/TenantConfig` primitive, the `persistence/` async DB pool + schema/migrations, the zod→pydantic JSON-Schema parity gate (FND-04), and the Foray CI seam (FND-05). NO business behavior — no Signal I/O, no extraction, no farmOS writes. Those are phases 57+.

Requirements in scope: **FND-01, FND-02, FND-03, FND-04, FND-05** (see REQUIREMENTS.md).

</domain>

<decisions>
## Implementation Decisions

### DB driver (discussed + locked with Santi)
- **D-01: psycopg3** is the Postgres driver. Rationale: API continuity with `src/farmos-agent/` (psycopg2) keeps one Postgres idiom repo-wide; near-mechanical translation of the Node `pg` calls; the workload (farmer messages + watchdog ticks) is low-volume so asyncpg's ~25-35% bulk-insert edge is irrelevant. Async via `psycopg_pool.AsyncConnectionPool`; `[binary]` extra bundles libpq. This overrides ARCHITECTURE.md's asyncpg lean (STACK.md + SUMMARY.md already recommended psycopg3).

### Claude's Discretion (defaults stated during discuss; Santi deferred these)
- **D-02: Migration approach** — keep the Node pattern of idempotent `CREATE TABLE IF NOT EXISTS` on boot (the Node alerter has NO migration tool; schema is created inline in `capture-db.js` / `outbound-db.js`). Add an additive-only guard: the Python stack must NOT issue any DROP/ALTER that breaks the schema the live Node stack still reads (both share the same TimescaleDB until cutover). No heavyweight migration tool (alembic/yoyo) unless planning finds a concrete need.
- **D-03: Repo location + package names** — Python stack lives under `src/farm-agent/` (matches the long-standing "farm-agent" naming in the port todo `2026-05-14-port-alerter-to-farm-agent-python.md`). Foray-island packages: `signal_io/`, `extraction/`, `confirm/`, `farmos_client/`, `capture/`, `persistence/`, `tenancy/`, `llm/`; mushy-private: `chamber/`. `boot.py` is the only module allowed to import across all packages. Final names are at planning discretion if a cleaner split emerges, but `chamber/` MUST be the sole private package (the Foray seam depends on it).
- **D-04: Schema-parity gate (FND-04)** — commit Node's emitted JSON Schema (`SUBMISSION_JSON_SCHEMA` from the zod `zod-to-json-schema` output) as a fixture file, and assert structural equality against pydantic's `model_json_schema()` in a pytest. Prefer a committed-fixture + structural-diff test over a live cross-process compare (deterministic, runs in CI without Node). `extra='forbid'` on every nested pydantic model; cross-field validators ported as `model_validator(mode='after')`.

### Cross-cutting constraints (from milestone + research — carry into planning)
- Foray seam (FND-05) is enforced by a CI check that FAILS the build if any non-`chamber` package imports from `chamber/` (grep gate).
- `tenancy/TenantConfig` is the lowest node in the dependency graph; no business module reads `os.environ` directly; secrets (API keys, DB password) stay env-only.
- Schema additions are additive-only vs the live shared schema (the Node stack keeps reading it until Phase 65 cutover).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone scope + strategy
- `.planning/REQUIREMENTS.md` — v1.12 requirements; FND-01..05 are this phase
- `.planning/PROJECT.md` §"Current Milestone: v1.12 Farm-Agent Python Port" — locked strategy (big-bang, port+cleanup, Foray seams)

### Research (committed `c702eea`)
- `.planning/research/SUMMARY.md` — synthesized stack + build order; recommends psycopg3
- `.planning/research/STACK.md` — library versions, signal-cli interop, what NOT to add
- `.planning/research/ARCHITECTURE.md` — package layout, dependency arrows, Foray seam, build order
- `.planning/research/PITFALLS.md` — zod→pydantic JSON-Schema drift (the FND-04 gate's reason for existing); ID-type drift

### Code to port / reference
- `src/agents/alerter/package.json` — Node deps to map to Python equivalents
- `src/agents/alerter/src/capture-db.js`, `src/agents/alerter/src/outbound-db.js` — current inline `CREATE TABLE` schema (no migration tool); the source of truth for `persistence/` tables
- `src/agents/alerter/src/extraction/schemas/` — the zod schemas whose JSON-Schema output FND-04 must match
- `src/farmos-agent/` — existing Python service precedent (psycopg2; but note it's ROS ament_python, NOT uv — the port deliberately uses uv/pyproject/non-ROS)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/farmos-agent/farmos_agent/farmos_client.py` — existing Python farmOS client + psycopg2 usage patterns; a reference for the eventual `farmos_client/` package (Phase 62) and for psycopg idioms now.
- The Node `capture-db.js` / `outbound-db.js` table DDL — port verbatim (additive-only) into `persistence/` migrations.

### Established Patterns
- Node alerter has NO migration framework — tables created via idempotent `CREATE TABLE IF NOT EXISTS` at boot. The Python port mirrors this (D-02).
- `farmos-agent` is an ament_python ROS package (setup.py/package.xml). The alerter port intentionally departs: standalone `uv` + `pyproject.toml`, `python:3.12-slim` base (no ROS) — the alerter has zero ROS dependency.
- Tenancy already exists as `tenants/<id>/` config dirs (live alerter config is compose ENV, not tenant YAML — see memory `project_alerter_config_env_not_tenant_yaml_live`); TenantConfig must layer YAML + env.

### Integration Points
- Shared TimescaleDB (same instance the Node alerter + bridge use) — `persistence/` connects here; additive-only schema; prod-leak hazard means validation/shadow runs use an isolated DB (Phase 64), not this one.
- Docker compose — a new `alerter-py` service (built from `src/farm-agent/`) joins the existing compose; coexists with the Node `alerter` until cutover.

</code_context>

<specifics>
## Specific Ideas

- "farm-agent" is the intended name (from the 2026-05-14 port todo) — use `src/farm-agent/`.
- The JSON-Schema parity gate is the single most important FND deliverable: it is the structural defense against the zod→pydantic drift that PITFALLS.md ranks as the #1 silent-regression risk. It must pass BEFORE any LLM call exists in the Python stack (so it lands in this foundation phase, not the extraction phase).

</specifics>

<deferred>
## Deferred Ideas

- Generalizing the additive-only origin guard into a full dev/prod origin split — that's the v1.13 watchdog-origin-guard candidate; Phase 62 ships only the minimal guard.

### Reviewed Todos (not folded)
- `2026-05-21-alerter-tz-montevideo...` — keyword-matched but belongs to Phase 63 (CHM-02); already tagged `resolves_phase: 63`.
- `2026-05-14-port-alerter-to-farm-agent-python.md` — the milestone umbrella; resolved across all of v1.12, not foldable into one phase.
- `2026-05-24-phase50-quote-thread-missing...` / `2026-05-25-cycle-1-finding-batch-mode...` — keyword false-positives for 56; belong to Phases 57 / 60.

</deferred>

---

*Phase: 56-Foundation*
*Context gathered: 2026-06-15*
