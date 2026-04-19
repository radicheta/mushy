// Phase 22 D-03: pure burn-in module.
// Exports formatBarText (pure string) and burnBar (async Buffer->Buffer).
// No I/O, no env reads, no telemetry cache access. index.js composes the inputs.
const { Jimp, JimpMime, loadFont } = require('jimp');
const fonts = require('jimp/fonts');

// Null/undefined/NaN -> '—' (en-dash, U+2014). Numbers -> toFixed(1). Gap over noise.
function fmtNum(v) {
    if (v === null || v === undefined) return '—';
    const n = Number(v);
    if (Number.isNaN(n)) return '—';
    return n.toFixed(1);
}

function fmtHum(v) {
    if (v === null || v === undefined) return '—';
    return v ? 'ON' : 'OFF';
}

// capturedAt: Date | ISO string. Pure, no side effects.
function formatBarText({ capturedAt, rh, temp, co2, hum }) {
    const iso = (capturedAt instanceof Date) ? capturedAt.toISOString() : String(capturedAt);
    return `${iso} · RH ${fmtNum(rh)}% · T ${fmtNum(temp)}°C · CO₂ ${fmtNum(co2)}ppm · HUM ${fmtHum(hum)}`;
}

// Bottom-bar layout: height = max(32, 10% of image), black @ 0.55 opacity, white text.
// jimp v1 API: loadFont + img.print({font, x, y, text, maxWidth}) + img.composite.
async function burnBar(inputBuffer, barText) {
    const img = await Jimp.read(inputBuffer);
    const width = img.bitmap.width;
    const height = img.bitmap.height;
    const barH = Math.max(32, Math.round(height * 0.10));
    const barY = height - barH;

    // Semi-transparent black bar composited over the bottom of the frame.
    const bar = new Jimp({ width, height: barH, color: 0x000000ff });
    bar.opacity(0.55);
    img.composite(bar, 0, barY);

    // Font size scales with image height. SANS_32_WHITE for >=640, else SANS_16_WHITE.
    const fontKey = height >= 640 ? 'SANS_32_WHITE' : 'SANS_16_WHITE';
    const font = await loadFont(fonts[fontKey]);

    // Vertical center inside the bar.
    const lineHeight = (font.common && font.common.lineHeight) || (height >= 640 ? 32 : 16);
    const textY = barY + Math.max(0, Math.round((barH - lineHeight) / 2));

    img.print({
        font,
        x: 8,
        y: textY,
        text: barText,
        maxWidth: width - 16
    });

    return await img.getBuffer(JimpMime.jpeg, { quality: 85 });
}

module.exports = { formatBarText, burnBar, fmtNum, fmtHum };
