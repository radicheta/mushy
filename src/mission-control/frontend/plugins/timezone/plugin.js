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

    function pad(n) { return n < 10 ? '0' + n : String(n); }

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
            parse: function (text) {
                var m = /^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/.exec(String(text).trim());
                if (!m) return Number(text) || 0;
                var localMs = Date.UTC(
                    parseInt(m[1], 10),
                    parseInt(m[2], 10) - 1,
                    parseInt(m[3], 10),
                    parseInt(m[4], 10),
                    parseInt(m[5], 10),
                    parseInt(m[6], 10)
                );
                return localMs - UYT_OFFSET_MS; // convert displayed UYT back to UTC
            },
            validate: function (text) {
                return !isNaN(Number(text)) ||
                       /^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/.test(String(text).trim());
            }
        });

        // ── UYT time system ─────────────────────────────────────────
        openmct.time.addTimeSystem({
            key: 'uyt',
            name: 'UYT',
            cssClass: 'icon-clock',
            timeFormat: 'uyt',
            durationFormat: 'duration',
            isUTCBased: true
        });
    };
}
