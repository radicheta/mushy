// MUSHY-110 -- the bridge must not die when Timescale drops an idle connection.
//
// Two tests, deliberately different in kind:
//
//   1. A behavioural test against a real pg Pool proves the failure mode is what
//      we think it is: an 'error' event with no listener throws, and with one it
//      does not. This is the actual mechanism that killed the bridge on the
//      2026-08-24 reboot.
//   2. A source-level wiring guard proves index.js actually attaches the handler.
//      It has to be source-level: index.js opens sockets and starts the server at
//      require() time, so it cannot be imported into a unit test. Without this
//      guard, deleting the handler would leave test 1 passing and the bridge dead.

const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');

const INDEX_SRC = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'index.js'), 'utf8'
);

describe('MUSHY-110 pool error resilience', () => {
    test('an idle-client error with no listener is fatal (the bug)', () => {
        // No connection is made -- emit() alone reproduces what pg does when a
        // pooled idle client dies, which is the whole failure mode.
        const bare = new Pool({ host: '127.0.0.1', port: 1 });
        expect(() => bare.emit('error', new Error(
            'terminating connection due to administrator command'
        ))).toThrow('terminating connection due to administrator command');
        bare.end().catch(() => {});
    });

    test('an idle-client error with a listener is survivable (the fix)', () => {
        const seen = [];
        const guarded = new Pool({ host: '127.0.0.1', port: 1 });
        guarded.on('error', (err) => seen.push(err.message));
        expect(() => guarded.emit('error', new Error(
            'terminating connection due to administrator command'
        ))).not.toThrow();
        expect(seen).toEqual(['terminating connection due to administrator command']);
        guarded.end().catch(() => {});
    });

    test("index.js attaches an 'error' handler to its pool", () => {
        expect(INDEX_SRC).toMatch(/pool\.on\(\s*['"]error['"]/);
    });

    test('index.js still builds exactly one pool, so one handler covers it', () => {
        // If a second `new Pool(` ever appears, it needs its own handler and this
        // test should fail rather than let the gap reopen somewhere else.
        const pools = INDEX_SRC.match(/new Pool\(/g) || [];
        expect(pools).toHaveLength(1);
    });
});
