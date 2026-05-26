# Farmer double-check before minting an unknown fungi_type (strain)

**Filed:** 2026-05-25 (Phase 54 Cycle-1 follow-on). Design locked with Santi.
**Supersedes:** the blind auto-mint approach (Cycle-1 finding B). `createMissingFungiType`
is gated OFF in the backfill harness until this lands.

## Why

Cycle-1 validation auto-minted extraction variants as bogus taxonomy terms:
`LIM` (for LIMA), `SHITAKE` (for SHI), `OYS`/`KOY` (for POY -- oyster synonym + P/K
OCR confusion). Blind minting pollutes the SHARED fungi_type taxonomy and hides real
ambiguities from the source of truth. The `ensureFungiTypeUuid(client, name, {create})`
mechanism exists (fungi-type-cache.js); what's missing is the confirm gate on `create`.

## Locked design (with Santi 2026-05-25)

1. **Detection = exact-match only, against the CURATED active set.** A strain code passes
   silently ONLY if it exactly matches a code in the curated active list
   ([[project_mossrock_active_strain_codes]] -- the 14 known codes), NOT "any existing
   fungi_type term in farmOS". Critical: dev farmOS already contains pollution terms
   (LIM/SHIITAKE/OYS/CAR, see cleanup below) that the bot cannot delete, so matching
   against live farmOS terms would let a re-extracted "LIM" exact-match the bogus term and
   silently pass. Match against the curated source-of-truth list instead. NO fuzzy
   auto-resolve -- never silently mis-map a real new strain one char from an existing one.

2. **Live capture:** when extraction yields an unknown strain, ask via the Phase 39
   confirm-loop / ask-back: "Hey, I saw 'XYZ' on today's log -- new strain, or did you
   mean <nearest known>? Confirm or correct." YES -> mint term + proceed. Correction ->
   remap to the canonical code.

3. **Backfill (async, bulk):** BATCHED confirm. Collect all unknown strain codes across
   the run; hold those drafts as `needs_review` (do NOT commit, do NOT mint); send ONE
   Signal message listing them ("Backfill found new codes: LIM, SHITAKE, OYS. Real new
   strains, or typos for LIMA/SHI/POY?"). On farmer reply, a follow-up pass mints the
   confirmed-new terms (ensureFungiTypeUuid create=true), remaps corrections, and commits
   the held drafts. Honors [[feedback_farmer_is_reality_source_of_truth]] +
   [[feedback_friction_policy_missing_vs_mismatch]] (genuinely-missing taxonomy = ask).

## Scope / touch points

- Strain resolver: exact-match check against known fungi_type terms (reuse fungi-type-cache).
- Live path: hook into confirm-loop ask-back (Phase 39) for the per-encounter prompt.
- Backfill path: unknown-strain collection + needs_review hold + one batched Signal
  message + a follow-up confirmed-mint+commit pass.
- `ensureFungiTypeUuid` already built; the confirm flow calls it with create=true only
  AFTER farmer confirmation.

## Cleanup owed from Cycle-1 validation (NEEDS FARMOS ADMIN)

Run 2026-05-25T23-52-52-434Z (blind-mint ON) created 4 bogus dev-farmOS fungi_type
terms. Confirmed via the app's own resolver (curl filter[name][value] was unreliable).
The `mushy-bot` user CANNOT delete them (DELETE -> 403); a farmOS admin must remove:

- LIM       d21746c9-d5db-44bc-9033-7d13653a90da   (variant of LIMA)
- SHIITAKE  8f0ba9c1-3d60-48c3-82b5-2cc8b774e417   (full name; should be SHI)
- OYS       0430811d-f0b2-42b2-b25e-39674a7e794f   (oyster; CSV uses POY)
- CAR       b0885c6e-9d2f-4c65-9743-720b2c107cc9   (unknown)

Canonical terms verified present + correct: LIMA, SHI, CAS, CAZ, KOY. POY is absent
(CSV ground truth uses POY but dev farmOS has no POY term). Also: the dev backfill
ASSETS + logs from the validation runs (22-35-41, 23-32-41, 23-52-52) are throwaway
test data -- wipe dev backfill assets before the real confirm-gated Cycle-1 run, or
accept upsert-reuse. Matching against the curated active set (design point 1) makes the
gate robust even while these bogus terms linger.
