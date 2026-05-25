# Eval strain regex `[A-Z]{2,4}` rejects valid codes CA3 + WEDGE

**Filed:** 2026-05-24 (surfaced during Phase 53-04 fixture curation, retry pass)
**Severity:** low — fixture-selection workaround in place; broader fix unlocks more eval coverage
**Scope:** Phase 53-04 eval validation layer (`src/agents/alerter/test/eval/ingestion/`)
**Related:** `[[reference_mushdatadump_benchmark]]` — known-strain list per HANDOFF.md

## What happened

While curating 8 fixtures for Phase 53-04's hermetic eval gate, two notebook pages were skipped because their strain codes fail the validator's `[A-Z]{2,4}` regex:

- **IMG_3790 (2025-05-21)** — contains strain `CA3` (3 chars but includes a digit; regex is alpha-only).
- **IMG_3820 (2025-11-03/05)** — contains strain `WEDGE` (5 chars; regex caps at 4).

Both are valid strain codes per `/mnt/slime-kingdom/shared/mushdatadump/HANDOFF.md`'s known-strain list:

```
CAS, SHI, DT, KOS, MALI, KOY, BP, CCM, CAZ, ENO, CA3, LIMA, POY, SH2, CY, WEDGE, WIN
```

The fixture curator worked around by picking other pages, but this silently reduces eval coverage and will reject valid future pages.

## Root cause

The regex `[A-Z]{2,4}` is too narrow for the known-strain reality:
- Alphanumeric codes exist: `CA3`, `SH2` (already passed because length-2-4 covers SH2; CA3 fails the alpha-only).
- 5-char codes exist: `WEDGE`.

## Proposed fix

Either:

1. **Replace with a stricter known-list check.** Validate against the explicit `KNOWN_STRAINS` set from `HANDOFF.md`, not a generic regex. Pro: catches typos too. Con: needs sync with farm's strain list as it grows.
2. **Broaden the regex.** `[A-Z][A-Z0-9]{1,4}` would cover all current cases (length 2-5, alphanumeric except first char). Pro: minimal. Con: more permissive, won't catch typos.

Recommend Option 1 — the strain list is small and farm-authoritative; a known-list check provides better data hygiene.

## Acceptance

- After fix: re-add IMG_3790 + IMG_3820 to the eval fixture set (10 fixtures total instead of 8).
- Existing 8 fixtures still pass.
- Unknown-strain fixture (synthetic, e.g. `FOO`) is REJECTED with a clear error message.

## Links

- Where the regex lives: search `src/agents/alerter/test/eval/ingestion/` (the Phase 54 retry agent identified it but didn't grep-locate it for me).
- Affected fixture candidates: IMG_3790, IMG_3820 in `/mnt/slime-kingdom/shared/mushdatadump/jpeg/`.
- Known-strain authority: `/mnt/slime-kingdom/shared/mushdatadump/HANDOFF.md`.
