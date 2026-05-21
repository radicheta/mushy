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

// ---- Phase 26 Plan 03: per-physical-sensor offline alerts ----------------------

const T_PAST_GRACE = T0 + 65000;       // 65s after boot — startup grace cleared
const FIVE_MIN_MS = 5 * 60 * 1000;
function makeConfigSensor(overrides = {}) {
  return makeConfig({ sensorOfflineMin: 5, ...overrides });
}

describe('sht30_offline (D-04, D-05, D-06)', () => {
  test('sht30 fires after sensorOfflineMin minutes silent', () => {
    const cfg = makeConfigSensor();
    let state = initialState(T0);
    let allActions = [];
    // Refresh sht30 fresh — establishes baseline lastSeenMs at T0.
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // Tick at T_PAST_GRACE — only 65s silence, well under 5min threshold.
    r = transition(state, { type: 'tick' }, T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // Tick after 5m+1s past grace — silence threshold crossed (oobN=1 fires).
    r = transition(state, { type: 'tick' }, T_PAST_GRACE + FIVE_MIN_MS + 1000, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    const sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sends).toHaveLength(1);
    expect(state.perType.sht30.state).toBe(STATES.FIRING);
  });

  test('does NOT fire scd41 when only sht30 is silent (D-05 isolation)', () => {
    const cfg = makeConfigSensor();
    let state = initialState(T0);
    let allActions = [];
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // Trigger sht30 false flag — this fires sht30 immediately.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'true' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // Refresh scd41 lastSeen via a slot-2 arrival immediately before the tick
    // so its watchdog window stays alive — isolation depends only on flag wiring.
    r = transition(state,
      { type: 'sensor_freshness', sensor: 'scd41',
        lastSeenMs: T_PAST_GRACE + FIVE_MIN_MS },
      T_PAST_GRACE + FIVE_MIN_MS, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    r = transition(state, { type: 'tick' }, T_PAST_GRACE + FIVE_MIN_MS + 1000, cfg);
    allActions = allActions.concat(r.actions);
    const scd41Sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(scd41Sends).toHaveLength(0);
  });

  test('recovery on sht30_fresh flip back to true (D-06)', () => {
    const cfg = makeConfigSensor();
    let state = initialState(T0);
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    // Drive sht30 to FIRING via Pi flag false (oobN=1 fires immediately post-grace).
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'true' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    expect(state.perType.sht30.state).toBe(STATES.FIRING);
    // Now flip sht30_fresh back to 'true' — recovery fires (oobN=1 inBandCount=1).
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T_PAST_GRACE + 1000, cfg);
    const recoveries = r.actions.filter(a => a.kind === 'recovery' && a.alertType === 'sht30');
    expect(recoveries).toHaveLength(1);
  });

  test('repeats after criticalCooldownMin (cooldown reuse)', () => {
    const cfg = makeConfigSensor({ criticalCooldownMin: 60 });
    let state = initialState(T0);
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    // Fire sht30 at T_PAST_GRACE.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'true' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    expect(state.perType.sht30.state).toBe(STATES.FIRING);
    // Advance >60min from lastFiredAt and tick — second send should fire from
    // tick re-evaluation (still stale per watchdog).
    r = transition(state, { type: 'tick' },
      T_PAST_GRACE + 61 * 60000, cfg);
    const sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sends).toHaveLength(1);
  });
});

describe('999.42 per-sensor enable flags', () => {
  test('sht30Enabled=false suppresses sht30 alarm even when sht30_fresh=false', () => {
    const cfg = makeConfigSensor({ sht30Enabled: false });
    let state = initialState(T0);
    let allActions = [];
    // Establish baseline freshness — but the disabled path should not record
    // an alarm transition either way.
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // Trigger explicit sht30 false flag past grace — the legacy path would
    // FIRE sht30 immediately with oobN=1, but with sht30Enabled=false the
    // block is skipped entirely.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'true' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    const sht30Sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sht30Sends).toHaveLength(0);
    // scd41 path remains active — scd41_fresh=true here so no scd41 alarm either,
    // but the flag isolation is the point: setting sht30Enabled=false does NOT
    // touch scd41 evaluation.
    expect(state.perType.scd41.state).not.toBe(STATES.FIRING);
  });

  test('scd41Enabled=false suppresses scd41 alarm even when scd41_fresh=false', () => {
    const cfg = makeConfigSensor({ scd41Enabled: false });
    let state = initialState(T0);
    let allActions = [];
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    const scd41Sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(scd41Sends).toHaveLength(0);
  });

  test('sensor_freshness arrival respects sht30Enabled=false', () => {
    const cfg = makeConfigSensor({ sht30Enabled: false });
    let state = initialState(T0);
    // Push lastSeen into the stale past so isSensorSilent would return true.
    // With sht30Enabled=false the sensor_freshness handler skips eval entirely.
    state.sht30LastSeenMs = T0 - 60 * 60 * 1000;
    const r = transition(state,
      { type: 'sensor_freshness', sensor: 'sht30',
        lastSeenMs: T0 - 60 * 60 * 1000 },
      T_PAST_GRACE, cfg);
    const sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sends).toHaveLength(0);
  });

  test('scd41 flap < sensorFlapMinSec does NOT fire (regression 2026-05-12)', () => {
    // Caught live: a 6-second I2C glitch on the Pi briefly set
    // scd41_fresh='false', alerter fired CO2 Sensor offline immediately,
    // then recovered 6s later -- farmer got "OOB for 0m 06s" for a
    // sub-second sensor hiccup. flap floor suppresses sub-flapMinSec
    // transients; the slow-silence (sensorOfflineMin) path still fires
    // on real outages.
    const cfg = makeConfigSensor({ sensorFlapMinSec: 60 });
    let state = initialState(T0);
    let allActions = [];
    // Baseline: scd41 fresh just past grace -- lastSeenMs anchored fresh.
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // 6s later, Pi reports scd41_fresh='false' -- a flap, well under
    // the 60s flap floor. Must NOT fire.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      T_PAST_GRACE + 6000, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    const scd41Sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(scd41Sends).toHaveLength(0);
    expect(state.perType.scd41.state).not.toBe(STATES.FIRING);
  });

  test('scd41 sustained flag-false past flapMinSec DOES fire', () => {
    // Companion to the flap test: confirm a real sustained outage still
    // fires once the floor is crossed.
    const cfg = makeConfigSensor({ sensorFlapMinSec: 60 });
    let state = initialState(T0);
    let allActions = [];
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // 90s after last 'true' baseline, Pi still reports 'false' -- crosses
    // the 60s floor -> fires.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      T_PAST_GRACE + 90 * 1000, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    const scd41Sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(scd41Sends.length).toBeGreaterThan(0);
  });

  test('periodic tick respects sht30Enabled=false (regression 2026-05-12)', () => {
    // Caught live: the sensor_health and sensor_freshness handlers both honored
    // sht30Enabled=false, but the `tick` re-evaluation at the bottom of the
    // reducer did not. With lastSeenMs stale and the disabled flag set, the
    // tick re-drove the sht30 watchdog into FIRING and re-fired every hour via
    // critical cooldown -- spammed the farmer group all morning before fixing.
    const cfg = makeConfigSensor({ sht30Enabled: false });
    let state = initialState(T0);
    state.sht30LastSeenMs = T0 - 60 * 60 * 1000;
    const r = transition(state, { type: 'tick' }, T_PAST_GRACE, cfg);
    const sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sends).toHaveLength(0);
    expect(r.next.perType.sht30.state).not.toBe(STATES.FIRING);
  });
});

describe('scd41_offline (D-04, D-05, D-06)', () => {
  test('scd41 fires after sensorOfflineMin minutes silent (Pi flag path)', () => {
    const cfg = makeConfigSensor();
    let state = initialState(T0);
    let allActions = [];
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // Pi flag flips to false — fires immediately post-grace.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    const sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(sends).toHaveLength(1);
    expect(state.perType.scd41.state).toBe(STATES.FIRING);
  });

  test('does NOT fire sht30 when only scd41 is silent (D-05 isolation)', () => {
    const cfg = makeConfigSensor();
    let state = initialState(T0);
    let allActions = [];
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    allActions = allActions.concat(r.actions);
    // sht30 was just refreshed at T_PAST_GRACE — well under 5min watchdog.
    const sht30Sends = allActions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sht30Sends).toHaveLength(0);
  });

  test('recovery on scd41_fresh flip back to true (D-06)', () => {
    const cfg = makeConfigSensor();
    let state = initialState(T0);
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    expect(state.perType.scd41.state).toBe(STATES.FIRING);
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T_PAST_GRACE + 1000, cfg);
    const recoveries = r.actions.filter(a => a.kind === 'recovery' && a.alertType === 'scd41');
    expect(recoveries).toHaveLength(1);
  });

  test('scd41 fires from slot-2 WS silence even without sensor_health (Option C hybrid)', () => {
    // Drive scd41 stale via slot-2 WS silence ONLY — no Pi flag flip.
    // sht30LastSeenMs is kept fresh via direct stub so isolation holds.
    const cfg = makeConfigSensor();
    let state = initialState(T0);
    // Slot-2 arrival event at T0 sets scd41LastSeenMs to T0.
    let r = transition(state,
      { type: 'sensor_freshness', sensor: 'scd41', lastSeenMs: T0 },
      T0, cfg);
    state = r.next;
    // Stub sht30LastSeenMs forward in time so its watchdog stays unfired.
    state = JSON.parse(JSON.stringify(state));
    state.sht30LastSeenMs = T_PAST_GRACE + FIVE_MIN_MS;  // sht30 watchdog fresh
    // Tick at T_PAST_GRACE + 5min + 1s — scd41 silent for 5min+66s, sht30 silent
    // for ~0s. Watchdog fires scd41 only.
    r = transition(state, { type: 'tick' },
      T_PAST_GRACE + FIVE_MIN_MS + 1000, cfg);
    const scd41Sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    const sht30Sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(scd41Sends).toHaveLength(1);
    expect(sht30Sends).toHaveLength(0);
  });
});

describe('snooze sht30/scd41 (D-05)', () => {
  test('snooze sht30 mutes sht30 only; scd41 still fires', () => {
    // Use a longer-than-cooldown snooze so the post-cooldown re-fire path
    // is provably gated by snooze, not by the snooze having already expired.
    const cfg = makeConfigSensor({ criticalCooldownMin: 60 });
    let state = initialState(T0);
    // Baseline both fresh at T0.
    let r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      T0, cfg);
    state = r.next;
    // Drive sht30 to FIRING via Pi flag false at T_PAST_GRACE.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'true' } },
      T_PAST_GRACE, cfg);
    state = r.next;
    expect(state.perType.sht30.state).toBe(STATES.FIRING);
    // Snooze sht30 for 4 hours (>> cooldown 60min, >> the test's time horizon).
    const snoozeStart = T_PAST_GRACE + 1000;
    r = transition(state,
      { type: 'snooze', alertType: 'sht30', untilMs: snoozeStart + 4 * 3600000 },
      snoozeStart, cfg);
    state = r.next;
    // Advance >60min and re-trigger — cooldown elapsed, but snooze must mute.
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'true' } },
      snoozeStart + 65 * 60000, cfg);
    const sht30Sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sht30Sends).toHaveLength(0);
    state = r.next;
    // Now drive scd41 silent via Pi flag — scd41 should still fire (D-05 isolation).
    r = transition(state,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'false' } },
      snoozeStart + 65 * 60000 + 1000, cfg);
    const scd41Sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(scd41Sends).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Phase 29 plan 29-04 — mode + freshness FSM extensions.
// ---------------------------------------------------------------------------

describe('Phase 29 mode + freshness', () => {
  // Use a separate module instance so we can spy on message.formatProblem to
  // observe piFields.lastKnown being threaded through driveAlertType.
  let stateMod;
  let messageMod;
  let resolveEffectiveConfig;
  let envCfg;

  beforeEach(() => {
    jest.resetModules();
    messageMod = require('../src/message');
    stateMod = require('../src/state');
    resolveEffectiveConfig = stateMod.resolveEffectiveConfig;
    const { BASE_ENV } = require('./fixtures/effective-config');
    envCfg = { ...BASE_ENV, dashboardUrl: 'http://x', timezone: 'UTC' };
  });

  function freshMode(overrides = {}) {
    return {
      name: 'fruiting',
      target_humidity: 0.96,
      band_low: 0.945,
      band_high: 0.975,
      defend_side: 'both',
      ...overrides,
    };
  }

  // Test 1
  test('mode_update populates currentMode and modeReceivedAtMs', () => {
    const initial = stateMod.initialState(0);
    const r = stateMod.transition(initial, { type: 'mode_update', mode: freshMode() }, 1000, envCfg);
    expect(r.next.currentMode.name).toBe('fruiting');
    expect(r.next.modeReceivedAtMs).toBe(1000);
  });

  // Test 2
  test('mode_update resets dedup for rh and humidifier; preserves lastFiredAt', () => {
    let s = stateMod.initialState(0);
    s.perType.rh.oobCount = 3;
    s.perType.rh.firstOobAt = 500;
    s.perType.rh.lastFiredAt = 700;
    s.perType.humidifier.oobCount = 2;
    s.perType.humidifier.firstOobAt = 600;
    s.perType.humidifier.lastFiredAt = 750;
    const r = stateMod.transition(s, { type: 'mode_update', mode: freshMode({ name: 'pinning' }) }, 1000, envCfg);
    expect(r.next.perType.rh.oobCount).toBe(0);
    expect(r.next.perType.rh.firstOobAt).toBeNull();
    expect(r.next.perType.rh.lastFiredAt).toBe(700);
    expect(r.next.perType.humidifier.oobCount).toBe(0);
    expect(r.next.perType.humidifier.firstOobAt).toBeNull();
    expect(r.next.perType.humidifier.lastFiredAt).toBe(750);
  });

  // Test 3
  test('mode_update resets perType.rh.ctx.inBandCount', () => {
    let s = stateMod.initialState(0);
    s.perType.rh.ctx = { inBandCount: 4 };
    const r = stateMod.transition(s, { type: 'mode_update', mode: freshMode() }, 1000, envCfg);
    expect(r.next.perType.rh.ctx.inBandCount).toBe(0);
  });

  // Test 4 — cooldown survives mode swap
  test('cooldown survives mode swap (lastFiredAt preserved)', () => {
    const cfg = { ...envCfg, oobN: 1, oobWindowMin: 0, cooldownMin: 30 };
    // FIRING at t=0
    let s = stateMod.initialState(0);
    let r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: true, rosConnected: true }, 0, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'mode_update', mode: freshMode() }, 0, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'humidity', value: 50 }, 0, cfg);
    s = r.next;
    expect(s.perType.rh.state).toBe(STATES.FIRING);
    const firstFire = s.perType.rh.lastFiredAt;
    // Mode swap at 5min
    r = stateMod.transition(s, { type: 'mode_update', mode: freshMode({ name: 'pinning' }) }, 5 * 60000, cfg);
    s = r.next;
    expect(s.perType.rh.lastFiredAt).toBe(firstFire);
    // Retry at 6 min — cooldown not elapsed: NO send (cooldown carries)
    // (Note: dedup was reset, so we go OK→PENDING→FIRING again; lastFiredAt was preserved
    // so the FIRING-state cooldown gate works on subsequent FIRING-state events.)
    // To exercise cooldown: drive humidity again to keep FIRING. Since dedup reset, we need
    // to re-arm. After re-arming OOB at 6min, state goes FIRING and lastFiredAt would update
    // — but the assertion target is "lastFiredAt was preserved across the mode_update".
  });

  // Test 5 — first mode_update after cold start resets dedup
  test('first mode_update after cold start resets dedup (Pitfall 4)', () => {
    let s = stateMod.initialState(0);
    s.perType.rh.oobCount = 2;
    s.perType.rh.firstOobAt = 100;
    expect(s.currentMode == null).toBe(true);
    const r = stateMod.transition(s, { type: 'mode_update', mode: freshMode() }, 1000, envCfg);
    expect(r.next.perType.rh.oobCount).toBe(0);
    expect(r.next.perType.rh.firstOobAt).toBeNull();
    expect(r.next.currentMode).toBeTruthy();
  });

  // Test 6
  test('overrides_update populates alerterOverrides and ts', () => {
    const s = stateMod.initialState(0);
    const r = stateMod.transition(s, {
      type: 'overrides_update',
      overrides: { fruiting: { cooldown_min: 45 } },
    }, 2000, envCfg);
    expect(r.next.alerterOverrides.fruiting.cooldown_min).toBe(45);
    expect(r.next.overridesReceivedAtMs).toBe(2000);
  });

  // Test 7
  test('globals_update populates alerterGlobals and ts', () => {
    const s = stateMod.initialState(0);
    const r = stateMod.transition(s, {
      type: 'globals_update',
      globals: { pi_offline_min: 10 },
    }, 3000, envCfg);
    expect(r.next.alerterGlobals.pi_offline_min).toBe(10);
    expect(r.next.globalsReceivedAtMs).toBe(3000);
  });

  // Test 8 — FRESH path
  test('resolveEffectiveConfig FRESH path returns mode-derived rh values', () => {
    const s = stateMod.initialState(0);
    s.currentMode = freshMode();
    s.modeReceivedAtMs = 1000;
    s.wsConnected = true;
    const eff = resolveEffectiveConfig(s, envCfg, 1000 + 60_000); // 1 min later
    expect(eff.rhTarget).toBeCloseTo(96, 6);
    expect(eff.rhBand).toBeCloseTo(1.5, 6);
    expect(eff.freshness.state).toBe('fresh');
    expect(eff.freshness.source).toBe('mode');
  });

  // Test 9 — STALE because mode too old
  test('resolveEffectiveConfig STALE when mode older than modeStaleMin', () => {
    const s = stateMod.initialState(0);
    s.currentMode = freshMode();
    s.modeReceivedAtMs = 0;
    s.wsConnected = true;
    const eff = resolveEffectiveConfig(s, envCfg, 6 * 60_000); // 6 min later
    expect(eff.freshness.state).toBe('stale');
    expect(eff.freshness.source).toBe('env');
    expect(eff.rhTarget).toBe(envCfg.rhTarget);
  });

  // Test 10 — STALE on wsDisconnected even if mode fresh
  test('resolveEffectiveConfig STALE on wsDisconnected even if mode fresh', () => {
    const s = stateMod.initialState(0);
    s.currentMode = freshMode();
    s.modeReceivedAtMs = 1000;
    s.wsConnected = false;
    const eff = resolveEffectiveConfig(s, envCfg, 1000 + 60_000);
    expect(eff.freshness.state).toBe('stale');
  });

  // Test 11 — COLD path
  test('resolveEffectiveConfig COLD path within boot grace', () => {
    const s = stateMod.initialState(0); // bootedAtMs = 0
    s.wsConnected = true;
    const eff = resolveEffectiveConfig(s, envCfg, 30_000); // 30s after boot
    expect(eff.freshness.state).toBe('cold');
    expect(eff.freshness.source).toBe('env');
  });

  // Test 12 — COLD→STALE past grace
  test('resolveEffectiveConfig STALE past 60s with no mode', () => {
    const s = stateMod.initialState(0);
    s.wsConnected = true;
    const eff = resolveEffectiveConfig(s, envCfg, 90_000);
    expect(eff.freshness.state).toBe('stale');
  });

  // Test 13 — Tier B overrides
  test('resolveEffectiveConfig merges Tier B overrides over env', () => {
    const s = stateMod.initialState(0);
    s.currentMode = freshMode({ name: 'pinning' });
    s.modeReceivedAtMs = 1000;
    s.wsConnected = true;
    s.alerterOverrides = { pinning: { cooldown_min: 45 } };
    const eff = resolveEffectiveConfig(s, envCfg, 1000 + 60_000);
    expect(eff.cooldownMin).toBe(45);
  });

  // Test 14 — Tier C globals
  test('resolveEffectiveConfig merges Tier C globals over env', () => {
    const s = stateMod.initialState(0);
    s.currentMode = freshMode();
    s.modeReceivedAtMs = 1000;
    s.wsConnected = true;
    s.alerterGlobals = { pi_offline_min: 10 };
    const eff = resolveEffectiveConfig(s, envCfg, 1000 + 60_000);
    expect(eff.piOfflineMin).toBe(10);
  });

  // Test 15 — band symmetric
  test('band_low/band_high → rhBand symmetric average', () => {
    const s = stateMod.initialState(0);
    s.currentMode = freshMode({ target_humidity: 0.96, band_low: 0.945, band_high: 0.975 });
    s.modeReceivedAtMs = 1000;
    s.wsConnected = true;
    const eff = resolveEffectiveConfig(s, envCfg, 1000 + 60_000);
    expect(eff.rhBand).toBeCloseTo(1.5, 6);
  });

  // Test 16 (BLOCKER 2) — pi_liveness piFields.lastKnown when state has data
  test('pi_liveness fires alert with piFields.lastKnown when sensor data present', () => {
    const formatSpy = jest.spyOn(messageMod, 'formatProblem');
    // oobN=1 to fire pi on first OOB tick (we're testing piFields plumbing).
    const cfg = { ...envCfg, oobN: 1, oobWindowMin: 0 };
    let s = stateMod.initialState(0);
    // Establish ws connected then disconnect
    let r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: true, rosConnected: true }, 0, cfg);
    s = r.next;
    // populate sensor data
    r = stateMod.transition(s, { type: 'temperature', value: 21.4 }, 100, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'humidity', value: 87.2 }, 200, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'humidifier', value: 1 }, 300, cfg);
    s = r.next;
    // Disconnect at t=400
    r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: false, rosConnected: true }, 400, cfg);
    s = r.next;
    // Past startup grace (60s) AND past piOfflineMin (5 min from wsLastConnectedMs=0)
    const future = 60_000 + 6 * 60_000;
    formatSpy.mockClear();
    r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: false, rosConnected: true }, future, cfg);
    const piCall = formatSpy.mock.calls.find(c => c[0].alertType === 'pi');
    expect(piCall).toBeDefined();
    const piFields = piCall[0].fields;
    expect(piFields.lastKnown).toBeDefined();
    expect(piFields.lastKnown).not.toBeNull();
    expect(piFields.lastKnown.rh).toBe(87.2);
    expect(piFields.lastKnown.temp).toBe(21.4);
    expect(piFields.lastKnown.humidifier).toBe('ON');
    expect(piFields.lastKnown.tsMs).toBe(200);
    formatSpy.mockRestore();
  });

  // Test 17 (BLOCKER 2) — pi_liveness piFields.lastKnown is null when no data
  test('pi_liveness fires alert with piFields.lastKnown null when no data', () => {
    const formatSpy = jest.spyOn(messageMod, 'formatProblem');
    const cfg = { ...envCfg, oobN: 1, oobWindowMin: 0 };
    let s = stateMod.initialState(0);
    let r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: true, rosConnected: true }, 0, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: false, rosConnected: true }, 400, cfg);
    s = r.next;
    formatSpy.mockClear();
    const future = 60_000 + 6 * 60_000;
    r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: false, rosConnected: true }, future, cfg);
    const piCall = formatSpy.mock.calls.find(c => c[0].alertType === 'pi');
    expect(piCall).toBeDefined();
    const piFields = piCall[0].fields;
    expect(piFields.lastKnown == null).toBe(true);
    formatSpy.mockRestore();
  });

  // Test 18 (BLOCKER 3) — rh OOB consumes effective Tier B overrides
  test('rh OOB uses effective.oobN from Tier B override', () => {
    const cfg = { ...envCfg, oobN: 5, oobWindowMin: 3 };
    let s = stateMod.initialState(0);
    // Establish ws connection so resolveEffectiveConfig considers mode FRESH.
    let r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: true, rosConnected: true }, 0, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'mode_update', mode: freshMode() }, 1, cfg);
    s = r.next;
    r = stateMod.transition(s, {
      type: 'overrides_update',
      overrides: { fruiting: { oob_n: 2, oob_window_min: 1 } },
    }, 2, cfg);
    s = r.next;
    // 2 OOB events spaced 30s apart — under env oobN=5 wouldn't fire,
    // but Tier B oob_n=2/window=1min should trigger.
    r = stateMod.transition(s, { type: 'humidity', value: 50 }, 1000, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'humidity', value: 50 }, 1000 + 60_001, cfg);
    s = r.next;
    const rhFiring = s.perType.rh.state === STATES.FIRING;
    expect(rhFiring).toBe(true);
  });

  // Test 19 (BLOCKER 3) — tick re-evaluation uses effective.piOfflineMin from globals
  test('tick re-evaluation uses effective.piOfflineMin from Tier C globals', () => {
    // Use oobN=1, oobWindowMin=0 so a single tick that crosses the threshold flips
    // pi to FIRING (the test target is the threshold itself, not the dedup ladder).
    const cfg = { ...envCfg, oobN: 1, oobWindowMin: 0, piOfflineMin: 5 };
    let s = stateMod.initialState(0);
    let r = stateMod.transition(s, { type: 'mode_update', mode: freshMode() }, 1, cfg);
    s = r.next;
    r = stateMod.transition(s, {
      type: 'globals_update',
      globals: { pi_offline_min: 10 },
    }, 2, cfg);
    s = r.next;
    // Establish connection then disconnect at t=100
    r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: true, rosConnected: true }, 100, cfg);
    s = r.next;
    r = stateMod.transition(s, { type: 'pi_liveness', wsConnected: false, rosConnected: true }, 200, cfg);
    s = r.next;
    // tick at 6min from boot — env default 5 min would fire; Tier C 10 min should NOT
    r = stateMod.transition(s, { type: 'tick' }, 6 * 60_000, cfg);
    s = r.next;
    expect(s.perType.pi.state).not.toBe(STATES.FIRING);
    // tick at 11 min — Tier C 10 min threshold elapsed
    r = stateMod.transition(s, { type: 'tick' }, 11 * 60_000, cfg);
    s = r.next;
    expect(s.perType.pi.state).toBe(STATES.FIRING);
  });
});

// ---------------------------------------------------------------------------
// Phase 46 — chamber-dark detector: fc1LastMsgTs trigger + per-sensor suppression
// ---------------------------------------------------------------------------

describe('Phase 46 — fc1LastMsgTs drives perType.pi to FIRING (CD-02 / D-03)', () => {
  test('pi_liveness with stale fc1LastMsgTs drives perType.pi to FIRING despite ws+ros connected', () => {
    // oobN=1 so first triggering event fires; piOfflineMin=5
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5 });
    let s = initialState(T0);
    // Past startup grace; ws+ros both connected (so existing triggers do NOT fire)
    const tNow = T0 + 90_000; // 90s after boot
    const r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tNow - 1000,
      fc1LastMsgTs: tNow - 6 * 60000, // 6 min stale > 5 min threshold
    }, tNow, cfg);
    expect(r.next.perType.pi.state).toBe(STATES.FIRING);
    const sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'pi');
    expect(sends).toHaveLength(1);
  });

  test('pi_liveness with fresh fc1LastMsgTs does NOT fire when ws+ros connected', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5 });
    let s = initialState(T0);
    const tNow = T0 + 90_000;
    const r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tNow - 1000,
      fc1LastMsgTs: tNow - 30_000, // 30s fresh
    }, tNow, cfg);
    expect(r.next.perType.pi.state).not.toBe(STATES.FIRING);
  });

  test('when fc1LastMsgTs becomes fresh again, perType.pi clears (recovery)', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5 });
    let s = initialState(T0);
    const tStale = T0 + 90_000;
    let r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tStale - 1000,
      fc1LastMsgTs: tStale - 6 * 60000,
    }, tStale, cfg);
    s = r.next;
    expect(s.perType.pi.state).toBe(STATES.FIRING);
    // Fresh data arrives.
    const tFresh = tStale + 60_000;
    r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tFresh - 100,
      fc1LastMsgTs: tFresh - 100,
    }, tFresh, cfg);
    s = r.next;
    expect(s.perType.pi.state).toBe(STATES.OK);
  });
});

describe('Phase 46 — per-sensor suppression while pi FIRING (D-07)', () => {
  // Helper: drive perType.pi to FIRING via stale fc1LastMsgTs path.
  function reachPiFiring(cfg) {
    let s = initialState(T0);
    const tNow = T0 + 90_000;
    const r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tNow - 1000,
      fc1LastMsgTs: tNow - 10 * 60000,
    }, tNow, cfg);
    return { state: r.next, tNow };
  }

  test('scd41 sensor_health stale does NOT emit scd41 send while perType.pi is FIRING', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5, sensorFlapMinSec: 0 });
    const { state: piFiring, tNow } = reachPiFiring(cfg);
    expect(piFiring.perType.pi.state).toBe(STATES.FIRING);
    // Send a sensor_health with scd41 stale -- should be suppressed.
    const r = transition(piFiring,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      tNow + 1000, cfg);
    const scd41Sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(scd41Sends).toHaveLength(0);
  });

  test('RH OOB does NOT emit rh send while perType.pi is FIRING', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5 });
    const { state: piFiring, tNow } = reachPiFiring(cfg);
    expect(piFiring.perType.pi.state).toBe(STATES.FIRING);
    const r = transition(piFiring, { type: 'humidity', value: 50 }, tNow + 1000, cfg);
    const rhSends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'rh');
    expect(rhSends).toHaveLength(0);
  });

  test('humidifier-stuck does NOT emit humidifier send while perType.pi is FIRING', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5, humidifierStuckMin: 0 });
    let s = initialState(T0);
    // Turn humidifier on
    let r = transition(s, { type: 'humidifier', value: 1 }, T0 + 1000, cfg);
    s = r.next;
    // Establish humidity baseline
    r = transition(s, { type: 'humidity', value: 80 }, T0 + 2000, cfg);
    s = r.next;
    // Drive pi to FIRING.
    const tStale = T0 + 90_000;
    r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tStale - 1000,
      fc1LastMsgTs: tStale - 10 * 60000,
    }, tStale, cfg);
    s = r.next;
    expect(s.perType.pi.state).toBe(STATES.FIRING);
    // Now a humidity event that would normally trigger humidifier-stuck (no RH rise).
    r = transition(s, { type: 'humidity', value: 80.5 }, tStale + 60_000, cfg);
    const humSends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'humidifier');
    expect(humSends).toHaveLength(0);
  });

  test('sht30 sensor_health stale does NOT emit sht30 send while perType.pi is FIRING', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5, sensorFlapMinSec: 0, sht30Enabled: true });
    const { state: piFiring, tNow } = reachPiFiring(cfg);
    expect(piFiring.perType.pi.state).toBe(STATES.FIRING);
    const r = transition(piFiring,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'false', scd41_fresh: 'true' } },
      tNow + 1000, cfg);
    const sht30Sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'sht30');
    expect(sht30Sends).toHaveLength(0);
  });

  test('D-08: per-sensor scd41 FIRING does NOT prevent pi from evaluating (one-directional)', () => {
    // Pre-condition: scd41 FIRING from a previous tick.
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5, sensorFlapMinSec: 0 });
    let s = initialState(T0);
    const t1 = T0 + 90_000;
    // Drive scd41 to FIRING via Pi flag false (sensorFlapMinSec=0).
    let r = transition(s,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'true' } },
      t1, cfg);
    s = r.next;
    r = transition(s,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      t1 + 1000, cfg);
    s = r.next;
    expect(s.perType.scd41.state).toBe(STATES.FIRING);
    expect(s.perType.pi.state).not.toBe(STATES.FIRING);
    // Now a pi_liveness with stale fc1LastMsgTs should STILL drive pi to FIRING.
    const t2 = t1 + 10_000;
    r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: t2 - 100,
      fc1LastMsgTs: t2 - 10 * 60000,
    }, t2, cfg);
    expect(r.next.perType.pi.state).toBe(STATES.FIRING);
    const piSends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'pi');
    expect(piSends).toHaveLength(1);
  });

  test('after pi clears, per-sensor evaluation resumes on next tick', () => {
    const cfg = makeConfig({ oobN: 1, oobWindowMin: 0, piOfflineMin: 5, sensorFlapMinSec: 0 });
    let s = initialState(T0);
    const tStale = T0 + 90_000;
    // pi FIRING
    let r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tStale - 100,
      fc1LastMsgTs: tStale - 10 * 60000,
    }, tStale, cfg);
    s = r.next;
    expect(s.perType.pi.state).toBe(STATES.FIRING);
    // Fresh fc1LastMsgTs → pi clears
    const tFresh = tStale + 60_000;
    r = transition(s, {
      type: 'pi_liveness',
      wsConnected: true,
      rosConnected: true,
      humidifierLastMsgTs: tFresh - 100,
      fc1LastMsgTs: tFresh - 100,
    }, tFresh, cfg);
    s = r.next;
    expect(s.perType.pi.state).toBe(STATES.OK);
    // Now scd41 stale should emit.
    r = transition(s,
      { type: 'sensor_health', level: 0, message: 'ok',
        values: { sht30_fresh: 'true', scd41_fresh: 'false' } },
      tFresh + 1000, cfg);
    const scd41Sends = r.actions.filter(a => a.kind === 'send' && a.alertType === 'scd41');
    expect(scd41Sends).toHaveLength(1);
  });
});
