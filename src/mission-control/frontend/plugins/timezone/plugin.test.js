// Run: node --test src/mission-control/frontend/plugins/timezone/
// Drives the UYT formats the way Open MCT 4.2's TimePopupFixed.vue does:
// the date box and the time box are filled and validated separately, then
// joined as `${date} ${time}` and parsed on Apply.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function install() {
    const formats = {};
    const timeSystems = {};
    const openmct = {
        telemetry: { addFormat: (f) => { formats[f.key] = f; } },
        time: { addTimeSystem: (ts) => { timeSystems[ts.key] = ts; } }
    };
    const ctx = {};
    vm.runInNewContext(
        fs.readFileSync(path.join(__dirname, 'plugin.js'), 'utf8') + '\nthis.TimezonePlugin = TimezonePlugin;',
        ctx
    );
    ctx.TimezonePlugin()(openmct);
    const ts = timeSystems.uyt;
    return { time: formats[ts.timeFormat], duration: formats[ts.durationFormat], ts };
}

// 2026-11-10 12:00:41 UYT == 15:00:41 UTC
const START = Date.UTC(2026, 10, 10, 15, 0, 41);

// TimePopupFixed.setViewFromBounds
function boxes(f, ms) {
    return { date: f.time.format(ms).split(' ')[0], time: f.duration.format(Math.abs(ms)) };
}

test('date box alone validates (TimePopupFixed.validateInput startDate)', () => {
    const f = install();
    for (const d of ['2026-09-30', '2026-10-31', '2026-11-05', '2026-11-10']) {
        assert.ok(f.time.validate(d), d);
    }
    assert.ok(!f.time.validate('2026-02-30'));
    assert.ok(!f.time.validate('2026-13-01'));
    assert.ok(!f.time.validate('garbage'));
});

test('time box shows UYT time of day, matching the bottom bar', () => {
    const f = install();
    const b = boxes(f, START);
    assert.deepStrictEqual(b, { date: '2026-11-10', time: '12:00:41' });
    assert.ok(f.duration.validate(b.time));
});

test('Apply with untouched boxes keeps the bounds (no 3 h drift)', () => {
    const f = install();
    const b = boxes(f, START);
    assert.strictEqual(f.time.parse(`${b.date} ${b.time}`), START);
});

test('date and time box agree across UYT midnight', () => {
    const f = install();
    const ms = Date.UTC(2026, 10, 11, 1, 30, 0); // 2026-11-10 22:30 UYT
    const b = boxes(f, ms);
    assert.deepStrictEqual(b, { date: '2026-11-10', time: '22:30:00' });
    assert.strictEqual(f.time.parse(`${b.date} ${b.time}`), ms);
});

test('real durations (realtime offsets) are not shifted', () => {
    const f = install();
    assert.strictEqual(f.duration.format(15 * 60 * 1000), '00:15:00');
    assert.strictEqual(f.duration.format(0), '00:00:00');
    assert.strictEqual(f.duration.parse('00:15:00'), 15 * 60 * 1000);
    assert.ok(!f.duration.validate('25:00:00'));
    assert.ok(!f.duration.validate('1:2:3'));
});
