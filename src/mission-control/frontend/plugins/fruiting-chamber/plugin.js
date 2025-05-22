define([
    'openmct'
], function (openmct) {
    // Define a new object type
    openmct.types.addType('fruiting-chamber', {
        name: 'Fruiting Chamber',
        description: 'A fruiting chamber for mushroom cultivation',
        creatable: true,
        cssClass: 'icon-fruiting-chamber'
    });

    // Add telemetry provider
    openmct.telemetry.addProvider({
        key: 'fruiting-chamber',
        name: 'Fruiting Chamber Telemetry',
        description: 'Telemetry from the fruiting chamber',
        supportsRequest: true,
        supportsSubscribe: true,
        request: function (domainObject, options) {
            return fetch('http://localhost:8081/rosbridge/topics/fc/temperature')
                .then(response => response.json())
                .then(data => {
                    return {
                        temperature: data.msg.temperature,
                        timestamp: data.msg.header.stamp.secs * 1000
                    };
                });
        },
        subscribe: function (domainObject, callback) {
            const ws = new WebSocket('ws://localhost:8081');
            let tempSub = null;
            let humiditySub = null;
            
            ws.onopen = function() {
                // Subscribe to temperature topic
                tempSub = {
                    op: 'subscribe',
                    topic: '/fc/temperature',
                    type: 'sensor_msgs/msg/Temperature'
                };
                ws.send(JSON.stringify(tempSub));
                
                // Subscribe to humidity topic
                humiditySub = {
                    op: 'subscribe',
                    topic: '/fc/humidity',
                    type: 'sensor_msgs/msg/RelativeHumidity'
                };
                ws.send(JSON.stringify(humiditySub));
            };
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                if (data.topic === '/fc/temperature') {
                    callback({
                        temperature: data.msg.temperature,
                        timestamp: data.msg.header.stamp.secs * 1000
                    });
                } else if (data.topic === '/fc/humidity') {
                    callback({
                        humidity: data.msg.relative_humidity * 100,
                        timestamp: data.msg.header.stamp.secs * 1000
                    });
                }
            };
            
            return function() {
                if (ws.readyState === WebSocket.OPEN) {
                    if (tempSub) ws.send(JSON.stringify({ op: 'unsubscribe', topic: '/fc/temperature' }));
                    if (humiditySub) ws.send(JSON.stringify({ op: 'unsubscribe', topic: '/fc/humidity' }));
                    ws.close();
                }
            };
        }
    });

    // Add view provider
    openmct.objectViews.addProvider({
        name: 'Fruiting Chamber View',
        key: 'fruiting-chamber-view',
        cssClass: 'icon-fruiting-chamber',
        canView: function (domainObject) {
            return domainObject.type === 'fruiting-chamber';
        },
        view: function (domainObject) {
            let container = document.createElement('div');
            container.className = 'fruiting-chamber-view';

            let temperatureDisplay = document.createElement('div');
            temperatureDisplay.className = 'temperature-display';
            temperatureDisplay.innerHTML = `
                <h3>Temperature</h3>
                <div class="value">--°C</div>
            `;

            let humidityDisplay = document.createElement('div');
            humidityDisplay.className = 'humidity-display';
            humidityDisplay.innerHTML = `
                <h3>Humidity</h3>
                <div class="value">--%</div>
            `;

            container.appendChild(temperatureDisplay);
            container.appendChild(humidityDisplay);

            let unsubscribe = openmct.telemetry.subscribe(domainObject, function (datum) {
                if (datum.temperature !== undefined) {
                    temperatureDisplay.querySelector('.value').textContent = `${datum.temperature.toFixed(1)}°C`;
                }
                if (datum.humidity !== undefined) {
                    humidityDisplay.querySelector('.value').textContent = `${datum.humidity.toFixed(1)}%`;
                }
            });

            return {
                show: function (container) {
                    container.appendChild(container);
                },
                destroy: function () {
                    unsubscribe();
                }
            };
        }
    });
}); 