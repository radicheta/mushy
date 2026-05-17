---
date: 2026-05-17
author: claude (overnight survey for v1.8 Phase 44 Plan-01 sourcing)
scope: count what's available in /mnt/mossrock/shared/mushdatadump-prod/ and recommend a sampling strategy for the 100-capture hand-classification smoke
companion-notes:
  - .planning/notes/2026-05-17-is-this-an-event-gate.md (target class distribution)
verdict: frozen corpus is too thin (3 captures); 100-sample MUST be drawn from live Timescale signal_capture on elder-plops with stratified sampling
---

# Prod corpus survey — v1.8 Phase 44 Plan-01

## 1. Directory shape

`/mnt/mossrock/shared/mushdatadump-prod/`:

- `2026-05-12_inoc_santi/` — first prod inoc session (May 12, 18:26 UTC)
- `2026-05-13_backlog_unprocessed/` — Phase 38/39 drafts that piled up during silent downtime (see `[[project_2026_05_13_phase39_40_silent_downtime]]`)

Date range: 2026-05-12 → 2026-05-13 (2 days, 3 organic captures).

## 2. File inventory

- 6 JSON (3 capture.json + 3 draft.json — frozen rows from signal_capture / signal_draft)
- 4 JPGs (2 in `2026-05-12_inoc_santi/`, 2 in 2026-05-13 squash harvest)
- 2 audio (16.2 MB m4a inoc narration, 40 KB butt-dial aac)
- 3 text transcripts/logs (pre-VAD, post-VAD, replay-output.txt)

## 3. Frozen captures available (3 total)

| Capture | Sender | Type | Raw text | Target class |
|---|---|---|---|---|
| `946a7b` | Santi  | text  | "👍"                                  | conversational-ack (phantom-draft class) |
| `ace0973`| Santi  | text  | "650g shiitake from logs"              | hard event (harvest w/ qty) |
| `55005e` | Vikki  | image | "Squash harvest from GH, 0.853 kg"     | hard event (multimodal: 2 photos + caption) |

## 4. Why the frozen corpus alone is insufficient

The 2026-05-17 event-gate note (section 3) calls for a 100-capture sample stratified into 6 classes. The frozen corpus has 3 rows covering 2 classes. There's no path to 100 from this directory alone.

## 5. Recommended Plan-01 sourcing

**Pull live from Timescale `signal_capture` on elder-plops:**

```sql
SELECT id, captured_at, sender, message_type, raw_text, transcript,
       attachment_paths, llm_reply, farmos_person, reply_target_kind
FROM signal_capture
WHERE captured_at >= '2026-05-10'
ORDER BY captured_at DESC
LIMIT 500;
```

Then hand-stratify down to 100 preserving the 2026-05-17 distribution:

| Class | Target count | Source heuristic |
|---|---|---|
| Hard event (image / audio / strain code / block name / >200 char text) | 36 | filter by `message_type IN ('image','audio')` OR length(raw_text) > 200 OR regex match |
| Confirm verbs (YES/NO/EDIT against in-flight draft) | 28 | filter by short text + draft existed within 30m |
| Conversational ack (phantom-draft class) | 8 | the 946a7b template: short text after attestation kickoff |
| UX-meta | 8 | hand-pick |
| Soft observation | 12 | mid-length free text, no strain code |
| Greetings / chit-chat | 8 | hand-pick |

Include the 3 frozen-corpus captures as seeds. Tag each row with `tenant=mossrock` per OSS-Foray Option α so the corpus is reusable when a second tenant exists.

## 6. Why stratified, not random

Phantom-ack is an 8% slice empirically — random sampling would give ~8 of them in 100, but with high variance. Stratified guarantees the gate is evaluated against the class that motivated finding 7. Per `[[feedback_real_data_before_ship_gate_pass]]`, the corpus must include >=1 real-session fixture from each class.

## 7. Ship-gate metrics (per event-gate note section 8)

- Zero farmer-facing preview pings on hand-labeled chit-chat (8 phantom-ack + 8 greetings + 8 UX-meta = 24 must-skip rows)
- >=95% event recall on the 36 hard-event + 12 soft-obs = 48 must-extract rows
- Confirm verbs (28) bypass extractor entirely via Phase 39 short-circuit — they should not even reach the gate

## 8. Logistics

- Hand-classification is operator/Don-Santiago work (cannot be automated; per `[[feedback_real_data_before_ship_gate_pass]]`).
- Output: a `.planning/phases/44-event-gate/44-hand-classified-100.jsonl` file alongside RUNBOOK.
- Append-only JSONL with `tenant_id`, `capture_id`, `class`, `expected_gate_action`, `notes`. Per `[[feedback_persist_paid_results_default]]` and `[[feedback_keep_paper_trail_of_intermediates]]`.
