/**
 * LogYardPlugin -- OpenMCT telemetry plugin for FC-2 (log-yard sprinklers).
 *
 * History comes from the bridge (GET <historyUrl>/<topic>?start&end).
 * Live data comes from the bridge WebSocket, which broadcasts every FC-2
 * message as {"fc2.<name>": value, "timestamp": ms} to all clients, so no
 * subscribe ops are sent.
 *
 * Usage: openmct.install(LogYardPlugin({ bridgeUrl: 'ws://host:8081', historyUrl: 'http://host:8081/history' }))
 */
(function () {
    'use strict';

    var ROOT_ID = { namespace: 'log-yard', key: 'root' };

    var MODES = [
        { key: 0, string: 'weather' },
        { key: 1, string: 'raining' },
        { key: 2, string: 'fallback' },
        { key: 3, string: 'night' }
    ];

    // key is the bridge topic (FC2_DB_TOPICS in bridge/src/fc2.js).
    var TOPICS = [
        { key: 'fc2.valve',            name: 'Valve',                unit: '',         min: 0, max: 1 },
        { key: 'fc2.duty_pct_1h',      name: 'Duty (1 h)',           unit: '%',        min: 0, max: 100 },
        { key: 'fc2.bursts_per_hour',  name: 'Bursts per hour',      unit: 'bursts/h' },
        { key: 'fc2.mode',             name: 'Mode',                 unit: '',         enumerations: MODES, min: 0, max: 3 },
        { key: 'fc2.temperature',      name: 'Temperature',          unit: '°C' },
        { key: 'fc2.humidity',         name: 'Humidity',             unit: '%',        min: 0, max: 100 },
        { key: 'fc2.wind',             name: 'Wind',                 unit: 'km/h' },
        { key: 'fc2.precipitation',    name: 'Precipitation',        unit: 'mm' },
        { key: 'fc2.et0',              name: 'Evapotranspiration (ET0)', unit: 'mm' },
        { key: 'fc2.weather_age_sec',  name: 'Weather age',          unit: 's' }
    ].map(function (t) {
        t.identifier = { namespace: 'log-yard', key: t.key };
        return t;
    });

    function findTopic(key) {
        return TOPICS.find(function (t) { return t.key === key; });
    }

    function LogYardPlugin(options) {
        var bridgeUrl = (options && options.bridgeUrl) || 'ws://localhost:8081';
        var historyUrl = (options && options.historyUrl) || 'http://localhost:8081/history';

        return function install(openmct) {

            openmct.types.addType('log-yard.topic', {
                name: 'Log Yard Telemetry',
                description: 'FC-2 log-yard sprinkler telemetry',
                cssClass: 'icon-telemetry',
                creatable: false
            });

            openmct.objects.addProvider('log-yard', {
                get: function (identifier) {
                    if (identifier.key === 'root') {
                        return Promise.resolve({
                            identifier: ROOT_ID,
                            name: 'FC-2 Log Yard',
                            type: 'folder',
                            location: 'ROOT',
                            composition: TOPICS.map(function (t) { return t.identifier; })
                        });
                    }
                    var topic = findTopic(identifier.key);
                    if (!topic) return Promise.resolve(null);
                    var range = {
                        key: 'value',
                        name: topic.name,
                        unit: topic.unit,
                        hints: { range: 1 }
                    };
                    if (topic.min !== undefined) range.min = topic.min;
                    if (topic.max !== undefined) range.max = topic.max;
                    if (topic.enumerations) {
                        range.format = 'enum';
                        range.enumerations = topic.enumerations;
                    }
                    return Promise.resolve({
                        identifier: topic.identifier,
                        name: topic.name,
                        type: 'log-yard.topic',
                        location: openmct.objects.makeKeyString(ROOT_ID),
                        telemetry: {
                            values: [
                                range,
                                { key: 'utc', name: 'Timestamp (UTC)', format: 'utc', hints: { domain: 2 } },
                                { key: 'uyt', source: 'utc', name: 'Timestamp (UYT)', format: 'uyt', hints: { domain: 1 } }
                            ]
                        }
                    });
                }
            });

            openmct.objects.addRoot(ROOT_ID);

            // ── Own WebSocket (bridge broadcasts to every client) ────────────
            var ws = null;
            var subs = {}; // topic key -> Set<callback>

            function hasActive() {
                return Object.keys(subs).some(function (k) { return subs[k].size > 0; });
            }

            function connect() {
                ws = new WebSocket(bridgeUrl);

                ws.onmessage = function (event) {
                    var data;
                    try { data = JSON.parse(event.data); } catch (e) { return; }
                    if (!data || typeof data !== 'object') return;
                    Object.keys(subs).forEach(function (key) {
                        if (data[key] === undefined) return;
                        var datum = { value: data[key], utc: data.timestamp };
                        subs[key].forEach(function (cb) {
                            try { cb(datum); } catch (e) { /* per-handler errors must not stop others */ }
                        });
                    });
                };

                ws.onclose = function () {
                    ws = null;
                    if (hasActive()) setTimeout(connect, 3000);
                };
            }

            openmct.telemetry.addProvider({
                supportsRequest: function (d) { return d.type === 'log-yard.topic'; },
                supportsSubscribe: function (d) { return d.type === 'log-yard.topic'; },
                request: function (domainObject, opts) {
                    var topic = findTopic(domainObject.identifier.key);
                    if (!topic) return Promise.resolve([]);
                    var url = historyUrl + '/' + encodeURIComponent(topic.key)
                        + '?start=' + opts.start + '&end=' + opts.end;
                    return fetch(url)
                        .then(function (resp) { return resp.ok ? resp.json() : []; })
                        .catch(function () { return []; });
                },
                subscribe: function (domainObject, callback) {
                    var topic = findTopic(domainObject.identifier.key);
                    if (!topic) return function () {};
                    if (!subs[topic.key]) subs[topic.key] = new Set();
                    subs[topic.key].add(callback);
                    if (!ws) connect();
                    return function unsubscribe() {
                        subs[topic.key].delete(callback);
                    };
                }
            });
        };
    }

    window.LogYardPlugin = LogYardPlugin;
})();
