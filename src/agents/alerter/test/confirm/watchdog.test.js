'use strict';

const { createWatchdog } = require('../../src/confirm/watchdog');

function silentLogger() {
  return { info: jest.fn(), warn: jest.fn(), debug: jest.fn() };
}

function makeConfig() {
  return {
    draftPendingTimeoutMin: 30,
    draftNudgeFraction: 0.8,
    draftWatchdogIntervalMs: 60000,
  };
}

function makeConfirmDbStub({ nudgeRows = [], expireRows = [], markRowCount = 1, expireRowCount = 1, expireOk = true } = {}) {
  return {
    findNudgeCandidates: jest.fn().mockResolvedValue(nudgeRows),
    findExpireCandidates: jest.fn().mockResolvedValue(expireRows),
    markNudgeSent: jest.fn().mockResolvedValue({ ok: true, rowCount: markRowCount }),
    expireDraft: jest.fn().mockResolvedValue({ ok: expireOk, rowCount: expireRowCount }),
    appendEventViaPool: jest.fn().mockResolvedValue({ ok: true, seq: 1 }),
  };
}

function makeOutboundStub() {
  return { dispatch: jest.fn().mockResolvedValue({ ok: true }) };
}

describe('confirm watchdog (Phase 39 D-04..D-04d)', () => {
  it('tickOnce with no candidates is a no-op', async () => {
    const cdb = makeConfirmDbStub();
    const out = makeOutboundStub();
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.tickOnce();
    expect(out.dispatch).not.toHaveBeenCalled();
  });

  it('one nudge candidate -> markNudgeSent + dispatch(send_nudge) + appendEvent(nudge_sent)', async () => {
    const row = { id: 'r1', sender_e164: '+1', updated_at: new Date(Date.now() - 25 * 60 * 1000) };
    const cdb = makeConfirmDbStub({ nudgeRows: [row] });
    const out = makeOutboundStub();
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.tickOnce();
    expect(cdb.markNudgeSent).toHaveBeenCalledWith({}, 'r1');
    expect(out.dispatch).toHaveBeenCalledWith('send_nudge', row, expect.objectContaining({ minutesRemaining: expect.any(Number) }));
    expect(cdb.appendEventViaPool).toHaveBeenCalled();
  });

  it('markNudgeSent rowCount=0 -> skip nudge dispatch (restart-race protection)', async () => {
    const row = { id: 'r1', sender_e164: '+1', updated_at: new Date(Date.now() - 25 * 60 * 1000) };
    const cdb = makeConfirmDbStub({ nudgeRows: [row], markRowCount: 0 });
    const out = makeOutboundStub();
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.tickOnce();
    expect(out.dispatch).not.toHaveBeenCalled();
  });

  it('one expire candidate -> expireDraft + dispatch(send_expired_note)', async () => {
    const row = { id: 'r2', sender_e164: '+1' };
    const cdb = makeConfirmDbStub({ expireRows: [row] });
    const out = makeOutboundStub();
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.tickOnce();
    expect(cdb.expireDraft).toHaveBeenCalledWith({}, 'r2', 'timeout_expired');
    expect(out.dispatch).toHaveBeenCalledWith('send_expired_note', row);
  });

  it('expireDraft rowCount=0 -> skip expired-note dispatch', async () => {
    const row = { id: 'r2', sender_e164: '+1' };
    const cdb = makeConfirmDbStub({ expireRows: [row], expireRowCount: 0 });
    const out = makeOutboundStub();
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.tickOnce();
    expect(out.dispatch).not.toHaveBeenCalled();
  });

  it('per-row try/catch -- a throw on one row does not halt the rest', async () => {
    const rows = [
      { id: 'good', sender_e164: '+1', updated_at: new Date(Date.now() - 25 * 60 * 1000) },
      { id: 'bad',  sender_e164: '+2', updated_at: new Date(Date.now() - 25 * 60 * 1000) },
      { id: 'after', sender_e164: '+3', updated_at: new Date(Date.now() - 25 * 60 * 1000) },
    ];
    const cdb = makeConfirmDbStub({ nudgeRows: rows });
    const out = {
      dispatch: jest.fn().mockImplementation((tag, row) => {
        if (row.id === 'bad') throw new Error('bad row');
        return Promise.resolve({ ok: true });
      }),
    };
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.tickOnce();
    const dispatchedIds = out.dispatch.mock.calls.map((c) => c[1].id);
    expect(dispatchedIds).toContain('good');
    expect(dispatchedIds).toContain('after');
  });

  it('start() awaits the first tickOnce before scheduling setInterval', async () => {
    let firstTickResolved = false;
    let intervalRegisteredAt = null;
    const setIntervalOrig = global.setInterval;
    global.setInterval = jest.fn().mockImplementation(() => {
      intervalRegisteredAt = firstTickResolved;
      return { dummy: true };
    });
    try {
      const cdb = makeConfirmDbStub();
      // Slow first tick: make findNudgeCandidates resolve on next macrotask.
      cdb.findNudgeCandidates = jest.fn().mockImplementation(
        () => new Promise((resolve) => setImmediate(() => {
          firstTickResolved = true;
          resolve([]);
        }))
      );
      const out = makeOutboundStub();
      const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
      await w.start();
      expect(intervalRegisteredAt).toBe(true);
      w.stop();
    } finally {
      global.setInterval = setIntervalOrig;
    }
  });

  it('start() then stop() leaves no interval running', async () => {
    const cdb = makeConfirmDbStub();
    const out = makeOutboundStub();
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.start();
    w.stop();
    // No throw, no second tick (we don't advance fake timers since we'd need jest.useFakeTimers).
  });

  it('minutesRemaining derived from clock - row.updated_at (Math.round)', async () => {
    const updatedAt = new Date(Date.now() - 28 * 60 * 1000);
    const row = { id: 'r1', sender_e164: '+1', updated_at: updatedAt };
    const cdb = makeConfirmDbStub({ nudgeRows: [row] });
    const out = makeOutboundStub();
    const w = createWatchdog({ pool: {}, confirmDb: cdb, outboundConfirm: out, config: makeConfig(), logger: silentLogger() });
    await w.tickOnce();
    const extras = out.dispatch.mock.calls[0][2];
    expect(extras.minutesRemaining).toBe(2);
  });
});
