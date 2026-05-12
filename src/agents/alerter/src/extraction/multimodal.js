'use strict';

// Phase 38 Plan 03 Task 1: multimodal helpers for Anthropic tool-use extraction.
//
// Responsibilities:
//   - readImageToBase64(path): read JPEG/PNG from disk, downscale if needed, base64-encode.
//   - downscaleIfNeeded(buffer, mimeType): enforce 5MB and 1.15MP ceiling per RESEARCH Pitfall 3.
//   - buildContentBlocks({text, transcript, images}): assemble Anthropic content blocks
//     in order text -> transcript -> images. Missing inputs are skipped (no empty blocks).
//
// Never throws on file IO; surfaces {ok:false, reason} per the project pattern.

const fs = require('fs').promises;
const path = require('path');
const Jimp = require('jimp');

const MAX_BYTES = 5 * 1024 * 1024;      // 5MB Anthropic image ceiling
const MAX_PIXELS = 1_150_000;           // 1.15MP recommended cap (RESEARCH Pitfall 3)
const IMAGE_MIME_RE = /^image\/(jpeg|png)$/i;

function mimeFromPath(p) {
  const ext = path.extname(p).toLowerCase();
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.png') return 'image/png';
  return 'application/octet-stream';
}

async function downscaleIfNeeded(buffer, mimeType, { logger = console } = {}) {
  try {
    if (!IMAGE_MIME_RE.test(mimeType || '')) {
      return { ok: true, buffer, media_type: mimeType };
    }
    let img;
    try {
      img = await Jimp.read(buffer);
    } catch (e) {
      // Not a decodable image; pass through unchanged.
      return { ok: true, buffer, media_type: mimeType };
    }
    const pixels = img.bitmap.width * img.bitmap.height;
    const needs = buffer.length > MAX_BYTES || pixels > MAX_PIXELS;
    if (!needs) return { ok: true, buffer, media_type: mimeType };

    // Compute scale to land at or under the pixel cap, then re-emit as JPEG (smaller).
    const scale = Math.sqrt(MAX_PIXELS / pixels);
    const newW = Math.max(1, Math.floor(img.bitmap.width * scale));
    const newH = Math.max(1, Math.floor(img.bitmap.height * scale));
    img.resize(newW, newH);
    img.quality(85);
    const outBuf = await img.getBufferAsync(Jimp.MIME_JPEG);
    logger.info && logger.info(`[multimodal] downscaled ${img.bitmap.width}x${img.bitmap.height} from ${pixels}px to ${newW * newH}px`);
    return { ok: true, buffer: outBuf, media_type: 'image/jpeg' };
  } catch (e) {
    logger.warn && logger.warn(`[multimodal] downscale degraded: ${e.message}`);
    return { ok: false, reason: e.message };
  }
}

async function readImageToBase64(imagePath, { logger = console } = {}) {
  try {
    const buf = await fs.readFile(imagePath);
    const mime = mimeFromPath(imagePath);
    const scaled = await downscaleIfNeeded(buf, mime, { logger });
    if (!scaled.ok) return scaled;
    return {
      ok: true,
      data: scaled.buffer.toString('base64'),
      media_type: scaled.media_type,
    };
  } catch (e) {
    logger.warn && logger.warn(`[multimodal] read degraded: ${e.message}`);
    return { ok: false, reason: e.message };
  }
}

function buildContentBlocks({ text, transcript, images } = {}) {
  const blocks = [];
  if (text && String(text).trim() !== '') {
    blocks.push({ type: 'text', text: String(text) });
  }
  if (transcript && String(transcript).trim() !== '') {
    blocks.push({ type: 'text', text: `Transcript: ${String(transcript)}` });
  }
  if (Array.isArray(images)) {
    for (const img of images) {
      if (!img || !img.data) continue;
      blocks.push({
        type: 'image',
        source: { type: 'base64', media_type: img.media_type || 'image/jpeg', data: img.data },
      });
    }
  }
  return blocks;
}

module.exports = {
  readImageToBase64,
  downscaleIfNeeded,
  buildContentBlocks,
  _internal: { mimeFromPath, MAX_BYTES, MAX_PIXELS },
};
