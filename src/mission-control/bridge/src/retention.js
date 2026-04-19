// Phase 21 D-04: retention for snapshots.
// unlink then DELETE; ENOENT treated as success. Other errors leave both in place.
const DEFAULT_RETENTION_DAYS = 365;
const DEFAULT_GRACE_DAYS = 30;
const MIN_RETENTION_DAYS = 30;
const DEFAULT_BATCH_LIMIT = 10000;

function clampRetentionDays(requested, floor = MIN_RETENTION_DAYS) {
    const n = parseInt(requested, 10);
    if (!Number.isFinite(n) || n < floor) return floor;
    return n;
}

function shouldPrune({ oldestDays, graceDays }) {
    if (oldestDays === null || oldestDays === undefined) return false;
    return oldestDays >= graceDays;
}

async function runPrune({
    pool, fs, now,
    retentionDays = DEFAULT_RETENTION_DAYS,
    graceDays = DEFAULT_GRACE_DAYS,
    batchLimit = DEFAULT_BATCH_LIMIT,
    log = console
}) {
    const effectiveRetention = clampRetentionDays(retentionDays);
    const ageCheck = await pool.query(
        "SELECT EXTRACT(EPOCH FROM (NOW() - MIN(captured_at)))/86400 AS days FROM snapshots"
    );
    const row = ageCheck.rows[0];
    const oldestDays = row && row.days !== null && row.days !== undefined ? parseFloat(row.days) : null;
    if (!shouldPrune({ oldestDays, graceDays })) {
        log.log('[retention] skip — oldest snapshot ' + oldestDays + ' days (grace ' + graceDays + ')');
        return { skipped: true, deleted: 0, failed: 0 };
    }
    const cutoff = new Date(now() - effectiveRetention * 86400 * 1000);
    const expired = await pool.query(
        "SELECT file_path FROM snapshots WHERE captured_at < $1 LIMIT $2",
        [cutoff, batchLimit]
    );
    let deleted = 0, failed = 0;
    for (const r of expired.rows) {
        try { await fs.promises.unlink(r.file_path); }
        catch (e) {
            if (e.code !== 'ENOENT') {
                log.error('[retention] unlink failed for ' + r.file_path + ': ' + e.message);
                failed++; continue;
            }
        }
        await pool.query("DELETE FROM snapshots WHERE file_path = $1", [r.file_path]);
        deleted++;
    }
    log.log('[retention] pruned ' + deleted + ' snapshots older than ' + effectiveRetention + ' days (' + failed + ' failed)');
    return { skipped: false, deleted, failed };
}

module.exports = {
    clampRetentionDays, shouldPrune, runPrune,
    DEFAULT_RETENTION_DAYS, DEFAULT_GRACE_DAYS, MIN_RETENTION_DAYS
};
