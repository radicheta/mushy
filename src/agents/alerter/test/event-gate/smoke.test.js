'use strict';

// Phase 44 Wave 0 stub — filled in by Plan-01 (corpus pull) + Plan-04 (assertions).
// Covers GATE-02 ship-gate metrics per CONTEXT D-22:
//   - 0 farmer-facing preview pings on 24 must-skip rows
//     (8 phantom-ack + 8 greetings + 8 UX-meta)
//   - ≥95% event recall on 48 must-extract rows (36 hard-event + 12 soft-obs)
//   - 28 confirm-verb rows bypass via Phase 39 short-circuit (receive-loop.js:220-264)
//
// Fixture path (operator-hand-classified JSONL, append-only):
//   .planning/phases/44-event-gate-durable-signal-outbound-tenant-aware/44-hand-classified-100.jsonl
// Schema per row: {tenant_id, capture_id, class, expected_gate_action, notes}

describe('event-gate/smoke — 100-capture ship-gate (stub)', () => {
  test.skip('Plan-01+Plan-04: 0 preview pings on 24 must-skip rows', () => {});
  test.skip('Plan-01+Plan-04: ≥95% event recall on 48 must-extract rows', () => {});
  test.skip('Plan-01+Plan-04: 28 confirm rows never reach gate (Phase 39 short-circuit)', () => {});
});
