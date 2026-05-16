# SCHEMA-04 Attestation

**Phase:** 43  
**Plan:** 06  
**Date:** 2026-05-16  
**Attested by:** Plan 43-06 executor (claude-sonnet-4-6)

## Command Run

```
cd src/agents/alerter && npm test
```

Working directory: `/mnt/slime-kingdom/opt/mushy/src/agents/alerter`  
No environment variables set. No flags passed.

## Test Suite Summary (literal output)

```
Test Suites: 1 skipped, 56 passed, 56 of 57 total
Tests:       8 skipped, 689 passed, 697 total
Snapshots:   0 total
Time:        8.076 s
```

## New Files -- PASS Lines (literal output)

```
PASS test/farmos/normalize.test.js
```

```
PASS test/farmos/integration/extractor-to-commit.test.js
  extractor -> normalize -> commit chain (Phase 43 Plan 05)
    ✓ Test 1 (seeding): extractor-shape -> normalize -> commit_success with block created (10 ms)
    ✓ Test 2 (activity, 2026-05-15 regression guard): lion's-mane transcript -> classified failure (3 ms)
    ✓ Test 3 (observation): extractor-shape -> normalize -> commit_success with notes containing state (4 ms)
    ✓ Test 4 (input): extractor-shape -> normalize -> commit_success with recipe_lot prepended in notes (2 ms)
    ✓ Test 5 (harvest): extractor-shape -> normalize -> commit_success with single synthesized bag via name-fallback (13 ms)
```

## No Environment Gate -- Verification

```
grep -E "(FARMOS_INTEGRATION|describe\.skip|it\.skip|process\.env\.\w+ ===)" \
  src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js \
  src/agents/alerter/test/farmos/normalize.test.js
```

Result: Only comment-line hits (no executable gate code):

```
test/farmos/integration/extractor-to-commit.test.js://   D-13: file location; no FARMOS_INTEGRATION gate (SCHEMA-04)
test/farmos/integration/extractor-to-commit.test.js:// Do NOT add a FARMOS_INTEGRATION=1 gate.
```

These are comment-only references; no conditional skip or `describe.skip` is present in either file.

## Jest Config -- No Exclusion

`src/agents/alerter/jest.config.js`:

```js
testPathIgnorePatterns: ['/node_modules/', '/fixtures/', '/helpers/', '/test/eval/']
```

The pattern `/test/farmos/integration/` is absent from the ignore list. Default Jest discovery via `testMatch: ['**/test/**/*.test.js']` picks up `test/farmos/integration/extractor-to-commit.test.js` automatically.

## Skipped Suite -- Old Gated Path (Expected)

The 1 skipped test suite is `test/farmos/integration.test.js` (the pre-existing Phase 40 Plan 07 suite). It explicitly gates on `FARMOS_INTEGRATION=1`:

```js
const RUN_INTEGRATION = process.env.FARMOS_INTEGRATION === '1';
const d = RUN_INTEGRATION ? describe : describe.skip;
```

This is the legacy pattern. The new suite (`test/farmos/integration/extractor-to-commit.test.js`) does NOT follow this pattern -- it runs unconditionally, as required by SCHEMA-04 and D-13.

## Attestation

SCHEMA-04 is satisfied.

Both `test/farmos/normalize.test.js` (Plan 43-01) and `test/farmos/integration/extractor-to-commit.test.js` (Plan 43-05) run under the bare `npm test` invocation with no environment variables, no flags, and no skip pragmas. All 5 chain integration tests pass. The default-run discipline is enforced by the absence of any `FARMOS_INTEGRATION` gate or `describe.skip` in both new files.

The contrast with the pre-existing `test/farmos/integration.test.js` (which IS gated) is intentional and documented in CONTEXT.md D-13: new suites must follow the default-run pattern; the old gated suite remains gated for backward compatibility.

**Cross-references:**
- CONTEXT.md D-13: "Suite runs under `npm test` by default; no environment gate."
- ROADMAP.md SCHEMA-04: "New integration suite runs under default `npm test` -- no FARMOS_INTEGRATION=1 gate."
