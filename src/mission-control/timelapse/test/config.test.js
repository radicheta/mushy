const { load } = require('../src/config');

describe('config.load', () => {
    const realExit = process.exit;
    const realErr = console.error;
    afterEach(() => { process.exit = realExit; console.error = realErr; });

    test('exits when TIMESCALE_PASSWORD missing', () => {
        const exit = jest.fn();
        process.exit = exit;
        console.error = jest.fn();
        load({});
        expect(exit).toHaveBeenCalledWith(1);
    });

    test('returns defaults when password set', () => {
        const cfg = load({ TIMESCALE_PASSWORD: 'x' });
        expect(cfg.timescaleHost).toBe('timescale');
        expect(cfg.cameraId).toBe('fc1');
        expect(cfg.fps).toBe(12);
        expect(cfg.timezone).toBe('America/Toronto');
        expect(cfg.port).toBe(8888);
        expect(cfg.snapshotDir).toBe('/data/snapshots');
        expect(cfg.timelapseDir).toBe('/data/timelapse');
        expect(cfg.cronSchedule).toBe('30 0 * * *');
    });

    test('TIMELAPSE_FPS overrides default and parses to int', () => {
        const cfg = load({ TIMESCALE_PASSWORD: 'x', TIMELAPSE_FPS: '24' });
        expect(cfg.fps).toBe(24);
    });
});
