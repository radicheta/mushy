'use strict';

/**
 * createHeartbeatScheduler — daily heartbeat scheduler.
 *
 * Fires a {type:'heartbeat_tick', summary} event exactly once per local-TZ day
 * when clock() reaches or exceeds config.heartbeatHour. Uses Intl.DateTimeFormat
 * for TZ-aware hour/day extraction so the check is correct across DST transitions.
 *
 * @param {object} opts
 * @param {object} opts.config         - from config.load(); uses .heartbeatHour and .timezone
 * @param {Function} opts.getSummary   - () => summary object forwarded in the event
 * @param {Function} opts.dispatch     - (event) => void
 * @param {number} [opts.intervalMs]   - how often to check (default 15 min)
 * @param {Function} [opts.clock]      - () => nowMs (default Date.now)
 * @param {object} [opts.logger]       - logger with .info/.error
 * @returns {{ start: Function, stop: Function }}
 */
function createHeartbeatScheduler({
  config,
  getEffective,
  getSummary,
  dispatch,
  intervalMs = 15 * 60 * 1000,
  clock = Date.now,
  logger = console,
}) {
  let timer = null;
  let lastFiredDay = null;

  // Intl formatter for TZ-aware date+hour extraction.
  // 'en-CA' gives YYYY-MM-DD for date parts which is easy to use as a string key.
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: config.timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hour12: false,
  });

  function tick() {
    try {
      const nowMs = clock();
      const parts = Object.fromEntries(
        fmt.formatToParts(new Date(nowMs)).map((p) => [p.type, p.value])
      );
      const day = `${parts.year}-${parts.month}-${parts.day}`;
      const hour = parseInt(parts.hour, 10);

      // Phase 29 plan 29-04: prefer Tier C runtime override when accessor wired.
      const heartbeatHour = (getEffective ? getEffective().heartbeatHour : config.heartbeatHour);

      if (hour >= heartbeatHour && day !== lastFiredDay) {
        const summary = getSummary();
        // Defer firing when the bridge hasn't replayed a sample yet (post-boot
        // race — e.g. restart at 17:00 with heartbeatHour=17 fires before any
        // RH/Temp/CO2 reaches state). Don't update lastFiredDay; next tick
        // (15min) retries. If data never arrives, we just skip the day —
        // better than sending "RH: null  ·  Temp: null  ·  CO2: null".
        if (summary && (summary.rh != null || summary.temp != null || summary.co2 != null)) {
          lastFiredDay = day;
          dispatch({ type: 'heartbeat_tick', summary });
          logger.info(`[heartbeat] fired for ${day}`);
        } else {
          logger.info(`[heartbeat] deferred for ${day} — bridge summary empty, will retry next tick`);
        }
      }
    } catch (e) {
      logger.error(`[heartbeat] tick error: ${e.message}`);
    }
  }

  return {
    start() {
      tick(); // immediate check on start
      timer = setInterval(tick, intervalMs);
    },
    stop() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    },
  };
}

module.exports = { createHeartbeatScheduler };
