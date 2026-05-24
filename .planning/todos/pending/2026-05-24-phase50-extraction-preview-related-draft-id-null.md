---
filed: 2026-05-24
source: Phase 50 LIVE-FIRE Step 3 (Santi-driven) — DB inspection during attestation
severity: data-quality bug (paper-trail-affecting; no farmer-visible symptom)
priority: medium (low farmer impact today, but blocks Phase 51 stub-merge audit and any "which outbound dispatched this draft" forensic)
---

# `extraction_preview` outbound rows missing `related_draft_id`

## What

`signal_outbound` rows with `intent='extraction_preview'` are landing with `related_draft_id=NULL` even when the draft was created in the same dispatch path 4ms earlier.

Observed 2026-05-24 ~16:24 ART during Phase 50 LIVE-FIRE Step 3:

```
draft  7c659b8c... created   2026-05-24 16:24:30.464604+00 status=awaiting_farmer log_type=observation
outbound 8824c524-... sent    2026-05-24 16:24:30.489+00 intent=extraction_preview related_draft_id=NULL
```

The 25ms gap is the dispatch wiring inside the same tick. The outbound carries the canonical preview body, has `signal_msg_ts` populated correctly, but doesn't record the draft it relates to.

## Why it matters

- **Forensic queries break.** "Show me every outbound the farmer ever saw for draft X" cannot be answered by joining on `related_draft_id` — preview rows are invisible to it.
- **Phase 51 stub-merge audit needs this column.** The upsert layer's reconciliation will want to walk every outbound tied to a draft to confirm the farmer was informed; NULL rows are silently skipped.
- **Phase 50 quote-threading sibling finding (`...quote-thread-missing-on-extraction-preview-and-ask-back.md`) needs this column populated** when it adds the quote payload to extraction_preview — the resolver fetches the related draft to build the quote target.

## Fix sketch

Find the `extraction_preview` dispatch site. Likely `src/agents/alerter/src/extraction/preview-dispatch.js` or `src/extraction/preview.js` or wired through `confirm/outbound-confirm.js` like the other acks. Pass `relatedDraftId: draftRow.id` into the `signal_outbound` insert.

Hermetic test: ensure every dispatch path under `confirm/` and `extraction/` that has a `draftRow` in scope populates `related_draft_id` when calling `outbound-db.insertOutbound(...)`. Could be a simple grep-gate + a parameterized test.

## Cross-references

- Sibling finding: `2026-05-24-phase50-quote-thread-missing-on-extraction-preview-and-ask-back.md`
- DB schema: `\d signal_outbound` (col `related_draft_id text`)
- Code: `src/agents/alerter/src/outbound-db.js` (`insertOutbound` shape)
