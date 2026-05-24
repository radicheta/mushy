# Phase 52: Session entity via asset--group + activity-log membership - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning
**Mode:** Auto-discuss — context distilled from existing design note (2026-05-24-session-as-asset-group-design.md) which already locks the shape after Phase 48's live-fire reversal. No new gray areas surfaced.

<domain>
## Phase Boundary

Re-introduce session-entity commit on the mushy side, but as `asset--group` (stock `farm_group` module) + one `log--activity` with `is_group_assignment=true` listing the N children — replacing the Phase 48 anonymous-`asset--fungi` shape that 422'd against real farmOS field config.

**In-scope:**
- New `groupAssets.upsertGroupAsset()` helper (alongside `assets.js`) that creates one `asset--group` named `inoc YYYY-MM-DD` (with `#N` suffix on same-day collision).
- New `activityLogs.createGroupAssignmentLog()` helper (alongside `logs.js`) that creates a single `log--activity` with `is_group_assignment=true`, `asset[]=childIds`, `group[]=[sessionGroupId]`, dated `event_date`.
- `commit-seeding-session.js`: re-introduce session-entity preflight — create the group asset first, then the N children with `parent=[sourceBlock]` ONLY (no secondary parent edge to session), then the membership log.
- Integration tests updated to expect 17 asset POSTs + 12 logs (was 16 + 11 in the no-session interim).
- Lineage walks unchanged: child → strain parent. New query path: `GET /api/log/activity?filter[is_group_assignment]=1&filter[asset.id]=<child_id>` resolves session membership.

**Out-of-scope:**
- Backfill of the 11 dev-farmOS children already landed without a group (separate cleanup).
- Backfill of the 11 prod-farmOS children (separate; gated on Phase 51 upsert layer).
- Session-level event handlers (contam-on-session, observation-on-session) — design ready, separate phase if/when needed.
- Prod-farmOS write of new sessions — gated separately by `FARMOS_INTEGRATION` flag per UAT findings.

</domain>

<decisions>
## Implementation Decisions

### Shape (locked by design note — no re-discussion)
- **Session entity** = single `asset--group` named `inoc YYYY-MM-DD`. Carries `name`, `status: active`, `notes` (provenance trailer + draft id), no QR.
- **Membership** = single `log--activity` with `is_group_assignment=true`, `asset[]=childIds`, `group[]=[sessionGroupId]`, name = "inoc 2026-05-22 (N bags)", timestamp = day-grain epoch matching seeding logs.
- **Children** carry `parent=[sourceBlock]` ONLY. NO `parent=[sessionGroup]` edge. Membership lives on the activity log, not on the asset (honors C4: "lineage = an event, not a property").
- **Naming collision policy:** `inoc YYYY-MM-DD #2`, `#3` … `#N`. Same convention Phase 48 originally planned; farmos team's question 3 stays open but `#N` is the working answer.
- **Group-asset timestamp semantics:** one-and-done at commit (one group log per session, NOT a stream of additive logs). Matches farmos team's question 4 default.

### Code organization
- New file: `src/agents/alerter/src/farmos/groupAssets.js` — `upsertGroupAsset({ name, notes, draftId, opts })`. Mirrors `assets.js` style.
- New file: `src/agents/alerter/src/farmos/activityLogs.js` — `createGroupAssignmentLog({ childIds, sessionGroupId, eventDate, name })`. Mirrors `logs.js` style.
- Modified: `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` — re-introduce session preflight using the new helpers; remove the `_resolveSessionName()` stub that was deleted in the interim.
- Modified: `src/agents/alerter/src/farmos/assets.js` — `allowNoFungiType` flag stays in place (no callers, but kept as escape hatch); revisit removal in a later cleanup phase.

### Upsert/idempotency
- **`upsertGroupAsset` uses `findAssetByName`** (existing pattern from `assets.js`). Same-name session on re-commit returns the existing UUID; idempotent on draft retry.
- **`createGroupAssignmentLog` is creation-only** for v1.10.1. If the same draft re-commits, a duplicate group log is acceptable (no harm — both reference the same children); Phase 51's upsert-by-stable-identity layer (separate milestone) will dedupe these properly once it ships.

### Test strategy
- Hermetic integration test: 17 asset POSTs (1 group + 5 source + 11 children) + 12 logs (1 activity + 11 seeding) on the May-22 fixture.
- Re-validate the existing partial-failure DELETE rollback path with new asset counts.
- Live-fire on dev farmOS (`:18080`) is a hard ship-gate — same pattern as Phase 48's `scripts/live-fire-48.js` (call it `live-fire-52.js`).
- NO prod live-fire in this phase — prod-session-write gating is a separate decision.

### Claude's Discretion
- File-level layout inside `groupAssets.js` / `activityLogs.js` (match `assets.js` / `logs.js` patterns).
- Whether to consolidate the partial-failure rollback logic (DELETE on commit failure) or duplicate it for the new entities. Recommend: extract a shared `rollbackEntities([{type, id}])` helper if duplication exceeds ~20 lines.
- Test fixture naming.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/agents/alerter/src/farmos/assets.js` — `findAssetByName`, `createFungiAsset` patterns to mirror for `upsertGroupAsset`.
- `src/agents/alerter/src/farmos/logs.js` — `createSeedingLog` pattern to mirror for `createGroupAssignmentLog`.
- `src/agents/alerter/src/farmos/client.js` — HTTP layer (POST/GET/PATCH) used by all entity modules.
- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` — current handler; reverse the interim no-session change to re-introduce a session preflight using the new group helpers.
- `scripts/live-fire-48.js` — proven dev-farmOS live-fire harness; clone as `live-fire-52.js` with the new expected counts.

### Established Patterns
- Each farmOS entity gets its own module file in `src/farmos/` with `create*` / `find*` exports.
- `commit-*.js` handlers orchestrate multi-entity writes with partial-failure rollback via DELETE.
- Hermetic tests assert exact POST counts per entity type and verify lineage walks afterwards.

### Integration Points
- `commit-router.js` routes drafts by `type`; `seeding_session` already routes to `commit-seeding-session.js` — no router change.
- `audit-logger.js` records all farmOS writes — both new entities auto-flow through it via the shared `client.js` layer.

</code_context>

<canonical_refs>
## Canonical References

- `.planning/notes/2026-05-24-session-as-asset-group-design.md` — **PRIMARY DESIGN DOC; locks shape.**
- `.planning/phases/48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-CONTEXT.md` — Gray Area A (the reversed Phase 48 lock; explains why this phase exists).
- `.planning/phases/48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md` — the 422 evidence that falsified the Phase 48 design.
- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` — the handler to modify.
- `src/agents/alerter/src/farmos/assets.js`, `logs.js`, `client.js` — patterns to mirror.
- `scripts/live-fire-48.js` — live-fire harness to clone.
- Memory: `[[project_session_is_production_shape_per_bag_is_storage]]` — why session identity must survive on the farmOS side.
- Memory: `[[reference_farmos_dev_vs_prod_on_elder_plops]]` — `:18080` dev, `:8082` prod; both API-name "Mossrock".
- farmOS-side: commit `1857037` (farm_group enabled on dev + prod) — dependency satisfied.

</canonical_refs>

<specifics>
## Specific Ideas

- "Session is to block like Playlist is to version in ShotGrid" — Santi's framing. Group:Fungi maps 1:1.
- The May-22 dev-farmOS data (11 children without group) is acceptable as-is for this phase — backfill is a later concern.
- The `is_group_assignment=true` flag on `log--activity` is the canonical farmOS pattern for membership assignment; no custom log type needed.

</specifics>

<deferred>
## Deferred Ideas

- Backfill of pre-Phase-52 children (dev: 11, prod: 11) with synthetic group assets + membership logs — separate cleanup phase.
- Prod-session-write enablement (currently `FARMOS_INTEGRATION` gated) — coordinate with farmos team on permissions for `asset/group` + `log/activity` CRUD before flipping.
- Session-level event handlers (contam-on-session, observation-on-session) — wait for actual farmer demand.
- Removal of `allowNoFungiType` escape hatch in `assets.js` — no callers, safe to remove in a later cleanup.

</deferred>
