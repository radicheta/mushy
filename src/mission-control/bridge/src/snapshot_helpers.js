// Phase 21: pure decision helpers for saveSnapshot — unit-testable without
// requiring the full bridge (which side-effect-inits ROS at require time).
function decideSource(mjpegClientsSize) {
    return mjpegClientsSize > 0 ? 'viewer' : 'idle';
}
function shouldSkipSnapshot({ latestFrame, lastFrameTime, now, maxAgeMs }) {
    if (!latestFrame) return true;
    if (!lastFrameTime) return true;
    return (now - lastFrameTime) > maxAgeMs;
}
module.exports = { decideSource, shouldSkipSnapshot };
