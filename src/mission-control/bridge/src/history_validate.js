// Phase 21 D-06a: pure param validation for GET /camera/history.
// Separated from index.js to keep it unit-testable without an express mock.
function validateHistoryParams(query, allowedCameraId, maxRangeMs) {
    const from = parseInt(query.from, 10);
    const to = parseInt(query.to, 10);
    const cameraId = (query.camera_id || allowedCameraId).toString();
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return { ok: false, status: 400, error: 'from and to query params required (ms epoch)' };
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
    return { ok: true, parsed: { from, to, cameraId } };
}
module.exports = { validateHistoryParams };
