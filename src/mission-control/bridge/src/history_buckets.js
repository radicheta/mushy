// Telemetry GET /history: range cap and server-side downsampling step (D-06).
// MUSHY-179: cap raised from 30 days to a year. Above that the request is
// refused; the step keeps a plot to roughly 1000-1500 points.
const HOUR = 3600000;
const DAY = 24 * HOUR;

const TELEMETRY_MAX_RANGE_MS = 366 * DAY;

// <=2h 5s; <=24h 1min; <=7d 10min; <=6 months 1h; up to a year 3h
function bucketInterval(rangeMs) {
    if (rangeMs <= 2 * HOUR) return '5 seconds';
    if (rangeMs <= DAY) return '1 minute';
    if (rangeMs <= 7 * DAY) return '10 minutes';
    if (rangeMs <= 183 * DAY) return '1 hour';
    return '3 hours';
}

module.exports = { bucketInterval, TELEMETRY_MAX_RANGE_MS };
