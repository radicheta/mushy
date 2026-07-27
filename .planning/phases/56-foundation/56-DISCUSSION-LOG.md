# Phase 56: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 56-Foundation
**Areas discussed:** DB driver (Migration approach, Repo location + names, Schema-parity gate deferred to Claude's discretion)

---

## DB driver

| Option | Description | Selected |
|--------|-------------|----------|
| psycopg3 | API continuity with farmos-agent's psycopg2, one Postgres idiom repo-wide, async pool, low-volume workload makes asyncpg's speed edge moot | ✓ |
| asyncpg | ~25-35% faster bulk inserts, but different API ($1 params, custom codecs), no sync mode, second Postgres idiom | |

**User's choice:** psycopg3
**Notes:** Overrides ARCHITECTURE.md's asyncpg lean; aligns with STACK.md + SUMMARY.md. Decision driven by API continuity (mechanical port of Node `pg` calls) and one idiom repo-wide, not performance.

---

## Claude's Discretion

Santi selected only "DB driver" to discuss; the following were presented with defaults and deferred to Claude:
- **Migration approach** — default: idempotent `CREATE TABLE IF NOT EXISTS` on boot (mirrors Node, which has no migration tool) + additive-only guard vs the shared live schema. No heavyweight migration tool unless planning finds a need.
- **Repo location + package names** — default: `src/farm-agent/` with Foray-island packages (signal_io/extraction/confirm/farmos_client/capture/persistence/tenancy/llm) and `chamber/` as the sole mushy-private package.
- **Schema-parity gate (FND-04)** — default: commit Node's emitted JSON Schema as a fixture + pytest structural diff (vs live cross-process compare).

## Deferred Ideas

- Generalizing the origin guard into a full dev/prod origin split — v1.13 watchdog-origin-guard candidate (Phase 62 ships only the minimal guard).
