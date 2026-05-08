'use strict';

// Phase 31 plan 31-04 — Jest tests for experiment_commands.js (parser) and
// receive-loop dispatch path.

const {
    parseExperimentCommand,
    DEFAULT_DURATION_MIN,
    HARD_CAP_MIN,
    VALID_NAMES,
} = require('../src/experiment_commands');

const { createReceiveLoop } = require('../src/receive-loop');

// =====================================================================
// parseExperimentCommand grammar
// =====================================================================

describe('parseExperimentCommand', () => {
    test('/force-condensation defaults N=15', () => {
        expect(parseExperimentCommand('/force-condensation')).toEqual({
            ok: true, kind: 'start', name: 'force-condensation', duration_minutes: DEFAULT_DURATION_MIN,
        });
    });

    test('/force-evaporation defaults N=15', () => {
        expect(parseExperimentCommand('/force-evaporation')).toEqual({
            ok: true, kind: 'start', name: 'force-evaporation', duration_minutes: 15,
        });
    });

    test('/force-condensation 30 → N=30', () => {
        expect(parseExperimentCommand('/force-condensation 30')).toEqual({
            ok: true, kind: 'start', name: 'force-condensation', duration_minutes: 30,
        });
    });

    test('lower bound N=1 accepted', () => {
        expect(parseExperimentCommand('/force-condensation 1').duration_minutes).toBe(1);
    });

    test('upper bound N=120 accepted', () => {
        expect(parseExperimentCommand('/force-condensation 120').duration_minutes).toBe(120);
    });

    test('N=0 rejected with help reply mentioning 1..120', () => {
        const r = parseExperimentCommand('/force-condensation 0');
        expect(r.ok).toBe(false);
        expect(r.reply).toMatch(/1.*120/);
    });

    test('N=121 rejected with help reply mentioning 120', () => {
        const r = parseExperimentCommand('/force-condensation 121');
        expect(r.ok).toBe(false);
        expect(r.reply).toMatch(/120/);
    });

    test('negative N rejected', () => {
        const r = parseExperimentCommand('/force-condensation -5');
        expect(r.ok).toBe(false);
        expect(r.reply).toMatch(/120/);
    });

    test('non-integer N rejected', () => {
        const r = parseExperimentCommand('/force-condensation 5.5');
        expect(r.ok).toBe(false);
    });

    test('garbage N rejected with help reply', () => {
        const r = parseExperimentCommand('/force-condensation abc');
        expect(r.ok).toBe(false);
        expect(r.reply).toMatch(/Usage/);
    });

    test('/cancel-experiment recognized', () => {
        expect(parseExperimentCommand('/cancel-experiment')).toEqual({ ok: true, kind: 'cancel' });
    });

    test('/cancel-experiment with trailing args rejected for clarity', () => {
        const r = parseExperimentCommand('/cancel-experiment foo');
        expect(r.ok).toBe(false);
        expect(r.reply).toMatch(/no arguments/);
    });

    test('case-insensitive command prefix; canonical name is lowercase', () => {
        const r = parseExperimentCommand('/Force-Condensation 15');
        expect(r.ok).toBe(true);
        expect(r.name).toBe('force-condensation');
    });

    test('unrelated text is passthrough (reply=null)', () => {
        expect(parseExperimentCommand('snooze rh 4h')).toEqual({ ok: false, reply: null });
        expect(parseExperimentCommand('how are the mushrooms?')).toEqual({ ok: false, reply: null });
    });

    test('force-condensation without slash does NOT match', () => {
        expect(parseExperimentCommand('force-condensation 15')).toEqual({ ok: false, reply: null });
    });

    test('whitespace trim around command', () => {
        const r = parseExperimentCommand('   /force-condensation   15   ');
        expect(r.ok).toBe(true);
        expect(r.duration_minutes).toBe(15);
    });

    test('unknown /force- variant passes through', () => {
        expect(parseExperimentCommand('/force-foo 15')).toEqual({ ok: false, reply: null });
    });

    test('non-string input rejected silently (passthrough)', () => {
        expect(parseExperimentCommand(null)).toEqual({ ok: false, reply: null });
        expect(parseExperimentCommand(undefined)).toEqual({ ok: false, reply: null });
        expect(parseExperimentCommand(42)).toEqual({ ok: false, reply: null });
    });

    test('exports honor CONTEXT D-14', () => {
        expect(DEFAULT_DURATION_MIN).toBe(15);
        expect(HARD_CAP_MIN).toBe(120);
        expect(VALID_NAMES.has('force-condensation')).toBe(true);
        expect(VALID_NAMES.has('force-evaporation')).toBe(true);
    });
});

// =====================================================================
// receive-loop dispatch
// =====================================================================

function mkSignalClient(envelopes = []) {
    return {
        receive: jest.fn(async () => envelopes),
        send: jest.fn(async () => undefined),
    };
}

function mkConfig(overrides = {}) {
    return {
        signalSender: '+15555550100',
        signalRecipient: '+15555550200',
        signalAdditionalSenders: [],
        receivePollSec: 1,
        ...overrides,
    };
}

function mkEnvelope(text, source = '+15555550100') {
    return {
        envelope: {
            source,
            dataMessage: { message: text, attachments: [] },
        },
    };
}

function mkLogger() {
    const lg = {
        infos: [], warns: [], errors: [],
        info(...a) { this.infos.push(a.join(' ')); },
        warn(...a) { this.warns.push(a.join(' ')); },
        error(...a) { this.errors.push(a.join(' ')); },
    };
    return lg;
}

describe('receive-loop experiment dispatch', () => {
    test('/force-condensation 10 POSTs to bridge and acks via Signal', async () => {
        const signalClient = mkSignalClient([mkEnvelope('/force-condensation 10')]);
        const config = mkConfig();
        const dispatch = jest.fn();
        const fetchImpl = jest.fn(async () => ({
            status: 200,
            json: async () => ({
                ok: true,
                started_at_iso: '2026-05-08T18:00:00Z',
                reverts_at_iso: '2026-05-08T18:10:00Z',
                prior_mode: 'fruiting',
            }),
        }));
        const logger = mkLogger();
        const loop = createReceiveLoop({
            signalClient, dispatch, config, logger,
            bridgeUrl: 'http://bridge:8080',
            fetchImpl,
        });
        // Manually run one tick to avoid the setInterval start.
        // The factory exposes start/stop; we exercise tick by calling start
        // (which runs an immediate poll) and immediately stopping.
        loop.start();
        // tick() is async; flush microtasks.
        await new Promise((r) => setTimeout(r, 10));
        loop.stop();

        expect(fetchImpl).toHaveBeenCalledTimes(1);
        const [url, init] = fetchImpl.mock.calls[0];
        expect(url).toBe('http://bridge:8080/control/experiment');
        expect(init.method).toBe('POST');
        const body = JSON.parse(init.body);
        expect(body).toEqual({ name: 'force-condensation', duration_minutes: 10 });

        expect(signalClient.send).toHaveBeenCalledTimes(1);
        const ack = signalClient.send.mock.calls[0][0];
        expect(ack).toMatch(/force-condensation/);
        expect(ack).toMatch(/10 min/);
        expect(ack).toMatch(/reverts/);
    });

    test('/cancel-experiment POSTs to cancel endpoint and acks', async () => {
        const signalClient = mkSignalClient([mkEnvelope('/cancel-experiment')]);
        const fetchImpl = jest.fn(async () => ({
            status: 200,
            json: async () => ({ ok: true, ended_at_iso: '2026-05-08T18:05:00Z' }),
        }));
        const loop = createReceiveLoop({
            signalClient, dispatch: jest.fn(), config: mkConfig(), logger: mkLogger(),
            bridgeUrl: 'http://bridge:8080', fetchImpl,
        });
        loop.start();
        await new Promise((r) => setTimeout(r, 10));
        loop.stop();

        expect(fetchImpl).toHaveBeenCalledTimes(1);
        expect(fetchImpl.mock.calls[0][0]).toBe('http://bridge:8080/control/cancel-experiment');
        const ack = signalClient.send.mock.calls[0][0];
        expect(ack).toMatch(/cancelled/);
        expect(ack).toMatch(/ended_at/);
    });

    test('bridge 4xx propagates error to Signal', async () => {
        const signalClient = mkSignalClient([mkEnvelope('/force-condensation 5')]);
        const fetchImpl = jest.fn(async () => ({
            status: 400,
            json: async () => ({ ok: false, error: 'experiment_in_progress' }),
        }));
        const loop = createReceiveLoop({
            signalClient, dispatch: jest.fn(), config: mkConfig(), logger: mkLogger(),
            bridgeUrl: 'http://bridge:8080', fetchImpl,
        });
        loop.start();
        await new Promise((r) => setTimeout(r, 10));
        loop.stop();

        const ack = signalClient.send.mock.calls[0][0];
        expect(ack).toMatch(/experiment_in_progress/);
    });

    test('fetch throws → generic dispatch-failed reply', async () => {
        const signalClient = mkSignalClient([mkEnvelope('/force-condensation')]);
        const fetchImpl = jest.fn(async () => { throw new TypeError('fetch failed'); });
        const logger = mkLogger();
        const loop = createReceiveLoop({
            signalClient, dispatch: jest.fn(), config: mkConfig(), logger,
            bridgeUrl: 'http://bridge:8080', fetchImpl,
        });
        loop.start();
        await new Promise((r) => setTimeout(r, 10));
        loop.stop();

        const ack = signalClient.send.mock.calls[0][0];
        expect(ack).toMatch(/dispatch failed/);
        expect(logger.warns.some((m) => /network error/.test(m))).toBe(true);
    });

    test('invalid experiment command replies help, does NOT POST', async () => {
        const signalClient = mkSignalClient([mkEnvelope('/force-condensation 999')]);
        const fetchImpl = jest.fn();
        const loop = createReceiveLoop({
            signalClient, dispatch: jest.fn(), config: mkConfig(), logger: mkLogger(),
            bridgeUrl: 'http://bridge:8080', fetchImpl,
        });
        loop.start();
        await new Promise((r) => setTimeout(r, 10));
        loop.stop();

        expect(fetchImpl).not.toHaveBeenCalled();
        const reply = signalClient.send.mock.calls[0][0];
        expect(reply).toMatch(/Usage/);
        expect(reply).toMatch(/1.*120/);
    });

    test('/force-* command does NOT trigger snooze dispatch', async () => {
        // snooze dispatch happens via dispatch({ type:'snooze', ... }). Our
        // experiment branch must short-circuit (continue) before snooze runs.
        const signalClient = mkSignalClient([mkEnvelope('/force-condensation 5')]);
        const dispatch = jest.fn();
        const fetchImpl = jest.fn(async () => ({
            status: 200,
            json: async () => ({ ok: true, started_at_iso: 'x', reverts_at_iso: 'y', prior_mode: 'fruiting' }),
        }));
        const loop = createReceiveLoop({
            signalClient, dispatch, config: mkConfig(), logger: mkLogger(),
            bridgeUrl: 'http://bridge:8080', fetchImpl,
        });
        loop.start();
        await new Promise((r) => setTimeout(r, 10));
        loop.stop();

        // dispatch is the snooze dispatcher; must NOT be called for an
        // experiment command.
        expect(dispatch).not.toHaveBeenCalled();
    });

    test('unrelated text passes through to snooze (passthrough behavior preserved)', async () => {
        // Non-experiment, non-snooze text → no fetch, no dispatch, no send.
        const signalClient = mkSignalClient([mkEnvelope('how are the mushrooms?')]);
        const dispatch = jest.fn();
        const fetchImpl = jest.fn();
        const loop = createReceiveLoop({
            signalClient, dispatch, config: mkConfig(), logger: mkLogger(),
            bridgeUrl: 'http://bridge:8080', fetchImpl,
        });
        loop.start();
        await new Promise((r) => setTimeout(r, 10));
        loop.stop();

        expect(fetchImpl).not.toHaveBeenCalled();
        // Snooze parser may not match either; no send and no dispatch should
        // fire for a freeform message that isn't a command.
        expect(dispatch).not.toHaveBeenCalled();
    });
});
