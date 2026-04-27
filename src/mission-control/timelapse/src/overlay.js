// Phase 23 D-06: pre-burn overlay (timestamp top-left, RH top-right) onto a JPEG frame.
// Pure async function — no I/O, no env. Caller injects buffer + values.
const { Jimp, JimpMime, loadFont } = require('jimp');
const fonts = require('jimp/fonts');

function fmtRh(v) {
    if (v === null || v === undefined) return null;
    const n = Number(v);
    if (Number.isNaN(n)) return null;
    return `RH ${n.toFixed(1)}%`;
}

async function burnOverlay(inputBuffer, { timestamp, rh }) {
    const img = await Jimp.read(inputBuffer);
    const height = img.bitmap.height;
    const width = img.bitmap.width;
    const fontKey = height >= 640 ? 'SANS_32_WHITE' : 'SANS_16_WHITE';
    const font = await loadFont(fonts[fontKey]);

    // Top-left: timestamp
    img.print({ font, x: 8, y: 8, text: String(timestamp), maxWidth: width - 16 });

    // Top-right: RH (gap-over-noise — omit if null/NaN)
    const rhText = fmtRh(rh);
    if (rhText) {
        // Approximate text width — DejaVuSans 16 ~= 8px/char, 32 ~= 16px/char.
        const charPx = height >= 640 ? 16 : 8;
        const approxWidth = rhText.length * charPx;
        img.print({ font, x: Math.max(8, width - approxWidth - 8), y: 8, text: rhText });
    }

    return await img.getBuffer(JimpMime.jpeg, { quality: 85 });
}

module.exports = { burnOverlay, fmtRh };
