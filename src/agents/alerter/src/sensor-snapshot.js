'use strict';

// Phase 25: rolling sensor snapshot for LLM grounding (D-11).
// Read-only consumer of bridge /farmer/summary. Returns null on any failure
// (non-200, timeout, parse error, network error) — never throws.

function createSensorSnapshotFetcher({ bridgeUrl, timeoutMs = 2000, logger = console }) {
  return async function fetchSnapshot() {
    try {
      const res = await fetch(`${bridgeUrl}/farmer/summary`, {
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) {
        logger.warn(`[sensor-snapshot] ${res.status}`);
        return null;
      }
      return await res.json();
    } catch (e) {
      logger.warn(`[sensor-snapshot] ${e.name}: ${e.message}`);
      return null;
    }
  };
}

module.exports = { createSensorSnapshotFetcher };
