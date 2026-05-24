# Observation-of-unknown-asset should backfill, not fail

**Filed:** 2026-05-24 (Santi-articulated during v1.9 UAT triage)
**Severity:** HIGH (UX-defining principle, blocks production farmOS write-through)
**Scope:** `src/agents/alerter/src/farmos/commits/commit-observation.js`, `commits/commit-harvest.js`, `commits/commit-input.js`, `commits/commit-activity.js`; possibly extraction prompt + draft schema
**Estimated:** Phase 52+, ~M (2-3 plans, needs farmer-UX-tested confirm flow)

## The principle (Santi, 2026-05-24)

> "If the farmer is recording an observation, the system replying 'that asset does not exist' would be comically wrong. The farmer just told us it exists. We should backfill it, maybe double-checking the ID just in case."

The farmer is reality's source of truth. If they observe block `260519_DT_1` and farmOS has never heard of it, farmOS is the one out of date, not the farmer. The system's job is to **reconcile**, not to **reject**.

## Current behavior (the bug)

`commit-observation.js:22-24`:

```js
if (assetIds.length === 0) {
  return { ok: false, reason: 'observation_requires_target' };
}
```

The QR/asset resolver (`qr.resolveQr`) returns `{found: false}` for any unknown ID -> commit fails -> farmer sees `couldn't save observation: couldn't match a block. Send EDIT to fix or NO to drop.`

This was tonight's blocker (in spirit, even though the actual block here was `FARMOS_INTEGRATION=0`): the well-formed DT_1/DT_2 observation drafts couldn't have committed even if perms were fine, because farmOS prod has no `260519_DT_1`.

## The fix shape

### Phase A: detect + double-check (no auto-write)

When `resolveQr` returns empty for an `asset_ref`:

1. **Fuzzy-match neighbors.** Query farmOS for assets matching the stem `260519_DT_*` or any nearby SEQ. If a close match exists, ask the farmer: "Did you mean `260519_DT_1` or one of these similar blocks: 260519_DT_a, 260518_DT_1, 260520_DT_1?"
2. **No neighbors found.** Ask: "I haven't seen `260519_DT_1` before. Should I create it as a new block and log the observation against it? (YES to create + log / NO to cancel / EDIT to fix the ID)"

Farmer YES -> mint asset + log. Farmer NO -> discard draft (no commit failure ack -- this is a learned operation, not an error).

### Phase B: name-pattern validation

`260519_DT_1` follows the locked B-system schema (`YYMMDD_strain_seq`). Before backfill, validate:
- `strain` is in the active strain map (`[[project_mossrock_active_strain_codes]]`: SHI SH2 KOY MAI MALI KOS DT CAS CAZ WIN ALM MOR BP LIMA -- yes, DT is active).
- `event_date` parses cleanly.
- `seq` is a positive integer.

If validation fails -> ask-back rather than backfill.

### Phase C: applies to harvest + input + activity too

Same principle: harvesting from an unknown block, applying input to an unknown block, doing an activity on an unknown block. All four log types should backfill-on-confirm, not fail.

`commit-seeding-session` (Phase 48) is the OPPOSITE pattern -- it MINTS new blocks (`260522_KOY_4..11`) as a normal part of operation. So the pattern is already half-implemented; we're generalizing it.

## Confidence-aware backfill

Tonight's DT_1/DT_2 drafts came in with `asset_ref` confidence = 0.9. That's HIGH. Auto-backfill at >=0.9 should probably be 1-step ("creating asset + log, YES to confirm or EDIT to correct").

At <0.9, the disambiguator + fuzzy-match path should run.

At <0.5, ask-back regardless (don't trust the extractor's guess).

## Anti-pattern to avoid

DO NOT auto-mint without farmer confirmation. The farmer is reality's source of truth ONLY for things they have actively asserted. An extractor hallucination ("I think this might be 260519_DTT_1") is NOT a farmer assertion; the farmer never typed/spoke that exact ID. Always show the inferred asset name back to the farmer before minting.

## Acceptance / regression guard

- Tonight's `01KSCW771VB2FDWBPWNS4MEHAZ` capture (photo + caption "DT tubs 0519 1 and 2") -> ground truth: 2 confirm_prompts, each with "create asset + log" option, farmer YES -> 2 new `asset/fungi` minted (named `260519_DT_1` / `_2`) + 2 observation logs attached.
- Known-asset case: farmer reports observation on `260118_KOY_12` -> existing behavior preserved (no creation prompt; just confirm + log).
- Typo case: farmer reports `260519_DT_99` (no neighbors within distance) -> ask-back rather than silent backfill.
- Hallucination case: extractor outputs an ID the farmer never typed/spoke -> farmer EDITs it before YES; backfill happens with the corrected ID.

## Why this matters beyond tonight

- Removes the largest single source of `commit_failed` drafts (asset-resolution failures).
- Lets `FARMOS_INTEGRATION=1` flip safely in production -- right now the gate is off in large part BECAUSE this path would fail noisily.
- Closes the asymmetry where `commit-seeding-session` already mints assets but `commit-observation` (and harvest/input/activity) refuses to.

## Links

- Source insight: 2026-05-24 conversation, Santi triaging Plan B failure
- Findings doc: `.planning/notes/2026-05-24-v1.9-uat-findings.md`
- Code today: `src/agents/alerter/src/farmos/commits/commit-observation.js:22-24`
- Pattern reference (mints assets): `src/agents/alerter/src/farmos/commits/commit-seeding-session.js`
- Active strain code map: `[[project_mossrock_active_strain_codes]]`
- Schema lock: `[[project_farmos_schema_locked_2026_05_11]]`
- Trinity context: `[[user_santi_radicheta_farmer1_trinity]]`
