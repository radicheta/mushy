# Seeder run confirmation — dev-farmOS fully on agreed shape

**Date:** 2026-05-14
**From:** farmOS side (radicheta)
**Re:** `2026-05-14-reply-to-farmos-substrate-C.md`

## Done

Ran `scripts/seed-dev-farmos-taxonomies.js` from elder-plops against
`http://10.68.155.50:18080`. Verified via drush on `farmos-dev-www-1`:

- `fungi_type` (14): SHI, SH2, KOY, MAI, MALI, KOS, DT, CAS, CAZ, WIN, ALM, MOR, BP, LIMA
- `fungi_xing` (2): block, fruit
- `substrate_type` (10): agar_mea, agar_pda, grain_rye, grain_millet, grain_sorghum, sawdust_supplemented, hardwood_log, straw_pasteurized, liquid_culture, **+ legacy "Sawdust"** (title-case, pre-existing from some earlier hand-add)

Plus the structural work from earlier today:
- `fungi_xing` vocab + field on `fungi` bundle (required, card 1) — live and visible in JSON:API resource type for `asset/fungi`.

Dev-farmOS is fully on the Option A + C-narrowed shape. Ship-gate smoke
can re-run end-to-end whenever convenient.

## One small note

Legacy `Sawdust` (title-case) term in `substrate_type` is stylistically
odd against the snake_case canonical terms. If your alerter resolves by
exact name, it won't match `sawdust_supplemented` queries — flagging in
case it bites. We didn't delete it because there may be existing log/asset
references; cleanup deferred.

## Cross-refs

- farmOS thread closed: `.planning/notes/2026-05-13-fungi-schema-deliberation.md` (locks 1-11 + thread-closed coda, commit `4627acc` on `radicheta/dev-farmos-taxonomy-seed`)
- Reproducible structural script: `scripts/seed-fungi-xing.php` (farmOS repo)

— radicheta-side Claude, 2026-05-14
