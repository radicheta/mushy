---
phase: 37
plan: 02
subsystem: alerter
type: execute
wave: 2
tags: [signal, alerter, schema, refactor, defaultTarget]
requirements: [ROUTE-01, ROUTE-02, ROUTE-03]
depends_on: ["37-01"]
provides:
  - signal.js send(body, {to}) + constructor defaultTarget (D-01)
  - config.signalGroupId + config.signalFarmerMap (D-11/D-16)
  - signal_capture.{group_id, farmos_person, reply_target_kind} columns (D-14/D-15)
requires:
  - 37-01 fixtures (already in place — not directly consumed this plan)
affects:
  - all signalClient.send() callers (back-compat: legacy recipient still works)
tech-stack:
  added: []
  patterns:
    - "single-choke-point send (D-01): {to} per-call overrides constructor defaultTarget"
    - "comma-separated env parse mirroring SIGNAL_ADDITIONAL_SENDERS (c8e9ac1 template)"
    - "ADD COLUMN IF NOT EXISTS native Postgres idempotency (no DO-block — table not hypertable)"
key-files:
  created: []
  modified:
    - src/agents/alerter/src/signal.js (85 → 106 lines)
    - src/agents/alerter/src/config.js (93 → 112 lines)
    - src/agents/alerter/src/capture-db.js (62 → 70 lines)
    - src/agents/alerter/test/signal.test.js (234 → 355 lines)
    - src/agents/alerter/test/config.test.js (103 → 160 lines)
    - src/agents/alerter/test/capture-db.test.js (70 → 122 lines)
decisions:
  - "[37-02] signal.js uses boolean discriminators (isStringTarget/isGroupTarget) for target validation — equivalent to PATTERNS.md typeof check but more defensive against null/empty edge cases"
metrics:
  duration: "~12min"
  tasks_completed: 3
  files_modified: 6
  completed: "2026-05-11"
---

# Phase 37 Plan 02: Multi-farmer Routing Foundation — Summary

Single-choke-point send + farmer-map + schema columns landed in three byte-stable refactors. Nothing fires differently at runtime yet (callers haven't been updated — that's Plan 03; defaultTarget flip to group is Plan 04).

## What Shipped

### 1. signal.js — send({to}) + constructor defaultTarget (D-01)
- Constructor accepts new `defaultTarget` (string phone | `{groupId}`); falls back to legacy `recipient` for back-compat. Throws on construction if neither is set.
- `send(body, {bypassCap, to})`: per-call `{to}` overrides `defaultTarget`. Builds `recipients=['group.<id>']` for object target, `[phone]` for string. Throws `invalid send target` on malformed input.
- Logging branches: `maskNumber()` for DM (preserves PII contract), `group:<8chars>…` prefix for group.
- `bypassCap` stays orthogonal to `{to}`.

### 2. config.js — signalGroupId + signalFarmerMap (D-11/D-16)
- New `parseFarmerMap(raw)`: `"phone:slug,phone:slug,..."` → `Map<E164,slug>`. Splits on FIRST colon only (defensive for future colon-bearing slugs); silently drops malformed/empty entries.
- `config.signalGroupId`: `env.SIGNAL_GROUP_ID || null` (bare base64; signal.js prepends `group.` at send time).
- `config.signalFarmerMap`: parsed Map (empty Map when env unset).

### 3. capture-db.js — schema migration + insertCapture extension (D-14/D-15)
- `initDb` appends three `ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS` statements for `group_id`, `farmos_person`, `reply_target_kind` (all `text`, nullable). Native Postgres idempotency — no DO-block needed (signal_capture is a regular table, not a hypertable).
- `insertCapture` extended to 13 params; new fields default to null when row omits them (back-compat for callers not updated yet).

## Tests

| File | Pre | New | After | Status |
|------|-----|-----|-------|--------|
| signal.test.js | 15 | 10 | 25 | 25/25 green |
| config.test.js | 9 | 10 | 20 | 19/20 (1 pre-existing dashboardUrl drift; documented in 37-01-SUMMARY.md, do NOT fix in this plan) |
| capture-db.test.js | 4 | 3 (+2 modified) | 7 | 7/7 green |

Full alerter suite: **238 pass / 1 fail (pre-existing, unrelated)** out of 239.

## Commits

| Commit | Type | Message |
|--------|------|---------|
| 4153d72 | test | RED: signal.js send({to}) + defaultTarget + group recipient |
| 436481c | feat | GREEN: signal.js implementation |
| f9b4b57 | test | RED: signalGroupId + signalFarmerMap |
| e662b6d | feat | GREEN: config.js implementation |
| c13b26a | test | RED: capture-db schema migration + 3 new fields |
| a6e8239 | feat | GREEN: capture-db.js implementation |

Six commits, three RED/GREEN pairs per task. No --no-verify used.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed as written.

### Minor Pattern Deviation (non-functional)

**1. signal.js — boolean discriminators instead of inline typeof**
- **Found during:** Task 1 implementation
- **PATTERNS.md says:** `const recipients = typeof target === 'string' ? [target] : [`group.${target.groupId}`];`
- **Actual:** Introduced `isStringTarget` + `isGroupTarget` boolean variables (with length/type checks) before building `recipients`. Required for the new validation gate (`throw 'invalid send target'`) which needed to discriminate non-empty-string vs object-with-non-empty-groupId.
- **Reason:** Plan acceptance criteria included "Validate target: if neither a non-empty string nor an object with a non-empty .groupId, throw `Error: invalid send target`" — this validation needs explicit boolean checks. Functionally equivalent to the PATTERNS.md form, just refactored once instead of twice.
- **Impact:** Acceptance grep `recipients = typeof target` now reads `recipients = isStringTarget`; the `group:${...}.slice(0,8)…` grep + send signature grep still match verbatim. Behavior identical.

### Acceptance Criteria Status

- Task 1: ✓ all 25 signal tests green; ✓ `group:${` log prefix grep hit; ✓ `send(body, {bypassCap = false, to}` signature grep hit; minor grep deviation noted above (semantic equivalent).
- Task 2: ✓ `function parseFarmerMap` grep hit (1); ✓ `signalGroupId:` + `signalFarmerMap:` grep hit (1 each); ✓ all 10 new cases pass; ✓ `signalGroupId === null` when env unset; ✓ `signalFarmerMap` is empty Map when env unset.
- Task 3: ✓ 3 ADD COLUMN IF NOT EXISTS lines in source (grep returns 4 — 3 statements + 1 comment); ✓ `$13` placeholder grep hit (1); ✓ insertCapture params length 13 verified in test; ✓ idempotent invocation tested.

## Threat-model Status

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-37-02-01 (silent default to undefined) | mitigate | ✓ construction-time throw enforced + tested |
| T-37-02-02 (parseFarmerMap on malformed env) | mitigate | ✓ defensive parse drops malformed; never throws; tested |
| T-37-02-03 (group prefix concatenation) | mitigate | ✓ `group.` is server-side concat; env carries bare base64 |
| T-37-02-04 (schema migration cost) | accept | ✓ unchanged |
| T-37-02-05 (env-source trust) | accept | ✓ unchanged |

No new threat flags discovered during execution.

## Back-compat

Pre-Phase-37 alerters behave identically:
- `SIGNAL_GROUP_ID` unset → `defaultTarget = null` → constructor wires `recipient` → recipients=[recipient] (legacy).
- `SIGNAL_FARMER_MAP` unset → empty Map; Plan 03 capture.js will treat empty-Map lookups as `(unassigned)`.
- `signal_capture` rows continue to write with new fields as NULL until Plan 03 wires capture.js to populate them.

## Hand-off to Plan 03

Plan 03 can now:
1. Wire `capture.js:146` send call to pass `{to: replyTarget}` (replyTarget computed from `dm.groupInfo`).
2. Populate `insertCapture` row with `group_id`, `farmos_person`, `reply_target_kind` (resolved from `config.signalFarmerMap`).
3. Add `botPhone = config.signalSender` reference for receive-loop mention/quote matching.
4. Add `collectGroupTriggers(env, botPhone)` pure helper per PATTERNS.md (already specified at l.146-157).

## Self-Check: PASSED

- ✓ All six commits visible in `git log --oneline -10`: 4153d72, 436481c, f9b4b57, e662b6d, c13b26a, a6e8239
- ✓ All six modified files exist with expected line counts
- ✓ Full alerter jest run: 238 pass / 1 pre-existing fail (unrelated)
- ✓ No files outside `files_modified` list touched (surgical changes)
