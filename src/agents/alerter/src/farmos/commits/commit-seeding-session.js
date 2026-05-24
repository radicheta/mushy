'use strict';

// Phase 52: seeding_session commit handler with session-entity preflight.
//
// Shape (locked by .planning/phases/52-.../52-CONTEXT.md):
//   1. PREFLIGHT: upsertGroupAsset for `inoc YYYY-MM-DD` (with `#N` collision
//      suffix up to #9). Session entity is asset--group from the stock
//      farm_group module (enabled farmos commit 1857037).
//   2. CHILDREN LOOP: source blocks + N child blocks each with
//      parent=[sourceBlock] ONLY -- NO secondary edge to the session group
//      (honors C4: lineage is an event, not a property).
//   3. POST-LOOP MEMBERSHIP LOG: one log--activity with is_group_assignment=true
//      binding all child UUIDs to the session group.
//
// All-or-nothing rollback (reverse order):
//   membership log (if created) -> children + source blocks (createdAssetIds
//   in reverse) -> session group (if just-created).

const assets = require('../assets');
const logs = require('../logs');
const groupAssets = require('../groupAssets');
const activityLogs = require('../activityLogs');

const COLLISION_MAX = 9;

function epochSecondsForDate(dateStr) {
  // YYYY-MM-DD interpreted as UTC midnight. Hermetic, no tz coupling.
  const ms = Date.parse(dateStr + 'T00:00:00Z');
  if (!Number.isFinite(ms)) return Math.floor(Date.now() / 1000);
  return Math.floor(ms / 1000);
}

// Probe `inoc <date>`, then `#2`...`#9`. Pick the first name that either
// misses OR hits an existing group whose notes trailer matches this draftId
// (idempotent re-commit). Returns {name, existingId?} on success, or null
// when COLLISION_MAX is exhausted by foreign-draft groups.
async function _resolveSessionName(client, eventDate, draftId) {
  const baseName = 'inoc ' + eventDate;
  for (let n = 1; n <= COLLISION_MAX; n++) {
    const candidate = n === 1 ? baseName : (baseName + ' #' + n);
    const lookup = await groupAssets.findGroupAssetByName(client, candidate);
    if (!lookup.found) {
      return { name: candidate, existingId: null };
    }
    // Hit -- check if it belongs to THIS draft via notes-trailer match.
    const r = await client.get('/api/asset/group/' + lookup.assetId);
    if (r.ok && r.body && r.body.data && r.body.data.attributes && r.body.data.attributes.notes) {
      const noteValue = r.body.data.attributes.notes.value || '';
      if (noteValue.indexOf('mushy:draft:' + draftId) !== -1) {
        return { name: candidate, existingId: lookup.assetId };
      }
    }
    // Foreign draft -- advance to next #N.
  }
  return null;
}

async function _cleanup(client, ctx, draft, createdAssetIds, originalReason, failedAtChildIndex, opts) {
  // Reverse order:
  //   1. membership log (if it was created)
  //   2. children + source blocks (createdAssetIds in reverse)
  //   3. session group asset (if just-created this run)
  const auditLogger = ctx && ctx.auditLogger;
  const membershipLogId = opts && opts.membershipLogId;
  const sessionGroupIdJustCreated = opts && opts.sessionGroupIdJustCreated;
  let attempted = 0;
  let failed = 0;
  const failedIds = [];

  async function _emitOrphan(id, r) {
    if (!auditLogger || typeof auditLogger.logCommit !== 'function') return;
    try {
      await auditLogger.logCommit('orphan_cleanup_failed', draft, {
        asset_ids: [id],
        reason: 'orphan_cleanup_failed',
        http_status: r.http_status != null ? r.http_status : null,
      });
    } catch (_) { /* audit failure is non-fatal */ }
  }

  if (membershipLogId) {
    attempted += 1;
    const r = await activityLogs.deleteActivityLog(client, membershipLogId);
    if (!r.ok) { failed += 1; failedIds.push(membershipLogId); await _emitOrphan(membershipLogId, r); }
  }

  for (let i = createdAssetIds.length - 1; i >= 0; i--) {
    const id = createdAssetIds[i];
    attempted += 1;
    const r = await assets.deleteFungiAsset(client, id);
    if (!r.ok) { failed += 1; failedIds.push(id); await _emitOrphan(id, r); }
  }

  if (sessionGroupIdJustCreated) {
    attempted += 1;
    const r = await groupAssets.deleteGroupAsset(client, sessionGroupIdJustCreated);
    if (!r.ok) { failed += 1; failedIds.push(sessionGroupIdJustCreated); await _emitOrphan(sessionGroupIdJustCreated, r); }
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

    const createdAssetIds = [];
    const childBlockIds = [];
    const childLogIds = [];
    const timestamp = epochSecondsForDate(eventDate);
    const notes = typeof dj.notes === 'string' ? dj.notes : '';

    // -------- PREFLIGHT: session group asset --------
    const nameRes = await _resolveSessionName(client, eventDate, draftId);
    if (!nameRes) {
      return { ok: false, reason: 'session_name_collision_exhausted', asset_ids: [], log_ids: [], file_ids: [] };
    }
    const sessionName = nameRes.name;
    const groupRes = await groupAssets.upsertGroupAsset(client, {
      name: sessionName,
      draftId,
      notes,
    });
    if (!groupRes.ok) {
      return { ok: false, reason: 'session_group_upsert_failed', asset_ids: [], log_ids: [], file_ids: [],
        farmos_response: { upsert_reason: groupRes.reason, http_status: groupRes.http_status } };
    }
    const sessionGroupId = groupRes.assetId;
    const sessionGroupJustCreated = groupRes.outcome === 'created';

    let childIndex = 0;

    for (const g of groups) {
      const species = g && g.species && g.species.value;
      const parentName = g && g.parent && g.parent.value;
      const qty = g && g.qty && g.qty.value;
      const childNames = (g && g.child_block_names && g.child_block_names.value) || [];
      if (!species || !parentName || !qty) {
        return _cleanup(client, ctx, draft, createdAssetIds,
          'invalid_group_shape', childIndex,
          { sessionGroupIdJustCreated: sessionGroupJustCreated ? sessionGroupId : null });
      }

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
            r.reason || 'source_block_upsert_failed', childIndex,
            { sessionGroupIdJustCreated: sessionGroupJustCreated ? sessionGroupId : null });
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
            'missing_child_block_name', childIndex,
            { sessionGroupIdJustCreated: sessionGroupJustCreated ? sessionGroupId : null });
        }
        // Children carry parent=[sourceBlock] ONLY -- NO sessionGroupId edge.
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
            childRes.reason || 'child_block_upsert_failed', childIndex,
            { sessionGroupIdJustCreated: sessionGroupJustCreated ? sessionGroupId : null });
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
            logRes.reason || 'seeding_log_upsert_failed', childIndex,
            { sessionGroupIdJustCreated: sessionGroupJustCreated ? sessionGroupId : null });
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

    // -------- POST-LOOP: membership log --------
    const membershipName = 'inoc ' + eventDate + ' (' + childBlockIds.length + ' bags)';
    const membershipRes = await activityLogs.createGroupAssignmentLog(client, {
      childIds: childBlockIds,
      sessionGroupId,
      eventDate,
      name: membershipName,
      draftId,
      notes,
    });
    if (!membershipRes.ok) {
      return _cleanup(client, ctx, draft, createdAssetIds,
        'membership_log_create_failed', childIndex,
        { sessionGroupIdJustCreated: sessionGroupJustCreated ? sessionGroupId : null });
    }

    // Build success return shape.
    const assetIdsOut = sessionGroupJustCreated
      ? [sessionGroupId, ...createdAssetIds]
      : [...createdAssetIds];
    const logIdsOut = [membershipRes.logId, ...childLogIds];

    return {
      ok: true,
      asset_ids: assetIdsOut,
      log_ids: logIdsOut,
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
