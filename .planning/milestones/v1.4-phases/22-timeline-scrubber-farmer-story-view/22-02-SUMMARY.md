---
phase: 22-timeline-scrubber-farmer-story-view
plan: 02
subsystem: bridge
tags: [phase-22, bridge, burn-in, snapshots, jimp, tdd]
dependency_graph:
  requires:
    - jimp ^1.6.1 (added in plan 22-01)
    - SNAPSHOT_BURNT_DIR env + /data/snapshots-burnt mount (plan 22-01)
    - /data -> /mnt/slime-kingdom/data symlink (plan 22-01, host-prepped)
  provides:
    - burn_bar module (pure formatBarText + burnBar)
    - saveSnapshot() writes raw + burnt twin with identical filename
    - runPrune mirror-deletes burnt twin alongside raw
  affects:
    - src/mission-control/bridge/src/burn_bar.js (new)
    - src/mission-control/bridge/src/index.js (saveSnapshot extended)
    - src/mission-control/bridge/src/retention.js (runPrune extended)
    - src/mission-control/bridge/test/burn_bar.test.js (new)
    - src/mission-control/bridge/test/retention.test.js (3 new cases)
    - src/mission-control/bridge/package.json (test script)
tech_stack:
  added: []
  patterns:
    - Fire-and-forget IIFE for sidecar writes (raw path never awaits burn)
    - Buffer pin (rawBuf = latestFrame) before async to prevent cross-frame aliasing
    - Path-prefix swap (rawDir -> burntDir) for mirror delete with startsWith guard
    - Gap-over-noise: null/undefined/NaN -> en-dash in overlay
key_files:
  created:
    - src/mission-control/bridge/src/burn_bar.js
    - src/mission-control/bridge/test/burn_bar.test.js
  modified:
    - src/mission-control/bridge/src/index.js
    - src/mission-control/bridge/src/retention.js
    - src/mission-control/bridge/test/retention.test.js
    - src/mission-control/bridge/package.json
decisions:
  - "Jest testMatch is test/**/*.test.js — burn_bar.test.js lives in test/ not src/ per project convention"
  - "npm test runs with --experimental-vm-modules: jimp v1 uses dynamic import for file-type detection, Jest's default CJS VM rejects it"
  - "burnBar pure function takes Buffer in, Buffer out. index.js owns telemetry-cache reads; module has zero env/IO dependencies"
  - "Font size scales with image height: SANS_32_WHITE when height >= 640, SANS_16_WHITE otherwise"
  - "Bar: max(32px, 10% of height), black @ 0.55 opacity, 8px padding, vertically centered"
metrics:
  duration_min: ~15
  tasks_completed: 2
  files_created: 2
  files_modified: 4
  commits: 3
  completed_date: 2026-04-19
---

# Phase 22 Plan 02: burn-in sidecar pipeline

One-liner: every snapshot now writes a raw + burnt pair; burnt carries a black-overlay bottom bar with ISO + RH + T + CO₂ + humidifier state; retention prune keeps both trees lockstep.

## What shipped

### Task 1 — burn_bar module (commits 8501d0b → 810cfc7)

RED commit `8501d0b`: test file landed with 8 failing assertions (module not yet present). GREEN commit `810cfc7`: `src/burn_bar.js` implemented, all 8 tests pass, plus the 33 pre-existing bridge tests still pass.

**`src/mission-control/bridge/src/burn_bar.js` (final content):**

```js
const { Jimp, JimpMime, loadFont } = require('jimp');
const fonts = require('jimp/fonts');

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

function formatBarText({ capturedAt, rh, temp, co2, hum }) {
    const iso = (capturedAt instanceof Date) ? capturedAt.toISOString() : String(capturedAt);
    return `${iso} · RH ${fmtNum(rh)}% · T ${fmtNum(temp)}°C · CO₂ ${fmtNum(co2)}ppm · HUM ${fmtHum(hum)}`;
}

async function burnBar(inputBuffer, barText) {
    const img = await Jimp.read(inputBuffer);
    const width = img.bitmap.width;
    const height = img.bitmap.height;
    const barH = Math.max(32, Math.round(height * 0.10));
    const barY = height - barH;

    const bar = new Jimp({ width, height: barH, color: 0x000000ff });
    bar.opacity(0.55);
    img.composite(bar, 0, barY);

    const fontKey = height >= 640 ? 'SANS_32_WHITE' : 'SANS_16_WHITE';
    const font = await loadFont(fonts[fontKey]);
    const lineHeight = (font.common && font.common.lineHeight) || (height >= 640 ? 32 : 16);
    const textY = barY + Math.max(0, Math.round((barH - lineHeight) / 2));

    img.print({ font, x: 8, y: textY, text: barText, maxWidth: width - 16 });
    return await img.getBuffer(JimpMime.jpeg, { quality: 85 });
}

module.exports = { formatBarText, burnBar, fmtNum, fmtHum };
```

Key contract:
- Pure: no I/O, no env reads, no telemetry access. index.js supplies all inputs.
- `formatBarText` works on both `Date` and ISO-string inputs (test case confirmed).
- Null / undefined / NaN → `—` en-dash (U+2014). Gap over noise, never fabricated zero.
- jimp v1 API (`Jimp`, `JimpMime`, `loadFont` as named exports; fonts live in `jimp/fonts`).

### Task 2 — saveSnapshot + retention wiring (commit 092b8d4)

**`saveSnapshot` before/after diff (body of `fs.writeFile` callback):**

Before:
```js
fs.writeFile(filepath, latestFrame, async (err) => {
    if (err) { console.error('[camera] snapshot write failed:', err.message); return; }
    console.log(`[camera] snapshot saved: ${filepath} ...`);
    if (!dbReady) return;
    try { await pool.query(`INSERT INTO snapshots ...`, [...]); }
    catch (e) { console.error('[snapshots] insert failed:', e.message); }
});
```

After:
```js
// Phase 22 D-03: pin rawBuf now to prevent cross-frame aliasing.
const rawBuf = latestFrame;
fs.writeFile(filepath, latestFrame, async (err) => {
    if (err) { console.error('[camera] snapshot write failed:', err.message); return; }
    console.log(`[camera] snapshot saved: ${filepath} ...`);

    // Phase 22 D-03: fire-and-forget burnt twin.
    const burntDir = path.join(SNAPSHOT_BURNT_DIR, CAMERA_ID, dateDir);
    const burntPath = path.join(burntDir, filename);
    const barText = formatBarText({
        capturedAt,
        rh:   latestTelemetry.humidity?.value,
        temp: latestTelemetry.temperature?.value,
        co2:  latestTelemetry.co2?.value,
        hum:  latestTelemetry.humidifier?.value
    });
    (async () => {
        try {
            fs.mkdirSync(burntDir, { recursive: true });
            const burnt = await burnBar(rawBuf, barText);
            fs.writeFile(burntPath, burnt, (werr) => {
                if (werr) console.error('[camera/burnt] write failed:', werr.message);
            });
        } catch (e) {
            console.error('[camera/burnt] burn failed:', e.message);
        }
    })();

    if (!dbReady) return;
    try { await pool.query(`INSERT INTO snapshots ...`, [...]); }  // UNCHANGED
    catch (e) { console.error('[snapshots] insert failed:', e.message); }
});
```

Plus module-top additions: `require('./burn_bar')`, `SNAPSHOT_BURNT_DIR` env const, startup equality guard (`process.exit(1)` if the two roots collide).

**`retention.js` runPrune loop diff:**

Before:
```js
for (const r of expired.rows) {
    try { await fs.promises.unlink(r.file_path); }
    catch (e) { if (e.code !== 'ENOENT') { log.error(...); failed++; continue; } }
    await pool.query("DELETE FROM snapshots WHERE file_path = $1", [r.file_path]);
    deleted++;
}
```

After:
```js
for (const r of expired.rows) {
    const rawPath = r.file_path;
    try { await fs.promises.unlink(rawPath); }
    catch (e) { if (e.code !== 'ENOENT') { log.error(...); failed++; continue; } }
    // Phase 22 D-03: mirror-delete burnt twin. ENOENT acceptable (gap over noise).
    if (rawDir && burntDir && rawPath.startsWith(rawDir)) {
        const burntPath = burntDir + rawPath.slice(rawDir.length);
        try { await fs.promises.unlink(burntPath); }
        catch (e) {
            if (e.code !== 'ENOENT') {
                log.error('[retention/burnt] unlink failed for ' + burntPath + ': ' + e.message);
            }
        }
    }
    await pool.query("DELETE FROM snapshots WHERE file_path = $1", [rawPath]);
    deleted++;
}
```

Signature extended with `rawDir = null, burntDir = null` params (back-compat: absence yields prior behavior). `index.js` `prunerArgs` builder now passes `rawDir: SNAPSHOT_DIR, burntDir: SNAPSHOT_BURNT_DIR` — the scheduler and startup-tick both get the mirror-delete behavior.

## Test output summary

`cd src/mission-control/bridge && npm test`:

```
Test Suites: 4 passed, 4 total
Tests:       44 passed, 44 total
Time:        1.68 s
```

Breakdown:
- `test/burn_bar.test.js` — 8 new (formatBarText × 6, burnBar × 2)
- `test/retention.test.js` — 12 (9 pre-existing + 3 new: mirror-delete, ENOENT-on-burnt, back-compat-no-args)
- `test/history.test.js` — pre-existing, still pass
- `test/snapshot.test.js` — pre-existing, still pass

`node -c src/index.js` and `node -c src/retention.js` both exit 0.

## Must-have coverage

| Must-have | Status |
|-----------|--------|
| Every saveSnapshot() writes raw JPEG + burnt twin with same filename | ✓ code + unit-test-covered burn_bar produces valid JPEG |
| Burnt JPEG bottom bar has ISO + RH + T + CO₂ + humidifier ON/OFF | ✓ formatBarText pure-tested with 6 cases |
| Null / undefined sensor → en-dash, never fabricated 0 | ✓ 2 dedicated test cases (all-null + NaN) |
| snapshots DB schema unchanged | ✓ `CREATE TABLE IF NOT EXISTS snapshots` unchanged; `git diff ... INSERT INTO snapshots` count = 0 |
| Raw write + DB insert never blocked by failed burnt write | ✓ IIFE with internal try/catch; no await from outer callback |
| retention.js prune deletes burnt twin alongside raw | ✓ code + 3 unit tests |
| burn_bar.js artifact + exports formatBarText + burnBar | ✓ |
| index.js contains SNAPSHOT_BURNT_DIR | ✓ 5 occurrences (const, guard, saveSnapshot, 2 prunerArgs) |
| retention.js contains snapshots-burnt path derivation | ✓ via rawDir/burntDir swap (3 refs each) |

## Acceptance-criteria grep receipts

```
grep -c SNAPSHOT_BURNT_DIR src/index.js        → 5  (>= 3 req)
grep -c require.*burn_bar src/index.js         → 1  (== 1 req)
grep -c [camera/burnt] src/index.js            → 3  (>= 1 req)
grep -c formatBarText src/index.js             → 2  (>= 1 req)
grep -cE snapshots-burnt src/index.js          → 1  (>= 1 req)
grep -c CREATE TABLE.*snapshots src/index.js   → 1  (== 1 unchanged)
grep -cE burntDir src/retention.js             → 3  (>= 2 req)
grep -c rawDir src/retention.js                → 3  (>= 2 req)
git diff src/index.js | grep ^\+.*INSERT INTO snapshots  → 0  (== 0 req)
grep -c — src/burn_bar.js                      → 3  (>= 1 req)
grep -cE toFixed\(1\) src/burn_bar.js          → 1  (>= 1 req)
```

All constraints met.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] burn_bar.test.js location: `test/` not `src/`**
- **Found during:** Task 1 pre-work (jest config inspection)
- **Issue:** Plan's acceptance criterion required the test at `src/mission-control/bridge/src/burn_bar.test.js`, but the bridge's `jest.config.js` has `testMatch: ['**/test/**/*.test.js']` — a file under `src/` would be invisible to `npm test` / `npx jest`.
- **Fix:** Placed the test at `test/burn_bar.test.js` alongside the pre-existing `retention.test.js`, `snapshot.test.js`, `history.test.js`. All other acceptance requirements (test count ≥5, content, pass status) satisfied at the new location.
- **Files modified:** `test/burn_bar.test.js` (new, in place of the plan's specified path)
- **Commit:** `8501d0b`

**2. [Rule 3 - Blocking] `--experimental-vm-modules` required for jest + jimp v1**
- **Found during:** Task 1 GREEN run
- **Issue:** `Jimp.read` internally calls `import('file-type')` (dynamic ESM import). Jest's default CJS VM throws `TypeError: A dynamic import callback was invoked without --experimental-vm-modules`. The burnBar JPEG-roundtrip test cannot run without the flag.
- **Fix:** Changed `package.json`'s `test` script from `"jest"` to `"node --experimental-vm-modules node_modules/.bin/jest"`. Flag is a no-op for the non-jimp test suites — all 44 tests still pass (verified).
- **Files modified:** `src/mission-control/bridge/package.json`
- **Commit:** `810cfc7`

**3. [Rule 2 - Missing coverage] Added 3 retention tests for mirror-delete**
- **Found during:** Task 2
- **Issue:** Plan said "extend retention tests ONLY IF they exist" — they did exist (`test/retention.test.js`). The new `rawDir`/`burntDir` branch was untested.
- **Fix:** Added 3 cases covering: happy-path mirror-delete, ENOENT on burnt twin (non-fatal), back-compat (no rawDir/burntDir → original behavior).
- **Commit:** `092b8d4`

### Intentional structural choices the plan called out

- **jimp v1 API import shape:** plan flagged this as "verify at start of task" — confirmed `const { Jimp, JimpMime, loadFont } = require('jimp')` + `const fonts = require('jimp/fonts')` is the correct v1 shape (`SANS_16_WHITE` etc. live on `jimp/fonts`, not on `Jimp.FONT_*`).
- **`print` uses object-style args** in jimp v1: `img.print({ font, x, y, text, maxWidth })` — plan pseudocode used positional args, which fail at runtime. Corrected in implementation.
- **`fmtNum` + `fmtHum` also exported** (not just `formatBarText` / `burnBar`) — useful for future unit tests and for DRY if index.js ever needs the helpers directly.

## Commits

- `8501d0b` test(22-02): add failing tests for burn_bar module — TDD RED gate
- `810cfc7` feat(22-02): implement burn_bar module (formatBarText + burnBar) — TDD GREEN gate
- `092b8d4` feat(22-02): wire burn-in into saveSnapshot + mirror prune in retention

## TDD Gate Compliance

- RED: `8501d0b` (test-only commit before implementation) — ✓
- GREEN: `810cfc7` (implementation + test script fix) — ✓
- REFACTOR: not needed; implementation landed clean and tests passed first try after GREEN

## Deferred / still pending (by design)

- **Live rebuild of bridge container** — plan 22-04 handles `docker compose up -d --build bridge` + runtime verification that burnt JPEGs appear on disk. Intentionally skipped here per the plan's no-rebuild clause.
- **`/camera/frame` route** — plan 22-03 adds the GET endpoint that serves burnt-by-default with `?raw=true` escape hatch.
- **farmOS CLAUDE-SYNC handoff entry** — deferred to plan 22-04 (rebuild + coordination).

## Self-Check: PASSED

- File `src/mission-control/bridge/src/burn_bar.js` exists ✓
- File `src/mission-control/bridge/test/burn_bar.test.js` exists ✓
- `module.exports` in burn_bar.js includes `formatBarText` and `burnBar` ✓
- `src/mission-control/bridge/src/index.js` has `require('./burn_bar')` and `SNAPSHOT_BURNT_DIR` ✓
- `src/mission-control/bridge/src/retention.js` has `rawDir` + `burntDir` params ✓
- `git log --oneline` shows commits `8501d0b`, `810cfc7`, `092b8d4` ✓
- `cd src/mission-control/bridge && npm test` → 44 passed, 0 failed ✓
- `node -c src/index.js` → exit 0 ✓
- `node -c src/retention.js` → exit 0 ✓
