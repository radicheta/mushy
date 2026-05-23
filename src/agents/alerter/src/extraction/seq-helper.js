'use strict';

// Phase 47 Plan 03 Task 1: SEQ helpers for the seeding_session ask-back path.
//
// Two pure helpers (mintChildBlockNames, yyyymmddToYymmdd) and one DB-backed
// helper (lookupLastSeqForDate) consumed by:
//   - Phase 47 pipeline.js -- to fill child_block_names after farmer reply.
//   - Phase 48 commit fan-out -- to compute the session-wide SEQ counter at
//     commit time (per [[b5-seq-is-per-session-not-per-strain]]).
//
// Design notes:
//   - lookupLastSeqForDate tolerates legacy SeedingLog rows AND new
//     SeedingSession rows in the same date. It returns the MAX SEQ across
//     all species (per the per-session lock; the SEQ counter spans species
//     within a single date's session).
//   - Parse failures on individual rows are swallowed (skip-on-error) so a
//     single malformed draft does not crash the lookup. The default is null.
//   - The 'NEEDS_SEQ' sentinel is explicitly excluded from SEQ parsing.

const { BLOCK_NAME_RE } = require('./schemas/seeding');

const EVENT_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

function yyyymmddToYymmdd(eventDate) {
  if (typeof eventDate !== 'string') {
    throw new Error('yyyymmddToYymmdd: eventDate must be a string');
  }
  const m = eventDate.match(EVENT_DATE_RE);
  if (!m) {
    throw new Error(`yyyymmddToYymmdd: bad eventDate '${eventDate}' (want YYYY-MM-DD)`);
  }
  return `${m[1].slice(2)}${m[2]}${m[3]}`;
}

/**
 * mintChildBlockNames({eventDateYYMMDD, speciesCode, startSeq, qty}) -> string[]
 *
 * Pure. Builds `qty` consecutive block names of the form
 * `${YYMMDD}_${SPECIES}_${startSeq+i}`. Each result is validated against
 * BLOCK_NAME_RE; throws Error('mint_invalid_block_name') on mismatch so a
 * lowercased species code or malformed date is caught immediately.
 */
function mintChildBlockNames({ eventDateYYMMDD, speciesCode, startSeq, qty }) {
  const out = [];
  for (let i = 0; i < qty; i += 1) {
    const name = `${eventDateYYMMDD}_${speciesCode}_${startSeq + i}`;
    if (!BLOCK_NAME_RE.test(name)) {
      throw new Error(`mint_invalid_block_name: ${name}`);
    }
    out.push(name);
  }
  return out;
}

// Extract trailing SEQ from a canonical B5 block_name (YYMMDD_SPECIES_SEQ).
// Returns a number or null when the input does not match BLOCK_NAME_RE.
function seqOf(blockName) {
  if (typeof blockName !== 'string') return null;
  if (blockName === 'NEEDS_SEQ') return null;
  if (!BLOCK_NAME_RE.test(blockName)) return null;
  const idx = blockName.lastIndexOf('_');
  if (idx < 0) return null;
  const n = Number(blockName.slice(idx + 1));
  return Number.isFinite(n) ? n : null;
}

function extractSeqsFromRow(draftJson) {
  // Tolerate any shape; never throw out of here.
  if (!draftJson || typeof draftJson !== 'object') return [];
  const seqs = [];
  try {
    const type = draftJson.type;
    if (type === 'seeding') {
      const s = seqOf(draftJson.block_name);
      if (s != null) seqs.push(s);
    } else if (type === 'seeding_session') {
      const groups = Array.isArray(draftJson.groups) ? draftJson.groups : [];
      for (const g of groups) {
        const cbn = g && g.child_block_names;
        const values = cbn && Array.isArray(cbn.value) ? cbn.value : [];
        for (const v of values) {
          const s = seqOf(v);
          if (s != null) seqs.push(s);
        }
      }
    }
  } catch (_e) {
    // skip-on-error: a single malformed draft must not break the lookup.
    return seqs;
  }
  return seqs;
}

/**
 * lookupLastSeqForDate(pool, eventDate, opts) -> Promise<
 *   {ok:true, lastSeq:number|null, source:'signal_draft'|'none'} |
 *   {ok:false, reason}
 * >
 *
 * Queries signal_draft for any in-flight, awaiting, or committed draft whose
 * event_date matches the requested day. Walks each row's draft_json, parses
 * SEQ from legacy seeding.block_name AND seeding_session.groups[].
 * child_block_names.value[], returns the MAX across all rows.
 *
 * Phase 48 will extend this to also union with farmOS-committed rows; the
 * signature is forward-compatible (opts is reserved).
 */
async function lookupLastSeqForDate(pool, eventDate, opts) {
  const { logger = console } = opts || {};
  if (typeof eventDate !== 'string' || !EVENT_DATE_RE.test(eventDate)) {
    return { ok: false, reason: 'bad_event_date' };
  }
  let rows;
  try {
    const r = await pool.query(
      `SELECT draft_json FROM signal_draft
        WHERE status IN ('committed','awaiting_farmer','confirmed','pending')
          AND draft_json->>'event_date' = $1`,
      [eventDate],
    );
    rows = r && r.rows ? r.rows : [];
  } catch (e) {
    if (logger && logger.warn) logger.warn(`[seq-helper] lookup failed: ${e.message}`);
    return { ok: false, reason: e.message };
  }
  let max = null;
  for (const row of rows) {
    const seqs = extractSeqsFromRow(row && row.draft_json);
    for (const s of seqs) {
      if (max == null || s > max) max = s;
    }
  }
  return { ok: true, lastSeq: max, source: max == null ? 'none' : 'signal_draft' };
}

module.exports = {
  mintChildBlockNames,
  yyyymmddToYymmdd,
  lookupLastSeqForDate,
  // Exposed for unit tests / Phase 48 reuse.
  _seqOf: seqOf,
  _extractSeqsFromRow: extractSeqsFromRow,
};
