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
  };
}

module.exports = { createCaptureHistory };
