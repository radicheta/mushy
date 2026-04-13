---
phase: 13
slug: farmos-daily-report
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | src/farmos-agent/tests/ (new — Wave 0 creates) |
| **Quick run command** | `pytest src/farmos-agent/tests/ -x -q` |
| **Full suite command** | `pytest src/farmos-agent/tests/` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/farmos-agent/tests/ -x -q`
- **After every plan wave:** Run `pytest src/farmos-agent/tests/`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 0 | FMOS-01 | — | N/A | unit | `pytest src/farmos-agent/tests/test_farmos_client.py -x -q` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | FMOS-02 | — | N/A | unit | `pytest src/farmos-agent/tests/test_report_builder.py -x -q` | ❌ W0 | ⬜ pending |
| 13-01-03 | 01 | 1 | FMOS-03 | — | N/A | unit | `pytest src/farmos-agent/tests/test_report_builder.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/farmos-agent/tests/test_farmos_client.py` — stubs for FMOS-01 (asset verification, auth)
- [ ] `src/farmos-agent/tests/test_report_builder.py` — stubs for FMOS-02, FMOS-03 (observation creation, env summary)
- [ ] `src/farmos-agent/tests/conftest.py` — shared fixtures (mock FarmOS responses, mock DB results)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| FC-1 visible in FarmOS UI | FMOS-01 (SC-1) | Requires browser access to FarmOS at 10.68.155.50:8082 | Navigate to /asset/28, verify name/metadata |
| Observation appears with snapshot | FMOS-02 (SC-2) | Requires running service against live FarmOS | Trigger report manually, check /asset/28/logs |
| Service survives restart | FMOS-03 (SC-4) | Requires docker restart + timing check | `docker compose restart farmos-agent`, wait, verify no duplicate |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
