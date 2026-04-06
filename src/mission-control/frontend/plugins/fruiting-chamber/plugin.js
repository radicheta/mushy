/**
 * FruitingChamberPlugin — OpenMCT telemetry plugin for fc1.
 *
 * Provides live humidity and temperature telemetry from the mushroom
 * fruiting chamber via rosbridge WebSocket (port 8081).
 *
 * Usage: openmct.install(FruitingChamberPlugin())
 *        openmct.install(FruitingChamberPlugin({ bridgeUrl: 'ws://myhost:8081' }))
 */
(function () {
    'use strict';

    var ROOT_ID = { namespace: 'fruiting-chamber', key: 'root' };

    var SENSORS = [
        {
            identifier: { namespace: 'fruiting-chamber', key: 'fc.humidity' },
            name: 'Humidity',
            unit: '%',
            topic: '/fc1/humidity',
            msgType: 'sensor_msgs/msg/RelativeHumidity',
            extract: function (msg) { return msg.relative_humidity * 100; },
            min: 50,
            max: 100
        },
        {
            identifier: { namespace: 'fruiting-chamber', key: 'fc.temperature' },
            name: 'Temperature',
            unit: '°C',
            topic: '/fc1/temperature',
            msgType: 'sensor_msgs/msg/Temperature',
            extract: function (msg) { return msg.temperature; },
            min: 10,
            max: 35
        },
        {
            identifier: { namespace: 'fruiting-chamber', key: 'fc.co2' },
            name: 'CO2',
            unit: 'ppm',
            topic: '/fc1/co2',
            msgType: 'std_msgs/msg/Float32',
            extract: function (msg) { return msg.data; },
            min: 300,
            max: 5000
        },
        {
            identifier: { namespace: 'fruiting-chamber', key: 'fc.humidifier' },
            name: 'Humidifier',
            unit: '',
            topic: '/fc1/actuators/humidifier',
            msgType: 'std_msgs/msg/Bool',
            extract: function (msg) { return msg.data ? 1 : 0; },
            min: 0,
            max: 1,
            type: 'actuator'
        }
    ];

    function getTimestamp(msg) {
        if (msg.header && msg.header.stamp) {
            var s = msg.header.stamp;
            var sec = s.sec !== undefined ? s.sec : (s.secs || 0);
            var nanosec = s.nanosec !== undefined ? s.nanosec : (s.nsecs || 0);
            if (sec > 0) return sec * 1000 + Math.floor(nanosec / 1e6);
        }
        return Date.now();
    }

    function FruitingChamberPlugin(options) {
        var bridgeUrl = (options && options.bridgeUrl) || 'ws://localhost:8081';

        return function install(openmct) {

            // ── Object type ──────────────────────────────────────────────────
            openmct.types.addType('fruiting-chamber.sensor', {
                name: 'Chamber Sensor',
                description: 'Live sensor telemetry from the mushroom fruiting chamber',
                cssClass: 'icon-telemetry',
                creatable: false
            });

            openmct.types.addType('fruiting-chamber.actuator', {
                name: 'Chamber Actuator',
                description: 'Live actuator state from the mushroom fruiting chamber',
                cssClass: 'icon-telemetry',
                creatable: false
            });

            // ── Object provider ──────────────────────────────────────────────
            openmct.objects.addProvider('fruiting-chamber', {
                get: function (identifier) {
                    if (identifier.key === 'root') {
                        return Promise.resolve({
                            identifier: ROOT_ID,
                            name: 'Fruiting Chamber FC-1',
                            type: 'folder',
                            location: 'ROOT',
                            composition: SENSORS.map(function (s) { return s.identifier; })
                        });
                    }
                    var sensor = SENSORS.find(function (s) {
                        return s.identifier.key === identifier.key;
                    });
                    if (!sensor) return Promise.resolve(null);
                    return Promise.resolve({
                        identifier: sensor.identifier,
                        name: sensor.name,
                        type: sensor.type === 'actuator' ? 'fruiting-chamber.actuator' : 'fruiting-chamber.sensor',
                        location: openmct.objects.makeKeyString(ROOT_ID),
                        telemetry: {
                            values: [
                                {
                                    key: 'value',
                                    name: sensor.name,
                                    unit: sensor.unit,
                                    min: sensor.min,
                                    max: sensor.max,
                                    hints: { range: 1 }
                                },
                                {
                                    key: 'utc',
                                    name: 'Timestamp (UTC)',
                                    format: 'utc',
                                    hints: { domain: 2 }
                                },
                                {
                                    key: 'uyt',
                                    source: 'utc',
                                    name: 'Timestamp (UYT)',
                                    format: 'uyt',
                                    hints: { domain: 1 }
                                }
                            ]
                        }
                    });
                }
            });

            // ── Root entry ───────────────────────────────────────────────────
            openmct.objects.addRoot(ROOT_ID);

            // ── Shared WebSocket (rosbridge protocol) ────────────────────────
            var ws = null;
            var subs = {}; // topic -> Set<handler>

            function sendIfOpen(msg) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify(msg));
                }
            }

            function connect() {
                ws = new WebSocket(bridgeUrl);

                ws.onopen = function () {
                    // Re-subscribe active topics after reconnect
                    Object.keys(subs).forEach(function (topic) {
                        if (subs[topic] && subs[topic].size > 0) {
                            var sensor = SENSORS.find(function (s) { return s.topic === topic; });
                            if (sensor) {
                                sendIfOpen({ op: 'subscribe', topic: topic, type: sensor.msgType });
                            }
                        }
                    });
                };

                ws.onmessage = function (event) {
                    var data;
                    try { data = JSON.parse(event.data); } catch (e) { return; }
                    if (data.op === 'publish' && data.topic && subs[data.topic]) {
                        subs[data.topic].forEach(function (cb) {
                            try { cb(data.msg); } catch (e) { /* swallow per-handler errors */ }
                        });
                    }
                };

                ws.onclose = function () {
                    ws = null;
                    var hasActive = Object.values(subs).some(function (s) { return s && s.size > 0; });
                    if (hasActive) {
                        setTimeout(connect, 3000);
                    }
                };
            }

            function addSub(sensor, handler) {
                if (!subs[sensor.topic]) subs[sensor.topic] = new Set();
                subs[sensor.topic].add(handler);
                if (!ws) {
                    connect();
                } else if (ws.readyState === WebSocket.OPEN) {
                    sendIfOpen({ op: 'subscribe', topic: sensor.topic, type: sensor.msgType });
                }
                // If readyState === CONNECTING, onopen will re-subscribe
            }

            function removeSub(sensor, handler) {
                if (!subs[sensor.topic]) return;
                subs[sensor.topic].delete(handler);
                if (subs[sensor.topic].size === 0) {
                    sendIfOpen({ op: 'unsubscribe', topic: sensor.topic });
                }
            }

            // ── Telemetry provider ───────────────────────────────────────────
            openmct.telemetry.addProvider({
                supportsRequest: function (domainObject) {
                    return domainObject.type === 'fruiting-chamber.sensor' || domainObject.type === 'fruiting-chamber.actuator';
                },
                supportsSubscribe: function (domainObject) {
                    return domainObject.type === 'fruiting-chamber.sensor' || domainObject.type === 'fruiting-chamber.actuator';
                },
                // No history source yet — return empty array.
                request: function (domainObject, options) {
                    return Promise.resolve([]);
                },
                subscribe: function (domainObject, callback) {
                    var sensor = SENSORS.find(function (s) {
                        return s.identifier.key === domainObject.identifier.key;
                    });
                    if (!sensor) return function () {};

                    var handler = function (msg) {
                        callback({
                            value: sensor.extract(msg),
                            utc: getTimestamp(msg)
                        });
                    };

                    addSub(sensor, handler);

                    return function unsubscribe() {
                        removeSub(sensor, handler);
                    };
                }
            });
        };
    }

    window.FruitingChamberPlugin = FruitingChamberPlugin;

})();
