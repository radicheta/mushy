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

1. **Detection = exact-match only.** A strain code passes silently ONLY if it exactly
   matches a known fungi_type term (the 14 active codes / existing terms:
   [[project_mossrock_active_strain_codes]]). NO fuzzy auto-resolve -- never silently
   mis-map a real new strain that's one char from an existing one. Anything not an exact
   match is "unknown" and must be farmer-confirmed.

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

## Cleanup owed from Cycle-1 validation

Run 2026-05-25T23-52-52-434Z (blind-mint ON) may have created bogus dev-farmOS
fungi_type terms (LIM, SHITAKE, OYS, CAR) + their assets. Verify via the app's own
client (curl filter[name][value] was unreliable in testing -- KOY also read absent) and
delete the non-canonical terms. dev-only.
