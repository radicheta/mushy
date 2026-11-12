const { createCanvas, loadImage, GlobalFonts } = require('@napi-rs/canvas');
const { burnOverlay, fmtRh, barText, meanLuma, FONT_FAMILY } = require('../src/overlay');

async function makeJpeg(color = '#336699', w = 640, h = 480) {
    const c = createCanvas(w, h);
    const ctx = c.getContext('2d');
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, w, h);
    return c.encode('jpeg', 95);
}

describe('fmtRh', () => {
    test('null -> null', () => { expect(fmtRh(null)).toBeNull(); });
    test('undefined -> null', () => { expect(fmtRh(undefined)).toBeNull(); });
    test('NaN -> null', () => { expect(fmtRh('abc')).toBeNull(); });
    test('88.5 -> "RH 88.5%"', () => { expect(fmtRh(88.5)).toBe('RH 88.5%'); });
    test('rounds to 1 decimal', () => { expect(fmtRh(88.456)).toBe('RH 88.5%'); });
});

describe('barText', () => {
    test('all readings present', () => {
        expect(barText({ timestamp: '2026-11-11 18:00', tzLabel: 'UYT', rh: 95.94, temp: 19.36, co2: 602.6 }))
            .toBe('2026-11-11 18:00 UYT  RH 95.9%  T 19.4°C  CO₂ 603 ppm');
    });
    test('missing readings are omitted (gap over noise)', () => {
        expect(barText({ timestamp: '2026-11-11 18:00', tzLabel: 'UYT', rh: null, temp: 19.4, co2: undefined }))
            .toBe('2026-11-11 18:00 UYT  T 19.4°C');
    });
});

describe('font', () => {
    test('DejaVu Sans Mono is available to canvas', () => {
        expect(GlobalFonts.has(FONT_FAMILY)).toBe(true);
    });
});

describe('meanLuma', () => {
    test('black frame is ~0, white frame is ~255', async () => {
        expect(await meanLuma(await makeJpeg('#000000'))).toBeLessThan(5);
        expect(await meanLuma(await makeJpeg('#ffffff'))).toBeGreaterThan(250);
    });
    test('mid grey is mid', async () => {
        const l = await meanLuma(await makeJpeg('#808080'));
        expect(l).toBeGreaterThan(110);
        expect(l).toBeLessThan(145);
    });
});

describe('burnOverlay', () => {
    test('returns a JPEG of the same size with a darkened bottom bar', async () => {
        const out = await burnOverlay(await makeJpeg('#ff0000'), { text: 'x' });
        expect(out[0]).toBe(0xFF);
        expect(out[1]).toBe(0xD8);
        const img = await loadImage(out);
        expect([img.width, img.height]).toEqual([640, 480]);
        const c = createCanvas(640, 480);
        const ctx = c.getContext('2d');
        ctx.drawImage(img, 0, 0);
        expect(ctx.getImageData(10, 10, 1, 1).data[0]).toBeGreaterThan(200);
        expect(ctx.getImageData(630, 470, 1, 1).data[0]).toBeLessThan(150);
    });
    test('CO₂ renders as its own glyph (not the Latin-1 "?" fallback)', async () => {
        const src = await makeJpeg('#808080');
        const a = await burnOverlay(src, { text: 'CO₂ 603 ppm' });
        const b = await burnOverlay(src, { text: 'CO? 603 ppm' });
        expect(a.equals(b)).toBe(false);
    });
});
