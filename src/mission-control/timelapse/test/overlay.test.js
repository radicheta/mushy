const { Jimp, JimpMime } = require('jimp');
const { burnOverlay, fmtRh } = require('../src/overlay');

async function makeJpeg(w = 640, h = 480) {
    const img = new Jimp({ width: w, height: h, color: 0x336699ff });
    return await img.getBuffer(JimpMime.jpeg, { quality: 85 });
}

describe('fmtRh', () => {
    test('null -> null', () => { expect(fmtRh(null)).toBeNull(); });
    test('undefined -> null', () => { expect(fmtRh(undefined)).toBeNull(); });
    test('NaN -> null', () => { expect(fmtRh('abc')).toBeNull(); });
    test('88.5 -> "RH 88.5%"', () => { expect(fmtRh(88.5)).toBe('RH 88.5%'); });
    test('rounds to 1 decimal', () => { expect(fmtRh(88.456)).toBe('RH 88.5%'); });
});

describe('burnOverlay', () => {
    test('returns JPEG buffer with magic bytes', async () => {
        const input = await makeJpeg();
        const out = await burnOverlay(input, { timestamp: '2026-04-26 14:30', rh: 88.5 });
        expect(Buffer.isBuffer(out)).toBe(true);
        expect(out[0]).toBe(0xFF);
        expect(out[1]).toBe(0xD8);
        expect(out[2]).toBe(0xFF);
    });

    test('rh=null omits RH segment without error', async () => {
        const input = await makeJpeg();
        const out = await burnOverlay(input, { timestamp: '2026-04-26 14:30', rh: null });
        expect(Buffer.isBuffer(out)).toBe(true);
    });

    test('rh=undefined treated as null', async () => {
        const input = await makeJpeg();
        const out = await burnOverlay(input, { timestamp: 'X', rh: undefined });
        expect(Buffer.isBuffer(out)).toBe(true);
    });

    test('output differs from input (something drawn)', async () => {
        const input = await makeJpeg();
        const out = await burnOverlay(input, { timestamp: '2026-04-26 14:30', rh: 88.5 });
        expect(out.length).not.toBe(input.length);
    });
});
