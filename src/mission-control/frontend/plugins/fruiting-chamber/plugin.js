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
            return fetch('http://localhost:8081/telemetry')
                .then(response => response.json());
        },
        subscribe: function (domainObject, callback) {
            const ws = new WebSocket('ws://localhost:8081');
            ws.onmessage = function (event) {
                callback(JSON.parse(event.data));
            };
            return function () {
                ws.close();
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
                temperatureDisplay.querySelector('.value').textContent = `${datum.temperature.toFixed(1)}°C`;
                humidityDisplay.querySelector('.value').textContent = `${datum.humidity.toFixed(1)}%`;
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