# Phase 38 batch-mode misroutes small multi-draft captures as needs_review

**Filed:** 2026-05-24 (surfaced during v1.9 live-fire UAT with Santi)
**Severity:** medium — degrades UX for legitimate multi-event captures from a single Signal message
**Scope:** Phase 38 extraction pipeline (`src/agents/alerter/src/extraction/pipeline.js`, Plan 08 batch mode); Phase 39 confirm-flow routing
**Related:** post-v1.9 follow-on (proposed Phase 51)

## What happened

Santi sent ONE Signal message with a photo + caption "DT tubs 0519 1 and 2" (2 simple tubs from 2026-05-19). The extractor correctly produced 2 well-formed observation drafts (one per tub, `asset_ref=260519_DT_1` / `_2`, confidence state=0.8 / asset_ref=0.9), but because `drafts.length > 1`, Plan 08's batch-mode path:

1. Auto-marked both drafts `status='needs_review'` with `needs_review_reason='batch_mode_low_conf'`.
2. Suppressed per-draft `confirm_prompt` to the farmer.
3. Fired the operator-channel `send_batch_review_summary` (Bug #2 already hotfixed via trinity-skip — see `2026-05-24-trinity-skip-operator-pings-when-operator-equals-sender.md`).

Result: 2 valid drafts sit in `needs_review` limbo. Farmer never sees them, never gets to YES/NO/EDIT, never lands logs in farmOS.

DB rows: `bb34475403…` (DT_1), `ccd52457c2…` (DT_2). Source capture: `01KSCW771VB2FDWBPWNS4MEHAZ`.

## Root cause

`pipeline.js:143` (Plan 08 batch mode): any `drafts.length > 1` extraction is treated as a paper-log scan (multi-event page from a notebook photo) and routed through the lower-trust review queue. The heuristic conflates two different patterns:

- **True paper-log scan**: 10+ rows on a notebook page, OCR'd. Low per-row confidence is real; operator-review gate is appropriate.
- **Multi-event single message**: a photo of 2-3 tubs with a single caption, or a voice note describing 3 harvests. Per-draft confidence is HIGH; should go through normal Phase 39 confirm flow as N separate `confirm_prompt`s.

## Proposed fix

Heuristic at the routing seam (between Phase 38 extraction emit and Phase 39 confirm dispatch):

```
if drafts.length > 5  OR  min(per-draft confidence) < 0.7:
  → batch-mode review queue (current behavior)
else:
  → normal Phase 39 confirm flow, N per-draft confirm_prompts
```

Pseudocode lives at routing seam, not in the extractor (extraction is pure; routing is policy).

## Acceptance / regression guard

- Tonight's `DT tubs 0519 1 and 2` capture (`01KSCW771VB2FDWBPWNS4MEHAZ`) becomes a named eval fixture under `test/eval/ingestion/fixtures/sessions/` or a new `test/eval/ingestion/fixtures/photos/` subdir. Ground truth: 2 confirm_prompts (one per tub) to the farmer, no operator-channel ping.
- A true paper-log scan fixture (e.g. May 22 paper-log photo) continues to hit the review queue.

## Out of scope (separate todo)

- The photo-vs-paper-log classifier — when a photo is NOT a paper log at all but the extractor still emits multi-draft, the underlying extraction quality is fine; routing is the bug. See sibling todo `2026-05-24-phase38-photo-vs-paper-log-classifier-too-eager.md`.

## Links

- Source capture: `01KSCW771VB2FDWBPWNS4MEHAZ`
- Stuck drafts: `bb34475403…`, `ccd52457c2…`
- Code: `src/agents/alerter/src/extraction/pipeline.js:143`, `src/agents/alerter/src/extraction/outbound.js:92-114`
- Related conversation: 2026-05-24 farmer UAT with Santi (post-v1.9 ship)
