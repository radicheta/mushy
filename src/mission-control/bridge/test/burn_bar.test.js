const { Jimp, JimpMime } = require('jimp');
const { formatBarText, burnBar } = require('../src/burn_bar');

const ISO = '2026-04-19T12:34:56.000Z';

describe('formatBarText', () => {
    test('all numeric values render with 1 decimal + HUM ON', () => {
        const s = formatBarText({
            capturedAt: new Date(ISO),
            rh: 88.5, temp: 21.3, co2: 620, hum: 1
        });
        expect(s).toBe(`${ISO} · RH 88.5% · T 21.3°C · CO₂ 620.0ppm · HUM ON`);
    });

    test('all null/undefined render as en-dash', () => {
        const s = formatBarText({
            capturedAt: ISO,
            rh: null, temp: undefined, co2: null, hum: null
        });
        expect(s).toBe(`${ISO} · RH —% · T —°C · CO₂ —ppm · HUM —`);
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

    test('NaN numeric renders as en-dash', () => {
        const s = formatBarText({
            capturedAt: ISO, rh: NaN, temp: 20, co2: 500, hum: 1
        });
        expect(s).toContain('RH —%');
    });

    test('Date and string ISO inputs both work', () => {
        const d = formatBarText({ capturedAt: new Date(ISO), rh: 50, temp: 20, co2: 500, hum: 1 });
        const s = formatBarText({ capturedAt: ISO, rh: 50, temp: 20, co2: 500, hum: 1 });
        expect(d).toBe(s);
    });
});

describe('burnBar', () => {
    test('produces a valid JPEG whose dimensions match input', async () => {
        const src = new Jimp({ width: 640, height: 480, color: 0xff0000ff });
        const srcBuf = await src.getBuffer(JimpMime.jpeg);
        const outBuf = await burnBar(srcBuf, 'test bar · RH 50.0% · T 20.0°C');
        expect(Buffer.isBuffer(outBuf)).toBe(true);
        expect(outBuf.length).toBeGreaterThan(0);

        const out = await Jimp.read(outBuf);
        expect(out.bitmap.width).toBe(640);
        expect(out.bitmap.height).toBe(480);

        // Bottom ~10% region should differ from source (overlay painted there).
        // Sample a pixel in the top area — should be reddish (source).
        // Sample a pixel in the bottom-center of the bar — should NOT be the pure source red.
        const { intToRGBA } = require('jimp');
        const top = intToRGBA(out.getPixelColor(10, 10));
        const bottom = intToRGBA(out.getPixelColor(320, 470));
        // Source was (255, 0, 0). The bar composites black at 0.55 opacity, so bottom pixel
        // will have r far below 255.
        expect(top.r).toBeGreaterThan(200);
        expect(bottom.r).toBeLessThan(top.r);
    });

    test('works on small images (height < 640 uses SANS_16 font)', async () => {
        const src = new Jimp({ width: 320, height: 240, color: 0x00ff00ff });
        const srcBuf = await src.getBuffer(JimpMime.jpeg);
        const outBuf = await burnBar(srcBuf, 'hi');
        const out = await Jimp.read(outBuf);
        expect(out.bitmap.width).toBe(320);
        expect(out.bitmap.height).toBe(240);
    });
});
