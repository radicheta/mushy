# Task 1.2 — Operator hand-classification instructions

**Status:** PLAN BLOCKED on operator. Task 1.2 cannot be automated per
`[[feedback_real_data_before_ship_gate_pass]]` + D-23.

## Files in front of you

| File | Role |
|------|------|
| `44-01-CLASSIFICATION-RUBRIC.md` | **READ THIS FIRST, end-to-end.** Defines the 6 tags. |
| `44-01-raw-corpus.jsonl` | Immutable 108-row dump. Don't edit. |
| `44-01-classification-template.jsonl` | 108 pre-filled lines, one per raw row. `class`, `expected_gate_action`, `notes` are all `"TODO"`. **EDIT THIS to produce the deliverable.** |
| `44-hand-classified-100.jsonl` | The deliverable — **does NOT exist yet.** Produced by trimming the template to 100 rows after labeling. |

## Workflow

1. `cat 44-01-CLASSIFICATION-RUBRIC.md` — read all 6 tag definitions + edge cases.
2. Open `44-01-classification-template.jsonl` in your editor.
3. For each of the 108 lines:
   - Replace `"class": "TODO"` with one of: `hard-event` / `confirm` / `phantom-ack` / `UX-meta` / `soft-obs` / `greetings`.
   - Replace `"expected_gate_action": "TODO"` with `skip` or `extract` per the
     rubric table (it's deterministic from `class`, but include it explicitly
     so the smoke harness can sanity-check).
   - Replace `"notes": "TODO"` with a one-line justification. For edge-case
     rows (rubric §"Edge cases"), call out the known gate misfire path.
4. Once labeled, count by class. Your target is the D-20 distribution:
   - 36 hard-event
   - 28 confirm
   - 8 phantom-ack
   - 8 UX-meta
   - 12 soft-obs
   - 8 greetings
5. **Trim to 100 rows.** Drop 8 rows (108 - 100 = 8 excess) that are
   redundant within their over-represented class. Save the result as
   `44-hand-classified-100.jsonl`.
6. Reply **"100 classified"** when done.

## Distribution sanity-check (run after step 5)

```bash
F=.planning/phases/44-event-gate-durable-signal-outbound-tenant-aware/44-hand-classified-100.jsonl
wc -l "$F"                                                    # → 100
jq -s 'group_by(.class) | map({(.[0].class): length}) | add' "$F"
# Expect: {"UX-meta":8, "confirm":28, "greetings":8, "hard-event":36, "phantom-ack":8, "soft-obs":12}
jq -c 'select(.tenant_id != "mossrock")' "$F"                 # → no output
jq -c 'select(.class == "TODO" or .expected_gate_action == "TODO")' "$F"  # → no output
```

Task 1.3 (executor) will re-run these and HALT if any fail.

## Known supply constraints (deviation from plan)

- **Plan asked for 500-row pull, reality is 108.** signal_capture has only
  108 rows total since 2026-04-01 (99 since 2026-05-10). Floor was widened to
  capture the full corpus. Documented in `44-01-pull-corpus.sql` header.
- **Hard-event slot is tight (~31 candidates for 36 target).** 25 rows have
  attachments + 6 text rows match strain-code regex. To hit 36 you'll likely
  need to promote 5 borderline soft-obs rows to hard-event. Bias toward the
  rubric definition — over-counting hard-event inflates POSITIVE recall and
  hides Haiku regressions, so prefer to leave the slot SHORT and document
  the deficit in `notes` rather than promote weak candidates.
- **No frozen-corpus seeds.** The 3 mushdatadump-prod seeds (946a7b, ace0973,
  55005e) referenced in D-20 are NOT in live signal_capture — they predate
  the table or were wiped during a Phase 25/26 reset. No action needed; just
  documenting why the seed-corpus step from `2026-05-17-prod-corpus-survey.md`
  §5 is a no-op.
- **D-22 third bullet** (28 confirm rows bypass via Phase 39) needs a
  cross-check: the 28 confirm-tagged rows MUST actually have had a draft
  in `awaiting_farmer` state at their `captured_at`, otherwise they are
  `phantom-ack` not `confirm`. The line between the two is load-bearing.

## Append-only discipline

Per `[[feedback_keep_paper_trail_of_intermediates]]`: do NOT edit a line in
`44-hand-classified-100.jsonl` once committed. If you need to re-classify a
capture after first pass, work in the template file, then re-emit the final
100-row file from scratch.
