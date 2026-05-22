'use strict';
// Phase 25: 24-hour rolling history per sender for LLM prompt context (D-10).

function createCaptureHistory({ pool }) {
  return {
    async selectRecentBySender(sender, sinceMs) {
      const since = new Date(sinceMs);
      const r = await pool.query(
        `SELECT captured_at, raw_text, transcript, message_type
         FROM signal_capture
         WHERE sender = $1 AND captured_at > $2
         ORDER BY captured_at ASC`,
        [sender, since]
      );
      return r.rows;
    },

    // Phase 44 Plan-05 (D-18): sibling query against signal_outbound for fmtHistory
    // merged-stream rendering. Returns {sent_at, body, intent} rows — the only
    // fields fmtHistory consumes. Mirror shape of selectRecentBySender.
    async selectRecentOutboundByRecipient(recipient, sinceMs) {
      const since = new Date(sinceMs);
      const r = await pool.query(
        `SELECT sent_at, body, intent
         FROM signal_outbound
         WHERE recipient_e164 = $1 AND sent_at > $2
         ORDER BY sent_at ASC`,
        [recipient, since]
      );
      return r.rows;
    },
  };
}

module.exports = { createCaptureHistory };
