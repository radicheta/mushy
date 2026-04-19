// Phase 21 D-06a: pure param validation for GET /camera/history.
// Per RESEARCH Q3 (RESOLVED): from/to are ISO-8601 strings.
function validateHistoryParams(query, allowedCameraId, maxRangeMs) {
    if (!query.from || !query.to) {
        return { ok: false, status: 400, error: 'from and to query params required (ISO-8601)' };
    }
    const from = Date.parse(query.from);
    const to = Date.parse(query.to);
    const cameraId = (query.camera_id || allowedCameraId).toString();
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return { ok: false, status: 400, error: 'from and to must be valid ISO-8601 timestamps' };
    }
    if (to < from) {
        return { ok: false, status: 400, error: 'to must be >= from' };
    }
    if (to - from > maxRangeMs) {
        return { ok: false, status: 400, error: 'Max range is 30 days' };
    }
    if (cameraId !== allowedCameraId) {
        return { ok: false, status: 400, error: 'Invalid camera_id' };
    }
    return { ok: true, parsed: { from, to, cameraId, fromIso: new Date(from).toISOString(), toIso: new Date(to).toISOString() } };
}
module.exports = { validateHistoryParams };
