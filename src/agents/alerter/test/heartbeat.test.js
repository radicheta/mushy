'use strict';

const { createHeartbeatScheduler } = require('../src/heartbeat');

// Helper: build a Date object at a specific local time in a timezone,
// returned as a UTC ms timestamp that Intl.DateTimeFormat will resolve back
// to that local time.
// We create the Date by constructing it in UTC and adjusting so that
// Intl.DateTimeFormat in the given timezone renders the desired time.
function makeClockAt({ year, month, day, hour, tz }) {
  // Use a known UTC offset by trying different offsets until Intl resolves correctly.
  // Simpler approach: format from a target ISO string and find the UTC ms.
  // We'll use the Date constructor with a known UTC string and verify via Intl.
  // Actually, the easiest approach: create a Date string with the local time and
  // parse using Intl to verify it matches — but we need the UTC ms value.
  //
  // Simple approach: iterate from a reference point. Since we're just making tests,
  // we'll construct the approximate UTC time and use the Intl formatter to get the
  // actual local hour, adjusting until it matches.
  //
  // Toronto EDT = UTC-4, EST = UTC-5. For testing, assume EDT (summer).
  // April 2024 = EDT = UTC-4.
  // So local 8:00 Toronto = UTC 12:00.
  const utcOffset = tz === 'America/Toronto' ? -4 : 0;
  const utcHour = (hour - utcOffset + 24) % 24;
  // Build ISO string
  const monthStr = String(month).padStart(2, '0');
  const dayStr = String(day).padStart(2, '0');
  const hourStr = String(utcHour).padStart(2, '0');
  return new Date(`${year}-${monthStr}-${dayStr}T${hourStr}:00:00Z`).getTime();
}

describe('createHeartbeatScheduler', () => {
  let dispatched;
  let getSummaryCalls;
  const SUMMARY = { rh: 90, temp: 22, co2: 800, humidifier: 'OFF', humidifierCycles: 2, piLastSeenSec: 5 };

  const baseConfig = {
    heartbeatHour: 8,
    timezone: 'America/Toronto',
  };

  const silentLogger = { info: () => {}, warn: () => {}, error: () => {} };

  beforeEach(() => {
    dispatched = [];
    getSummaryCalls = 0;
  });

  test('Test A: dispatches heartbeat_tick exactly once at configured hour', () => {
    // 8:00 EDT = UTC 12:00 on 2024-04-18
    const clockMs = makeClockAt({ year: 2024, month: 4, day: 18, hour: 8, tz: 'America/Toronto' });
    const clock = () => clockMs;

    const scheduler = createHeartbeatScheduler({
      config: baseConfig,
      getSummary: () => { getSummaryCalls++; return SUMMARY; },
      dispatch: (e) => dispatched.push(e),
      intervalMs: 999999, // don't fire interval
      clock,
      logger: silentLogger,
    });

    scheduler.start();
    scheduler.stop();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].type).toBe('heartbeat_tick');
    expect(dispatched[0].summary).toEqual(SUMMARY);
  });

  test('Test B: no second dispatch on same day if already fired', () => {
    // First tick at 8:00, second tick at 8:05 same day
    let callCount = 0;
    const times = [
      makeClockAt({ year: 2024, month: 4, day: 18, hour: 8, tz: 'America/Toronto' }),  // 8:00
      makeClockAt({ year: 2024, month: 4, day: 18, hour: 8, tz: 'America/Toronto' }) + 5 * 60000, // 8:05
    ];
    const clock = () => times[Math.min(callCount++, times.length - 1)];

    const scheduler = createHeartbeatScheduler({
      config: baseConfig,
      getSummary: () => SUMMARY,
      dispatch: (e) => dispatched.push(e),
      intervalMs: 999999,
      clock,
      logger: silentLogger,
    });

    // Manually call tick twice by using start (first tick) + calling internal tick again
    // We can test by using a very short interval and jest fake timers approach,
    // but the plan says to test directly. Let's create two schedulers simulating two ticks:
    scheduler.start();
    scheduler.stop();
    // Now simulate a second tick by creating another scheduler that starts at 8:05
    // but has the same "last fired day" — we do this by running start/stop twice
    // on the SAME scheduler instance.
    // Actually we need to test the same instance fires only once.
    // The scheduler stores lastFiredDay internally. After start(), tick() ran once.
    // We can't call tick() again externally. Let's test via a very short intervalMs + fake timers.

    // Re-do: use jest fake timers
    jest.useFakeTimers();
    dispatched = [];
    callCount = 0;
    const clock2 = () => times[Math.min(callCount++, times.length - 1)];
    const scheduler2 = createHeartbeatScheduler({
      config: baseConfig,
      getSummary: () => SUMMARY,
      dispatch: (e) => dispatched.push(e),
      intervalMs: 100,
      clock: clock2,
      logger: silentLogger,
    });
    scheduler2.start();
    // Advance past one interval — second tick should not fire
    jest.advanceTimersByTime(200);
    scheduler2.stop();
    jest.useRealTimers();

    expect(dispatched).toHaveLength(1); // still only 1
  });

  test('Test C: no dispatch before configured hour (7:59)', () => {
    const clockMs = makeClockAt({ year: 2024, month: 4, day: 18, hour: 7, tz: 'America/Toronto' }) + 59 * 60000; // 7:59
    const clock = () => clockMs;

    const scheduler = createHeartbeatScheduler({
      config: baseConfig,
      getSummary: () => SUMMARY,
      dispatch: (e) => dispatched.push(e),
      intervalMs: 999999,
      clock,
      logger: silentLogger,
    });

    scheduler.start();
    scheduler.stop();

    expect(dispatched).toHaveLength(0);
  });

  test('Test D: next-day rollover triggers new dispatch', () => {
    jest.useFakeTimers();

    let dayOffset = 0;
    // Day 0 tick at 8:00, day 1 tick at 8:00
    const day0Clock = makeClockAt({ year: 2024, month: 4, day: 18, hour: 8, tz: 'America/Toronto' });
    const day1Clock = makeClockAt({ year: 2024, month: 4, day: 19, hour: 8, tz: 'America/Toronto' });
    let tickIndex = 0;
    const times = [day0Clock, day1Clock];
    const clock = () => {
      const t = times[Math.min(tickIndex, times.length - 1)];
      return t;
    };

    const scheduler = createHeartbeatScheduler({
      config: baseConfig,
      getSummary: () => SUMMARY,
      dispatch: (e) => dispatched.push(e),
      intervalMs: 100,
      clock,
      logger: silentLogger,
    });

    scheduler.start(); // first tick at day0 8:00 → dispatches
    expect(dispatched).toHaveLength(1);

    tickIndex = 1; // next ticks will use day1Clock
    jest.advanceTimersByTime(150); // triggers the interval tick
    scheduler.stop();
    jest.useRealTimers();

    expect(dispatched).toHaveLength(2);
    expect(dispatched[1].type).toBe('heartbeat_tick');
  });

  test('Test E: getSummary() is called on each dispatch and result forwarded', () => {
    const summaries = [
      { rh: 90, temp: 22 },
      { rh: 91, temp: 23 },
    ];
    let callCount = 0;
    const clockMs = makeClockAt({ year: 2024, month: 4, day: 18, hour: 8, tz: 'America/Toronto' });

    const scheduler = createHeartbeatScheduler({
      config: baseConfig,
      getSummary: () => summaries[callCount++],
      dispatch: (e) => dispatched.push(e),
      intervalMs: 999999,
      clock: () => clockMs,
      logger: silentLogger,
    });

    scheduler.start();
    scheduler.stop();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].summary).toEqual(summaries[0]);
    expect(callCount).toBe(1);
  });

  test('Test F: defers firing when summary has no rh/temp/co2 (post-boot race)', () => {
    // Heartbeat hour reached, but bridge hasn't replayed any samples yet —
    // summary fields are all null. Scheduler must NOT dispatch and must NOT
    // burn the day's slot; next tick retries.
    jest.useFakeTimers();
    const clockMs = makeClockAt({ year: 2024, month: 4, day: 18, hour: 8, tz: 'America/Toronto' });
    let callCount = 0;
    const summaries = [
      { rh: null, temp: null, co2: null, humidifier: 'OFF', humidifierCycles: 0, piLastSeenSec: null },
      { rh: 90,   temp: 22,   co2: 800,  humidifier: 'OFF', humidifierCycles: 1, piLastSeenSec: 5    },
    ];

    const scheduler = createHeartbeatScheduler({
      config: baseConfig,
      getSummary: () => summaries[Math.min(callCount++, summaries.length - 1)],
      dispatch: (e) => dispatched.push(e),
      intervalMs: 100,
      clock: () => clockMs,
      logger: silentLogger,
    });

    scheduler.start(); // first tick: empty summary → defer
    expect(dispatched).toHaveLength(0);

    jest.advanceTimersByTime(150); // second tick: summary now has data → fire
    scheduler.stop();
    jest.useRealTimers();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].type).toBe('heartbeat_tick');
    expect(dispatched[0].summary.rh).toBe(90);
  });
});
