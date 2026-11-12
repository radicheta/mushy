// MUSHY-188: local-day helpers. A farm day is LOCAL midnight to local midnight
// (MUSHY-94). Pure, Intl-only; the zone is passed in (config.timezone).

function partsAt(ms, timeZone) {
    const fmt = new Intl.DateTimeFormat('en-CA', {
        timeZone, hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
    return Object.fromEntries(fmt.formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
}

// Zone offset (ms, local minus UTC) in effect at instant ms.
function offsetAt(ms, timeZone) {
    const p = partsAt(ms, timeZone);
    const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
    return asUtc - Math.floor(ms / 1000) * 1000;
}

// UTC instant of local midnight starting `date` (YYYY-MM-DD).
function localMidnight(date, timeZone) {
    const [y, m, d] = date.split('-').map(Number);
    const guess = Date.UTC(y, m - 1, d);
    let t = guess - offsetAt(guess, timeZone);
    t = guess - offsetAt(t, timeZone); // re-check across a DST edge
    return t;
}

function nextDate(date) {
    const [y, m, d] = date.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}

// [start, end) as UTC ISO strings for the local day `date`.
function localDayBounds(date, timeZone) {
    return [
        new Date(localMidnight(date, timeZone)).toISOString(),
        new Date(localMidnight(nextDate(date), timeZone)).toISOString(),
    ];
}

function localDateOf(instant, timeZone) {
    const p = partsAt(new Date(instant).getTime(), timeZone);
    return `${p.year}-${p.month}-${p.day}`;
}

// "YYYY-MM-DD HH:MM" in the local zone.
function formatLocal(ms, timeZone) {
    const p = partsAt(ms, timeZone);
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

module.exports = { localDayBounds, localDateOf, formatLocal, nextDate };
