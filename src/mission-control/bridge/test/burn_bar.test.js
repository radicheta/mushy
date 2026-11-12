const fs = require('fs');
const { createCanvas, loadImage } = require('@napi-rs/canvas');
const { formatBarText, burnBar, FONT_PATH } = require('../src/burn_bar');

const ISO = '2026-04-19T12:34:56.000Z';
// 12:34:56Z is 09:34:56 in Montevideo (UTC-3, no DST).
const LOCAL = '2026-04-19 09:34:56 UYT';

async function solidJpeg(width, height, color) {
    const c = createCanvas(width, height);
    const ctx = c.getContext('2d');
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, width, height);
    return c.encode('jpeg', 95);
}

async function decode(buf) {
    const img = await loadImage(buf);
    const c = createCanvas(img.width, img.height);
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    return { width: img.width, height: img.height, px: (x, y) => ctx.getImageData(x, y, 1, 1).data };
}

describe('formatBarText', () => {
    test('all numeric values render with 1 decimal + HUM ON, local time', () => {
        const s = formatBarText({
            capturedAt: new Date(ISO),
            rh: 88.5, temp: 21.3, co2: 620, hum: 1
        });
        expect(s).toBe(`${LOCAL} · RH 88.5% · T 21.3°C · CO₂ 620.0ppm · HUM ON`);
    });

    test('local date rolls back across UTC midnight', () => {
        const s = formatBarText({ capturedAt: '2026-11-12T01:39:42.000Z', rh: 50, temp: 20, co2: 500, hum: 1 });
        expect(s.startsWith('2026-11-11 22:39:42 UYT')).toBe(true);
    });

    test('all null/undefined render as n/a', () => {
        const s = formatBarText({
            capturedAt: ISO,
            rh: null, temp: undefined, co2: null, hum: null
        });
        expect(s).toBe(`${LOCAL} · RH n/a · T n/a · CO₂ n/a · HUM n/a`);
    });

    test('hum=0 renders HUM OFF', () => {
        const s = formatBarText({
            capturedAt: ISO, rh: 50, temp: 20, co2: 500, hum: 0
        });
        expect(s).toContain('HUM OFF');
    });

    test('hum=1 renders HUM ON', () => {
        const s = formatBarText({
            capturedAt: ISO, rh: 50, temp: 20, co2: 500, hum: 1
        });
        expect(s).toContain('HUM ON');
    });

    test('NaN numeric renders as n/a', () => {
        const s = formatBarText({
            capturedAt: ISO, rh: NaN, temp: 20, co2: 500, hum: 1
        });
        expect(s).toContain('RH n/a ·');
    });

    test('Date and string ISO inputs both work', () => {
        const d = formatBarText({ capturedAt: new Date(ISO), rh: 50, temp: 20, co2: 500, hum: 1 });
        const s = formatBarText({ capturedAt: ISO, rh: 50, temp: 20, co2: 500, hum: 1 });
        expect(d).toBe(s);
    });
});

describe('burnBar', () => {
    test('font file exists', () => {
        expect(fs.existsSync(FONT_PATH)).toBe(true);
    });

    test('produces a valid JPEG whose dimensions match input', async () => {
        const srcBuf = await solidJpeg(640, 480, '#ff0000');
        const outBuf = await burnBar(srcBuf, 'test bar · RH 50.0% · T 20.0°C');
        expect(Buffer.isBuffer(outBuf)).toBe(true);
        expect(outBuf.length).toBeGreaterThan(0);

        const out = await decode(outBuf);
        expect(out.width).toBe(640);
        expect(out.height).toBe(480);

        // Source was (255, 0, 0). The bar composites black at 0.55 opacity, so
        // a bottom pixel has r far below the untouched top.
        const top = out.px(10, 10);
        const bottom = out.px(630, 470);
        expect(top[0]).toBeGreaterThan(200);
        expect(bottom[0]).toBeLessThan(top[0]);
    });

    test('works on small images', async () => {
        const srcBuf = await solidJpeg(320, 240, '#00ff00');
        const out = await decode(await burnBar(srcBuf, 'hi'));
        expect(out.width).toBe(320);
        expect(out.height).toBe(240);
        expect(out.px(10, 10)[1]).toBeGreaterThan(200);
        expect(out.px(310, 235)[1]).toBeLessThan(out.px(10, 10)[1]);
    });

    // MUSHY-186: the old jimp bitmap font had no U+2082 and drew it as '?'.
    // With a real glyph, 'CO₂' and 'CO?' must render differently.
    test('subscript two renders as its own glyph, not ?', async () => {
        const srcBuf = await solidJpeg(640, 480, '#808080');
        const a = await burnBar(srcBuf, 'CO₂ 603.0ppm');
        const b = await burnBar(srcBuf, 'CO? 603.0ppm');
        expect(a.equals(b)).toBe(false);
    });

    test('long bar text is shrunk to fit the image width', async () => {
        const srcBuf = await solidJpeg(640, 480, '#ffffff');
        const text = formatBarText({ capturedAt: ISO, rh: 100, temp: 100, co2: 10000, hum: 0 });
        const out = await decode(await burnBar(srcBuf, text));
        // Right-most column of the bar must be bar-only (no glyph ink clipped at the edge).
        const edge = out.px(638, 460);
        const barOnly = out.px(638, 434);
        expect(Math.abs(edge[0] - barOnly[0])).toBeLessThan(25);
    });
});
