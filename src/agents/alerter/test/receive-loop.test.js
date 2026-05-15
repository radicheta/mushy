'use strict';

const { createReceiveLoop, collectGroupTriggers } = require('../src/receive-loop');
const fakeSignalServer = require('./helpers/fake-signal-server');

const BOT_PHONE = '+59891840205';
const F2_PHONE = '+59892893012';
const UNKNOWN_PHONE = '+15550009999';

const groupSilentEnv = require('./fixtures/envelopes/group-silent.json')[0];
const groupMentionEnv = require('./fixtures/envelopes/group-mention.json')[0];
const groupCommandEnv = require('./fixtures/envelopes/group-command.json')[0];
const groupReplyToBotEnv = require('./fixtures/envelopes/group-reply-to-bot.json')[0];
const groupMentionAndCommandEnv = require('./fixtures/envelopes/group-mention-and-command.json')[0];
const groupMentionIosObjEnv = require('./fixtures/envelopes/group-mention-ios-obj.json')[0];
const groupUnknownSenderEnv = require('./fixtures/envelopes/group-unknown-sender.json')[0];

const silentLogger = { info: () => {}, warn: () => {}, error: () => {} };

const baseConfig = {
  signalSender: '+1111111111',
  signalRecipient: '+1111111111',
  receivePollSec: 0.05,
};

function makeSignalClient(server) {
  return {
    receive: async () => {
      const res = await fetch(`${server.url}/v1/receive/${encodeURIComponent('+1111111111')}`);
      return await res.json();
    },
    send: async (body) => {
      const res = await fetch(`${server.url}/v2/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: body, number: '+1111111111', recipients: ['+1111111111'] }),
      });
      return { ok: res.ok };
    },
  };
}

describe('createReceiveLoop', () => {
  let server;
  let loop;

  beforeEach(async () => {
    server = await fakeSignalServer.start();
  });

  afterEach(async () => {
    if (loop) loop.stop();
    await server.close();
  });

  test('Test A: valid snooze envelope dispatches snooze event within 500ms', async () => {
    const dispatched = [];
    const nowMs = Date.now();
    const clock = () => nowMs;

    // Push a valid snooze envelope
    server.received.push({
      envelope: { source: '+1111111111', dataMessage: { message: 'snooze rh 4h' } }
    });

    const client = makeSignalClient(server);
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].type).toBe('snooze');
    expect(dispatched[0].alertType).toBe('rh');
    expect(dispatched[0].untilMs).toBeGreaterThan(nowMs);
  });

  test('Test B: snooze-prefixed malformed command triggers help-text reply, no dispatch', async () => {
    // 25-05: only snooze-prefixed malformed text triggers fuzzy help; arbitrary text
    // ("mute rh") now flows to the capture pipeline (covered by capture-fanout test below).
    const dispatched = [];
    const clock = () => Date.now();

    server.received.push({
      envelope: { source: '+1111111111', dataMessage: { message: 'snooze rh banana' } }
    });

    const client = makeSignalClient(server);
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(server.sent).toHaveLength(1);
    expect(server.sent[0].message).toMatch(/snooze/i);
  });

  test('Test C: envelope from unrecognized sender is ignored', async () => {
    const dispatched = [];
    const clock = () => Date.now();

    server.received.push({
      envelope: { source: '+9999999999', dataMessage: { message: 'snooze rh 4h' } }
    });

    const client = makeSignalClient(server);
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(server.sent).toHaveLength(0);
  });

  test('Test D: if receive() throws, loop continues on next tick', async () => {
    const dispatched = [];
    let callCount = 0;
    const clock = () => Date.now();

    const brokenClient = {
      receive: async () => {
        callCount++;
        if (callCount === 1) throw new Error('network error');
        return [];
      },
      send: async () => {},
    };

    loop = createReceiveLoop({
      signalClient: brokenClient,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();

    await new Promise((resolve) => setTimeout(resolve, 300));
    loop.stop();

    // Loop did not die: at least 2 calls were made (first threw, second succeeded)
    expect(callCount).toBeGreaterThanOrEqual(2);
    expect(dispatched).toHaveLength(0); // no valid snooze events
  });

  test('R4-fastpath: bare "mute" dispatches snooze, capturePipeline.handle NOT called, ack sent', async () => {
    const dispatched = [];
    const captureCalls = [];
    const sent = [];
    const clock = () => 1000;
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+1111111111', dataMessage: { message: 'mute' } } }];
          return [];
        };
      })(),
      send: async (body) => { sent.push(body); return { ok: true }; },
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].type).toBe('snooze');
    expect(dispatched[0].alertType).toBe('all');
    expect(captureCalls).toHaveLength(0);
    expect(sent.some((b) => /muted for 24h/i.test(b))).toBe(true);
  });

  test('R6-budget: snooze fast-path NOT awaiting capturePipeline.handle (never-resolves capture)', async () => {
    const dispatched = [];
    const clock = () => 1000;
    let receiveCalls = 0;
    const client = {
      receive: async () => {
        receiveCalls++;
        return [{ envelope: { source: '+1111111111', dataMessage: { message: 'mute' } } }];
      },
      send: async () => ({ ok: true }),
    };
    // capture handle returns a promise that never resolves
    const capturePipeline = { handle: () => new Promise(() => {}) };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 250));
    loop.stop();
    // Two ticks at 50ms poll → at least 2 dispatches (proves loop did NOT block on capture)
    expect(dispatched.length).toBeGreaterThanOrEqual(2);
    expect(dispatched[0].type).toBe('snooze');
  });

  test('R7: non-whitelisted sender → no dispatch, no capture, logger.warn fired', async () => {
    const dispatched = [];
    const captureCalls = [];
    const warnings = [];
    const clock = () => 1000;
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+99999999999', dataMessage: { message: 'mute' } } }];
          return [];
        };
      })(),
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: { info: () => {}, warn: (m) => warnings.push(m), error: () => {} },
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(captureCalls).toHaveLength(0);
    expect(warnings.some((w) => /rejected sender/i.test(w))).toBe(true);
  });

  test('capture-fanout: text-only non-snooze envelope → capturePipeline.handle called, no dispatch', async () => {
    const dispatched = [];
    const captureCalls = [];
    const clock = () => 1000;
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+1111111111', dataMessage: { message: 'hello' } } }];
          return [];
        };
      })(),
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(captureCalls).toHaveLength(1);
    expect(captureCalls[0].envelope.source).toBe('+1111111111');
    expect(captureCalls[0].envelope.dataMessage.message).toBe('hello');
  });

  test('capture-fanout: attachment-only (no text) → capturePipeline.handle called', async () => {
    const dispatched = [];
    const captureCalls = [];
    const clock = () => 1000;
    const att = { id: 'att1', contentType: 'image/jpeg' };
    const client = {
      receive: (() => {
        let n = 0;
        return async () => {
          n++;
          if (n === 1) return [{ envelope: { source: '+1111111111', dataMessage: { message: null, attachments: [att] } } }];
          return [];
        };
      })(),
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async (env) => { captureCalls.push(env); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: (e) => dispatched.push(e),
      config: baseConfig,
      capturePipeline,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 200));
    loop.stop();

    expect(dispatched).toHaveLength(0);
    expect(captureCalls).toHaveLength(1);
    expect(captureCalls[0].envelope.dataMessage.attachments).toHaveLength(1);
    expect(captureCalls[0].envelope.dataMessage.message).toBe(null);
  });

  test('capture-fanout: pipeline rejection is caught (logger.warn), loop continues', async () => {
    const warnings = [];
    let receiveCalls = 0;
    const clock = () => 1000;
    const client = {
      receive: async () => {
        receiveCalls++;
        return [{ envelope: { source: '+1111111111', dataMessage: { message: 'hello' } } }];
      },
      send: async () => ({ ok: true }),
    };
    const capturePipeline = { handle: async () => { throw new Error('boom'); } };
    loop = createReceiveLoop({
      signalClient: client,
      dispatch: () => {},
      config: baseConfig,
      capturePipeline,
      logger: { info: () => {}, warn: (m) => warnings.push(m), error: () => {} },
      clock,
    });
    loop.start();
    await new Promise((r) => setTimeout(r, 250));
    loop.stop();

    expect(receiveCalls).toBeGreaterThanOrEqual(2); // loop kept ticking
    expect(warnings.some((w) => /capture/i.test(w) && /boom/.test(w))).toBe(true);
  });

  // ============================================================
  // Phase 37 Plan 03 — Group routing tests
  // ============================================================

  describe('collectGroupTriggers (pure helper)', () => {
    test('group-silent → empty Set', () => {
      const out = collectGroupTriggers(groupSilentEnv, BOT_PHONE);
      expect(out.size).toBe(0);
    });

    test('group-mention → Set has "mention"', () => {
      const out = collectGroupTriggers(groupMentionEnv, BOT_PHONE);
      expect(out.has('mention')).toBe(true);
      expect(out.size).toBe(1);
    });

    test('group-command → Set has "command"', () => {
      const out = collectGroupTriggers(groupCommandEnv, BOT_PHONE);
      expect(out.has('command')).toBe(true);
      expect(out.size).toBe(1);
    });

    test('group-reply-to-bot → Set has "quote"', () => {
      const out = collectGroupTriggers(groupReplyToBotEnv, BOT_PHONE);
      expect(out.has('quote')).toBe(true);
    });

    test('group-mention-and-command → Set has both', () => {
      const out = collectGroupTriggers(groupMentionAndCommandEnv, BOT_PHONE);
      expect(out.has('mention')).toBe(true);
      expect(out.has('command')).toBe(true);
      expect(out.size).toBe(2);
    });

    // 2026-05-15 fix: Signal iOS renders @mentions as U+FFFC object-replacement char.
    // The command-keyword detector regex must tolerate the OBJ-char prefix or commands
    // route to the LLM instead of the mute/snooze handler (Attestation D live finding 2026-05-11).
    test('group-mention-iOS (OBJ-char) → Set has both mention and command', () => {
      const out = collectGroupTriggers(groupMentionIosObjEnv, BOT_PHONE);
      expect(out.has('mention')).toBe(true);
      expect(out.has('command')).toBe(true);
    });

    test('wrong botPhone → no false positives on mention fixture', () => {
      const out = collectGroupTriggers(groupMentionEnv, '+9999999999');
      expect(out.has('mention')).toBe(false);
    });

    test('wrong botPhone → no false positives on quote fixture', () => {
      const out = collectGroupTriggers(groupReplyToBotEnv, '+9999999999');
      expect(out.has('quote')).toBe(false);
    });

    test('quote matcher accepts authorNumber field (Risk #9 defensive)', () => {
      const env = {
        envelope: {
          dataMessage: {
            quote: { authorNumber: BOT_PHONE, author: undefined, text: 'foo' },
          },
        },
      };
      const out = collectGroupTriggers(env, BOT_PHONE);
      expect(out.has('quote')).toBe(true);
    });

    test('accepts both env shapes (env.envelope vs env directly)', () => {
      // Direct dataMessage shape — capture's envWrapper sometimes passes the inner envelope
      const env = { dataMessage: { message: 'mute' } };
      const out = collectGroupTriggers(env, BOT_PHONE);
      expect(out.has('command')).toBe(true);
    });
  });

  describe('group routing (receive-loop integration)', () => {
    const groupConfig = {
      signalSender: BOT_PHONE,
      signalRecipient: BOT_PHONE,
      signalAdditionalSenders: [F2_PHONE, UNKNOWN_PHONE],
      receivePollSec: 0.05,
    };

    function makeClient(envelopes) {
      let n = 0;
      const sends = [];
      return {
        sends,
        client: {
          receive: async () => {
            n++;
            if (n === 1) return envelopes;
            return [];
          },
          send: jest.fn(async (body, opts) => { sends.push({ body, opts }); return { ok: true }; }),
        },
      };
    }

    test('group-silent: capture row written with kind=none, no signal send', async () => {
      const captureCalls = [];
      const { client, sends } = makeClient([groupSilentEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: () => {},
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      expect(captureCalls).toHaveLength(1);
      expect(captureCalls[0].ctx.replyTargetKind).toBe('none');
      expect(captureCalls[0].ctx.groupId).toBe('hKw0KX1gte8Mnjw7fMlMCsPc7s/g3drpkpVsBwPcxwE=');
      expect(captureCalls[0].ctx.suppressReply).toBe(true);
      expect(sends).toHaveLength(0); // no signal send fired
    });

    test('group-mention: ONE signal send to {groupId} via capture branch', async () => {
      const captureCalls = [];
      const { client } = makeClient([groupMentionEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: () => {},
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      expect(captureCalls).toHaveLength(1);
      expect(captureCalls[0].ctx.replyTargetKind).toBe('group');
      expect(captureCalls[0].ctx.suppressReply).toBe(false);
    });

    test('group-command (mute): ONE dispatch, snooze branch fires; capture suppresses reply', async () => {
      const dispatched = [];
      const captureCalls = [];
      const { client, sends } = makeClient([groupCommandEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: (e) => dispatched.push(e),
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      // mute → snooze dispatch
      expect(dispatched).toHaveLength(1);
      expect(dispatched[0].type).toBe('snooze');
      // snooze branch sent the ack (one send only)
      expect(sends).toHaveLength(1);
      // command branch hard-stops (continue) — capture not called for group-command
      // because existing snooze branch ends with `continue`. Capture is NOT called here.
      // That preserves D-09 single-reply.
      expect(captureCalls).toHaveLength(0);
    });

    test('group-mention-iOS (OBJ-char): mute dispatches snooze (2026-05-15 fix)', async () => {
      const dispatched = [];
      const captureCalls = [];
      const { client, sends } = makeClient([groupMentionIosObjEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: (e) => dispatched.push(e),
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      // U+FFFC + space + mute must route through commandText strip to snooze parser.
      expect(dispatched).toHaveLength(1);
      expect(dispatched[0].type).toBe('snooze');
      expect(sends).toHaveLength(1);
      expect(captureCalls).toHaveLength(0);
    });

    test('group-mention-and-command: EXACTLY ONE reply (D-09 dedupe)', async () => {
      const dispatched = [];
      const captureCalls = [];
      const { client, sends } = makeClient([groupMentionAndCommandEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: (e) => dispatched.push(e),
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      // mute keyword matches snooze parser → dispatch fires
      expect(dispatched).toHaveLength(1);
      // ONE signal send (the snooze ack); capture branch does not run after `continue`
      expect(sends).toHaveLength(1);
    });

    test('group-command from F2 (non-operator) still dispatches mute (D-10)', async () => {
      const dispatched = [];
      // F2_PHONE is already the source in group-command.json
      const { client } = makeClient([groupCommandEnv]);
      const capturePipeline = { handle: async () => {} };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: (e) => dispatched.push(e),
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      expect(dispatched).toHaveLength(1);
      expect(dispatched[0].type).toBe('snooze');
      expect(dispatched[0].alertType).toBe('all');
    });

    test('group-unknown-sender (whitelisted but not in farmer-map): capture runs normally', async () => {
      const captureCalls = [];
      const { client } = makeClient([groupUnknownSenderEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: () => {},
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      expect(captureCalls).toHaveLength(1);
      expect(captureCalls[0].ctx.replyTargetKind).toBe('none'); // silent group msg
      expect(captureCalls[0].ctx.groupId).toBeTruthy();
    });

    test('DM envelope unchanged: ctx.replyTargetKind=dm passed to capture', async () => {
      const captureCalls = [];
      const dmEnv = require('./fixtures/envelopes/text.json')[0];
      const { client } = makeClient([dmEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: () => {},
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      expect(captureCalls).toHaveLength(1);
      expect(captureCalls[0].ctx.replyTargetKind).toBe('dm');
      expect(captureCalls[0].ctx.groupId).toBeNull();
      expect(captureCalls[0].ctx.suppressReply).toBe(false);
    });

    test('groupInfo.type=UPDATE → treated as non-group, no trigger eval', async () => {
      const updateEnv = JSON.parse(JSON.stringify(groupMentionEnv));
      updateEnv.envelope.dataMessage.groupInfo.type = 'UPDATE';
      const captureCalls = [];
      const { client, sends } = makeClient([updateEnv]);
      const capturePipeline = { handle: async (env, ctx) => { captureCalls.push({ env, ctx }); } };
      loop = createReceiveLoop({
        signalClient: client,
        dispatch: () => {},
        config: groupConfig,
        capturePipeline,
        logger: silentLogger,
        clock: () => 1000,
      });
      loop.start();
      await new Promise((r) => setTimeout(r, 200));
      loop.stop();

      // Treated as non-group → DM-style handling. text='@bot status' — no snooze parse,
      // not an experiment command, falls to capture branch as a DM.
      expect(captureCalls).toHaveLength(1);
      expect(captureCalls[0].ctx.replyTargetKind).toBe('dm');
    });
  });

  test('Test E: stop() halts further receive() calls', async () => {
    const clock = () => Date.now();
    let callCount = 0;

    const countingClient = {
      receive: async () => { callCount++; return []; },
      send: async () => {},
    };

    loop = createReceiveLoop({
      signalClient: countingClient,
      dispatch: () => {},
      config: baseConfig,
      logger: silentLogger,
      clock,
    });
    loop.start();
    await new Promise((resolve) => setTimeout(resolve, 100));
    const countAfterStart = callCount;
    loop.stop();
    const countAfterStop = callCount;
    await new Promise((resolve) => setTimeout(resolve, 200));
    const countAfterWait = callCount;

    expect(countAfterStop).toBeGreaterThan(0); // loop ran at least once
    // After stop, no further calls (allow one in-flight tick to complete)
    expect(countAfterWait).toBeLessThanOrEqual(countAfterStop + 1);
  });
});
