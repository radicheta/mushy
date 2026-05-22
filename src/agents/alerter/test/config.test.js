'use strict';

const { load, maskNumber } = require('../src/config');

// Phase 44 D-11: TENANT_ID='__none__' opts the legacy tests out of the new
// layered loader (no such tenant dir → empty tenant config). Existing tests
// that assert env-only behavior MUST use this base so the just-shipped
// tenants/mossrock/config.yaml does not override their synthetic env.
const BASE_ENV = {
  SIGNAL_SENDER: '+1',
  SIGNAL_RECIPIENT: '+2',
  TIMESCALE_PASSWORD: 'testpw',
  ANTHROPIC_API_KEY: 'sk-test',
  TENANT_ID: '__none__',
};

describe('config.load', () => {
  test('Test A: returns object with all fields populated from defaults', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.bridgeWsUrl).toBe('ws://host.docker.internal:8081');
    expect(cfg.bridgeHealthUrl).toBe('http://host.docker.internal:8081/health');
    expect(cfg.signalApiUrl).toBe('http://signal-cli:8080');
    expect(cfg.signalSender).toBe('+1');
    expect(cfg.signalRecipient).toBe('+2');
    expect(cfg.rhTarget).toBe(90);
    expect(cfg.rhBand).toBe(3);
    expect(cfg.oobN).toBe(5);
    expect(cfg.oobWindowMin).toBe(3);
    expect(cfg.cooldownMin).toBe(30);
    expect(cfg.criticalCooldownMin).toBe(60);
    expect(cfg.piOfflineMin).toBe(5);
    expect(cfg.humidifierStuckMin).toBe(30);
    expect(cfg.heartbeatHour).toBe(8);
    expect(cfg.receivePollSec).toBe(30);
    expect(cfg.maxSendsPerHour).toBe(20);
    expect(cfg.timezone).toBe('America/Toronto');
    expect(cfg.dashboardUrl).toBe('http://elder-plops-ts:8081/farmer');
    expect(cfg.logLevel).toBe('info');
  });

  test('Test B: load({}) throws mentioning SIGNAL_SENDER', () => {
    expect(() => load({})).toThrow('SIGNAL_SENDER');
  });

  test('Test C: ALERT_RH_TARGET parsed as float', () => {
    const cfg = load({ ...BASE_ENV, ALERT_RH_TARGET: '92.5' });
    expect(cfg.rhTarget).toBe(92.5);
  });

  test('Test D: non-numeric ALERT_OOB_N throws', () => {
    expect(() => load({ ...BASE_ENV, ALERT_OOB_N: 'not-a-number' })).toThrow();
  });

  // Phase 25 tests
  test('Test F: throws when TIMESCALE_PASSWORD missing', () => {
    const env = { ...BASE_ENV };
    delete env.TIMESCALE_PASSWORD;
    expect(() => load(env)).toThrow('TIMESCALE_PASSWORD');
  });

  test('Test G: throws when ANTHROPIC_API_KEY missing', () => {
    const env = { ...BASE_ENV };
    delete env.ANTHROPIC_API_KEY;
    expect(() => load(env)).toThrow('ANTHROPIC_API_KEY');
  });

  test('Test H: Phase 25 defaults', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.timescaleHost).toBe('host.docker.internal');
    expect(cfg.whisperUrl).toBe('http://host.docker.internal:8090');
    expect(cfg.captureBaseDir).toBe('/data/signal-capture');
    expect(cfg.bridgeHttpUrl).toBe('http://host.docker.internal:8081');
    expect(cfg.captureRetentionDays).toBe(30);
    expect(cfg.captureRetentionCron).toBe('15 3 * * *');
  });

  test('Test I: Phase 25 env overrides', () => {
    const cfg = load({
      ...BASE_ENV,
      TIMESCALE_HOST: 'myhost',
      WHISPER_URL: 'http://mywhisper:9000',
      CAPTURE_BASE_PATH: '/mnt/data/capture',
      BRIDGE_HTTP_URL: 'http://mybridge:8082',
      CAPTURE_RETENTION_DAYS: '60',
      CAPTURE_RETENTION_CRON: '0 2 * * *',
    });
    expect(cfg.timescaleHost).toBe('myhost');
    expect(cfg.whisperUrl).toBe('http://mywhisper:9000');
    expect(cfg.captureBaseDir).toBe('/mnt/data/capture');
    expect(cfg.bridgeHttpUrl).toBe('http://mybridge:8082');
    expect(cfg.captureRetentionDays).toBe(60);
    expect(cfg.captureRetentionCron).toBe('0 2 * * *');
  });

  test('Test J: non-integer CAPTURE_RETENTION_DAYS throws', () => {
    expect(() => load({ ...BASE_ENV, CAPTURE_RETENTION_DAYS: 'bad' })).toThrow();
  });
});

describe('Phase 37: parseFarmerMap + signalGroupId + signalFarmerMap', () => {
  test('signalGroupId === null when SIGNAL_GROUP_ID unset', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.signalGroupId).toBeNull();
  });

  test('signalGroupId reflects env value (bare base64, no prefix normalization)', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_GROUP_ID: 'Z3JvdXBfaWQ=' });
    expect(cfg.signalGroupId).toBe('Z3JvdXBfaWQ=');
  });

  test('signalFarmerMap is empty Map when SIGNAL_FARMER_MAP unset', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.signalFarmerMap).toBeInstanceOf(Map);
    expect(cfg.signalFarmerMap.size).toBe(0);
  });

  test('signalFarmerMap parses single entry', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_FARMER_MAP: '+5982:f1' });
    expect(cfg.signalFarmerMap.size).toBe(1);
    expect(cfg.signalFarmerMap.get('+5982')).toBe('f1');
  });

  test('signalFarmerMap parses three entries', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_FARMER_MAP: '+5982:f1,+5983:zoy,+5984:f3' });
    expect(cfg.signalFarmerMap.size).toBe(3);
    expect(cfg.signalFarmerMap.get('+5983')).toBe('zoy');
  });

  test('signalFarmerMap trims whitespace', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_FARMER_MAP: '+5982:f1, +5983:zoy , +5984:f3' });
    expect(cfg.signalFarmerMap.size).toBe(3);
    expect(cfg.signalFarmerMap.get('+5983')).toBe('zoy');
  });

  test('signalFarmerMap drops empty and malformed entries', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_FARMER_MAP: '+5982:f1,,malformed,+5983:zoy' });
    expect(cfg.signalFarmerMap.size).toBe(2);
    expect(cfg.signalFarmerMap.get('+5982')).toBe('f1');
    expect(cfg.signalFarmerMap.get('+5983')).toBe('zoy');
  });

  test('signalFarmerMap drops entries with no colon', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_FARMER_MAP: 'justAphone' });
    expect(cfg.signalFarmerMap.size).toBe(0);
  });

  test('signalFarmerMap drops entries with empty phone', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_FARMER_MAP: ':orphanslug' });
    expect(cfg.signalFarmerMap.size).toBe(0);
  });

  test('signalFarmerMap drops entries with empty slug', () => {
    const cfg = load({ ...BASE_ENV, SIGNAL_FARMER_MAP: '+5982:' });
    expect(cfg.signalFarmerMap.size).toBe(0);
  });
});

describe('Phase 38: extraction knobs', () => {
  test('extractionConfidenceThreshold defaults to 0.7', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.extractionConfidenceThreshold).toBe(0.7);
  });

  test('draftIdleGapMin defaults to 30', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.draftIdleGapMin).toBe(30);
  });

  test('maxAskbackTurns defaults to 3', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.maxAskbackTurns).toBe(3);
  });

  test('EXTRACTION_CONFIDENCE_THRESHOLD env override picked up', () => {
    const cfg = load({ ...BASE_ENV, EXTRACTION_CONFIDENCE_THRESHOLD: '0.85' });
    expect(cfg.extractionConfidenceThreshold).toBe(0.85);
  });

  test('DRAFT_IDLE_GAP_MIN env override picked up', () => {
    const cfg = load({ ...BASE_ENV, DRAFT_IDLE_GAP_MIN: '45' });
    expect(cfg.draftIdleGapMin).toBe(45);
  });

  test('MAX_ASKBACK_TURNS env override picked up', () => {
    const cfg = load({ ...BASE_ENV, MAX_ASKBACK_TURNS: '5' });
    expect(cfg.maxAskbackTurns).toBe(5);
  });

  test('out-of-range threshold (negative) falls back to default 0.7', () => {
    const cfg = load({ ...BASE_ENV, EXTRACTION_CONFIDENCE_THRESHOLD: '-0.5' });
    expect(cfg.extractionConfidenceThreshold).toBe(0.7);
  });

  test('out-of-range threshold (>1) falls back to default 0.7', () => {
    const cfg = load({ ...BASE_ENV, EXTRACTION_CONFIDENCE_THRESHOLD: '1.5' });
    expect(cfg.extractionConfidenceThreshold).toBe(0.7);
  });
});

describe('Phase 39 confirm-loop knobs', () => {
  let warnSpy;
  beforeEach(() => {
    warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
  });
  afterEach(() => {
    warnSpy.mockRestore();
  });

  test('Phase 39 defaults', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.draftPendingTimeoutMin).toBe(30);
    expect(cfg.draftNudgeFraction).toBe(0.8);
    expect(cfg.draftWatchdogIntervalMs).toBe(60000);
    expect(cfg.maxEditTurns).toBe(3);
  });

  test('Phase 39 env overrides', () => {
    const cfg = load({
      ...BASE_ENV,
      DRAFT_PENDING_TIMEOUT_MIN: '45',
      DRAFT_NUDGE_FRACTION: '0.75',
      DRAFT_WATCHDOG_INTERVAL_MS: '30000',
      MAX_EDIT_TURNS: '5',
    });
    expect(cfg.draftPendingTimeoutMin).toBe(45);
    expect(cfg.draftNudgeFraction).toBe(0.75);
    expect(cfg.draftWatchdogIntervalMs).toBe(30000);
    expect(cfg.maxEditTurns).toBe(5);
  });

  test('DRAFT_NUDGE_FRACTION clamps out-of-range to 0.8', () => {
    expect(load({ ...BASE_ENV, DRAFT_NUDGE_FRACTION: '1.5' }).draftNudgeFraction).toBe(0.8);
    expect(load({ ...BASE_ENV, DRAFT_NUDGE_FRACTION: '-0.1' }).draftNudgeFraction).toBe(0.8);
    expect(load({ ...BASE_ENV, DRAFT_NUDGE_FRACTION: '0' }).draftNudgeFraction).toBe(0.8);
    expect(load({ ...BASE_ENV, DRAFT_NUDGE_FRACTION: '1' }).draftNudgeFraction).toBe(0.8);
  });

  test('returned object is frozen', () => {
    'use strict';
    const cfg = load({ ...BASE_ENV });
    expect(() => { cfg.maxEditTurns = 99; }).toThrow();
  });
});

// Phase 44 TENANT-01 — layered tenant-file → env → default loader.
//
// MOSSROCK_ENV: drops TENANT_ID='__none__' from BASE_ENV so tests can opt in
// to the just-shipped tenants/mossrock/ fixtures (the production default).
describe('Phase 44: layered tenant loader', () => {
  const MOSSROCK_ENV = (() => { const e = { ...BASE_ENV }; delete e.TENANT_ID; return e; })();

  test('B1: load(env) signature preserved — synthetic env still works (TENANT_ID=__none__)', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.signalSender).toBe('+1');
    expect(cfg.signalRecipient).toBe('+2');
    expect(Object.isFrozen(cfg)).toBe(true);
  });

  test('B2: tenantId defaults to "mossrock" when TENANT_ID unset', () => {
    const cfg = load({ ...MOSSROCK_ENV });
    expect(cfg.tenantId).toBe('mossrock');
  });

  test('B3: tenant file overrides env when both present (mossrock has EVENT_GATE_CONVO_MODE=silent)', () => {
    // tenant_id defaults to mossrock; env tries to set "off"; tenant wins.
    const cfg = load({ ...MOSSROCK_ENV, EVENT_GATE_CONVO_MODE: 'off' });
    expect(cfg.eventGateConvoMode).toBe('silent');
  });

  test('B4: env overrides default when tenant file missing (TENANT_ID=__none__)', () => {
    const cfg = load({ ...BASE_ENV, EVENT_GATE_CONVO_MODE: 'negative_only' });
    expect(cfg.eventGateConvoMode).toBe('negative_only');
  });

  test('B5: default when both tenant and env missing (TENANT_ID=__none__)', () => {
    const cfg = load({ ...BASE_ENV });
    expect(cfg.eventGateConvoMode).toBe('silent');
  });

  test('B6: strains is the 14-element array from tenants/mossrock/strains.yaml', () => {
    const cfg = load({ ...MOSSROCK_ENV });
    expect(Array.isArray(cfg.strains)).toBe(true);
    expect(cfg.strains).toHaveLength(14);
    expect(cfg.strains[0]).toBe('SHI');
    expect(cfg.strains).toContain('LIMA');
  });

  test('B7: eventGateConvoMode field exists on the frozen object', () => {
    const cfg = load({ ...MOSSROCK_ENV });
    expect(cfg).toHaveProperty('eventGateConvoMode');
    expect(typeof cfg.eventGateConvoMode).toBe('string');
  });

  test('B8: tenantId field exists on the frozen object (consumed by signal.js Plan-02)', () => {
    const cfg = load({ ...MOSSROCK_ENV });
    expect(cfg).toHaveProperty('tenantId');
    expect(typeof cfg.tenantId).toBe('string');
  });

  test('B9: secrets still come from env (anthropicApiKey via mustEnv even when tenant file present)', () => {
    // Even though tenants/mossrock/config.yaml is read, ANTHROPIC_API_KEY is NOT
    // sourced from there — it MUST come from env (mustEnv). Remove it → throws.
    const env = { ...MOSSROCK_ENV };
    delete env.ANTHROPIC_API_KEY;
    expect(() => load(env)).toThrow('ANTHROPIC_API_KEY');
    // And when present, it resolves to the env value (not anything from tenant file).
    const cfg = load({ ...MOSSROCK_ENV });
    expect(cfg.anthropicApiKey).toBe('sk-test');
  });

  test('B4-FIELD-SURFACE: all 12 frozen-config fields are !== undefined with fixtures + 3 secret env vars', () => {
    const cfg = load({ ...MOSSROCK_ENV, FARMOS_PASSWORD: 'fpw-test' });
    const required = [
      'anthropicApiKey',
      'farmosPassword',
      'farmosUrl',
      'farmosUsername',
      'farmosIntegration',
      'signalSender',
      'signalRecipient',
      'signalGroupId',
      'signalFarmerMap',
      'strains',
      'eventGateConvoMode',
      'tenantId',
    ];
    for (const k of required) {
      expect(cfg[k]).not.toBeUndefined();
    }
  });

  test('B-W9: SIGNAL_FARMER_MAP from tenant YAML loads as a Map<phone, slug>', () => {
    const cfg = load({ ...MOSSROCK_ENV });
    expect(cfg.signalFarmerMap).toBeInstanceOf(Map);
    // tenants/mossrock/config.yaml seeds Santi + bot.
    expect(cfg.signalFarmerMap.get('+59892893012')).toBe('f1');
    expect(cfg.signalFarmerMap.get('+59891840205')).toBe('bot');
  });

  test('B-T-44-06-02: TENANT_ID path traversal cannot escape tenants/ base', () => {
    // Even if attacker sets TENANT_ID='../etc', loadTenantFile must return {}.
    // Trip-wire: synthetic env passing through; no throw, and eventGateConvoMode
    // falls back to default 'silent' (no foreign file got read).
    const cfg = load({ ...BASE_ENV, TENANT_ID: '../../../etc' });
    expect(cfg.eventGateConvoMode).toBe('silent');
    expect(cfg.tenantId).toBe('../../../etc'); // recorded as-is, but no file resolved
  });
});

describe('maskNumber', () => {
  test('Test E: masks middle digits, preserves first 2 and last 4, correct length', () => {
    const result = maskNumber('+15551234567');
    expect(result).not.toContain('1234');
    expect(result).toContain('4567');
    expect(result.length).toBe(12);
  });
});
