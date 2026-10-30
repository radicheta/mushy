const { FC2_TOPICS, FC2_DB_TOPICS, subscribeFc2 } = require('../src/fc2');
function fakeNode() { const subs = []; return { subs, createSubscription: (type, topic, a, b) => subs.push({ type, topic, opts: b ? a : undefined, cb: b || a }) }; }

test('every db topic is fc2.-prefixed and unique', () => {
  expect(FC2_DB_TOPICS.every(t => t.startsWith('fc2.'))).toBe(true);
  expect(new Set(FC2_DB_TOPICS).size).toBe(FC2_DB_TOPICS.length);
  expect(FC2_DB_TOPICS).toContain('fc2.duty_pct_1h');
});
test('valve is latched and stored as 1/0', async () => {
  const n = fakeNode(); const ins = jest.fn(); const q = { q: 1 };
  const bc = jest.fn();
  subscribeFc2(n, { insertTelemetry: ins, broadcast: bc, transientLocalQos: q, now: () => 1000 });
  const v = n.subs.find(s => s.topic === '/fc2/valve');
  expect(v.opts).toEqual({ qos: q });
  await v.cb({ data: true });
  expect(ins).toHaveBeenCalledWith('fc2.valve', 1, 1000, 1000 * 1e6);
  expect(bc).toHaveBeenCalledWith({ 'fc2.valve': 1, timestamp: 1000 });
});
test('live broadcast never uses an FC-1 field name', async () => {
  const FC1_FIELDS = ['humidity', 'temperature', 'co2', 'humidifier', 'humidity_2', 'temperature_2',
    'humidifier_duty', 'humidity_target', 'pid_output', 'vpd', 'water_vapor'];
  const n = fakeNode(); const bc = jest.fn();
  subscribeFc2(n, { insertTelemetry: jest.fn(), broadcast: bc, transientLocalQos: {}, now: () => 1 });
  for (const s of n.subs) await s.cb({ data: 1 });
  const keys = bc.mock.calls.flatMap(([m]) => Object.keys(m));
  expect(keys.some(k => FC1_FIELDS.includes(k))).toBe(false);
});
test('float topics store msg.data', async () => {
  const n = fakeNode(); const ins = jest.fn();
  subscribeFc2(n, { insertTelemetry: ins, broadcast: jest.fn(), transientLocalQos: {}, now: () => 5 });
  await n.subs.find(s => s.topic === '/fc2/duty_pct_1h').cb({ data: 1.5 });
  expect(ins).toHaveBeenCalledWith('fc2.duty_pct_1h', 1.5, 5, 5e6);
});
test('a createSubscription that throws drops only its own topic', () => {
  const subs = [];
  const node = { createSubscription: (type, topic, a, b) => {
    if (topic === '/fc2/weather/wind') throw new Error('boom');
    subs.push(topic);
  } };
  const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
  expect(() => subscribeFc2(node, { insertTelemetry: jest.fn(), broadcast: jest.fn(), transientLocalQos: {} })).not.toThrow();
  expect(warn).toHaveBeenCalledWith('[fc2] subscribe failed for /fc2/weather/wind: boom');
  warn.mockRestore();
  expect(subs.length).toBe(FC2_TOPICS.length - 1);
  expect(subs).not.toContain('/fc2/weather/wind');
});
test('insertTelemetry rejecting still broadcasts', async () => {
  const n = fakeNode(); const bc = jest.fn();
  const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
  subscribeFc2(n, { insertTelemetry: jest.fn().mockRejectedValue(new Error('db')), broadcast: bc, transientLocalQos: {}, now: () => 7 });
  await n.subs.find(s => s.topic === '/fc2/mode').cb({ data: 2 });
  warn.mockRestore();
  expect(bc).toHaveBeenCalledWith({ 'fc2.mode': 2, timestamp: 7 });
});
