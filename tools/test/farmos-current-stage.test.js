'use strict';

const { deriveStage, parseArgs } = require('../farmos-current-stage');

function activity(id, name, ts) {
  return { id, type: 'activity', attributes: { name, timestamp: ts } };
}
function seeding(id, ts) {
  return { id, type: 'seeding', attributes: { name: 'inoculation', timestamp: ts } };
}
function observation(id, ts) {
  return { id, type: 'observation', attributes: { name: 'contam_check', timestamp: ts } };
}

describe('parseArgs', () => {
  test('returns help when no args', () => {
    expect(parseArgs(['node', 'x']).help).toBe(true);
  });
  test('positional uuid + --at', () => {
    const r = parseArgs(['node', 'x', 'abc-uuid', '--at', '2026-05-20T10:00:00Z']);
    expect(r.uuid).toBe('abc-uuid');
    expect(r.at).toBe('2026-05-20T10:00:00Z');
  });
});

describe('deriveStage C1', () => {
  test('pre-inoc: empty log list', () => {
    expect(deriveStage([]).stage).toBe('pre-inoc');
  });

  test('colonizing: seeding log present, no later transitions', () => {
    const logs = [seeding('s1', '2026-05-13T10:00Z')];
    const r = deriveStage(logs);
    expect(r.stage).toBe('colonizing');
    expect(r.evidence.id).toBe('s1');
  });

  test('colonizing: observation logs do not advance stage', () => {
    const logs = [
      seeding('s1', '2026-05-13T10:00Z'),
      observation('o1', '2026-05-20T10:00Z'),
      observation('o2', '2026-05-27T10:00Z'),
    ];
    expect(deriveStage(logs).stage).toBe('colonizing');
  });

  test('fruiting: cold_shock activity advances from colonizing', () => {
    const logs = [
      seeding('s1', '2026-05-13T10:00Z'),
      activity('a1', 'cold_shock', '2026-06-10T10:00Z'),
    ];
    const r = deriveStage(logs);
    expect(r.stage).toBe('fruiting');
    expect(r.evidence.name).toBe('cold_shock');
  });

  test('spent: archive_spent terminal', () => {
    const logs = [
      seeding('s1', '2026-05-13T10:00Z'),
      activity('a1', 'cold_shock', '2026-06-10T10:00Z'),
      activity('a2', 'archive_spent', '2026-07-01T10:00Z'),
    ];
    expect(deriveStage(logs).stage).toBe('spent');
  });

  test('contaminated: contam terminal', () => {
    const logs = [
      seeding('s1', '2026-05-13T10:00Z'),
      activity('a1', 'contam', '2026-05-20T10:00Z'),
    ];
    expect(deriveStage(logs).stage).toBe('contaminated');
  });

  test('contaminated locks even if later logs filed', () => {
    const logs = [
      seeding('s1', '2026-05-13T10:00Z'),
      activity('a1', 'contam', '2026-05-20T10:00Z'),
      activity('a2', 'cold_shock', '2026-05-25T10:00Z'),
    ];
    expect(deriveStage(logs).stage).toBe('contaminated');
  });

  test('relocate activity does not advance stage', () => {
    const logs = [
      seeding('s1', '2026-05-13T10:00Z'),
      activity('a1', 'relocate', '2026-05-25T10:00Z'),
    ];
    expect(deriveStage(logs).stage).toBe('colonizing');
  });
});
