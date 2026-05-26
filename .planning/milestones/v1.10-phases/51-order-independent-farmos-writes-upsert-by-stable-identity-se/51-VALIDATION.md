---
phase: 51
slug: order-independent-farmos-writes-upsert-by-stable-identity-se
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-24
---

# Phase 51 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Framework correction (per RESEARCH §Critical Findings): the alerter agent uses **Jest**, not `node:test`. CONTEXT.md's `node:test` lock is overridden here; plans must follow.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Jest 29.x (already installed in `src/agents/alerter/package.json`) |
| **Config file** | `src/agents/alerter/jest.config.js` (existing) |
| **Quick run command** | `cd src/agents/alerter && npx jest test/farmos/ --runInBand` |
| **Full suite command** | `cd src/agents/alerter && npm test` |
| **Estimated runtime** | ~15s (farmos slice), ~45s (full alerter suite) |

---

## Sampling Rate

- **After every task commit:** Run `cd src/agents/alerter && npx jest <touched-test-file> --runInBand`
- **After every plan wave:** Run `cd src/agents/alerter && npx jest test/farmos/`
- **Before `/gsd:verify-work`:** Full alerter suite must be green + UPSERT-07 live-fire script must produce a passing receipt against dev farmOS
- **Max feedback latency:** ~15s (farmos slice)

---

## Per-Requirement Verification Map

| Req | Verification Type | Automated Command / Manual Step |
|-----|-------------------|---------------------------------|
| UPSERT-01 (`upsertFungiAsset`) | Jest unit + integration via mock-client | `npx jest test/farmos/assets.test.js` |
| UPSERT-02 (`upsertLog` seeding) | Jest unit + integration via mock-client | `npx jest test/farmos/logs.test.js` |
| UPSERT-03 (`_mergeAssetFields` rules) | Jest pure-function unit tests | `npx jest test/farmos/merge.test.js` |
| UPSERT-04 (etag — DEGRADED) | Soft revision_id compare with audit-log dimension; planner decides one of {soft-compare, drop, defer} given farmOS does not honor `If-Match` (RESEARCH critical finding #2) | `npx jest test/farmos/upsert-concurrency.test.js` |
| UPSERT-05 (stub detection) | Jest unit + property fixture | `npx jest test/farmos/stub-detection.test.js` |
| UPSERT-06 (hermetic ship-gate property tests) | Jest with seeded `crypto.randomInt` permutations (20×); print seed on failure | `npx jest test/farmos/upsert-property.test.js` |
| UPSERT-07 (live-fire) | Manual / scripted replay against dev farmOS | `node scripts/live-fire-51.js` (sibling-copy of `scripts/live-fire-48.js`) — emit receipt; commit receipt under `.planning/notes/2026-05-XX-phase-51-live-fire.md` |

---

## Wave 0 Requirements

- [ ] Extend `src/agents/alerter/test/farmos/mock-client.js` with `mockPatch(path, response)` registry + etag/412 protocol surface (front-loaded per RESEARCH §3 — mock currently has no `patch`/`delete`)
- [ ] One Wave-0 `curl` probe (manual or scripted) against dev farmOS to confirm `notes` field `\n---\n` round-trip fidelity (RESEARCH open Q4)
- [ ] `src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json` — the May-22 + Jan-18 + Mar-04 trio fixture for property tests
- [ ] Confirm `client.patch` plumbs `opts.headers` (one-line `_doFetch` extension if needed — RESEARCH §2)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live-fire replay produces no duplicate stubs in dev farmOS | UPSERT-07 | Requires real dev-farmOS write side-effects; can't run in CI | `node scripts/live-fire-51.js --dev`; query asset list before/after; assert 4 stubs (no growth) and children's `parent[]` resolves to existing UUIDs |
| `notes` field round-trip preserves `\n---\n` separator | UPSERT-03 dedup rule | farmOS Drupal text-field normalization is implementation-defined | One-off `curl PATCH` against dev, GET back, byte-compare |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (mock PATCH surface + notes-roundtrip probe + property fixtures)
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter
- [ ] Framework correction (Jest, not `node:test`) reflected in all plans

**Approval:** pending
