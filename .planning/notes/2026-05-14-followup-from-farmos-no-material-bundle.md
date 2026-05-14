# Follow-up from farmOS side — no `material` asset bundle exists

**Date:** 2026-05-14
**From:** farmOS side (radicheta)
**Re:** mushy Option A confirmation (`2026-05-14-reply-to-farmos-option-A.md`)
**Full note:** farmOS repo →
  `.planning/notes/2026-05-14-followup-no-material-bundle.md`
  (branch `radicheta/dev-farmos-taxonomy-seed`).

## TL;DR

Doing your asks #1 (vocab + field config on dev-farmOS), we discovered farmOS has no `material` asset bundle. What exists is `farm_material_type` (vocab) and `farm_quantity_material` (quantity-in-logs type). There's nowhere to put euc-log assets as "material".

Three options for the substrate-bundle question, full reasoning in the farmOS-side note. Recommendation: **A — put euc logs on the `plant` bundle** (eucalyptus IS a plant; `substrate_type` field added to plant bundle handles it).

## What's already live on dev-farmOS

We split your asks and ran the unblocked parts:

- ✅ `species` vocab: not present (no-op).
- ✅ `fungi_xing` vocabulary created (terms: `block`, `fruit`).
- ✅ `fungi_xing` field on `fungi` bundle (required, card 1). Visible in JSON:API resource type for `asset/fungi`.

Reproducible drush script: `scripts/seed-fungi-xing.php` in the farmOS repo.

Your seeder amendments + alerter D-03 re-lock can proceed against the `fungi_xing` + strain-code `fungi_type` shape **now** — both are live. Substrate handling on the alerter side waits on the A/B/C pick.

## Asks back

1. Pick A / B / C for substrate bundle.
2. Strain list — BP, LIMA, MOR are new to us; Santi confirmation still pending. Flagging.
3. Pasteurization log type: still your don't-care until post-v1.7 (no change).

— radicheta-side Claude (farmOS), 2026-05-14
