---
phase: 63
slug: chamber-alerter
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-13
---

# Phase 63 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Detailed detector/config/TZ/seam assertions are specified in the
> `## Validation Architecture` section of `63-RESEARCH.md`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥9.1 + pytest-asyncio (uv-managed; `asyncio_mode = "auto"`) |
| **Config file** | src/farm-agent/pyproject.toml |
| **Quick run command** | `cd src/farm-agent && uv run pytest tests/chamber/ -x` |
| **Full suite command** | `cd src/farm-agent && uv run pytest tests/ && uv run lint-imports` |
| **Estimated runtime** | ~30 seconds (unit-heavy; no live bridge/DB in CI path) |

---

## Sampling Rate

- **After every task commit:** `cd src/farm-agent && uv run pytest tests/chamber/ -x`
- **After every plan wave:** `cd src/farm-agent && uv run pytest tests/ && uv run lint-imports`
- **Before `/gsd:verify-work`:** Full suite green including the newly-activated lint-imports contract
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 63-01-01 | 01 | 1 | CHM-01 (D-00) | T-63-01/02 | seam gate enforced both ways | integration | `cd src/farm-agent && uv run lint-imports && uv run pytest tests/test_import_linter_contract.py -x` | ❌ W0 | ⬜ pending |
| 63-01-02 | 01 | 1 | CHM-01 (D-00) | T-63-01 | grep gate scans all 8 Foray pkgs | integration | `cd src/farm-agent && uv run pytest tests/test_foray_seam.py -x` | ✓ update | ⬜ pending |
| 63-02-01 | 02 | 1 | CHM-01 | T-63-SC | package legitimacy verified | manual (blocking) | operator verifies pypi.org | — | ⬜ pending |
| 63-02-02 | 02 | 1 | CHM-01 | T-63-SC | deps installed, importable | smoke | `cd src/farm-agent && uv run python -c "import websockets; from zoneinfo import ZoneInfo; ZoneInfo('America/Montevideo')"` | — | ⬜ pending |
| 63-03-01 | 03 | 1 | CHM-01 (D-03) | T-63-03 | rate cap self-sufficient after field move | unit | `cd src/farm-agent && uv run pytest tests/test_signal_ratecap.py tests/test_tenancy.py -x` | ✓ update | ⬜ pending |
| 63-03-02 | 03 | 1 | CHM-02 (D-02/D-04) | T-63-04 | secrets injected, Montevideo default | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_config.py -x` | ❌ W0 | ⬜ pending |
| 63-04-01 | 04 | 2 | CHM-01 (D-07) | T-63-12 | detectors: stale-suspend, fc1-dark 3min | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_rules.py -x` | ❌ W0 | ⬜ pending |
| 63-04-02 | 04 | 2 | CHM-01 | T-63-05/06 | snooze parser no-raise, whitelisted | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_snooze.py -x` | ❌ W0 | ⬜ pending |
| 63-05-01 | 05 | 2 | CHM-02 (SC2) | T-63-08 | all time renders Montevideo/UYT | unit (snapshot) | `cd src/farm-agent && uv run pytest tests/chamber/test_message.py -x` | ❌ W0 | ⬜ pending |
| 63-05-02 | 05 | 2 | CHM-01 | T-63-09 | heartbeat defers on empty summary | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_heartbeat.py -x` | ❌ W0 | ⬜ pending |
| 63-06-01 | 06 | 2 | CHM-01 | T-63-10/11 | ws client fail-open, injected http | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_ws_client.py -x` | ❌ W0 | ⬜ pending |
| 63-06-02 | 06 | 2 | CHM-01 (SC1 timing) | T-63-10 | backoff 1s→30s doubling parity | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_ws_client.py -x` | ❌ W0 | ⬜ pending |
| 63-07-01 | 07 | 3 | CHM-01 (D-01) | T-63-12 | Tier A/B/C + freshness resolver | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_state.py -x -k "resolve or has_mode or stale or initial"` | ❌ W0 | ⬜ pending |
| 63-07-02 | 07 | 3 | CHM-01 (D-06/D-07) | T-63-12/13 | fast-fire override, mode-swap cooldown | unit | `cd src/farm-agent && uv run pytest tests/chamber/test_state.py -x` | ❌ W0 | ⬜ pending |
| 63-08-01 | 08 | 4 | CHM-01 (D-06) | T-63-14 | service composes, in-memory FSM | smoke | `cd src/farm-agent && uv run python -c "from farm_agent.chamber import service"` | ❌ W0 | ⬜ pending |
| 63-08-02 | 08 | 4 | CHM-01 (SC1/D-05) | T-63-14/15/16 | one loop, composite dispatch, SC1 | integration | `cd src/farm-agent && uv run pytest tests/chamber/test_service_wiring.py tests/test_boot.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · Populated by the planner from RESEARCH.md Validation Architecture.*

---

## Wave 0 Requirements

- [ ] Corrected `src/farm-agent/.lint-imports` `source_modules` (Plan 01, Pitfall 7) + `test_foray_seam.py` `FORAY_PACKAGES` list (Plan 01, Pitfall 8)
- [ ] `tests/test_import_linter_contract.py` — new, wires lint-imports into pytest for the first time (Plan 01, D-00)
- [ ] `uv add websockets tzdata` + legitimacy gate (Plan 02)
- [ ] `tests/chamber/__init__.py` + `tests/chamber/conftest.py` — ChamberConfig test factory (Plan 03)
- [ ] Montevideo/UYT snapshot fixture for the CHM-02 TZ assertion (Plan 05, `test_hhmm_renders_montevideo_not_utc`)
- [ ] Update `tests/test_tenancy.py` + `tests/test_signal_ratecap.py` for the D-03 field move (Plan 03)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Package legitimacy of websockets + tzdata | CHM-01 | Supply-chain gate ([ASSUMED] names) | Verify both on pypi.org before `uv add` (Plan 02 Task 1, blocking-human) |
| Live pi-offline Signal alert to f1 on fc-core stop | CHM-01 (SC1) | Requires live fc1 + Signal container | Induce fc-core stop / bridge disconnect; confirm f1 receives pi-offline alert within timeout. (The automated `test_bridge_disconnect_fires_pi_alert` proves the FSM timing with an injected fake client; live send is prod-readiness confirmation.) |

*The SC1 timing behavior has automated coverage (Plan 08 Task 2); the live send to a real phone is the only manual leg.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
