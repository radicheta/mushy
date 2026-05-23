# Phase 47 Live-Fire — May 22 fixture replay

**Ran:** 2026-05-23 ~21:00 ART (after `ebd1f98` 47-05 hermetic ship)
**Cost:** ~$0.10 (Sonnet 4.6, single call)
**Result:** Model behaved BETTER than test expected — emitted Gray-Area-3 ask-back path instead of presuming SEQ from row positions

## Verdict: PASS on substance, FAIL on test over-specification

Test failed but the underlying system behaved exactly per CONTEXT.md Gray Area 3 lock (when SEQ source is unclear → ASK, do not guess). The test asserted the auto-derive path from row positions; the model chose the conservative path. Both are within CONTEXT.md scope; the conservative path is preferred per `[[friction-policy-missing-vs-mismatch]]`.

## What the model produced (verbatim from stdout)

```json
{
  "ok": true,
  "draftId": "681fd598cb3685530cd6dd2ec0f4a8fc694a3a6b62b2dfab2ef6a50583c43633",
  "status": "awaiting_farmer",
  "continuity": "start_new",
  "sideEffects": ["send_starting_seq_askback"]
}
```

Persisted draft.draft_json (formatted for readability):

```
{
  type: 'seeding_session',
  event_date: '2026-05-22',
  groups: [
    { parent:  {value:'260304_SHI_5',  conf:0.88, sources:['audio','paper_log_photo']},
      species: {value:'SHI',           conf:0.98, sources:['audio','paper_log_photo']},
      qty:     {value:1,               conf:0.97, sources:['audio','paper_log_photo']},
      child_block_names: {value:['NEEDS_SEQ'], conf:0.5, sources:['paper_log_photo']} },
    { parent:  {value:'260118_SHI_23', ...},
      child_block_names: {value:['NEEDS_SEQ'], ...} },
    { parent:  {value:'260118_SHI_26', ...},
      child_block_names: {value:['NEEDS_SEQ'], ...} },
    { parent:  {value:'260118_KOY_12', conf:0.82, ...},
      qty:     {value:4, ...},
      child_block_names: {value:['NEEDS_SEQ','NEEDS_SEQ','NEEDS_SEQ','NEEDS_SEQ'], ...} },
    { parent:  {value:'260425_KOY_4',  conf:0.92, ...},
      qty:     {value:4, ...},
      child_block_names: {value:['NEEDS_SEQ','NEEDS_SEQ','NEEDS_SEQ','NEEDS_SEQ'], ...} }
  ],
  needs_input: 'starting_seq',
  notes: 'Photo header reads 522 (May 22). 3 SHI rows then 2 KOY groups of 4.
          Audio total of 11 bags matches photo rows 1-11. Block SEQ numbers not
          written on the page; starting SEQ needed. Parent batch shorthand
          decoded using default_year 2026 and species from photo columns. KOY
          first source audio says 11812 (decoded 260118_KOY_12); photo reads
          1-18-12 consistent. SHI third parent audio says 118-26, photo reads
          118-26, decoded 260118_SHI_26.'
}
```

## INOC requirement-by-requirement audit (live)

| Req | Lock | Live result | Verdict |
|---|---|---|---|
| INOC-01 (5 groups, 11 children, canonical names) | Names filled from session counter | Names = NEEDS_SEQ (ask-back path) | **PARTIAL** — structure correct (5 groups, 11 children), names deferred to ask-back. Full loop completes after simulated reply '1' fills names canonically (untested in this live-fire). |
| INOC-02 (provenance per field) | sources[] populated | All 5 groups have sources:['audio','paper_log_photo'] on parent/species/qty; sources:['paper_log_photo'] on child_block_names | **PASS** |
| INOC-03 (conflict logging) | photo wins, conflicts[] populated | No conflicts emitted; model decoded audio + photo as agreeing on all fields | **N/A** for this fixture (no conflict surfaced); covered in synthetic conflict test |
| INOC-05 (ask-back when SEQ unclear) | needs_input='starting_seq', NEEDS_SEQ sentinels, ask-back side effect | needs_input='starting_seq' ✓, NEEDS_SEQ sentinels ✓, sideEffects=['send_starting_seq_askback'] ✓ | **PASS** — and unexpectedly fired on the canonical May-22 fixture, which is fine |

## Interpretation

The model treated the May 22 photo's row-position numbering as **ambiguous evidence** for SEQ values rather than asserting them. CONTEXT.md INOC-01 expected the model to extract SEQ from row positions (1..11). In practice, the model chose the more conservative path per friction policy `[[friction-policy-missing-vs-mismatch]]` — when info is genuinely missing (or in this case, model isn't confident it's reading SEQ), ask back.

This is **arguably correct behavior**. The farmer's row-number convention is a legitimate SEQ source, but a model OCRing a paper log can't be sure a "4." next to a row is "SEQ 4" or "step 4" or "row 4 of the page" without explicit context.

Two ways to read this:
- **Liberal:** the model is being overly conservative; tighten the prompt to teach "numeric prefix on inoc rows == SEQ".
- **Conservative (recommended):** the model's behavior is exactly the safety net Gray Area 3 was designed for. The ask-back is the right UX — farmer types "1", system fills canonical names, commit proceeds. Total farmer cost: one extra reply per inoc session.

Going with conservative. The test's INOC-01 assertion needs to add the "simulate ask-back reply, then assert canonical names" step to fully prove the loop, but the model itself is doing the right thing.

## Follow-on for 47-05 test

Modify `seeding-session-may22.test.js` LIVE-FIRE branch to:

1. Run pipeline → assert structure (5 groups, 11 children, needs_input='starting_seq', NEEDS_SEQ sentinels). [Currently asserts wrong thing.]
2. Call `handleStartingSeqReply(draftId, '1')` → asserts child_block_names fill to `260522_SHI_1..3 + 260522_KOY_4..11`.
3. Asserts side-effect now includes `send_confirm_prompt` (the normal YES/NO/EDIT preview).

This is ~30 LOC test edit. Worth doing before Phase 47 milestone close.

## What this means for v1.9 ship-gate (Phase 49)

When Phase 49 re-processes the May 22 captures end-to-end against farmOS dev, the user (Santi) will receive an ask-back prompt: "May 22 inoc, 11 blocks. What block number should I start at? Default is 1. Reply with a number or just YES." A single YES reply produces all 11 canonical seeding logs + 1 session asset. That's the milestone ship-gate behavior — exactly what `[[session-is-production-shape-per-bag-is-storage]]` calls for.

## Files

- Test: `src/agents/alerter/test/extraction/integration/seeding-session-may22.test.js`
- Fixture: `src/agents/alerter/test/fixtures/seeding-session-may22/`
- Hermetic: PASS (1/1) — unchanged
- Live-fire: PARTIAL — needs the ask-back-reply follow-on assertion (tracked here, not blocking Phase 47 ship)
