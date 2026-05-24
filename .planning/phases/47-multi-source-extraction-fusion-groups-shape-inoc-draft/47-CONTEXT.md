# Phase 47: Multi-source extraction fusion + groups-shape inoc draft — Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Source:** Interactive discuss session 2026-05-23 (4 gray areas resolved)

<domain>
## Phase Boundary

A multimodal inoc capture (audio + photo of paper log + optional text + image of bag labels) produces ONE draft of new top-level type `seeding_session` in the groups-shape that mirrors how the farmer actually thinks about inoc: "May 22, 11 blocks across 5 parents and 2 species." Each field carries per-source provenance metadata (inline object-per-value: `{value, confidence, sources[]}`) so cross-source disagreement is detectable at commit time. Conflict resolution policy is photo-wins-silently with an audit-log entry; missing-data resolution policy is ask-back with a sensible default. Legacy `SeedingLog` (single-bag flat shape) stays for non-session seeding events; new type does NOT replace it.

This phase delivers the EXTRACTION half only. Phase 48 picks up the COMMIT half (session asset + per-bag fan-out + group-by-parent confirm preview).

In scope:
- New Zod schema `SeedingSession` (top-level `Draft` discriminated-union member) with groups[] and inline-provenance fields.
- New schema `SeedingSessionGroup` with `parent`, `species`, `qty`, `child_block_names[]` — each modeled as `{value, confidence, sources[]}`.
- Extractor system prompt revision teaching the model: (a) emit groups-shape when the page/audio describes a multi-parent OR multi-species session; (b) prefer photo for SEQ and parent-batch identifiers; (c) when sources disagree, photo wins, log the conflict; (d) when SEQ source is absent, emit `needs_input='starting_seq'` rather than guessing.
- New ask-back flow: `needs_input='starting_seq'` triggers a "What SEQ should I start at? Last today was N=..., default N+1" prompt. Farmer reply numeric → re-render with full block_names → normal YES/NO/EDIT preview.
- Conflict logging in `draft.draft_json.conflicts[]` (NOT in farmer preview).
- Extraction continues to emit `drafts[]` array (multi-draft submission stays for genuine multi-event pages); a `seeding_session` IS one draft element, not many.
- Single-parent legacy support: a 1-parent N-children inoc still extracts as `seeding_session` with `groups[1]` (per `[[multi-parent-inoc-batch]]` acceptance #4). Legacy `SeedingLog` is reserved for single-bag-no-session contexts (rare).

Out of scope (Phase 48):
- Session asset write to farmOS.
- Per-bag commit fan-out from one `seeding_session` draft → N farmOS seeding logs + 1 session asset.
- Group-by-parent confirm preview rendering. (Phase 47 emits a draft with the conflict/provenance data; Phase 48 renders the farmer preview from it.)
- EDIT routing into a session draft (does EDIT replace whole session? one group? one bag?). Defer to Phase 48 commit-side design.

Out of scope (deferred entirely):
- Conflict UX for `harvest` (when scale photo says 1.2kg, audio says 1.1kg). Same policy probably applies but defer until a real harvest fixture surfaces it.
- LLM-inferred SEQ from DB max+1 (rejected as Option C in gray area 3 discuss; ask-back is the lock).
- Mid-session capture continuity (turn 1 has 5 blocks, turn 2 has 6 more; same session). Treat as separate sessions for first ship; revisit if real-data evidence shows the pattern.
</domain>

<decisions>
## Implementation Decisions

### Gray Area 1 — Draft schema: groups-shape, new top-level type
**Lock: new `SeedingSession` discriminated-union member.** Per-bag drafts (Option A) lose session identity; hybrid (Option C) creates EDIT-ambiguity that supersedes Phase-50 quote-thread work before it ships.

Schema sketch (Zod-ish; finalize at plan-phase):

```
SeedingSession = z.object({
  type: z.literal('seeding_session'),
  event_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),  // YYYY-MM-DD, day-grain
  groups: z.array(SeedingSessionGroup).min(1),
  needs_input: z.enum(['starting_seq']).optional(),
  conflicts: z.array(ConflictEntry).optional(),
  notes: z.string().optional(),
}).strict()
```

The `groups[]` carries the canonical session data. `event_date` is day-grain (YYYY-MM-DD); the per-bag event_timestamp is derived at commit time (Phase 48) — every bag in the session shares the session's date.

Legacy `SeedingLog` is NOT removed. The discriminated-union now has both. The extractor system prompt decides which to emit based on cardinality (`groups.length >= 1` AND `total_blocks > 1` → `seeding_session`; else `seeding`).

### Gray Area 2 — Provenance: inline object-per-value
**Lock: each field that could come from multiple sources is `{value, confidence, sources[]}`** where `sources[]` is a subset of `['audio','paper_log_photo','bag_label_photo','text','model_inference']`.

Applies to: `group.parent`, `group.species`, `group.qty`, `group.child_block_names` (the value here is `string[]`).

Does NOT apply to: `type` (always 'seeding_session'), `event_date` (single value from audio/photo agreement OR ask-back), `notes` (free text from one source).

Token cost watch: extractor response is ~3x verbose vs flat. For typical sessions (1–8 groups), this is bounded. If a real session ever exceeds the context budget, fall back to "provenance only on contested fields" (gray area 2 Option C). Tracked as a watch, not a P0.

### Gray Area 3 — Photo-absent SEQ: ask-back with last-today default
**Lock: when paper-log photo is absent AND no explicit SEQ in audio, extractor emits the draft with `child_block_names` populated as sentinel `'NEEDS_SEQ'` strings AND `needs_input='starting_seq'`.** Pipeline detects this and renders an ask-back prompt:

```
May 22 inoc, 11 blocks. What SEQ should I start at?
Last SEQ today was 260522_KOY_3, so default is 4.
Reply with a number or just YES for the default.
```

The "last today" hint comes from a `SELECT MAX(seq) FROM signal_draft / farmOS logs WHERE date = event_date GROUP BY ...` lookup at pipeline time (NOT at extraction time — keeps the extractor pure). If no prior SEQ today, hint says "default is 1".

Farmer reply: numeric `N` → fill `child_block_names` from N. Just `YES` → fill from default. Then re-render confirm preview through Phase 48's group-by-parent table.

Photo IS present: photo wins, no ask-back, even if confidence is low (the audit log captures the low-confidence read for forensics).

### Gray Area 4 — Conflict UX: photo wins silently, log to draft.draft_json.conflicts[]
**Lock: NEVER surface OCR-vs-Whisper conflicts to the farmer.** Photo (the canonical farmer-authored artifact) wins. Conflict is logged in `draft.draft_json.conflicts[]` with shape:

```
{ path: 'groups[1].parent.value',
  candidates: [
    {value: '260118_SHI_23', source: 'audio',           confidence: 0.7},
    {value: '260118_SHI_25', source: 'paper_log_photo', confidence: 0.95}
  ],
  resolution: 'photo_wins_implicit'
}
```

**Explicit override of memory `[[extraction-holistic-multi-source-fusion]]` rule 2 ("never silently pick one").** Refined policy: silent photo-wins is acceptable for source mismatch; ask-back is reserved for genuine missing-data. Audit log is the fidelity mechanism.

Cohesion with other picks: the 4 locked decisions optimize for friction OK on missing-data (Gray area 3), friction NOT OK on trivial source conflict (Gray area 4). Memory update committed alongside this CONTEXT.md.

### Other locked policies (carried from memory)

- B5 SEQ is per-session (1..N across all strains in a day's session), not per-strain. Per `[[b5-seq-is-per-session-not-per-strain]]`.
- Multi-source fusion: audio + image(s) + text fused into one draft per turn-bundle. Per `[[extraction-holistic-multi-source-fusion]]`.
- Session is the production unit; per-bag is storage. Per `[[session-is-production-shape-per-bag-is-storage]]`. Phase 47 produces the session-shaped draft; Phase 48 writes per-bag.
- Multi-parent batch is THE common shape (~80% of real sessions). Per `[[multi-parent-inoc-batch]]`.
- No em-dashes in any farmer-facing text. Per `[[no-em-dashes-in-artifacts]]`.
- Round numbers via `fmtNum`. Per `[[round-farmer-numbers]]`.

### Style locks (apply to ask-back + future Phase 48 preview)

- "Last SEQ today was N=..., default N+1" hint — no em-dashes, no jargon ("block number" not "SEQ" in farmer-facing copy; "SEQ" is dev shorthand).
- Named address (`Hi {name},`) when sender_name resolvable from `signalFarmerMap`.
</decisions>

<canonical_refs>
## Canonical References (MUST read before planning)

- `.planning/phases/47-…/47-CONTEXT.md` (this file)
- `[[multi-parent-inoc-batch-is-the-common-shape]]` — driver: 11 bags from 5 parents is the May 22 canonical shape
- `[[extraction-holistic-multi-source-fusion]]` — fusion rules; **note Phase 47 refinement: silent photo-wins on conflict (memory update committed alongside)**
- `[[session-is-production-shape-per-bag-is-storage]]` — storage/surface decoupling; this phase produces the session-shaped draft, Phase 48 writes per-bag
- `[[b5-seq-is-per-session-not-per-strain]]` — locked schema clarification: SEQ counter is session-wide
- `[[farmos-schema-locked-2026-05-11]]` — B5/B7/C4/C5 locked schema; this phase honors B5 + B7
- `src/agents/alerter/src/extraction/prompts/system.js` — current system prompt; main edit target
- `src/agents/alerter/src/extraction/schemas/seeding.js` — current `SeedingLog` (kept); add `SeedingSession` alongside
- `src/agents/alerter/src/extraction/schemas/index.js` — discriminated-union; extend with new type
- `src/agents/alerter/src/extraction/extractor.js` — extractor caller; needs to handle new ask-back state
- `src/agents/alerter/src/extraction/pipeline.js` — pipeline; needs `needs_input='starting_seq'` handling + ask-back rendering
- `src/agents/alerter/src/extraction/validator.js` — validation; needs to accept new shape
- `src/agents/alerter/src/extraction/preview-builder.js` — confirm preview; for Phase 47 emit a minimal "groups-shape draft, awaiting SEQ if needed" preview (Phase 48 ships the group-by-parent table)
- Real test fixtures: May 22 session captures (`01KS8KHYTRJDZQEM5C4P989B8B` audio, `01KS8KHYTSYYGV500ZQVEY12VX` photo, `01KS8PT5YH9G76Y3BC54TZV19B` text) — use as gold-standard fixture for Phase 47 ship-gate

## ROADMAP-named requirements (proposed; lock at plan-phase)

INOC-01 — Replay 2026-05-22 audio+photo through new extractor → emits ONE `seeding_session` draft with 5 groups, 11 children, child_block_names per session-wide counter `260522_SHI_1..3 + 260522_KOY_4..11`.
INOC-02 — Each group field is provenance-tagged: `parent.sources` includes 'audio' or 'paper_log_photo' or both; `child_block_names.sources` is 'paper_log_photo' when photo present.
INOC-03 — Synthetic conflict fixture (audio:'118-23', photo:'118-25') → draft has `groups[1].parent.value === '260118_SHI_25'` (photo wins) AND `draft.draft_json.conflicts[0]` captures both candidates. Farmer-facing preview NEVER mentions the conflict.
INOC-04 (carry-fwd to Phase 48) — Single-parent legacy session extracts as `seeding_session` with `groups.length === 1`.
INOC-05 (Phase 47-specific) — Photo-absent session → draft has `needs_input='starting_seq'`, child_block_names sentinel `'NEEDS_SEQ'`; ask-back prompt renders correctly; farmer numeric reply fills block_names.
</canonical_refs>

<code_context>
## Existing Code Insights

**Extractor (`src/agents/alerter/src/extraction/`):**
- System prompt at `prompts/system.js` already supports multi-draft submission (`drafts[]`) per Plan 38-08. The new shape ADDS a top-level type to the discriminated union, doesn't break submit_extraction.
- Schemas under `schemas/` are Zod `.strict()` discriminated-union members; adding `SeedingSession` is additive.
- `extractor.js` does the tool-use call + validation. New shape: same call, new schema branch.
- `pipeline.js` handles the post-extraction state machine (ask-back, draft persistence, confirm dispatch). This is where the new `needs_input='starting_seq'` ask-back path lives — mirror existing ask-back patterns (e.g., the Phase 38 ask-back for low confidence).

**Confirm preview (`src/agents/alerter/src/extraction/preview-builder.js`):**
- For Phase 47: emit a minimal preview that says "May 22 inoc, 11 blocks — awaiting SEQ" when `needs_input='starting_seq'`, OR a minimal "11 blocks across 5 groups, group-by-parent preview to come from Phase 48" placeholder. Phase 48 owns the production preview.

**DB schema:**
- `signal_draft.draft_json` is `jsonb` — accepts the new shape without migration. `signal_draft.log_type` is `text` — extend the allowed-values set (in app code, no DB constraint) with `'seeding_session'`.

**Last-SEQ lookup:**
- `SELECT MAX(...) FROM signal_draft WHERE event_date = $1 AND status = 'committed'` — would need to extract SEQ from `block_name` regex. Cheap one-time query; cache per-session.
- ALSO needs to query farmOS dev for committed-but-not-yet-mirrored SEQ (Phase 48 will mirror committed drafts to farmOS — but for Phase 47, farmOS query is the source of truth for "last today").

**May 22 capture data — already in prod DB:**
- audio `01KS8KHYTRJDZQEM5C4P989B8B` — 761-char transcript
- photo `01KS8KHYTSYYGV500ZQVEY12VX` — paper-log image
- text `01KS8PT5YH9G76Y3BC54TZV19B` — 131-char follow-up
- expired draft `6edaaba7` (1 of 11 captured) — keep as failed-state forensics
- discarded draft `e3a564d0` (observation fallback) — keep as failed-state forensics

The ship-gate at end of Phase 49 will re-process these captures through the new pipeline. Phase 47 ship-gate is a narrower: extract this turn → emit valid `seeding_session` draft with correct shape (block_names, provenance, no conflicts since photo is clear).
</code_context>

<specifics>
## Specific Ideas

- Plan size: M (likely 4-5 plans, ~1-2 days).
- Plan structure proposal (lock at plan-phase):
  - P-01: New schemas (`SeedingSession`, `SeedingSessionGroup`, `ConflictEntry`, `Provenanced<T>`) + discriminated-union extension + unit tests.
  - P-02: System prompt revision + few-shot example for groups-shape multi-parent + conflict-resolution policy.
  - P-03: Pipeline `needs_input='starting_seq'` handling + ask-back render + last-SEQ-today lookup helper.
  - P-04: Preview-builder placeholder for `seeding_session` (Phase 48 ships real preview).
  - P-05: Integration test using May 22 captures as gold fixtures.
- Token-cost watch: log each extraction call's input+output tokens, compare to pre-Phase-47 baseline.
- Real-data testing: use the May 22 captures as the named regression fixture (Phase 49 will formalize the eval corpus; Phase 47 just needs the test to pass).
- The "Last SEQ today" lookup is a Phase 47 helper that Phase 48's commit fan-out will also use — design with both consumers in mind, place under `extraction/seq-helper.js` or similar so Phase 48 can require it.
</specifics>

<deferred>
## Deferred Ideas

- Conflict UX for harvest (scale photo vs audio) — same policy probably; defer until real fixture surfaces it.
- LLM-inferred SEQ from DB max+1 (Option B in Gray area 3) — explicitly rejected; ask-back is the policy.
- Mid-session continuity (multi-turn capture stitched into one session) — treat each turn as a separate session for first ship; revisit when real evidence shows the pattern.
- Provenance "only on contested fields" sparse encoding (Gray area 2 Option C) — fallback if token cost ever becomes a problem.
- Conflict-aware EDIT routing ("the conflict was on row 2, EDIT row 2 only") — Phase 48 commit-side design problem; not Phase 47.
- Quote-threading on the ask-back ("which SEQ?") prompt — Phase 50 territory; out of scope here.
- Phase 38 backfill (re-extract old captures through new extractor) — not in this phase. Phase 49 may decide which historical fixtures to re-extract for eval purposes.
</deferred>
