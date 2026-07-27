---
phase: 60
slug: extraction-pipeline
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-26
---

# Phase 60 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv) |
| **Config file** | src/farm-agent/pyproject.toml |
| **Quick run command** | `cd src/farm-agent && uv run pytest -q tests/test_extraction_*.py tests/test_seq_helper.py tests/test_multimodal.py` |
| **Full suite command** | `cd src/farm-agent && uv run pytest -q` |
| **Estimated runtime** | ~4 seconds (mocked Anthropic client; no real API) |

---

## Sampling Rate

- **After every task commit:** run the quick command for the touched extraction test file.
- **After every plan wave:** run the full suite.
- **Before verification:** full suite green + the FND-04 parity test green.
- **Max feedback latency:** ~5 seconds.

---

## Per-Task Verification Map

> Refined by the planner per plan. Baseline expectations:

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 60-XX | foundation | 1 | XTR-01 | T-60-SC | Pillow dep legitimacy-gated; prompts verbatim; fixture copied | unit | `uv run pytest -q tests/test_schema_parity.py` | ❌ W0 | ⬜ pending |
| 60-XX | multimodal+seq | 2 | XTR-02 | — | fail-open on bad image (skip+WARNING); BLOCK_NAME_RE fullmatch; per-session SEQ | unit | `uv run pytest -q tests/test_multimodal.py tests/test_seq_helper.py` | ❌ W0 | ⬜ pending |
| 60-XX | extractor+retry | 3 | XTR-02, XTR-03 | T-44-04-01 | 2-call retry (tool_result is_error + tool_use_id); 2nd fail→needs_review never throws; api key not logged | unit | `uv run pytest -q tests/test_extraction_extractor.py` | ❌ W0 | ⬜ pending |
| 60-XX | fixture replay | 3 | XTR-01 | — | 5 groups/11 children/260522_SHI_1..3+KOY_4..11/provenance via mocked tool_use | unit | `uv run pytest -q tests/test_extraction_fixture.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> All Wave 0 items are delivered by the foundation plan (wave 1). `wave_0_complete: true`.

- [ ] `Pillow` added to pyproject.toml (Wave 0 dep, package-legitimacy gate at execute time).
- [ ] `tests/fixtures/extraction/seeding-session-may22/` — copied fixture (transcript, paper-log.jpg, text-followup, expected-draft.json).
- [ ] `tests/conftest.py` — `FakeAnthropicClient` extended for the Messages tool_use envelope + retry simulation.
- [ ] `farm_agent/extraction/prompts.py` — verbatim Node system prompt + few-shot with cache_control.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-Sonnet accuracy on the live 2026-05-22 fixture (real audio+photo → correct 5-group/11-child draft + provenance) | XTR-01 | Needs a live ANTHROPIC_API_KEY + costs real API calls; deferred like Phase 58/59 live-fires | marker/env-gated test runs the real extractor on the fixture; assert draft shape + block names; record token/cache usage |

*The mocked-tool_use test proves the extractor WIRING + retry + schema + seq-minting + multimodal assembly; the real-Sonnet run proves model EXTRACTION ACCURACY and is operator-run.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (Pillow, fixture, fake client, prompts)
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-26
