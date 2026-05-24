# Phase 38 photo-vs-paper-log classifier is too eager (photos of physical bags treated as paper-log scans)

**Filed:** 2026-05-24 (surfaced during v1.9 live-fire UAT with Santi)
**Severity:** low-medium — wrong extraction shape on photo-only captures of physical things; recoverable but adds farmer-friction
**Scope:** Phase 38 extractor system prompt (`src/agents/alerter/src/extraction/prompts/system.js`)
**Related:** sibling todo `2026-05-24-phase38-batch-mode-misroutes-small-multi-draft-captures.md`

## What happened

Santi sent a Signal message: photo of 2 spawn-tubs + caption "DT tubs 0519 1 and 2". The extractor treated this as a paper-log-scan-style multi-row page and emitted 2 observation drafts even though the photo wasn't a paper log at all — it was a photo of two physical tubs.

The drafts themselves are well-formed (`asset_ref=260519_DT_1` / `_2`, sensible state text, day-grain timestamp) so the extraction recovered. But the classification ("this is a paper log") is wrong.

Tonight only mattered because of the downstream routing bug (`needs_review` auto-mark) — see sibling todo. If routing is fixed, this becomes lower-priority. But it's still wrong.

## Root cause

The extractor system prompt teaches "multi-bag visible → emit per-bag drafts" but doesn't distinguish between:
- **Paper log photo**: notebook page with handwritten rows, OCR-able grid
- **Physical bag/tub photo**: 1-N physical objects of the same kind in frame, sometimes with caption

Both produce `drafts.length > 1` from a single capture. Only the first should be flagged as a paper-log scan in `signal_capture.capture_subtype` or similar metadata.

## Proposed fix

Either:

1. **Extractor prompt enhancement** — add a few-shot pair distinguishing paper-log vs physical-tub photos; output a `capture_kind: 'paper_log' | 'physical_object_photo' | 'voice_note' | 'text'` field on the extraction envelope.
2. **Vision-only pre-classifier** — fast Haiku-class call on the image alone before the full extraction: "is this image a notebook/paper page with handwritten rows, or a photo of physical objects?" Cheap, deterministic.

Option 2 is more robust but adds latency. Option 1 is cheaper but the extractor has more cognitive load.

## Out of scope

- This is NOT the routing bug. Even if classification were perfect, the >1-draft batch routing would still misroute small-N captures. Fix that first.

## Links

- Source capture: `01KSCW771VB2FDWBPWNS4MEHAZ` (DT tubs photo, NOT a paper log)
- Counter-example paper-log fixture: 2026-05-22 paper-log photo at `mushdatadump-prod/2026-05-12_inoc_santi/XAbzzUidkLR3irhVmjea.jpg`
- Code: `src/agents/alerter/src/extraction/prompts/system.js`
- Phase 38 Plan 08 (batch mode origin)
- Related conversation: 2026-05-24 farmer UAT with Santi
