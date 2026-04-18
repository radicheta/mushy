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

      if (hour >= config.heartbeatHour && day !== lastFiredDay) {
        lastFiredDay = day;
        dispatch({ type: 'heartbeat_tick', summary: getSummary() });
        logger.info(`[heartbeat] fired for ${day}`);
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
