'use strict';

// Phase 39 in-memory pg pool fake. Backs signal_draft rows + signal_draft_event
// rows in memory and supports the SQL patterns confirm-db.js issues.
//
// Recognized statements (string-matched, not parsed):
//   ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS ...      -> noop (records call)
//   CREATE TABLE IF NOT EXISTS signal_draft_event ...           -> noop
//   CREATE INDEX IF NOT EXISTS ...                              -> noop
//   BEGIN / COMMIT / ROLLBACK                                   -> noop
//   UPDATE signal_draft SET status='confirmed' ... WHERE id=$1 AND status='awaiting_farmer' RETURNING id
//   UPDATE signal_draft SET status='discarded' ...
//   UPDATE signal_draft SET status='expired' / status='needs_review' ...
//   UPDATE signal_draft SET nudge_sent_at=NOW() ... WHERE id=$1 AND nudge_sent_at IS NULL
//   UPDATE signal_draft SET edit_turn_count = edit_turn_count + 1 ... RETURNING edit_turn_count
//   UPDATE signal_draft SET draft_json=$2, per_field_confidence=$3, farmer_facing_preview=$4 ...
//   INSERT INTO signal_draft_event ... RETURNING seq
//   SELECT * FROM signal_draft WHERE sender_e164=$1 AND status='awaiting_farmer' ORDER BY updated_at DESC LIMIT 1
//   SELECT id, sender_e164, ... FROM signal_draft WHERE status='awaiting_farmer' AND nudge_sent_at IS NULL AND updated_at < NOW() - ...
//   SELECT id, sender_e164, ... FROM signal_draft WHERE status='awaiting_farmer' AND updated_at < NOW() - ...
//
// Time math uses pool._now() so tests can advance the clock.

function makeFakePool() {
  const drafts = new Map(); // id -> row
  const events = []; // {draft_id, seq, event, payload, created_at}
  const captures = new Map(); // id -> row (Phase 50 Plan 03)
  const outbounds = []; // array of {signal_msg_ts, related_draft_id, sent_at, ...} (Phase 50 Plan 04)
  let nowMs = Date.now();
  let captureSelectShouldThrow = false; // Plan 50-03: simulate DB error on capture lookup

  function _now() {
    return new Date(nowMs);
  }

  function setNow(ms) {
    nowMs = ms;
  }

  function seedDraft(row) {
    const full = Object.assign(
      {
        id: row.id,
        sender_e164: row.sender_e164 || '+15550001234',
        farmos_person: row.farmos_person || null,
        source_capture_ids: row.source_capture_ids || [],
        status: row.status || 'awaiting_farmer',
        log_type: row.log_type || null,
        draft_json: row.draft_json || null,
        per_field_confidence: row.per_field_confidence || null,
        askback_turns: row.askback_turns || 0,
        farmer_facing_preview: row.farmer_facing_preview || null,
        needs_review_reason: row.needs_review_reason || null,
        reply_target_kind: row.reply_target_kind || 'dm',
        group_id: row.group_id || null,
        edit_turn_count: row.edit_turn_count || 0,
        nudge_sent_at: row.nudge_sent_at || null,
        confirmed_at: row.confirmed_at || null,
        discarded_at: row.discarded_at || null,
        expired_at: row.expired_at || null,
        terminal_reason: row.terminal_reason || null,
        created_at: row.created_at || _now(),
        updated_at: row.updated_at || _now(),
      },
      row
    );
    drafts.set(full.id, full);
    return full;
  }

  function getDraft(id) {
    return drafts.get(id);
  }

  function getEvents(draftId) {
    return events.filter((e) => e.draft_id === draftId);
  }

  // Plan 50-03: signal_capture seed/lookup helpers.
  function seedCapture(row) {
    const full = Object.assign(
      {
        id: row.id,
        sender: row.sender || '+15550001234',
        signal_msg_ts: row.signal_msg_ts == null ? null : row.signal_msg_ts,
        raw_text: row.raw_text == null ? null : row.raw_text,
      },
      row
    );
    captures.set(full.id, full);
    return full;
  }
  function setCaptureSelectThrow(v) {
    captureSelectShouldThrow = !!v;
  }

  // Plan 50-04: signal_outbound seed for findDraftByQuotedMsgTs.
  function seedOutbound(row) {
    const full = Object.assign(
      {
        signal_msg_ts: row.signal_msg_ts == null ? null : row.signal_msg_ts,
        related_draft_id: row.related_draft_id == null ? null : row.related_draft_id,
        sent_at: row.sent_at || _now(),
      },
      row
    );
    outbounds.push(full);
    return full;
  }

  async function query(sql, params) {
    params = params || [];
    const s = String(sql);

    // Plan 50-04: signal_outbound JOIN signal_draft for findDraftByQuotedMsgTs.
    // Match: SELECT d.* FROM signal_outbound o JOIN signal_draft d ON d.id = o.related_draft_id WHERE o.signal_msg_ts = $1 ORDER BY o.sent_at DESC LIMIT 1
    if (/FROM\s+signal_outbound/i.test(s) && /JOIN\s+signal_draft/i.test(s) && /signal_msg_ts/.test(s)) {
      const ts = params[0];
      const matches = outbounds
        .filter((o) => o.signal_msg_ts === ts && o.related_draft_id != null && drafts.has(o.related_draft_id))
        .sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at));
      const out = matches[0];
      if (!out) return { rows: [], rowCount: 0 };
      const draft = drafts.get(out.related_draft_id);
      return { rows: [draft], rowCount: 1 };
    }

    // Plan 50-03: signal_capture SELECT for getCaptureQuoteTarget.
    if (/FROM\s+signal_capture/i.test(s) && /signal_msg_ts/.test(s) && /WHERE\s+id\s*=\s*\$1/i.test(s)) {
      if (captureSelectShouldThrow) {
        throw new Error('simulated capture select failure');
      }
      const id = params[0];
      const row = captures.get(id);
      return { rows: row ? [row] : [], rowCount: row ? 1 : 0 };
    }

    if (/^\s*ALTER TABLE/i.test(s)) return { rows: [], rowCount: 0 };
    if (/^\s*CREATE TABLE/i.test(s)) return { rows: [], rowCount: 0 };
    if (/^\s*CREATE INDEX/i.test(s)) return { rows: [], rowCount: 0 };
    if (/^\s*BEGIN/i.test(s) || /^\s*COMMIT/i.test(s) || /^\s*ROLLBACK/i.test(s)) {
      return { rows: [], rowCount: 0 };
    }

    // INSERT INTO signal_draft_event ...
    if (/INSERT INTO signal_draft_event/i.test(s)) {
      const draftId = params[0];
      const event = params[1];
      const payloadRaw = params[2];
      let payload = null;
      if (payloadRaw != null) {
        try {
          payload = typeof payloadRaw === 'string' ? JSON.parse(payloadRaw) : payloadRaw;
        } catch (_) {
          payload = payloadRaw;
        }
      }
      const existing = events.filter((e) => e.draft_id === draftId);
      const seq = existing.length === 0 ? 1 : Math.max(...existing.map((e) => e.seq)) + 1;
      events.push({ draft_id: draftId, seq, event, payload, created_at: _now() });
      return { rows: [{ seq }], rowCount: 1 };
    }

    // Phase 45 Plan 04 follow-on: findAwaitingForSender now matches
    // status IN ('awaiting_farmer','commit_failed') with awaiting_farmer
    // preferred. Hotfix 2026-05-23 (findActiveDraftsForSender variant): the
    // list-shape query uses `status='awaiting_farmer' OR (status='commit_failed'
    // AND updated_at > now() - interval '6 hours')` to age out stale ack-debt
    // drafts. Match both shapes (legacy IN-list and the new disjunction).
    const isListVariantHotfix = /sender_e164/.test(s)
      && /status\s*=\s*'awaiting_farmer'/.test(s)
      && /status\s*=\s*'commit_failed'\s+AND\s+updated_at\s*>/i.test(s);
    const isLegacyInList = /status\s+IN\s*\(\s*'awaiting_farmer'\s*,\s*'commit_failed'\s*\)/i.test(s);
    if (/SELECT \*\s+FROM signal_draft/i.test(s) && /sender_e164/.test(s) && (isLegacyInList || isListVariantHotfix)) {
      const sender = params[0];
      const sixHrsAgoMs = _now() - 6 * 60 * 60 * 1000;
      const matches = Array.from(drafts.values()).filter((r) => {
        if (r.sender_e164 !== sender) return false;
        if (r.status === 'awaiting_farmer') return true;
        if (r.status === 'commit_failed') {
          if (!isListVariantHotfix) return true; // legacy IN-list: no staleness filter
          return new Date(r.updated_at).getTime() > sixHrsAgoMs;
        }
        return false;
      });
      // awaiting_farmer wins over commit_failed; within status, newer updated_at wins.
      matches.sort((a, b) => {
        const ra = a.status === 'awaiting_farmer' ? 0 : 1;
        const rb = b.status === 'awaiting_farmer' ? 0 : 1;
        if (ra !== rb) return ra - rb;
        return new Date(b.updated_at) - new Date(a.updated_at);
      });
      // Phase 50 Plan-04: list-shape variant (findActiveDraftsForSender) has no
      // LIMIT 1 clause -- return all matches. Single-row variant keeps LIMIT 1.
      if (/LIMIT\s+1/i.test(s)) {
        const row = matches[0] || null;
        return { rows: row ? [row] : [], rowCount: row ? 1 : 0 };
      }
      return { rows: matches, rowCount: matches.length };
    }
    // Legacy: SELECT * FROM signal_draft WHERE sender_e164=$1 AND status='awaiting_farmer' ORDER BY updated_at DESC LIMIT 1
    if (/SELECT \*\s+FROM signal_draft/i.test(s) && /sender_e164/.test(s) && /status='awaiting_farmer'/.test(s)) {
      const sender = params[0];
      const matches = Array.from(drafts.values()).filter(
        (r) => r.sender_e164 === sender && r.status === 'awaiting_farmer'
      );
      matches.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
      const row = matches[0] || null;
      return { rows: row ? [row] : [], rowCount: row ? 1 : 0 };
    }

    // SELECT ... FROM signal_draft WHERE status='awaiting_farmer' AND nudge_sent_at IS NULL AND updated_at < NOW() - ($1 || ' minutes')::interval
    if (/SELECT[\s\S]+FROM signal_draft/i.test(s) && /nudge_sent_at IS NULL/.test(s)) {
      const minutes = parseInt(params[0], 10);
      const threshMs = nowMs - minutes * 60 * 1000;
      const rows = Array.from(drafts.values()).filter(
        (r) =>
          r.status === 'awaiting_farmer' &&
          r.nudge_sent_at == null &&
          new Date(r.updated_at).getTime() < threshMs
      );
      return { rows, rowCount: rows.length };
    }

    // SELECT ... FROM signal_draft WHERE status='awaiting_farmer' AND updated_at < NOW() - ($1 || ' minutes')::interval
    if (/SELECT[\s\S]+FROM signal_draft/i.test(s) && /status='awaiting_farmer'/.test(s) && /updated_at <\s+NOW\(\)/.test(s)) {
      const minutes = parseInt(params[0], 10);
      const threshMs = nowMs - minutes * 60 * 1000;
      const rows = Array.from(drafts.values()).filter(
        (r) =>
          r.status === 'awaiting_farmer' &&
          new Date(r.updated_at).getTime() < threshMs
      );
      return { rows, rowCount: rows.length };
    }

    // UPDATE signal_draft ... transitions
    if (/^\s*UPDATE signal_draft/i.test(s)) {
      const id = params[0];
      const row = drafts.get(id);
      if (!row) return { rows: [], rowCount: 0 };

      // Plan 45-03 Option X: commit_failed -> awaiting_farmer transition (re-activate for EDIT).
      if (/status='awaiting_farmer'/.test(s) && /status='commit_failed'/.test(s)) {
        if (row.status !== 'commit_failed') return { rows: [], rowCount: 0 };
        row.status = 'awaiting_farmer';
        row.updated_at = _now();
        return { rows: [{ id: row.id }], rowCount: 1 };
      }

      // edit_turn_count increment (bumpEditTurn) -- detect first since it includes RETURNING edit_turn_count
      if (/edit_turn_count = edit_turn_count \+ 1/.test(s)) {
        if (row.status !== 'awaiting_farmer') return { rows: [], rowCount: 0 };
        row.edit_turn_count = (row.edit_turn_count || 0) + 1;
        row.updated_at = _now();
        return { rows: [{ edit_turn_count: row.edit_turn_count }], rowCount: 1 };
      }

      // markNudgeSent
      if (/nudge_sent_at=NOW\(\)/.test(s) && /nudge_sent_at IS NULL/.test(s)) {
        if (row.nudge_sent_at != null) return { rows: [], rowCount: 0 };
        row.nudge_sent_at = _now();
        row.updated_at = _now();
        return { rows: [{ id: row.id }], rowCount: 1 };
      }

      // updateDraftAfterEdit (multi-column)
      if (/draft_json=\$2/.test(s) && /per_field_confidence=\$3/.test(s)) {
        if (row.status !== 'awaiting_farmer') return { rows: [], rowCount: 0 };
        row.draft_json = params[1];
        row.per_field_confidence = params[2];
        row.farmer_facing_preview = params[3];
        row.updated_at = _now();
        return { rows: [], rowCount: 1 };
      }

      // confirmDraft
      if (/status='confirmed'/.test(s)) {
        if (row.status !== 'awaiting_farmer') return { rows: [], rowCount: 0 };
        row.status = 'confirmed';
        row.confirmed_at = _now();
        row.terminal_reason = 'farmer_yes';
        row.updated_at = _now();
        return { rows: [{ id: row.id }], rowCount: 1 };
      }
      // discardDraft
      if (/status='discarded'/.test(s)) {
        if (row.status !== 'awaiting_farmer') return { rows: [], rowCount: 0 };
        row.status = 'discarded';
        row.discarded_at = _now();
        row.terminal_reason = 'farmer_no';
        row.updated_at = _now();
        return { rows: [{ id: row.id }], rowCount: 1 };
      }
      // expireDraft (cap exceeded -> needs_review)
      if (/status='needs_review'/.test(s)) {
        if (row.status !== 'awaiting_farmer') return { rows: [], rowCount: 0 };
        row.status = 'needs_review';
        row.terminal_reason = params[1];
        row.updated_at = _now();
        // expired_at stays NULL
        return { rows: [{ id: row.id }], rowCount: 1 };
      }
      // expireDraft (timeout / superseded -> expired)
      if (/status='expired'/.test(s)) {
        if (row.status !== 'awaiting_farmer') return { rows: [], rowCount: 0 };
        row.status = 'expired';
        row.expired_at = _now();
        row.terminal_reason = params[1];
        row.updated_at = _now();
        return { rows: [{ id: row.id }], rowCount: 1 };
      }
    }

    // Default: empty result
    return { rows: [], rowCount: 0 };
  }

  async function connect() {
    return {
      query,
      release() {},
    };
  }

  return {
    query,
    connect,
    _now,
    setNow,
    seedDraft,
    getDraft,
    getEvents,
    seedCapture,
    setCaptureSelectThrow,
    seedOutbound,
    _drafts: drafts,
    _events: events,
    _outbounds: outbounds,
  };
}

module.exports = { makeFakePool };
