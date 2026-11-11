/**
 * TimezonePlugin — registers a UYT (UTC-3) time system for OpenMCT.
 *
 * The built-in UTCTimeSystem remains untouched. This adds a separate
 * 'uyt' time system with its own formatter that displays UTC epoch
 * milliseconds shifted by -3 hours. All internal timestamps stay as
 * UTC epoch ms — only the display string changes.
 *
 * Telemetry objects should declare a domain with:
 *   { key: 'uyt', source: 'utc', format: 'uyt', hints: { domain: 2 } }
 * so OpenMCT reads the 'utc' property from the datum when the 'uyt'
 * time system is active, without duplicating data.
 */
function TimezonePlugin() {
    var UYT_OFFSET_MS = -3 * 60 * 60 * 1000;

    var ONE_YEAR_MS = 365 * 24 * 60 * 60 * 1000;
    var HMS = /^([01]\d|2[0-3]):([0-5]\d):([0-5]\d)$/;

    function pad(n) { return n < 10 ? '0' + n : String(n); }

    // "YYYY-MM-DD[ HH:mm[:ss]]" read as UYT wall clock -> Date.UTC of
    // those fields, or null if malformed or not a real date (2026-02-30).
    function parseUyt(text) {
        var m = /^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/
            .exec(String(text).trim());
        if (!m) return null;
        var f = m.slice(1).map(function (v) { return v ? parseInt(v, 10) : 0; });
        var ms = Date.UTC(f[0], f[1] - 1, f[2], f[3], f[4], f[5]);
        var d = new Date(ms);
        if (d.getUTCFullYear() !== f[0] || d.getUTCMonth() !== f[1] - 1 ||
            d.getUTCDate() !== f[2] || f[3] > 23 || f[4] > 59 || f[5] > 59) {
            return null;
        }
        return ms;
    }

    return function install(openmct) {
        // ── UYT formatter ───────────────────────────────────────────
        openmct.telemetry.addFormat({
            key: 'uyt',
            format: function (ms) {
                var d = new Date(ms + UYT_OFFSET_MS);
                return d.getUTCFullYear() + '-' +
                       pad(d.getUTCMonth() + 1) + '-' +
                       pad(d.getUTCDate()) + ' ' +
                       pad(d.getUTCHours()) + ':' +
                       pad(d.getUTCMinutes()) + ':' +
                       pad(d.getUTCSeconds());
            },
            // Open MCT 4.2's fixed-time popup validates the date box on its
            // own ("2026-11-05"), so the time part must be optional here.
            parse: function (text) {
                var p = parseUyt(text);
                if (p === null) return Number(text) || 0;
                return p - UYT_OFFSET_MS; // convert displayed UYT back to UTC
            },
            validate: function (text) {
                return !isNaN(Number(text)) || parseUyt(text) !== null;
            }
        });

        // ── UYT time-of-day / duration formatter ────────────────────
        // The popup fills its time boxes with durationFormat.format(epochMs)
        // and parses `${date} ${time}` with the 'uyt' format above. The stock
        // 'duration' format prints UTC time of day, so the boxes showed UTC and
        // every Apply moved the window 3 h later. Values of a year or more are
        // epoch timestamps and get the UYT shift; anything smaller is a real
        // duration (realtime offsets, imagery age) and is left alone.
        openmct.telemetry.addFormat({
            key: 'uyt-duration',
            format: function (ms) {
                var d = new Date(ms >= ONE_YEAR_MS ? ms + UYT_OFFSET_MS : ms);
                return pad(d.getUTCHours()) + ':' +
                       pad(d.getUTCMinutes()) + ':' +
                       pad(d.getUTCSeconds());
            },
            parse: function (text) {
                var m = HMS.exec(String(text).trim());
                if (!m) return 0;
                return ((+m[1] * 60 + +m[2]) * 60 + +m[3]) * 1000;
            },
            validate: function (text) {
                return HMS.test(String(text).trim());
            }
        });

        // ── UYT time system ─────────────────────────────────────────
        openmct.time.addTimeSystem({
            key: 'uyt',
            name: 'UYT',
            cssClass: 'icon-clock',
            timeFormat: 'uyt',
            durationFormat: 'uyt-duration',
            isUTCBased: true
        });
    };
}
