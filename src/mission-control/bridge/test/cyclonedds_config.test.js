// MUSHY-170: the bridge's DDS peer list is the repo file, baked into the image.
//
// Prod used to mount a host file (~/.config/cyclonedds.xml) over it, so the
// repo copy was dead: MUSHY-168 merged FC-2's peer and the bridge still could
// not see FC-2 until the host file was edited by hand.
const fs = require('fs');
const path = require('path');

const BRIDGE = path.resolve(__dirname, '..');
const ROOT = path.resolve(BRIDGE, '../../..');
const xml = fs.readFileSync(path.join(BRIDGE, 'cyclonedds.xml'), 'utf8');
const override = fs.readFileSync(path.join(ROOT, 'docker-compose.override.yml'), 'utf8');
const dockerfile = fs.readFileSync(path.join(BRIDGE, 'Dockerfile'), 'utf8');

// Only the bridge: service block, comment lines dropped.
const bridgeBlock = override
  .split(/\n(?=  \S)/)
  .find((b) => b.startsWith('  bridge:'))
  .split('\n')
  .filter((ln) => !ln.trim().startsWith('#'))
  .join('\n');

test('bridge reads the cyclonedds.xml the Dockerfile copies in', () => {
  expect(dockerfile).toMatch(/COPY src\/mission-control\/bridge\/ \.\/\n/);
  expect(dockerfile).toMatch(/WORKDIR \/opt\/bridge/);
  expect(bridgeBlock).toContain('CYCLONEDDS_URI=file:///opt/bridge/cyclonedds.xml');
});

test('no host file is mounted over the DDS config', () => {
  expect(bridgeBlock).not.toMatch(/-\s+\S*cyclonedds\S*\.xml:/);
});

test('peer list: elder-plops, FC-1, FC-2 over wg0, multicast off', () => {
  const peers = [...xml.matchAll(/<Peer address="([^"]+)"/g)].map((m) => m[1]);
  expect(peers).toEqual(['172.16.10.3', '172.16.10.5', '172.16.10.6']);
  const ifaces = [...xml.matchAll(/<NetworkInterface name="([^"]+)" multicast="([^"]+)"/g)];
  expect(ifaces.map((m) => [m[1], m[2]])).toEqual([['wg0', 'false']]);
  expect(xml).toContain('<AllowMulticast>false</AllowMulticast>');
});
