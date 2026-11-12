// Phase 23 D-06 / MUSHY-188: bottom-bar overlay and frame brightness.
// Pure async functions, no I/O, no env. Rendered with @napi-rs/canvas and a
// system TrueType font: jimp's bitmap fonts were Latin-1 only (CO₂ -> "CO?").
const { createCanvas, loadImage } = require('@napi-rs/canvas');

// fonts-dejavu (font-dejavu on alpine) - found by canvas through the system font dirs.
const FONT_FAMILY = 'DejaVu Sans Mono';

function fmtNum(v, digits) {
    if (v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isNaN(n) ? null : n.toFixed(digits);
}

function fmtRh(v) {
    const s = fmtNum(v, 1);
    return s === null ? null : `RH ${s}%`;
}

// "2026-11-11 18:00 UYT  RH 95.9%  T 19.4°C  CO₂ 603 ppm"; missing readings omitted.
function barText({ timestamp, tzLabel, rh, temp, co2 }) {
    const t = fmtNum(temp, 1);
    const c = fmtNum(co2, 0);
    return [
        `${timestamp} ${tzLabel}`,
        fmtRh(rh),
        t === null ? null : `T ${t}°C`,
        c === null ? null : `CO₂ ${c} ppm`,
    ].filter(Boolean).join('  ');
}

async function decode(buf) {
    const img = await loadImage(buf);
    const canvas = createCanvas(img.width, img.height);
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    return { canvas, ctx, width: img.width, height: img.height };
}

// Mean Rec.601 luma, 0-255. Lights-off frames on fc1 sit < 20, lit >= 90.
async function meanLuma(buf) {
    const { ctx, width, height } = await decode(buf);
    const d = ctx.getImageData(0, 0, width, height).data;
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    return sum / (d.length / 4);
}

// Semi-transparent black bar at the bottom, white text shrunk to fit the width.
async function burnOverlay(inputBuffer, { text }) {
    const { canvas, ctx, width, height } = await decode(inputBuffer);
    const barH = Math.max(28, Math.round(height * 0.07));
    const barY = height - barH;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    ctx.fillRect(0, barY, width, barH);

    const pad = 8;
    let size = Math.round(barH * 0.55);
    ctx.font = `bold ${size}px "${FONT_FAMILY}"`;
    while (size > 8 && ctx.measureText(text).width > width - 2 * pad) {
        size -= 1;
        ctx.font = `bold ${size}px "${FONT_FAMILY}"`;
    }
    ctx.fillStyle = '#ffffff';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, pad, barY + barH / 2);
    return canvas.encode('jpeg', 90);
}

module.exports = { burnOverlay, barText, fmtRh, meanLuma, FONT_FAMILY };
