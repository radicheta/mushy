// Phase 22 D-02: pure param validation for GET /camera/frame.
// at = ISO-8601 timestamp (required). camera_id = allowlist (defaults to CAMERA_ID). raw = 'true' flag.
// Deliberately does NOT accept file_path (path-traversal concern — see 22-CONTEXT.md L124-L126).
function validateFrameParams(query, allowedCameraId) {
    if (!query.at) {
        return { ok: false, status: 400, error: 'at query param required (ISO-8601)' };
    }
    const atMs = Date.parse(query.at);
    if (!Number.isFinite(atMs)) {
        return { ok: false, status: 400, error: 'at must be a valid ISO-8601 timestamp' };
    }
    const cameraId = (query.camera_id || allowedCameraId).toString();
    if (cameraId !== allowedCameraId) {
        return { ok: false, status: 400, error: 'Invalid camera_id' };
    }
    const raw = query.raw === 'true';
    return { ok: true, parsed: { at: new Date(atMs), cameraId, raw } };
}
module.exports = { validateFrameParams };
