const { rebuildRange } = require('../src/rebuild');

const quiet = { info: () => {}, warn: () => {}, error: () => {} };

describe('rebuildRange', () => {
    test('composes every local date from..to inclusive, in order', async () => {
        const compose = jest.fn(async () => ({ frames_used: 10 }));
        const r = await rebuildRange('2026-10-30', '2026-11-02', compose, quiet);
        expect(compose.mock.calls.map((c) => c[0])).toEqual(['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02']);
        expect(r).toEqual({ ok: 4, skipped: 0, failed: [] });
    });

    test('a failing day is recorded and the rest still run', async () => {
        const compose = jest.fn(async (d) => {
            if (d === '2026-11-01') throw new Error('boom');
            return d === '2026-11-02' ? { skipped: true, reason: 'too_few_frames' } : { frames_used: 1 };
        });
        const r = await rebuildRange('2026-10-31', '2026-11-02', compose, quiet);
        expect(r).toEqual({ ok: 1, skipped: 1, failed: [{ date: '2026-11-01', error: 'boom' }] });
    });
});
