# MUSHY-94 historical backfill -- 2026-08-19

Committed farm history was edited. Authorised by Don Santiago the same day, with
the explicit condition that a log carrying a real clock time is left alone.

**146 logs moved from UTC midnight to local midnight. 116 human-created logs
untouched. 0 failures.**

Pre-`e57c3b8` the commit path stored a date-only farm event at `00:00Z`, which
`America/Montevideo` renders at 21:00 the *previous* day. Every one of those
logs displayed a day earlier than the name it carried.

## The condition held, and the data made it unambiguous

The two sets turned out to be disjoint by author:

| | at exact UTC midnight | carrying a real clock time |
|---|---|---|
| mushy-committed | **146** (rewritten) | 0 |
| human-created | 0 | **116** (untouched) |

No human log sat at UTC midnight, so the filter could not have caught one. Exact
UTC midnight (`timestamp % 86400 == 0`) was the discriminator.

## Files

| file | what |
|---|---|
| `01-survey-before.jsonl` | full pre-change snapshot, 262 logs |
| `02-receipts.jsonl` | per-log `before` + `verified` receipt, 146 verified, each carrying `old_timestamp` |
| `03-survey-after.jsonl` | state after the first pass |
| `04-survey-final.jsonl` | final state, 0 logs at UTC midnight |

`02-receipts.jsonl` carries the old value for every edited log, so this is
reversible: patch `timestamp` back to `old_timestamp`.

## Verified after the fact, not assumed

Every patch was confirmed by re-reading the log; a 200 was not taken as evidence.
Then, against the final survey:

- human logs whose timestamp changed: **0**
- mushy logs not at local midnight: **0**
- distinct shifts applied: **{+10800s}** -- exactly +3h, nothing moved further
- logs whose name-date disagrees with their rendered date: **0** (was the whole
  complaint)

## The one thing that nearly went wrong

The first survey **missed 28 logs while duplicating 28 others**. farmOS
paginates inconsistently without an explicit sort, so `page[limit]=200` plus a
`next` link returned an overlapping window. The counts still looked plausible
(262 rows both times), and the arithmetic only failed to reconcile because the
rewrite reported 27 skips it could not otherwise account for.

Had the run been trusted on "146 candidates, 0 failed", 28 seeding logs would
have been left silently a day early -- indistinguishable from success. The
survey now sorts by `drupal_internal__id`.

**Lesson: reconcile the arithmetic of a batch, do not read the failure count.**
`0 failed` was true and the batch was still incomplete.

## Pre-existing data issue, not touched

`seeding/63 'Inoc 260514_DT_998'` is named for 2026-05-14 but timestamped
2025-05-15. Bag `998` and the year disagreement mark it as a test row. It was
shifted by the same one day as everything else; its name/date contradiction is
older than this work and is not addressed here.
