---
phase: 38
slug: extraction-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-12
---

# Phase 38 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Derived from `38-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest ^29.7.0 (already installed in `src/agents/alerter/package.json`) |
| **Config file** | `src/agents/alerter/jest.config.js` (existing) + new `src/agents/alerter/test/eval/extraction/jest.config.js` (eval-specific: `runInBand`, `testTimeout: 600000`) |
| **Quick run command** | `cd src/agents/alerter && npm test -- test/extraction/` |
| **Full suite command** | `cd src/agents/alerter && npm test` |
| **Eval command** | `cd src/agents/alerter && npm run eval:extraction` (new script; D-07 ship-gate) |
| **Estimated runtime (unit)** | ~20–30 s |
| **Estimated runtime (eval)** | ~5–10 min over mushdatadump v1.6 (73 cases × ~3 turns, cached prompt) |

---

## Sampling Rate

- **After every task commit:** `cd src/agents/alerter && npm test -- test/extraction/` (unit suite; <30s).
- **After every plan wave:** `cd src/agents/alerter && npm test` (full alerter suite).
- **Before `/gsd-verify-work`:** Full suite must be green AND `npm run eval:extraction` must hit D-07 ship-gate (≥90% schema-valid AND ≥75% required-field exact-match OR appropriate ask-back).
- **Max feedback latency:** 30 s (unit), 10 min (eval).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 38-01-* | 01 (Wave 0) | 0 | EXT-01..EXT-05 | T-38-01 (LLM off-schema) | Zod parse rejects off-schema; partial-unique index enforces one-in-flight | unit | `npm test -- test/extraction/schemas.test.js` | ❌ W0 | ⬜ pending |
| 38-02-* | 02 (Wave 1) | 1 | EXT-01 | T-38-01 | Schema-conformant JSON via Anthropic tool-use; Zod safeParse retry | unit | `npm test -- test/extraction/extractor.test.js -t "tool-use"` | ❌ W0 | ⬜ pending |
| 38-02-* | 02 (Wave 1) | 1 | EXT-01 | T-38-01 | Off-schema field path → mark needs_review | unit | `npm test -- test/extraction/validator.test.js -t "off-schema"` | ❌ W0 | ⬜ pending |
| 38-02-* | 02 (Wave 1) | 1 | EXT-02 | — | B5 regex `^[0-9]{6}_[A-Z]{3}_[0-9]+$` enforced | unit | `npm test -- test/extraction/schemas.test.js -t "B5 block_name"` | ❌ W0 | ⬜ pending |
| 38-03-* | 03 (Wave 1) | 1 | EXT-03 | T-38-02 (fusion drop) | One multimodal capture-set → one draft | unit + eval | `npm test -- test/extraction/extractor.test.js -t "fusion"` + eval dim 8 | ❌ W0 | ⬜ pending |
| 38-04-* | 04 (Wave 1) | 1 | EXT-04 | — | Confidence < 0.7 OR required-field unresolved → ask-back fires | unit | `npm test -- test/extraction/state-machine.test.js -t "ask-back trigger"` | ❌ W0 | ⬜ pending |
| 38-04-* | 04 (Wave 1) | 1 | EXT-04 | T-38-03 (askback overflow) | 3-turn cap → needs_review | unit | `npm test -- test/extraction/state-machine.test.js -t "3-turn cap"` | ❌ W0 | ⬜ pending |
| 38-04-* | 04 (Wave 1) | 1 | EXT-04 | — | 30min idle force-new + Phase 39 confirm/discard force-new | unit | `npm test -- test/extraction/state-machine.test.js -t "30min cap"` | ❌ W0 | ⬜ pending |
| 38-05-* | 05 (Wave 2) | 2 | EXT-05 | — | Multi-parent harvest extraction (C4) | unit + eval | `npm test -- test/extraction/schemas.test.js -t "harvest lineage"` + eval dim 4 | ❌ W0 | ⬜ pending |
| 38-06-* | 06 (Wave 2) | 2 | EXT-02 / EXT-04 (cross-cutting) | T-38-04 (em-dash leak) | Em-dash + float sweep on every outbound farmer-facing string | unit | `npm test -- test/extraction/sanitize.test.js` | ❌ W0 | ⬜ pending |
| 38-07-* | 07 (Wave 3) | 3 | D-07 ship-gate | — | mushdatadump pass bar achieved | offline gate | `npm run eval:extraction` writes `38-EVAL-REPORT.md` | ❌ W0 | ⬜ pending |
| 38-08-* | 08 (Wave 3) | 3 | EXT-01..EXT-05 (smoke) | — | signal_draft CRUD + partial-unique index + replay-safe id | unit | `npm test -- test/extraction/extraction-db.test.js` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

Task IDs follow `{phase}-{plan}-{task}` once the planner emits PLAN.md files in Step 8 — this table will be re-keyed during pattern-mapping / planner output.

---

## Wave 0 Requirements

Wave 0 lands all scaffolding before any LLM-call code in Wave 1+. From research §Validation Architecture:

- [ ] `src/agents/alerter/test/extraction/schemas.test.js` — Zod schema round-trip + B5 regex + discriminated-union exhaustiveness
- [ ] `src/agents/alerter/test/extraction/extractor.test.js` — orchestration (continuity → extract → state)
- [ ] `src/agents/alerter/test/extraction/state-machine.test.js` — status transitions, 30min cap, 3-turn cap
- [ ] `src/agents/alerter/test/extraction/multimodal.test.js` — image downscale + base64 builder
- [ ] `src/agents/alerter/test/extraction/sanitize.test.js` — em-dash + float sweep enforcement
- [ ] `src/agents/alerter/test/extraction/extraction-db.test.js` — signal_draft CRUD + partial-unique index behavior
- [ ] `src/agents/alerter/test/extraction/validator.test.js` — Zod safeParse + retry envelope
- [ ] `src/agents/alerter/test/eval/extraction/jest.config.js` — separate config (long timeout, runInBand, isolated jest project name)
- [ ] `src/agents/alerter/test/eval/extraction/mushdatadump.test.js` — load fixtures + run scoring
- [ ] `src/agents/alerter/test/eval/extraction/scoring.js` — Brier / ECE / set-equality helpers (per AI-SPEC §5 calibration dimension)
- [ ] `src/agents/alerter/test/eval/extraction/fixtures/` — env-var pointer to `/mnt/mossrock/shared/mushdatadump/` (do NOT copy)
- [ ] `src/agents/alerter/package.json` — add `"eval:extraction": "jest --config test/eval/extraction/jest.config.js --runInBand"`
- [ ] `src/agents/alerter/package.json` — add `zod@^3.25.x` + `zod-to-json-schema@^3.24.x` deps
- [ ] DB migration — `signal_draft` table + partial-unique index on `(sender_e164) WHERE status IN ('pending','awaiting_farmer')`; idempotent CREATE TABLE / ADD COLUMN per Phase 25/37 pattern

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-farmer ask-back round-trip on Signal | EXT-04 SC#3 | Requires live Signal + a real farmer reading + replying | Out of Phase 38 scope; flows into Phase 39 (Farmer Confirmation Loop) UAT. Phase 38 attests against mushdatadump only. |
| Production-log advisory smoke (path TBD) | EXT-01..EXT-05 | Path not yet identified; Don Santiago to confirm during execution | Once path is supplied, run `EXTRACTION_FIXTURE_DIR=<path> npm run eval:extraction` and compare to mushdatadump baseline. Advisory only — does not block ship if mushdatadump bar is met. |

---

## Validation Sign-Off

- [ ] All tasks have automated verify OR Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references in the verification map
- [ ] No watch-mode flags in CI invocations
- [ ] Feedback latency < 30 s (unit) / < 10 min (eval)
- [ ] `nyquist_compliant: true` set in frontmatter after planner authors PLAN.md files with task IDs

**Approval:** pending — flip to approved once planner output is keyed into the per-task verification map.
