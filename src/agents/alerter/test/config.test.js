'use strict';

const { load, maskNumber } = require('../src/config');

const BASE_ENV = {
  SIGNAL_SENDER: '+1',
  SIGNAL_RECIPIENT: '+2',
  TIMESCALE_PASSWORD: 'testpw',
  ANTHROPIC_API_KEY: 'sk-test',
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

describe('maskNumber', () => {
  test('Test E: masks middle digits, preserves first 2 and last 4, correct length', () => {
    const result = maskNumber('+15551234567');
    expect(result).not.toContain('1234');
    expect(result).toContain('4567');
    expect(result.length).toBe(12);
  });
});
