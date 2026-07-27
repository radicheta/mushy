---
phase: 56
slug: foundation
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-15
---

# Phase 56 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 1.x (`asyncio_mode = "auto"`) |
| **Config file** | `src/farm-agent/pyproject.toml` ([tool.pytest.ini_options]) — Wave 0 installs |
| **Quick run command** | `cd src/farm-agent && uv run pytest tests/unit/ -q` |
| **Full suite command** | `cd src/farm-agent && uv run pytest -q` |
| **Estimated runtime** | ~15 seconds (no live DB; migrations run against an ephemeral test Postgres or tmp schema) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/ -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 56-xx | TBD | 1 | FND-01 | — | daemon boots, structured logs, no secrets logged | integration | `docker compose up alerter-py` logs "boot complete" <5s | ❌ W0 | ⬜ pending |
| 56-xx | TBD | 1 | FND-02 | T-56-01 | secrets env-only; no os.environ in business modules | unit | `pytest tests/unit/test_config.py` + grep guard | ❌ W0 | ⬜ pending |
| 56-xx | TBD | 1 | FND-03 | — | additive-only migrations; idempotent re-run | integration | `pytest tests/integration/test_migrations.py` (run twice → no-op) | ❌ W0 | ⬜ pending |
| 56-xx | TBD | 2 | FND-04 | — | pydantic JSON-Schema == committed Node fixture | unit | `pytest tests/unit/test_schema_parity.py` (zero diff) | ❌ W0 | ⬜ pending |
| 56-xx | TBD | 1 | FND-05 | — | no non-chamber import of chamber/ | unit | `pytest tests/unit/test_foray_seam.py` (grep gate) | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · Task IDs finalized by planner.*

---

## Wave 0 Requirements

- [ ] `src/farm-agent/pyproject.toml` — uv project + pytest config (`asyncio_mode = "auto"`)
- [ ] `src/farm-agent/tests/conftest.py` — shared fixtures (ephemeral test Postgres / tmp schema, TenantConfig fixture)
- [ ] `src/farm-agent/tests/fixtures/submission_json_schema.json` — committed Node `SUBMISSION_JSON_SCHEMA` fixture (generated once via node script) for FND-04 parity test
- [ ] pytest + pytest-asyncio + psycopg[binary] + psycopg-pool installed via `uv sync`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `docker compose up alerter-py` boot-in-5s on the real elder-plops host | FND-01 | Compose + host networking + shared-DB reachability is environment-specific | Bring up the service on elder-plops; confirm "boot complete" log line within 5s and the Node `alerter` is unaffected |

*All schema/config/migration/seam behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-15 (gsd-plan-checker PASS, 0 blockers)
