---
date: 2026-05-15
event_window_utc: 2026-05-15T23:30 to 23:48
farmer: santi (f1)
draft_id: 1fb28e709118807ed301b4c3b45f5042f194eabb9ab0000f288e9163fec93733
type: bridged-prod-event (Phase 40 happy-path UAT closure)
verdict: PASS via manual bridge -- exposed Phase 38<->Phase 40 schema mismatch for activity log_type
filing_for: discuss-later, companion to [[2026-05-15-rambo-th-window-unscripted-run]]
---

# Phase 40 happy-path UAT via lion's mane bridged commit

Santi sent an audio note about moving a lion's mane block to the fruiting
chamber. Like Vikki's Rambo draft, it hit `commit_failed`. Unlike Vikki's,
we manually bridged it to completion to drive Phase 40 happy-path UAT to
a closeout. Bridging surfaced a new finding: Phase 38 extractor output
shape does not match Phase 40 commit-activity input shape for activity
log_type. Phase 39 EDIT loop never caught it because EDIT re-extracts
into the same mold; the mismatch is downstream of extraction.

## Timeline

| UTC | What |
|---|---|
| 23:30:51 | Santi audio capture (transcribed by Whisper): "Two days ago, I put a lion's mane block into the fruiting chamber to fruiting Two days ago forgot to tell to tell you so yeah log it up Lion" |
| 23:30:57 | Phase 38 extracted activity/relocate draft: asset_ref="<UNKNOWN>" conf 0.0, event_timestamp 2026-05-13 conf 0.6 |
| 23:31:54 | EDIT-1 from Santi: "I dont understand what asset-ref means. Please speak in farmer to me." (finding 1d: jargon in farmer-facing preview) |
| 23:32:20 | YES from Santi |
| 23:32:45 / 23:33:15 / 23:33:45 | 3 commit_attempt -> retry -> failed (no_target_asset_for_activity) |
| 23:33:45 | terminal commit_failed; bot silent (same NORTH-STAR violation as Vikki) |
| 23:46:00 | Operator bridge begins -- probe farmOS prod for fungi assets |
| 23:46:15 | Discovered: no LIMA blocks in prod (only SHI/DT/WIN/KOY from 2026-04-25 backfill) |
| 23:46:30 | Created LIMA block 260415_LIMA_1 (uuid e0be0952-e77b-4316-8be6-28abdc62b134) via direct farmOS POST. id_tag=LIMA-260415-1 type=other. fungi_type=LIMA. fungi_xing=block. |
| 23:46:45 | Reshaped draft_json: added qr_codes=["LIMA-260415-1"], activity_subtype="relocate", timestamp=1778630400 unix. Cleared asset_ref + event_timestamp ISO fields. Reset status to confirmed, commit_attempt_count=0, commit_failed_reason=NULL, committed_at_attempt=NULL. |
| 23:47:20 | Watchdog picked up retry: commit_attempt |
| 23:47:22 | **commit_success** HTTP 201 in 1555ms. Log uuid 92632908-e88c-4480-a04a-cbac4ffce999. |
| 23:47:58 | Manual ack to Santi (Spanish per language stack, no em-dashes) |

## Phase 40 happy-path UAT verdict: PASS (with caveats)

- **Live attestation:** real audio -> extract -> EDIT -> confirm -> commit -> prod-farmOS activity log with valid asset relationship. End-to-end loop closed.
- **What was synthetic:** the LIMA block backfill (operator-created, not from a Phase 40 seeding commit). Necessary because no prior seeding of this strain was logged.
- **What was bridged:** the draft_json reshape from extractor shape -> commit-router shape. This is the finding-of-the-day below; the bridge step itself is operator-only.

## NEW Finding 4: Phase 38 extractor output schema != Phase 40 commit-activity input schema

**Where:** `src/agents/alerter/src/farmos/commits/commit-activity.js` vs `src/agents/alerter/src/extraction/...` (Phase 38 prompt + tool-use response shape).

**Mismatch:**

| commit-activity expects | Phase 38 extractor emits |
|---|---|
| `dj.qr_codes: string[]` (resolves each to assetId via `qr.resolveQr`) | `dj.asset_ref: string` (with `<UNKNOWN>` sentinel when unknown) |
| `dj.activity_subtype: string` | `dj.name: string` (used as activity name like "relocate") |
| `dj.timestamp: number` (unix seconds) | `dj.event_timestamp: string` (ISO 8601 like "2026-05-13T00:00:00Z") |

**Why it matters:** Phase 38 ship-gate passes on schema-conformance (B1-B7) but B1-B7 is the *farmer-input* schema, not the *farmOS-commit-input* schema. The translation layer between them does not exist for activity log_type. Observation and seeding paths happen to align (observation: asset_ref->no-target-required-on-farmOS-side is mostly tested via fixtures with farm-level fallback assumed; seeding: extractor emits the names that commit-seeding's resolveOrCreate consumes). Activity is the surface where the mismatch shows.

**Why Phase 39 EDIT loop didn't catch it:** EDIT re-runs Phase 38 extraction with farmerCorrection threaded in. The output remains in the extractor's shape, which is also what the EDIT loop validates back to. The mismatch is downstream of where EDIT can intervene.

**Fix candidates:**

- **(a)** Add a `commit-router` pre-step that normalizes extractor-shape draft_json to commit-shape before dispatch. Lowest blast radius; preserves both schemas at their boundaries.
- **(b)** Update Phase 38 extractor to emit the commit-shape directly. Loses the extractor-shape's semantic clarity (asset_ref vs qr_codes carry different meaning to the farmer); not recommended.
- **(c)** Add integration tests that exercise extractor-output -> commit-router for each log_type. Catches future drift. Should ship alongside (a).

**Recommendation:** (a) + (c) bundled. Same-week-fix class once Don Santiago green-lights.

## Cross-cutting observations

### "No LIMA blocks in prod" is itself a finding

The 2026-04-25 paper-log backfill only covered SHI/DT/WIN/KOY (the 12 inoc-sheet rows that were in scope). Real strains being grown right now include LIMA, KOY, MAI, etc. that have no farmOS-side asset. Every activity/observation/harvest log referencing those strains will fail no_target_asset_for_* until either:
- A retroactive seeding event is committed for each strain to bring the block into existence, OR
- The commit-router gains a "create-block-on-demand" fallback when the named QR doesn't resolve.

This is a real production gap, not just a UAT artifact. Filing as a v1.8 candidate: **seed backfill sweep for all active strains** OR **on-demand block create in commit-router activity path**.

### Findings 1d (jargon) re-confirmed live

The Vikki/Rambo finding 1d was "bot uses jargon farmers don't understand." Today Santi explicitly pushed back: *"I dont understand what asset-ref means. Please speak in farmer to me."* That is the same finding with a second live data point. The fix needs to:
- Replace "asset_ref" with farmer-language terms per log_type: "block ID" for activity/observation, "source block" for harvest, "batch" for seeding.
- Live in `preview-builder.js` (the surface that emits the askback). Same module that already strips em-dashes.

### Finding 3 (commit_failed silence) re-confirmed

Same NORTH-STAR violation. Santi confirmed lion's mane move via YES at 23:32:20; by 23:33:45 the system silently dropped it. Without the operator bridge it would have stayed dropped indefinitely.

## Recommended filings (Don Santiago to scope)

1. **999.x: Phase 38<->Phase 40 schema mismatch for activity log_type** (Finding 4). Same-week-fix.
2. **999.x: preview-builder jargon translation** (Finding 1d, re-confirmed). Same-week-fix.
3. **999.x: commit-failed farmer reply** (Finding 3 from Rambo note, re-confirmed). Already filed; bumped to higher confidence.
4. **999.x: seed backfill sweep for all active strains** (new). Or alternatively the on-demand-block-create fallback. v1.8 scope decision.
5. **v1.8 candidate:** Phase 40 paper-log backfill audit -- compare strain codes in current farmOS asset set to known-active strain codes (memory `project_mossrock_active_strain_codes`) and surface the gaps.

## Artifacts

- LIMA block: `260415_LIMA_1` uuid `e0be0952-e77b-4316-8be6-28abdc62b134` (prod-farmOS http://10.68.155.50:8082)
- Activity log: `relocate 2026-05-13` uuid `92632908-e88c-4480-a04a-cbac4ffce999`
- Audio capture: `01KRPZMZ79370J0YQM9SKTWJZ2`
- Draft: `1fb28e709118807ed301b4c3b45f5042f194eabb9ab0000f288e9163fec93733`
- Bridge ack to Santi: signal-cli timestamp 1778888876265 (2026-05-15T23:47:58Z)

EOF -- pick this up in the discussion session, paired with `2026-05-15-rambo-th-window-unscripted-run.md`.
