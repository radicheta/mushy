// MUSHY-112 -- the bridge must accept connections while ROS is still starting.
//
// Source-level guard, same reason as db_pool_error.test.js: index.js opens
// sockets at require() time, so it cannot be imported into a unit test. The
// defect is purely positional -- server.listen() sat inside the
// rclnodejs.init().then() block, which blocks ~160s on DDS discovery -- so the
// check is that the bind happens before that block opens.

const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'src', 'index.js'), 'utf8');

describe('MUSHY-112 listen before ROS init', () => {
    test('server.listen(8081) is called before rclnodejs.init()', () => {
        // Anchored at line start: a comment mentioning rclnodejs.init().then()
        // appears earlier in the file and must not be mistaken for the block.
        const listen = SRC.search(/^server\.listen\(8081/m);
        const rosInit = SRC.search(/^rclnodejs\.init\(\)\.then\(/m);
        expect(listen).toBeGreaterThan(-1);
        expect(rosInit).toBeGreaterThan(-1);
        expect(listen).toBeLessThan(rosInit);
    });

    test('there is exactly one listen call', () => {
        expect(SRC.match(/server\.listen\(/g)).toHaveLength(1);
    });

    test('/health reports ROS readiness from rosReady, so false is answerable', () => {
        expect(SRC).toMatch(/ros:\s*\{\s*connected:\s*rosReady/);
    });
});
