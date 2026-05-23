# Fixtures: May 22 2026 seeding session (real prod capture)

Source: prod `signal_capture` rows + on-disk attachments. Pulled 2026-05-23 by
Phase 47 Plan 05 executor.

| File | Origin | Notes |
|------|--------|-------|
| `transcript.txt` | `signal_capture.transcript` of `01KS8KHYTRJDZQEM5C4P989B8B` (761 chars) | Whisper transcript of the voice memo. Plain text, one line, lowercase. |
| `text-followup.txt` | `signal_capture.raw_text` of `01KS8PT5YH9G76Y3BC54TZV19B` (131 chars) | Farmer text confirming "please process this inoc session". |
| `paper-log.jpg` | `/data/signal-capture/2026-05-22/19-45-49-01KS8KHYTSYYGV500ZQVEY12VX-4-z7i6VzwYu1daWLH54R.jpg.jpg` (~81 KB JPEG) | Photo of the paper log for the May 22 session. Binary; checked in as-is. |
| `expected-draft.json` | Hand-built from `47-CONTEXT.md` INOC-01 spec | Canonical `seeding_session` output the extractor should emit. Used as the hermetic mock response (wrapped in `tool_use` envelope by the test) and as the gold reference for live-fire diff. |

## Why these files

INOC-01..02 demand a real-data regression guard. Phase 49 will formalize the
eval corpus; for Phase 47 ship-gate these three files ARE the corpus.

## Canonical expected output

5 groups, 11 children, session-wide SEQ counter starting at 1:

- SHI x 1 parent `260304_SHI_5` -> `260522_SHI_1`
- SHI x 1 parent `260118_SHI_23` -> `260522_SHI_2`
- SHI x 1 parent `260118_SHI_26` -> `260522_SHI_3`
- KOY x 4 parent `260118_KOY_12` -> `260522_KOY_4..7`
- KOY x 4 parent `260425_KOY_4` -> `260522_KOY_8..11`

The transcript is ambiguous on KOY parent decoding ("one eighteen twelve" vs
"104" mid-stream); CONTEXT.md INOC-01 only locks the child_block_names list
as the regression guard, not the parent strings. Live-fire deviations on
parent strings are recorded but not failing.

## Live-fire

These same fixtures power both the hermetic and live-fire branches of
`seeding-session-may22.test.js`. Live-fire is gated behind
`EVAL_RUN_LIVE=1`. See `47-05-SUMMARY.md` for the invocation.
