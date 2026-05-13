'use strict';

const {
  transition,
  isTerminal,
  CONFIRM_STATUS,
  CONFIRM_EVENTS,
} = require('../../src/confirm/state-machine');

function awaiting(over = {}) {
  return Object.assign({ status: 'awaiting_farmer', edit_turn_count: 0, nudge_sent_at: null }, over);
}

describe('confirm state-machine (Phase 39)', () => {
  describe('YES family', () => {
    it('awaiting_farmer + FARMER_YES -> confirmed/send_confirm_ack', () => {
      const r = transition(awaiting(), { type: CONFIRM_EVENTS.FARMER_YES });
      expect(r.nextStatus).toBe('confirmed');
      expect(r.side_effects).toEqual(['send_confirm_ack']);
      expect(r.reason).toBe('farmer_yes');
    });
    it('confirmed + FARMER_YES -> idempotent ack (D-02 + D-02a)', () => {
      const r = transition({ status: 'confirmed', edit_turn_count: 0 }, { type: 'farmer_yes' });
      expect(r.nextStatus).toBe('confirmed');
      expect(r.side_effects).toEqual(['send_confirm_idempotent_ack']);
      expect(r.reason).toBe('already_confirmed');
    });
    it('discarded + FARMER_YES -> noop (inactive)', () => {
      const r = transition({ status: 'discarded', edit_turn_count: 0 }, { type: 'farmer_yes' });
      expect(r.side_effects).toEqual(['noop']);
      expect(r.reason).toBe('inactive');
    });
  });

  describe('NO family', () => {
    it('awaiting_farmer + FARMER_NO -> discarded/send_discard_ack', () => {
      const r = transition(awaiting(), { type: 'farmer_no' });
      expect(r.nextStatus).toBe('discarded');
      expect(r.side_effects).toEqual(['send_discard_ack']);
    });
    it('expired + FARMER_NO -> noop', () => {
      const r = transition({ status: 'expired', edit_turn_count: 0 }, { type: 'farmer_no' });
      expect(r.side_effects).toEqual(['noop']);
    });
  });

  describe('EDIT family', () => {
    it('awaiting_farmer + FARMER_EDIT at edit_turn_count=0 -> run_edit_reextraction, count=1', () => {
      const r = transition(awaiting({ edit_turn_count: 0 }), { type: 'farmer_edit', maxEditTurns: 3 });
      expect(r.nextStatus).toBe('awaiting_farmer');
      expect(r.nextEditTurnCount).toBe(1);
      expect(r.side_effects).toEqual(['run_edit_reextraction']);
    });
    it('at edit_turn_count=2 (one below cap) -> run_edit_reextraction, count=3', () => {
      const r = transition(awaiting({ edit_turn_count: 2 }), { type: 'farmer_edit', maxEditTurns: 3 });
      expect(r.side_effects).toEqual(['run_edit_reextraction']);
      expect(r.nextEditTurnCount).toBe(3);
    });
    it('at edit_turn_count=3 (cap) -> needs_review/send_edit_cap_msg (D-03a)', () => {
      const r = transition(awaiting({ edit_turn_count: 3 }), { type: 'farmer_edit', maxEditTurns: 3 });
      expect(r.nextStatus).toBe('needs_review');
      expect(r.side_effects).toEqual(['send_edit_cap_msg']);
      expect(r.reason).toBe('edit_cap_exceeded');
    });
    it('confirmed + FARMER_EDIT -> noop', () => {
      const r = transition({ status: 'confirmed', edit_turn_count: 0 }, { type: 'farmer_edit', maxEditTurns: 3 });
      expect(r.side_effects).toEqual(['noop']);
    });
  });

  describe('NUDGE', () => {
    it('awaiting_farmer + NUDGE_DUE + nudge_sent_at=null -> [send_nudge, mark_nudge_sent]', () => {
      const r = transition(awaiting({ nudge_sent_at: null }), { type: 'nudge_due' });
      expect(r.side_effects).toEqual(['send_nudge', 'mark_nudge_sent']);
      expect(r.reason).toBe('nudge');
    });
    it('awaiting_farmer + NUDGE_DUE + nudge_sent_at=Date -> noop (already_nudged)', () => {
      const r = transition(awaiting({ nudge_sent_at: new Date() }), { type: 'nudge_due' });
      expect(r.side_effects).toEqual(['noop']);
      expect(r.reason).toBe('already_nudged');
    });
  });

  describe('EXPIRE', () => {
    it('awaiting_farmer + EXPIRE_DUE -> expired/send_expired_note', () => {
      const r = transition(awaiting(), { type: 'expire_due' });
      expect(r.nextStatus).toBe('expired');
      expect(r.side_effects).toEqual(['send_expired_note']);
    });
    it('expired + EXPIRE_DUE -> noop', () => {
      const r = transition({ status: 'expired', edit_turn_count: 0 }, { type: 'expire_due' });
      expect(r.side_effects).toEqual(['noop']);
    });
  });

  describe('SUPERSEDED', () => {
    it('awaiting_farmer + SUPERSEDED -> expired/noop (silent)', () => {
      const r = transition(awaiting(), { type: 'superseded' });
      expect(r.nextStatus).toBe('expired');
      expect(r.side_effects).toEqual(['noop']);
      expect(r.reason).toBe('superseded_by_newer_draft');
    });
  });

  describe('Purity', () => {
    it('two identical calls return deep-equal results and do not mutate state', () => {
      const s = awaiting({ edit_turn_count: 1 });
      const snapshot = JSON.parse(JSON.stringify(s));
      const r1 = transition(s, { type: 'farmer_edit', maxEditTurns: 3 });
      const r2 = transition(s, { type: 'farmer_edit', maxEditTurns: 3 });
      expect(r1).toEqual(r2);
      expect(s).toEqual(snapshot);
    });
  });

  describe('isTerminal', () => {
    it('marks confirmed/discarded/expired/needs_review as terminal', () => {
      expect(isTerminal('confirmed')).toBe(true);
      expect(isTerminal('discarded')).toBe(true);
      expect(isTerminal('expired')).toBe(true);
      expect(isTerminal('needs_review')).toBe(true);
      expect(isTerminal('awaiting_farmer')).toBe(false);
      expect(isTerminal('pending')).toBe(false);
    });
  });
});
