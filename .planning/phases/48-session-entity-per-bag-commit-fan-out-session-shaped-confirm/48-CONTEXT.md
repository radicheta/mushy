# Phase 48: Session entity + per-bag commit fan-out + session-shaped confirm preview — Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Source:** Auto-mode discuss (gsd-autonomous); locked decisions derived from ROADMAP success criteria + Phase 47 CONTEXT + locked v1.9 schema memories.

<domain>
## Phase Boundary

Phase 47 shipped the EXTRACTION half — a `seeding_session` draft with groups-shape + inline provenance + photo-wins conflict policy + `needs_input='starting_seq'` ask-back. Phase 48 picks up the **COMMIT half**:

1. **Confirm preview** for a `seeding_session` draft renders as a compact group-by-parent table (one row per group, plus a summary header). Farmer can cross-check against paper notebook + shelf in seconds. Replaces the placeholder rendered by Phase 47's preview-builder.
2. **Per-bag fan-out**: a single YES on a `seeding_session` draft commits as N farmOS `seeding` logs (one per child block), each with its specific source parent (audio-extracted) as the primary `parent` ref per B7.
3. **Session asset**: every fan-out also creates ONE anonymous `fungi` asset that serves as the SECONDARY `parent` ref on every child seeding log. This is the lineage-stitching artifact — querying farmOS for "May 22 inoc session" returns all 11 children via the session asset's children walk.
4. **Idempotency**: duplicate YES on the same `signal_draft.draft_uuid` produces no double-write — neither N+1 logs, nor a second session asset. Idempotency key = `draft_uuid` (the row already exists in `signal_draft`; `signal_commit` uses it as the unique key per Phase 40 audit).
5. **Single-parent legacy** (`groups.length === 1`, N children sharing one parent) still goes through the same path: still creates a session asset (for shape consistency), still fans out to N seeding logs.

In scope:
- New `farmosCommitSeedingSession(draft)` commit handler that emits the session asset first, then N children referencing both the original parent block AND the session asset.
- `signal_commit` schema extension: idempotency check covers session-shape drafts; one `signal_commit` row per draft (NOT per child log — the row's `farmos_log_ids[]` carries the N child IDs + `farmos_asset_ids[]` carries the session-asset ID).
- `commit-router.js` dispatch: `draft.type === 'seeding_session'` → new handler.
- Preview rendering: `preview.js` (or sibling) gets a new `renderSeedingSession(draft)` branch producing the group-by-parent table. Replaces the placeholder from `47-04-PLAN.md`.
- Ship-gate: hermetic eval re-runs the 2026-05-22 fixture and asserts 11 logs + 1 asset written, lineage walks clean, double-YES is a no-op.

Out of scope (Phase 49):
- Real-session eval corpus + CI named regression guard.
- Re-running the May 22 audio+photo end-to-end (operator-attested ship gate for v1.9 itself).
- Marking the May 22 failed drafts `e3a564d0…` + `6edaaba7…` as `discarded`.

Out of scope (Phase 50):
- Quote-threading on the YES ack so EDIT/NO replies route by Signal-quote rather than ID disambiguation.

Out of scope (deferred entirely):
- EDIT routing into a session draft (replace whole session? one group? one bag?). Phase 50 quote-threading is expected to make this a per-bag operation by quoting the line in the table; if not, Phase 51 picks it up.
- Cross-session bundle continuity (turn 1 → turn 2 same session).
- Session asset retroactive linking from existing pre-v1.9 single-bag logs.
</domain>

<decisions>
## Implementation Decisions

### Gray Area A — Session asset shape & naming
**Lock: anonymous `fungi` asset, name = `inoc YYYY-MM-DD` (or `inoc YYYY-MM-DD #N` when a same-date session already exists).**

Rationale:
- `fungi` is the only native asset type available under C5 (no custom session-bundle type per B7 native-only). It is the closest semantic fit — a session "produces fungi colonies", and the session asset is the parent-of-record for those colonies on shelf.
- `name` is short and farmer-readable: "inoc 2026-05-22". Disambiguation suffix `#2` triggers only if a same-date session asset already exists (rare; handled by a `SELECT count(*) FROM farmos assets WHERE name LIKE 'inoc YYYY-MM-DD%'` pre-flight in the commit handler).
- No QR code minted for the session asset (QR is per child block only — operator-side B-system convention per `[[project_farmos_schema_locked_2026_05_11]]`).
- No `location` ref; no `parent` refs on the asset itself; no `birthdate` (the children's seeding logs carry event_date).

### Gray Area B — Lineage encoding (B7 multi-parent)
**Lock: each child seeding log's `entity.parent[]` array contains TWO `taxonomy_term--fungi` refs**: the source block (primary, audio-extracted) AND the session asset (secondary, generated this commit). Both are valid `parent` references per the locked B7 schema (C4 lineage-via-log-refs).

Order in array: **source block first, session asset second.** Downstream lineage walkers prefer the first parent as "primary"; the session asset is "the bundle this came from", queryable but not the primary lineage hop.

### Gray Area C — Confirm preview shape
**Lock: compact group-by-parent table, max 5 visible groups + folded tail, with farmer-facing date + total + per-group rows.**

Template (rendered example for May 22 fixture):

```
Inoc session — 2026-05-22
11 blocks across 5 parents

KEY  PARENT          SPECIES  QTY  CHILDREN
1    260304_SHI_5    SHI      1    260522_SHI_1
2    260118_SHI_23   SHI      1    260522_SHI_2
3    260118_SHI_26   SHI      1    260522_SHI_3
4    260118_KOY_12   KOY      4    260522_KOY_4..7
5    260425_KOY_4    KOY      4    260522_KOY_8..11

YES to commit | NO to cancel | EDIT to change
```

Rules:
- KEY column is the 1-based group index — needed for future EDIT-by-group routing (Phase 50 quote-threading may obviate but the column is cheap).
- CHILDREN column uses range collapse (`260522_KOY_4..7`) when 3+ consecutive SEQs share a strain; explicit comma-list otherwise.
- If `groups.length > 5`, render the first 5 + a `… (M more groups)` trailing row. (Real sessions are usually ≤ 5 per `[[project_inoc_shape_multi_parent_batch]]`.)
- No conflict surfacing in the preview (Phase 47 Gray Area 4 lock — conflicts live in `draft.draft_json.conflicts[]` audit-only).
- `notes` field (free-text) rendered as a trailing italic line if present.

### Gray Area D — Idempotency contract
**Lock: idempotency key = `signal_draft.draft_uuid`. Single `signal_commit` row per draft.** Second YES on the same draft hits the `UNIQUE(draft_uuid)` constraint on `signal_commit` and short-circuits to a "already committed" ack rather than retrying the write.

Schema delta:
- `signal_commit.farmos_asset_ids` already exists per Phase 40 (text array). Re-use for the session asset ID.
- `signal_commit.farmos_log_ids` text array carries the N child seeding log IDs (one per child).
- `UNIQUE(draft_uuid)` constraint is the idempotency gate. Confirm it exists in Phase 40 migration; if not, add it in 48-01.

**Partial-failure policy: all-or-nothing transactionally** at the alerter side. If asset write succeeds but any child log write fails, the handler MUST delete the orphan asset (DELETE /api/asset/fungi/{uuid}) and surface `commit_failed` so the ack message goes to the farmer per Phase 45 NORTH-STAR (no silent failures). The asset cleanup is best-effort; if cleanup fails too, log to `audit-logger.js` for operator sweep.

### Gray Area E — Confirm preview source-of-truth
**Lock: `confirm/preview.js` renders the preview from the LIVE draft row at preview-time** (no precomputed preview string stored on the draft). This matches Phase 47's design — preview is a pure function of `signal_draft.draft_json`. Phase 47 stored a placeholder string in `signal_draft.farmer_facing_preview`; Phase 48 either (a) keeps that column null and renders on demand, or (b) writes the rendered table into it at extraction-emit time. Lock = **(b) write at extraction-emit time** so the alerter's renderer is consistent across draft types (other commit handlers store preview strings). Implementation: extend `preview.js`'s `renderDraftPreview()` dispatch table with the new branch; call it once at `signal_draft` row insert time.

### Other locked policies (carried from Phase 47 + project memory)

- **No emoji or em-dashes in farmer-facing preview** per `[[feedback_no_em_dashes_in_artifacts]]`. The renderer uses ASCII only.
- **Round numbers** per `[[feedback_round_farmer_numbers]]`: QTY is integer; no decimal counts.
- **Friction policy**: ask-back ONLY for genuine missing data; canonical-source-wins silently when sources disagree (`[[feedback_friction_policy_missing_vs_mismatch]]`).
- **No silent failure after farmer YES**: every terminal state post-YES produces a Signal reply per Phase 45 (`[[feedback_no_silent_failure_after_farmer_confirm]]`). Both `commit_success` ("11 logs + session asset written") and `commit_failed` ("could not write log #4 — operator notified") must round-trip to the farmer.
- **Tenant-aware schema** (OSS-Foray Option α per `[[project_2026_05_17_oss_foray_alpha_lock]]`): any new `signal_*` row or new persisted entity carries `tenant_id` (default `mossrock`). The session asset itself is in farmOS and inherits the farmOS tenant scope — no new column needed on the alerter side.

</decisions>

<code_context>
## Existing Code Insights

Researcher will deepen. Initial scout:

- `src/agents/alerter/src/farmos/commits/commit-router.js` — current dispatch on `draft.type`. Phase 48 adds one branch: `'seeding_session' → commitSeedingSession()`.
- `src/agents/alerter/src/farmos/commits/commit-seeding.js` — the legacy single-bag seeding committer. Phase 48 reuses its per-child-log write loop helpers but adds an asset-first preflight.
- `src/agents/alerter/src/farmos/assets.js` — existing fungi-asset creation path (Phase 40). Reuse `createFungiAsset({name, ...})`.
- `src/agents/alerter/src/confirm/preview.js` — current `renderDraftPreview(draft)` dispatch table. Add `renderSeedingSession` branch.
- `src/agents/alerter/src/farmos/commit-db.js` — `signal_commit` table I/O. Verify `UNIQUE(draft_uuid)` constraint; add migration if missing.
- `src/agents/alerter/test/fixtures/` — Phase 47 added May-22 fixtures; reuse in 48 ship-gate.

</code_context>

<specifics>
## Specific Ideas

- May 22 ship-gate (hermetic): replay the Phase 47 `seeding_session` draft fixture (5 groups, 11 children) → assert exactly 11 farmOS seeding logs + 1 fungi asset created in dev farmOS instance. Second YES on same draft → no new writes, ack reads "already committed". Lineage walk from any child block returns 2 parents (source block + session asset) cleanly.

- Single-parent legacy fixture: synthesize a 1-group, 5-children draft → assert 5 seeding logs + 1 session asset, all 5 children share one specific parent + the session asset.

- Conflict fixture (audio vs photo disagreement on parent block ID): asserts photo-wins resolution flows through correctly; conflict array preserved on draft row; preview shows photo's value only (no conflict surfacing).

- `commit_failed` partial-fail fixture: simulate a 4xx on child log #4 → assert asset deleted, `signal_commit` row marked failed, farmer-facing failed ack queued.

</specifics>

<deferred>
## Deferred Ideas

- **EDIT routing into a session draft** (Phase 50 expected to solve via quote-threading).
- **Cross-session continuity** (turn 1 + turn 2 same session) — no real-data evidence yet.
- **Session asset retroactive linking** for pre-v1.9 single-bag logs.
- **QR code for session asset** — operator workflow doesn't need it; child blocks carry the operator-tracked QR.
- **Asset name disambiguation collision policy** when `inoc YYYY-MM-DD #N` for N > 9 (unlikely, defer).

</deferred>

<canonical_refs>
## Canonical Refs

- `.planning/phases/47-multi-source-extraction-fusion-groups-shape-inoc-draft/47-CONTEXT.md` — Phase 47 locks (groups-shape draft, provenance shape, photo-wins, starting_seq ask-back)
- `.planning/phases/40-farmos-write-path/` — Phase 40 audit, `signal_commit` schema, idempotency
- `[[project_farmos_schema_locked_2026_05_11]]` — C1–C5 + B1–B7 + P1–P5 locked schema
- `[[project_inoc_shape_multi_parent_batch]]` — N children from M>1 parents = THE common shape
- `[[project_b5_seq_is_per_session_not_per_strain]]` — per-session SEQ semantics
- `[[project_session_is_production_shape_per_bag_is_storage]]` — session identity must survive
- `[[feedback_no_silent_failure_after_farmer_confirm]]` — every post-YES terminal state acks
- `[[feedback_friction_policy_missing_vs_mismatch]]` — ask-back vs canonical-wins
- `.planning/notes/2026-05-17-oss-foray-decision.md` — tenant-aware from day one

</canonical_refs>
