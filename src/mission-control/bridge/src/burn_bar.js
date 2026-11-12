// Phase 22 D-03: pure burn-in module.
// Exports formatBarText (pure string) and burnBar (async Buffer->Buffer).
// No I/O, no env reads, no telemetry cache access. index.js composes the inputs.
//
// MUSHY-186: text is drawn with a TrueType font via @napi-rs/canvas. jimp's
// bitmap fonts were Latin-1 only and drew CO₂ as "CO?".
const { createCanvas, loadImage, GlobalFonts } = require('@napi-rs/canvas');

// fonts-dejavu-core (installed in the Dockerfile).
const FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf';
const FONT_FAMILY = 'BarMono';
GlobalFonts.registerFromPath(FONT_PATH, FONT_FAMILY);

// The farm is in Uruguay: UTC-3, no DST.
const TIME_ZONE = 'America/Montevideo';
const TZ_LABEL = 'UYT';
const localFmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE, hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
});

// Null/undefined/NaN -> 'n/a' (unit dropped). Numbers -> toFixed(1) + unit. Gap over noise.
function fmtNum(v, unit = '') {
    if (v === null || v === undefined) return 'n/a';
    const n = Number(v);
    if (Number.isNaN(n)) return 'n/a';
    return n.toFixed(1) + unit;
}

function fmtHum(v) {
    if (v === null || v === undefined) return 'n/a';
    return v ? 'ON' : 'OFF';
}

// "2026-11-11 18:00:18 UYT"
function fmtLocal(capturedAt) {
    const p = Object.fromEntries(localFmt.formatToParts(new Date(capturedAt)).map(x => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second} ${TZ_LABEL}`;
}

// capturedAt: Date | ISO string. Pure, no side effects.
function formatBarText({ capturedAt, rh, temp, co2, hum }) {
    return `${fmtLocal(capturedAt)} · RH ${fmtNum(rh, '%')} · T ${fmtNum(temp, '°C')} · CO₂ ${fmtNum(co2, 'ppm')} · HUM ${fmtHum(hum)}`;
}

// Bottom-bar layout: height = max(32, 10% of image), black @ 0.55 opacity, white text.
// Font starts at 40% of the bar height and shrinks until the text fits the width.
async function burnBar(inputBuffer, barText) {
    const img = await loadImage(inputBuffer);
    const { width, height } = img;
    const canvas = createCanvas(width, height);
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);

    const barH = Math.max(32, Math.round(height * 0.10));
    const barY = height - barH;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    ctx.fillRect(0, barY, width, barH);

    const pad = 8;
    let size = Math.round(barH * 0.4);
    ctx.font = `${size}px ${FONT_FAMILY}`;
    while (size > 8 && ctx.measureText(barText).width > width - 2 * pad) {
        size -= 1;
        ctx.font = `${size}px ${FONT_FAMILY}`;
    }
    ctx.fillStyle = '#ffffff';
    ctx.textBaseline = 'middle';
    ctx.fillText(barText, pad, barY + barH / 2);

    return canvas.encode('jpeg', 85);
}

module.exports = { formatBarText, burnBar, fmtNum, fmtHum, FONT_PATH };
