'use strict';

// Phase 48 Plan 02: seeding_session commit handler.
//
// Asset-first preflight per Gray Area A lock: create one anonymous fungi
// session asset named `inoc YYYY-MM-DD` (with `#N` collision suffix up to #9),
// then fan out N child seeding logs each with its source block + the session
// asset encoded as the child block's asset->asset parent[] lineage.
//
// All-or-nothing: if any child write fails, every asset created this run is
// DELETE'd in reverse order (children first, then source blocks, then session)
// and the handler returns ok=false. Best-effort cleanup: DELETE failures
// emit an audit line (orphan_cleanup_failed) for operator sweep, but the
// handler still returns ok=false without throwing.
//
// Lineage encoding correction vs CONTEXT.md Gray Area B: the [source, session]
// pair lives on the CHILD BLOCK ASSET's parent[] (asset->asset), NOT on the
// seeding log entity. CONTEXT.md says "taxonomy_term--fungi" refs which is a
// naming misstatement; the actual encoding is asset--fungi.parent[]. See the
// 48-02 SUMMARY for the call-out.
//
// Session-asset fungi_type handling: extended assets.create-fungi-asset with an
// `allowNoFungiType: true` flag (Plan 02 chose the simpler path; see SUMMARY).
// fungi_xing for the session asset re-uses the existing 'block' term so no
// taxonomy work is required on the farmOS side. Operator decision flagged in
// SUMMARY.

const assets = require('../assets');
const logs = require('../logs');

function epochSecondsForDate(dateStr) {
  // YYYY-MM-DD interpreted as UTC midnight. Hermetic, no tz coupling.
  const ms = Date.parse(dateStr + 'T00:00:00Z');
  if (!Number.isFinite(ms)) return Math.floor(Date.now() / 1000);
  return Math.floor(ms / 1000);
}

async function _cleanup(client, ctx, draft, createdAssetIds, originalReason, failedAtChildIndex) {
  // Reverse order: children first (last in), then source blocks, then session
  // (first in) -- mirrors creation stack.
  const auditLogger = ctx && ctx.auditLogger;
  let attempted = 0;
  let failed = 0;
  const failedIds = [];
  for (let i = createdAssetIds.length - 1; i >= 0; i--) {
    const id = createdAssetIds[i];
    attempted += 1;
    const r = await assets.deleteFungiAsset(client, id);
    if (!r.ok) {
      failed += 1;
      failedIds.push(id);
      if (auditLogger && typeof auditLogger.logCommit === 'function') {
        try {
          await auditLogger.logCommit('orphan_cleanup_failed', draft, {
            asset_ids: [id],
            reason: 'orphan_cleanup_failed',
            http_status: r.http_status != null ? r.http_status : null,
          });
        } catch (_) { /* audit failure is non-fatal */ }
      }
    }
  }
  return {
    ok: false,
    reason: 'partial_commit_failed',
    asset_ids: [],
    log_ids: [],
    file_ids: [],
    farmos_response: {
      original_reason: originalReason,
      failed_at_child_index: failedAtChildIndex,
      orphan_attempted_count: attempted,
      orphan_cleanup_failed_count: failed,
      orphan_cleanup_failed_ids: failedIds,
    },
  };
}

async function commitSeedingSession(client, draft, ctx) {
  try {
    const dj = (draft && draft.draft_json) || {};
    const eventDate = dj.event_date;
    const groups = Array.isArray(dj.groups) ? dj.groups : [];
    const draftId = draft && draft.id;
    if (!eventDate || groups.length === 0) {
      return { ok: false, reason: 'invalid_seeding_session', asset_ids: [], log_ids: [], file_ids: [] };
    }

    // Phase 48 Gray Area A LOCK ("anonymous fungi session asset") REVERSED
    // 2026-05-24: live-fire on dev farmOS returned HTTP 422 (fungi_type NOT
    // NULL enforced). Patching to fungi_type:(unassigned) or :session would
    // smuggle a non-strain into a strain field. Per the Playlist:Version
    // analogy (santi 2026-05-24), a session is a first-class entity of a
    // DIFFERENT kind from a block, with membership pointers as its primary
    // data. The right farmOS shape is `asset--group` from the stock
    // `farm_group` module, which is not currently enabled on either dev or
    // prod farmOS. Until that lands, ship children + logs only; session
    // identity is recoverable from "all seeding logs on this date by this
    // sender". See .planning/notes/2026-05-24-session-as-asset-group-design.md.
    const createdAssetIds = [];
    const childBlockIds = [];
    const childLogIds = [];
    const timestamp = epochSecondsForDate(eventDate);
    const notes = typeof dj.notes === 'string' ? dj.notes : '';

    let childIndex = 0; // 0-based across the whole session

    for (const g of groups) {
      const species = g && g.species && g.species.value;
      const parentName = g && g.parent && g.parent.value;
      const qty = g && g.qty && g.qty.value;
      const childNames = (g && g.child_block_names && g.child_block_names.value) || [];
      if (!species || !parentName || !qty) {
        return _cleanup(client, ctx, draft, createdAssetIds,
          'invalid_group_shape', childIndex);
      }

      // Source block resolution: skip lookup/create for NO_PARENT sentinel.
      // Phase 51 UPSERT-01: route through upsertFungiAsset so a re-run against a
      // populated farmOS is idempotent. Only push to createdAssetIds when
      // outcome==='created' — patched/noop assets must NOT be rolled back on
      // partial-commit failure (T-51-10 mitigation).
      let sourceBlockId = null;
      if (parentName !== 'NO_PARENT') {
        const r = await assets.upsertFungiAsset(client, {
          name: parentName,
          fungiTypeName: species,
          fungiXingName: 'block',
          draftId,
        });
        if (!r.ok) {
          return _cleanup(client, ctx, draft, createdAssetIds,
            r.reason || 'source_block_upsert_failed', childIndex);
        }
        sourceBlockId = r.assetId;
        if (r.outcome === 'created') createdAssetIds.push(sourceBlockId);
        if (ctx && ctx.auditLogger && typeof ctx.auditLogger.logCommit === 'function') {
          try {
            await ctx.auditLogger.logCommit('upsert_outcome', draft, {
              asset_ids: [sourceBlockId],
              outcome: r.outcome,
              conflicts: r.conflicts,
              etag_source: r.etag_source,
            });
          } catch (_) { /* audit failure is non-fatal */ }
        }
      }

      for (let i = 0; i < qty; i++) {
        const childName = childNames[i];
        if (!childName) {
          return _cleanup(client, ctx, draft, createdAssetIds,
            'missing_child_block_name', childIndex);
        }
        const parentIds = sourceBlockId ? [sourceBlockId] : [];
        const childRes = await assets.upsertFungiAsset(client, {
          name: childName,
          fungiTypeName: species,
          fungiXingName: 'block',
          parentIds,
          draftId,
        });
        if (!childRes.ok) {
          return _cleanup(client, ctx, draft, createdAssetIds,
            childRes.reason || 'child_block_upsert_failed', childIndex);
        }
        const childBlockId = childRes.assetId;
        if (childRes.outcome === 'created') createdAssetIds.push(childBlockId);
        childBlockIds.push(childBlockId);
        if (ctx && ctx.auditLogger && typeof ctx.auditLogger.logCommit === 'function') {
          try {
            await ctx.auditLogger.logCommit('upsert_outcome', draft, {
              asset_ids: [childBlockId],
              outcome: childRes.outcome,
              conflicts: childRes.conflicts,
              etag_source: childRes.etag_source,
            });
          } catch (_) { /* audit failure is non-fatal */ }
        }

        const logRes = await logs.upsertLog(client, 'seeding', {
          name: 'Inoc ' + childName,
          timestamp,
          assetIds: [childBlockId],
          notes,
          draftId,
        });
        if (!logRes.ok) {
          return _cleanup(client, ctx, draft, createdAssetIds,
            logRes.reason || 'seeding_log_upsert_failed', childIndex);
        }
        childLogIds.push(logRes.logId);
        if (ctx && ctx.auditLogger && typeof ctx.auditLogger.logCommit === 'function') {
          try {
            await ctx.auditLogger.logCommit('upsert_outcome', draft, {
              log_ids: [logRes.logId],
              outcome: logRes.outcome,
              conflicts: logRes.conflicts || [],
              etag_source: logRes.etag_source,
            });
          } catch (_) { /* audit failure is non-fatal */ }
        }
        childIndex += 1;
      }
    }

    return {
      ok: true,
      asset_ids: createdAssetIds,
      log_ids: childLogIds,
      file_ids: [],
      http_status: 201,
    };
  } catch (e) {
    return {
      ok: false,
      reason: (e && e.message) || 'commit_seeding_session_error',
      asset_ids: [], log_ids: [], file_ids: [],
    };
  }
}

module.exports = commitSeedingSession;
