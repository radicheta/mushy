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
        },
        {
            identifier: { namespace: 'fruiting-chamber', key: 'fc.humidity_2' },
            name: 'Humidity (SCD41)',
            unit: '%',
            topic: '/fc1/humidity_2',
            msgType: 'sensor_msgs/msg/RelativeHumidity',
            extract: function (msg) { return msg.relative_humidity * 100; },
            min: 50,
            max: 100
        },
        {
            identifier: { namespace: 'fruiting-chamber', key: 'fc.temperature_2' },
            name: 'Temperature (SCD41)',
            unit: '°C',
            topic: '/fc1/temperature_2',
            msgType: 'sensor_msgs/msg/Temperature',
            extract: function (msg) { return msg.temperature; },
            min: 10,
            max: 35
        }
    ];

    var CAMERA_ID  = { namespace: 'fruiting-chamber', key: 'fc.camera' };
    var HEALTH_ID  = { namespace: 'fruiting-chamber', key: 'fc.health' };

    /**
     * StatusLight primitive — green/red/grey dot with a label.
     * Reusable: Phase 16 will instantiate N of these for sensors/actuators/bridge.
     *
     * @param {Element} parentEl - DOM element to append the light into
     * @param {string}  label    - Display label (e.g. "Feed live")
     * @returns {{ setGreen(tooltip?), setRed(tooltip?), setGrey(tooltip?), destroy() }}
     */
    function makeStatusLight(parentEl, label) {
        var root = document.createElement('span');
        root.className = 'fc-status-light';
        root.setAttribute('data-label', label);
        root.setAttribute('data-state', 'unknown');
        root.style.display = 'inline-flex';
        root.style.alignItems = 'center';
        root.style.gap = '6px';
        root.style.padding = '2px 8px';
        root.style.borderRadius = '4px';
        root.style.background = 'rgba(0,0,0,0.6)';
        root.style.border = '1px solid #555';
        root.style.fontSize = '11px';
        root.style.fontWeight = '600';
        root.style.letterSpacing = '0.05em';
        root.style.textTransform = 'uppercase';
        root.style.color = '#ccc';

        var dot = document.createElement('span');
        dot.className = 'dot';
        dot.style.width = '8px';
        dot.style.height = '8px';
        dot.style.borderRadius = '50%';
        dot.style.background = '#555';
        dot.style.display = 'inline-block';
        root.appendChild(dot);

        var labelEl = document.createElement('span');
        labelEl.className = 'label';
        labelEl.textContent = label;
        root.appendChild(labelEl);

        parentEl.appendChild(root);

        function setState(state, color, borderColor, tooltip) {
            root.setAttribute('data-state', state);
            dot.style.background = color;
            root.style.borderColor = borderColor;
            if (tooltip !== undefined) root.title = tooltip;
        }

        return {
            setGreen: function (tooltip) { setState('ok',      '#4ecdc4', '#4ecdc4', tooltip); },
            setRed:   function (tooltip) { setState('bad',     '#e74c3c', '#e74c3c', tooltip); },
            setGrey:  function (tooltip) { setState('unknown', '#555',    '#555',    tooltip); },
            destroy:  function () { if (root.parentNode) root.parentNode.removeChild(root); }
        };
    }

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
        var historyUrl = (options && options.historyUrl) || 'http://localhost:8081/history';
        var cameraUrl = (options && options.cameraUrl) || 'http://localhost:8081/camera/mjpeg';

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

            openmct.types.addType('fruiting-chamber.camera', {
                name: 'Chamber Camera',
                description: 'Live camera feed from the mushroom fruiting chamber',
                cssClass: 'icon-image',
                creatable: false
            });

            openmct.types.addType('fruiting-chamber.health', {
                name: 'System Health',
                description: 'Six-light system health strip for FC-1',
                cssClass: 'icon-activity',
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
                            composition: SENSORS.map(function (s) { return s.identifier; }).concat([CAMERA_ID, HEALTH_ID])
                        });
                    }
                    if (identifier.key === 'fc.health') {
                        return Promise.resolve({
                            identifier: HEALTH_ID,
                            name: 'System Health',
                            type: 'fruiting-chamber.health',
                            location: openmct.objects.makeKeyString(ROOT_ID)
                        });
                    }
                    if (identifier.key === 'fc.camera') {
                        return Promise.resolve({
                            identifier: CAMERA_ID,
                            name: 'Camera',
                            type: 'fruiting-chamber.camera',
                            location: openmct.objects.makeKeyString(ROOT_ID)
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

                    // Map raw broadcast field names to sensor keys for dispatch
                    // index.js broadcasts {humidity, temperature, co2, humidifier, timestamp}
                    var fieldToKey = {
                        humidity:      'fc.humidity',
                        temperature:   'fc.temperature',
                        co2:           'fc.co2',
                        humidifier:    'fc.humidifier',
                        humidity_2:    'fc.humidity_2',
                        temperature_2: 'fc.temperature_2'
                    };

                    Object.keys(fieldToKey).forEach(function (field) {
                        if (data[field] !== undefined) {
                            var key = fieldToKey[field];
                            var sensor = SENSORS.find(function (s) { return s.identifier.key === key; });
                            if (!sensor) return;

                            // Build datum directly — broadcast values are already in display units
                            // (bridge sends humidity*100, temperature in C, co2 as float, humidifier as 0/1)
                            // Do NOT reconstruct a synthetic ROS msg and pass through sensor.extract()
                            // — that would cause a double-transform (e.g. humidity already multiplied by 100)
                            var datum = {
                                value: data[field],
                                utc: data.timestamp
                            };

                            if (subs[sensor.topic]) {
                                subs[sensor.topic].forEach(function (cb) {
                                    try { cb(datum); } catch (e) { /* swallow per-handler errors */ }
                                });
                            }
                        }
                    });
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
                request: function (domainObject, options) {
                    var sensor = SENSORS.find(function (s) {
                        return s.identifier.key === domainObject.identifier.key;
                    });
                    if (!sensor) return Promise.resolve([]);

                    var url = historyUrl
                        + '/' + encodeURIComponent(sensor.identifier.key)
                        + '?start=' + options.start
                        + '&end='   + options.end;

                    return fetch(url)
                        .then(function (resp) {
                            if (!resp.ok) return [];
                            return resp.json();
                        })
                        .catch(function () { return []; });
                },
                subscribe: function (domainObject, callback) {
                    var sensor = SENSORS.find(function (s) {
                        return s.identifier.key === domainObject.identifier.key;
                    });
                    if (!sensor) return function () {};

                    var handler = function (msgOrDatum) {
                        if (msgOrDatum.utc !== undefined && msgOrDatum.value !== undefined) {
                            // Already a datum from the new onmessage handler
                            callback(msgOrDatum);
                        } else {
                            // Legacy ROS msg — extract value and timestamp
                            callback({
                                value: sensor.extract(msgOrDatum),
                                utc: getTimestamp(msgOrDatum)
                            });
                        }
                    };

                    addSub(sensor, handler);

                    return function unsubscribe() {
                        removeSub(sensor, handler);
                    };
                }
            });
            // ── Camera view provider (D-13, D-14) ──────────────────────────
            openmct.objectViews.addProvider({
                key: 'fruiting-chamber.camera-view',
                name: 'Camera Feed',
                canView: function (domainObject) {
                    return domainObject.type === 'fruiting-chamber.camera';
                },
                view: function (domainObject) {
                    var container;
                    return {
                        show: function (el) {
                            container = el;
                            var healthUrl = cameraUrl.replace('/camera/mjpeg', '/health');
                            var pollId = null;

                            // Layout — absolute-positioned lights row overlaid on black background
                            container.innerHTML = '';
                            container.style.display = 'flex';
                            container.style.flexDirection = 'column';
                            container.style.alignItems = 'stretch';
                            container.style.height = '100%';
                            container.style.background = '#000';
                            container.style.position = 'relative';

                            // Lights row — top-right corner, above image
                            var lightsRow = document.createElement('div');
                            lightsRow.style.display = 'flex';
                            lightsRow.style.gap = '8px';
                            lightsRow.style.padding = '8px';
                            lightsRow.style.position = 'absolute';
                            lightsRow.style.top = '0';
                            lightsRow.style.right = '0';
                            lightsRow.style.zIndex = '10';
                            container.appendChild(lightsRow);

                            var feedLight = makeStatusLight(lightsRow, 'Feed live');
                            var subLight  = makeStatusLight(lightsRow, 'Camera subscribed');
                            feedLight.setGrey('waiting for first /health response');
                            subLight.setGrey('waiting for first /health response');

                            // Camera image
                            var img = document.createElement('img');
                            img.src = cameraUrl;
                            img.alt = 'FC-1 Camera Feed';
                            img.style.maxWidth = '100%';
                            img.style.maxHeight = '100%';
                            img.style.objectFit = 'contain';
                            img.style.margin = 'auto';

                            var fallback = document.createElement('p');
                            fallback.style.display = 'none';
                            fallback.style.color = '#888';
                            fallback.style.padding = '2em';
                            fallback.style.textAlign = 'center';
                            fallback.textContent = 'Camera feed unavailable. Check that the bridge is running and the camera is connected.';

                            img.onerror = function () {
                                img.style.display = 'none';
                                fallback.style.display = 'block';
                            };
                            container.appendChild(img);
                            container.appendChild(fallback);

                            function updateLights() {
                                fetch(healthUrl).then(function (r) { return r.json(); }).then(function (data) {
                                    var cam = (data && data.camera) || {};

                                    // Camera subscribed light — grey is not a failure state
                                    if (cam.subscribed === true) {
                                        subLight.setGreen('bridge is subscribed to /fc1/camera/compressed (' + (cam.clients || 0) + ' MJPEG client(s))');
                                    } else {
                                        subLight.setGrey('no MJPEG viewers — fc_camera is idle (1 frame/hr) by design');
                                    }

                                    // Feed live light — D-03 gap-over-noise: red if stale OR null
                                    // Green only if numeric age < 10s AND subscribed (prevents false-green on idle heartbeat)
                                    var age = cam.last_frame_age_sec;
                                    if (typeof age === 'number' && age < 10 && cam.subscribed === true) {
                                        feedLight.setGreen('last frame ' + age.toFixed(1) + 's ago');
                                    } else if (age === null || age === undefined) {
                                        feedLight.setRed('no frame received yet');
                                    } else {
                                        feedLight.setRed('last frame ' + age.toFixed(1) + 's ago — stream is not live');
                                    }
                                }).catch(function () {
                                    feedLight.setGrey('/health unreachable');
                                    subLight.setGrey('/health unreachable');
                                });
                            }

                            updateLights();
                            pollId = setInterval(updateLights, 5000);
                            container._fcCameraPollId = pollId;
                            container._fcLights = [feedLight, subLight];
                        },
                        destroy: function () {
                            if (container) {
                                if (container._fcCameraPollId) {
                                    clearInterval(container._fcCameraPollId);
                                }
                                // Destroy each makeStatusLight instance (feedLight, subLight)
                                if (container._fcLights) {
                                    container._fcLights.forEach(function (l) { l.destroy(); });
                                }
                                container.innerHTML = '';
                            }
                        }
                    };
                }
            });
            // ── System Health view provider (Phase 16-02) ───────────────────
            openmct.objectViews.addProvider({
                key: 'fruiting-chamber.health-view',
                name: 'System Health',
                canView: function (domainObject) {
                    return domainObject.type === 'fruiting-chamber.health';
                },
                view: function (domainObject) {
                    var container;
                    var pollId = null;
                    var lights = {};
                    var lastSensorHealth = null;      // last sensor_health from WS
                    var lastSensorHealthTs = null;    // ms epoch of last arrival
                    var healthUrl = (options && options.historyUrl)
                        ? options.historyUrl.replace('/history', '/health')
                        : 'http://localhost:8081/health';

                    // Dedicated WebSocket for sensor_health broadcasts.
                    // Opens independently so it does not disturb the shared
                    // telemetry WS connection managed by the telemetry provider.
                    var healthWs = null;
                    function openHealthWs() {
                        try { healthWs = new WebSocket(bridgeUrl); } catch (e) { healthWs = null; return; }
                        healthWs.onmessage = function (event) {
                            var data;
                            try { data = JSON.parse(event.data); } catch (e) { return; }
                            if (data && data.sensor_health) {
                                lastSensorHealth = data.sensor_health;
                                lastSensorHealthTs = Date.now();
                                updateSensorsAndGraceLights();
                            }
                        };
                        healthWs.onclose = function () {
                            healthWs = null;
                            setTimeout(openHealthWs, 3000);
                        };
                    }

                    function updateSensorsAndGraceLights() {
                        if (!lights.sensors) return;
                        // Sensors light
                        if (!lastSensorHealth || (Date.now() - (lastSensorHealthTs || 0)) > 10000) {
                            lights.sensors.setGrey('no /fc1/sensor_health message in the last 10s');
                        } else if (lastSensorHealth.level === 0) {
                            lights.sensors.setGreen('sensors OK — ' + (lastSensorHealth.message || ''));
                        } else if (lastSensorHealth.level === 1) {
                            var elapsed = (lastSensorHealth.values && lastSensorHealth.values.grace_elapsed_sec) || '?';
                            var total   = (lastSensorHealth.values && lastSensorHealth.values.grace_total_sec)   || '?';
                            lights.sensors.setGrey('warming up ' + elapsed + '/' + total + 's');
                        } else {
                            lights.sensors.setRed(lastSensorHealth.message || 'sensor error');
                        }

                        // Grace light — meaningful only during WARN; grey otherwise (D-01 #6)
                        if (lastSensorHealth && lastSensorHealth.level === 1) {
                            var e = (lastSensorHealth.values && lastSensorHealth.values.grace_elapsed_sec) || '?';
                            var t = (lastSensorHealth.values && lastSensorHealth.values.grace_total_sec)   || '?';
                            lights.grace.setGrey('warming up ' + e + '/' + t + 's');
                        } else if (lastSensorHealth && lastSensorHealth.level === 0) {
                            lights.grace.setGreen('grace complete');
                        } else {
                            lights.grace.setGrey('unknown');
                        }
                    }

                    return {
                        show: function (el) {
                            container = el;
                            container.innerHTML = '';
                            container.style.display = 'flex';
                            container.style.flexDirection = 'row';
                            container.style.flexWrap = 'wrap';
                            container.style.gap = '8px';
                            container.style.padding = '8px';
                            container.style.alignItems = 'center';
                            container.style.background = '#111';

                            // Six makeStatusLight instances — one per subsystem
                            lights.sensors    = makeStatusLight(container, 'Sensors');
                            lights.cameraFeed = makeStatusLight(container, 'Camera feed');
                            lights.humidifier = makeStatusLight(container, 'Humidifier');
                            lights.bridge     = makeStatusLight(container, 'Bridge');
                            lights.pi         = makeStatusLight(container, 'Pi reachable');
                            lights.grace      = makeStatusLight(container, 'Grace');
                            lights.snapshots  = makeStatusLight(container, 'Snapshots');

                            Object.keys(lights).forEach(function (k) {
                                lights[k].setGrey('waiting for first /health response');
                            });

                            openHealthWs();

                            function pollHealth() {
                                fetch(healthUrl).then(function (r) {
                                    if (!r.ok) throw new Error('HTTP ' + r.status);
                                    return r.json();
                                }).then(function (data) {
                                    // Bridge light — we got a response at all
                                    lights.bridge.setGreen('/health 200 OK');

                                    // Pi reachable light — ros.connected
                                    if (data.ros && data.ros.connected === true) {
                                        lights.pi.setGreen('ROS node is up and spinning');
                                    } else {
                                        lights.pi.setRed('bridge is up but rclnodejs is not ready');
                                    }

                                    // Camera feed light — same logic as Phase 14's Feed live
                                    var cam = data.camera || {};
                                    var age = cam.last_frame_age_sec;
                                    if (typeof age === 'number' && age < 10 && cam.subscribed === true) {
                                        lights.cameraFeed.setGreen('last frame ' + age.toFixed(1) + 's ago');
                                    } else if (age === null || age === undefined) {
                                        lights.cameraFeed.setGrey('no frame received yet');
                                    } else if (cam.subscribed !== true) {
                                        lights.cameraFeed.setGrey('no MJPEG viewers — fc_camera idle by design');
                                    } else {
                                        lights.cameraFeed.setRed('last frame ' + age.toFixed(1) + 's ago — stream is not live');
                                    }

                                    // Humidifier light — 30s liveness window on last_msg_ts
                                    var hum = data.humidifier || {};
                                    if (typeof hum.last_msg_ts === 'number') {
                                        var ageMs = Date.now() - hum.last_msg_ts;
                                        if (ageMs < 30000) {
                                            lights.humidifier.setGreen('last message ' + Math.round(ageMs / 1000) + 's ago');
                                        } else {
                                            lights.humidifier.setGrey('no humidifier message in ' + Math.round(ageMs / 1000) + 's');
                                        }
                                    } else {
                                        lights.humidifier.setGrey('no humidifier message received yet');
                                    }

                                    // Phase 21 D-06b: Snapshots chip — green >=200/24h, red ==0, grey unknown/degraded
                                    var snap = data.snapshots || {};
                                    var last24 = (typeof snap.last_24h === 'number') ? snap.last_24h : null;
                                    var oldest = snap.oldest_at || null;
                                    if (last24 === null) {
                                        lights.snapshots.setGrey('snapshots stats unavailable (DB down?)');
                                    } else if (last24 === 0) {
                                        lights.snapshots.setRed('0 snapshots in last 24h — persister broken');
                                    } else if (last24 < 200) {
                                        lights.snapshots.setGrey(last24 + ' snapshots in last 24h (degraded; oldest ' + (oldest || 'unknown') + ')');
                                    } else {
                                        lights.snapshots.setGreen(last24 + ' snapshots in last 24h (oldest ' + (oldest || 'none') + ')');
                                    }

                                    // Sensors + Grace lights update on every WS message;
                                    // also refresh here so a stale WS feed flips Sensors to grey.
                                    updateSensorsAndGraceLights();
                                }).catch(function (e) {
                                    lights.bridge.setRed('/health unreachable: ' + e.message);
                                    lights.pi.setGrey('bridge unreachable — cannot determine ROS state');
                                    lights.cameraFeed.setGrey('bridge unreachable');
                                    lights.humidifier.setGrey('bridge unreachable');
                                    if (lights.snapshots) lights.snapshots.setGrey('bridge unreachable');
                                });
                            }

                            pollHealth();
                            pollId = setInterval(pollHealth, 2000);
                            container._fcHealthPollId = pollId;
                        },
                        destroy: function () {
                            if (container && container._fcHealthPollId) {
                                clearInterval(container._fcHealthPollId);
                            }
                            // Destroy each makeStatusLight instance in the health strip
                            Object.keys(lights).forEach(function (k) {
                                if (lights[k]) lights[k].destroy();
                            });
                            if (healthWs) {
                                try { healthWs.onclose = null; healthWs.close(); } catch (e) {}
                                healthWs = null;
                            }
                            if (container) container.innerHTML = '';
                        }
                    };
                }
            });
        };
    }

    window.FruitingChamberPlugin = FruitingChamberPlugin;

})();
