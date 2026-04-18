'use strict';

const { transition, initialState, STATES } = require('../src/state');

// Base config used across tests
const config = {
  rhTarget: 90,
  rhBand: 3,
  oobN: 5,
  oobWindowMin: 3,
  cooldownMin: 30,
  criticalCooldownMin: 60,
  piOfflineMin: 5,
  humidifierStuckMin: 30,
  heartbeatHour: 8,
  dashboardUrl: 'http://elder-plops-ts:8081/farmer',
  timezone: 'America/Toronto',
};

const T0 = 1000000; // base timestamp

function makeConfig(overrides = {}) {
  return { ...config, ...overrides };
}

// Helper: create an OOB humidity event
const oobEvent = { type: 'humidity', value: 83.0 };
// Helper: create an in-band humidity event
const inBandEvent = { type: 'humidity', value: 90.0 };

/**
 * Helper: get state to FIRING for RH alert.
 * Uses oobN=1 and oobWindowMin=0 to fire on first OOB event.
 */
function reachFiringRh(cfg = null) {
  const c = cfg || makeConfig({ oobN: 1, oobWindowMin: 0 });
  const st = initialState(T0);
  const r = transition(st, oobEvent, T0, c);
  return { state: r.next, config: c };
}

/**
 * Helper: get state to FIRING for RH alert using real oobN=5 and window.
 * Events are spaced 1 min apart so the 5th event satisfies the 3-min window.
 */
function reachFiringRhSlowDebounce() {
  let state = initialState(T0);
  const cfg = makeConfig();
  for (let i = 0; i < 5; i++) {
    const r = transition(state, oobEvent, T0 + i * 60000, cfg);
    state = r.next;
  }
  return { state, config: cfg };
}

describe('OOB debounce (ALRT-03)', () => {
  test('4 consecutive OOB events: PENDING, no send action', () => {
    let state = initialState(T0);
    // Events spaced 1 min apart; 4 events = window of 3min total, but oobN=5 not reached
    let allActions = [];
    for (let i = 0; i < 4; i++) {
      const r = transition(state, oobEvent, T0 + i * 60000, makeConfig());
      state = r.next;
      allActions = allActions.concat(r.actions);
    }
    expect(state.perType.rh.state).toBe(STATES.PENDING);
    expect(allActions.filter(a => a.kind === 'send')).toHaveLength(0);
  });

  test('5th OOB event AND window >= oobWindowMin: send action emitted', () => {
    const { state, allActions } = (() => {
      let s = initialState(T0);
      let acts = [];
      // Events spaced 1 min apart: first at T0, 5th at T0+4min (window=4min >= 3min, count=5)
      for (let i = 0; i < 5; i++) {
        const r = transition(s, oobEvent, T0 + i * 60000, makeConfig());
        s = r.next;
        acts = acts.concat(r.actions);
      }
      return { state: s, allActions: acts };
    })();
    expect(state.perType.rh.state).toBe(STATES.FIRING);
    const sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'rh');
    expect(sends).toHaveLength(1);
  });
});

describe('window gate', () => {
  test('5 OOB events within 30s (< 3min window): no send', () => {
    let state = initialState(T0);
    let allActions = [];
    // Events 2 seconds apart — total span 8s, well under 3min
    for (let i = 0; i < 5; i++) {
      const r = transition(state, oobEvent, T0 + i * 2000, makeConfig());
      state = r.next;
      allActions = allActions.concat(r.actions);
    }
    expect(allActions.filter(a => a.kind === 'send')).toHaveLength(0);
  });

  test('6th OOB event at 4min mark: send fires', () => {
    let state = initialState(T0);
    let allActions = [];
    // First 5 events within 30s (count reaches oobN but window too small)
    for (let i = 0; i < 5; i++) {
      const r = transition(state, oobEvent, T0 + i * 2000, makeConfig());
      state = r.next;
      allActions = allActions.concat(r.actions);
    }
    // 6th event at 4min mark — window now >= oobWindowMin, count >= oobN
    const r = transition(state, oobEvent, T0 + 4 * 60000, makeConfig());
    state = r.next;
    allActions = allActions.concat(r.actions);
    const sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'rh');
    expect(sends).toHaveLength(1);
  });
});

describe('recovery_exactly_once (ALRT-02 invariant, Pitfall 3)', () => {
  test('5 consecutive in-band after FIRING: exactly one recovery, no more', () => {
    // Get to FIRING using oobN=1, oobWindowMin=0 for simplicity
    const { state: firingState, config: cfg } = reachFiringRh();
    expect(firingState.perType.rh.state).toBe(STATES.FIRING);

    let state = firingState;
    let recoveries = [];
    // Feed 5 in-band events (oobN=1 means 1 in-band = recovery)
    for (let i = 0; i < 5; i++) {
      const r = transition(state, inBandEvent, T0 + 1000 + i * 1000, cfg);
      state = r.next;
      recoveries = recoveries.concat(r.actions.filter(a => a.kind === 'recovery'));
    }
    expect(recoveries).toHaveLength(1);
    expect(state.perType.rh.state).toBe(STATES.OK);

    // Further in-band events emit nothing
    for (let i = 0; i < 3; i++) {
      const r = transition(state, inBandEvent, T0 + 10000 + i * 1000, cfg);
      state = r.next;
      expect(r.actions.filter(a => a.kind === 'recovery')).toHaveLength(0);
    }
  });

  test('recovery with real oobN=5 requires 5 consecutive in-band events', () => {
    const { state: firingState, config: cfg } = reachFiringRhSlowDebounce();
    expect(firingState.perType.rh.state).toBe(STATES.FIRING);

    let state = firingState;
    let recoveries = [];
    for (let i = 0; i < 5; i++) {
      const r = transition(state, inBandEvent, T0 + 10 * 60000 + i * 1000, cfg);
      state = r.next;
      recoveries = recoveries.concat(r.actions.filter(a => a.kind === 'recovery'));
    }
    expect(recoveries).toHaveLength(1);
    expect(state.perType.rh.state).toBe(STATES.OK);
  });
});

describe('cooldown (ALRT-03)', () => {
  test('repeat send suppressed within cooldownMin; fires after cooldownMin', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, cooldownMin: 30 });
    const st = initialState(T0);

    // Fire immediately (oobN=1, oobWindowMin=0)
    const r1 = transition(st, oobEvent, T0, cfg);
    expect(r1.actions.filter(a => a.kind === 'send')).toHaveLength(1);

    // During cooldown: no repeat
    const r2 = transition(r1.next, oobEvent, T0 + 29 * 60000, cfg);
    expect(r2.actions.filter(a => a.kind === 'send')).toHaveLength(0);

    // After cooldown: repeat fires
    const r3 = transition(r2.next, oobEvent, T0 + 31 * 60000, cfg);
    expect(r3.actions.filter(a => a.kind === 'send')).toHaveLength(1);
  });
});

describe('severity cadences', () => {
  test('RH (WARN) repeats after cooldownMin (30min), not criticalCooldownMin (60min)', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, cooldownMin: 30, criticalCooldownMin: 60 });
    let state = initialState(T0);

    // Fire RH (WARN)
    const r1 = transition(state, oobEvent, T0, cfg);
    expect(r1.actions.filter(a => a.kind === 'send' && a.alertType === 'rh')).toHaveLength(1);
    state = r1.next;

    // At T0+31min, RH (WARN) repeats (cooldownMin=30 elapsed)
    const r2 = transition(state, oobEvent, T0 + 31 * 60000, cfg);
    expect(r2.actions.filter(a => a.kind === 'send' && a.alertType === 'rh')).toHaveLength(1);
  });
});

describe('warmup_suppresses_rh (ALRT-05)', () => {
  test('sensor_health level=1 suppresses OOB humidity events', () => {
    let state = initialState(T0);
    // Set warm-up
    const r1 = transition(state, { type: 'sensor_health', level: 1, message: 'warming up', values: {} }, T0, makeConfig());
    state = r1.next;
    expect(state.warmingUp).toBe(true);

    // 10 OOB events should produce zero RH send actions
    let allActions = [];
    for (let i = 0; i < 10; i++) {
      const r = transition(state, oobEvent, T0 + i * 60000, makeConfig());
      state = r.next;
      allActions = allActions.concat(r.actions);
    }
    expect(allActions.filter(a => a.kind === 'send' && a.alertType === 'rh')).toHaveLength(0);

    // After level=0, warmingUp clears
    const r2 = transition(state, { type: 'sensor_health', level: 0, message: 'ok', values: {} }, T0 + 60 * 60000, makeConfig());
    state = r2.next;
    expect(state.warmingUp).toBe(false);
  });
});

describe('warmup_suppresses_humidifier_stuck (ALRT-05)', () => {
  test('sensor_health level=1 suppresses humidifier stuck alerts', () => {
    // Use humidifierStuckMin=0 so stuck condition triggers immediately on any humidity event
    const cfg = makeConfig({ humidifierStuckMin: 0, oobN: 1, oobWindowMin: 0 });
    let state = initialState(T0);

    // Turn on humidifier
    let r = transition(state, { type: 'humidifier', value: 1 }, T0, cfg);
    state = r.next;

    // Set warm-up
    r = transition(state, { type: 'sensor_health', level: 1, message: 'warming up', values: {} }, T0 + 100, cfg);
    state = r.next;
    expect(state.warmingUp).toBe(true);

    // Feed humidity while in warm-up — humidifier is ON and stuck condition would fire without warmup
    let allActions = [];
    for (let i = 0; i < 5; i++) {
      r = transition(state, { type: 'humidity', value: 82 }, T0 + i * 1000 + 200, cfg);
      state = r.next;
      allActions = allActions.concat(r.actions);
    }
    expect(allActions.filter(a => a.kind === 'send' && a.alertType === 'humidifier')).toHaveLength(0);
  });
});

describe('warmup_does_NOT_suppress_sensor_error (ALRT-05)', () => {
  test('sensor_health level=2 fires even during warm-up', () => {
    let state = initialState(T0);

    // Set warm-up via level=1
    let r = transition(state, { type: 'sensor_health', level: 1, message: 'warming up', values: {} }, T0, makeConfig());
    state = r.next;
    expect(state.warmingUp).toBe(true);

    // sensor_health level=2 should still fire sensor ERROR
    r = transition(state, { type: 'sensor_health', level: 2, message: 'ERROR', values: {} }, T0 + 35000, makeConfig());
    const sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sensor');
    expect(sends).toHaveLength(1);
  });
});

describe('snooze_mutes_sends', () => {
  test('after snooze, FIRING state preserved but no sends until untilMs', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, cooldownMin: 30 });
    let state = initialState(T0);

    // Get to FIRING
    let r = transition(state, oobEvent, T0, cfg);
    state = r.next;
    expect(state.perType.rh.state).toBe(STATES.FIRING);

    // Snooze rh for 1 hour
    r = transition(state, { type: 'snooze', alertType: 'rh', untilMs: T0 + 3600000 }, T0 + 100, cfg);
    state = r.next;

    // OOB events during snooze (after cooldown would otherwise expire): no sends
    for (let i = 0; i < 3; i++) {
      r = transition(state, oobEvent, T0 + 31 * 60000 + i * 1000, cfg);
      state = r.next;
      expect(r.actions.filter(a => a.kind === 'send' && a.alertType === 'rh')).toHaveLength(0);
    }

    // State is still FIRING (snooze doesn't clear alert state)
    expect(state.perType.rh.state).toBe(STATES.FIRING);
  });
});

describe('snooze_all_does_NOT_mute_heartbeat', () => {
  test('snooze all does not suppress heartbeat_tick actions', () => {
    let state = initialState(T0);
    // Snooze all alert types
    let r = transition(state, { type: 'snooze', alertType: 'all', untilMs: T0 + 86400000 }, T0, makeConfig());
    state = r.next;

    // Force heartbeat to trigger by setting lastHeartbeatDay to a different day
    state.lastHeartbeatDay = '2000-01-01';
    // 2026-04-18T12:00:00Z = 8am EDT (America/Toronto, UTC-4)
    const now8am = new Date('2026-04-18T12:00:00Z').getTime();
    r = transition(state, {
      type: 'heartbeat_tick',
      summary: { rh: 90, temp: 22, co2: 800, humidifier: 'OFF', humidifierCycles: 0, piLastSeenSec: 5 },
    }, now8am, makeConfig());
    const heartbeats = r.actions.filter(a => a.kind === 'heartbeat');
    expect(heartbeats).toHaveLength(1);
  });
});

describe('startup_grace', () => {
  test('Pi-offline not fired in first 60s after boot', () => {
    const bootNow = T0;
    // piOfflineMin=0 so that without the grace, it would fire immediately
    const cfg = makeConfig({ piOfflineMin: 0 });
    let state = initialState(bootNow);

    // Pi liveness: wsConnected=false, within 60s of boot
    const r = transition(state, {
      type: 'pi_liveness',
      wsConnected: false,
      rosConnected: false,
      humidifierLastMsgTs: null,
    }, bootNow + 30000, cfg);
    const sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'pi');
    expect(sends).toHaveLength(0);
  });
});

describe('temperature_store_only', () => {
  test('temperature event sets currentTemp with zero actions', () => {
    const st = initialState(T0);
    const { next, actions } = transition(st, { type: 'temperature', value: 23.4 }, T0, makeConfig());
    expect(next.currentTemp).toBe(23.4);
    expect(actions).toHaveLength(0);
  });
});

describe('co2_store_only', () => {
  test('co2 event sets currentCo2 with zero actions', () => {
    const st = initialState(T0);
    const { next, actions } = transition(st, { type: 'co2', value: 812 }, T0, makeConfig());
    expect(next.currentCo2).toBe(812);
    expect(actions).toHaveLength(0);
  });
});

describe('humidifier_cycle_counting', () => {
  test('three 0->1 transitions within 24h result in humidifierCyclesLast24h === 3', () => {
    let state = initialState(T0);

    // Cycle 1: off -> on -> off
    let r = transition(state, { type: 'humidifier', value: 1 }, T0, makeConfig());
    state = r.next;
    r = transition(state, { type: 'humidifier', value: 0 }, T0 + 60000, makeConfig());
    state = r.next;

    // Cycle 2
    r = transition(state, { type: 'humidifier', value: 1 }, T0 + 120000, makeConfig());
    state = r.next;
    r = transition(state, { type: 'humidifier', value: 0 }, T0 + 180000, makeConfig());
    state = r.next;

    // Cycle 3
    r = transition(state, { type: 'humidifier', value: 1 }, T0 + 240000, makeConfig());
    state = r.next;

    expect(state.humidifierCyclesLast24h).toBe(3);
  });
});
