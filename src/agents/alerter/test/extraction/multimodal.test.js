'use strict';

// Phase 38 Plan 03 Task 1: multimodal.js unit tests.
// Covers buildContentBlocks ordering, readImageToBase64 success + ENOENT,
// downscaleIfNeeded skip-small + downscale-large.

const fs = require('fs');
const os = require('os');
const path = require('path');
const Jimp = require('jimp');

const {
  buildContentBlocks,
  readImageToBase64,
  downscaleIfNeeded,
  _internal,
} = require('../../src/extraction/multimodal');

const silentLogger = { warn: () => {}, info: () => {}, error: () => {} };

describe('multimodal.buildContentBlocks', () => {
  test('text + transcript + 1 image -> 3 blocks in order', () => {
    const blocks = buildContentBlocks({
      text: 'tray 4 pinning',
      transcript: 'voice memo body',
      images: [{ data: 'aGVsbG8=', media_type: 'image/jpeg' }],
    });
    expect(blocks).toHaveLength(3);
    expect(blocks[0]).toEqual({ type: 'text', text: expect.stringMatching(/tray 4 pinning/) });
    expect(blocks[1]).toEqual({ type: 'text', text: expect.stringMatching(/voice memo body/) });
    expect(blocks[2]).toEqual({
      type: 'image',
      source: { type: 'base64', media_type: 'image/jpeg', data: 'aGVsbG8=' },
    });
  });

  test('missing text/transcript yields no empty blocks', () => {
    const blocks = buildContentBlocks({ text: '', transcript: null, images: [] });
    expect(blocks).toEqual([]);
  });

  test('multiple images preserved in order', () => {
    const blocks = buildContentBlocks({
      text: null,
      transcript: null,
      images: [
        { data: 'aaa', media_type: 'image/jpeg' },
        { data: 'bbb', media_type: 'image/png' },
      ],
    });
    expect(blocks).toHaveLength(2);
    expect(blocks[0].source.media_type).toBe('image/jpeg');
    expect(blocks[1].source.media_type).toBe('image/png');
  });
});

describe('multimodal.downscaleIfNeeded', () => {
  test('small jpeg passes through unchanged', async () => {
    const img = await new Jimp(100, 100, 0xff0000ff);
    const buf = await img.getBufferAsync(Jimp.MIME_JPEG);
    const out = await downscaleIfNeeded(buf, 'image/jpeg', { logger: silentLogger });
    expect(out.ok).toBe(true);
    expect(out.buffer.length).toBe(buf.length);
    expect(out.media_type).toBe('image/jpeg');
  });

  test('large image (>1.15MP) is downscaled', async () => {
    const img = await new Jimp(2000, 2000, 0x00ff00ff);
    const buf = await img.getBufferAsync(Jimp.MIME_JPEG);
    const out = await downscaleIfNeeded(buf, 'image/jpeg', { logger: silentLogger });
    expect(out.ok).toBe(true);
    expect(out.buffer.length).toBeLessThan(buf.length);
    // Verify downscaled image pixel count <= 1.15MP
    const reread = await Jimp.read(out.buffer);
    const pixels = reread.bitmap.width * reread.bitmap.height;
    expect(pixels).toBeLessThanOrEqual(1_150_000);
  }, 20000);

  test('non-image mime type passes through unchanged', async () => {
    const buf = Buffer.from('not an image');
    const out = await downscaleIfNeeded(buf, 'application/pdf', { logger: silentLogger });
    expect(out.ok).toBe(true);
    expect(out.buffer).toBe(buf);
  });
});

describe('multimodal.readImageToBase64', () => {
  let tmpDir;
  beforeAll(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mm-test-'));
  });
  afterAll(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  test('reads existing jpeg, returns base64 + media_type', async () => {
    const img = await new Jimp(50, 50, 0xff00ffff);
    const p = path.join(tmpDir, 'small.jpg');
    await img.writeAsync(p);
    const out = await readImageToBase64(p, { logger: silentLogger });
    expect(out.ok).toBe(true);
    expect(typeof out.data).toBe('string');
    expect(out.data.length).toBeGreaterThan(0);
    expect(out.media_type).toBe('image/jpeg');
  });

  test('ENOENT -> {ok:false, reason} without throwing', async () => {
    let threw = false;
    let out;
    try {
      out = await readImageToBase64('/nonexistent/path/never.jpg', { logger: silentLogger });
    } catch (_) {
      threw = true;
    }
    expect(threw).toBe(false);
    expect(out.ok).toBe(false);
    expect(typeof out.reason).toBe('string');
  });

  test('png file detected by extension', async () => {
    const img = await new Jimp(40, 40, 0x0000ffff);
    const p = path.join(tmpDir, 'thing.png');
    await img.writeAsync(p);
    const out = await readImageToBase64(p, { logger: silentLogger });
    expect(out.ok).toBe(true);
    expect(out.media_type).toBe('image/png');
  });
});
