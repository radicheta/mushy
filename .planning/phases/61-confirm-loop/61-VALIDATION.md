---
phase: 61
slug: confirm-loop
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-28
---

# Phase 61 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv) |
| **Config file** | src/farm-agent/pyproject.toml |
| **Quick run command** | `cd src/farm-agent && uv run pytest -q tests/confirm/` |
| **Full suite command** | `cd src/farm-agent && uv run pytest -q` |
| **Estimated runtime** | ~3s (pure FSM) + DB-gated race tests skip without :5434 |

---

## Sampling Rate

- **After every task commit:** run the quick command for the touched confirm test file.
- **After every plan wave:** run the full suite.
- **Before verification:** full suite green (DB-gated tests run against :5434 when available).
- **Max feedback latency:** ~5s.

---

## Per-Task Verification Map

> Refined by the planner per plan. Baseline expectations:

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 61-XX | foundation | 1 | CNF-01 | — | TenantConfig fields (draft_nudge_fraction=0.8, max_edit_turns); confirm_repo never-throws | unit | `uv run pytest -q tests/confirm/test_confirm_repo.py` | ❌ W0 | ⬜ pending |
| 61-XX | fsm | 2 | CNF-01 | T-39-D-02 | pure transition() table == Node table every case; no I/O | unit | `uv run pytest -q tests/confirm/test_state_machine.py` | ❌ W0 | ⬜ pending |
| 61-XX | watchdog+guards | 3 | CNF-02 | T-39-D-04 | dup-YES → 1 confirmed (SQL guard); 2 concurrent mark_nudge_sent → 1 nudge; asyncio.Lock prevents tick overlap | unit+db | `uv run pytest -q tests/confirm/test_watchdog.py` | ❌ W0 | ⬜ pending |
| 61-XX | strain-confirm | 3 | CNF-01 | — | curated-14 exact-match passthrough; unknown → hold/ask-back; unknown reply → fall through (no re-ask) | unit | `uv run pytest -q tests/confirm/test_strain_ask_back.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> All Wave 0 items are delivered by the foundation plan (wave 1). `wave_0_complete: true`.

- [ ] `farm_agent/tenancy/tenant.py` — add `draft_nudge_fraction: float` (default 0.8) and `max_edit_turns: int` (Node defaults). [RESEARCH finding: both absent today]
- [ ] `farm_agent/confirm/confirm_repo.py` — never-throws DAO over signal_draft + signal_draft_event.
- [ ] `tests/confirm/` + conftest fixtures (FakeConfirmRepo + DB-gated draft fixture).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end farmer YES→confirmed→(Phase-62 commit) over live Signal | CNF-01 | The real farmOS commit is Phase 62; full live round-trip needs the live Signal + farmOS stack | deferred to Phase 62 live-fire / cutover |

*The pure FSM test proves the transition table; DB-gated tests prove the SQL idempotency + race guards. The full live confirm→commit round-trip is exercised once Phase 62 (Write Path) lands.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (TenantConfig fields, confirm_repo, test dir)
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-28
