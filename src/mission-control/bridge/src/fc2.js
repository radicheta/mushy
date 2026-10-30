// FC-2 (outdoor log-yard sprinklers) telemetry: subscribe, store, broadcast live.
// Live broadcast keys are the full fc2.* names, never bare FC-1 field names
// (the FC-1 plugin maps bare `temperature`/`humidity` onto FC-1 sensors).
const F = 'std_msgs/msg/Float32';
const FC2_TOPICS = [
    { ros: '/fc2/valve', type: 'std_msgs/msg/Bool', db: 'fc2.valve', latched: true },
    { ros: '/fc2/duty_pct_1h', type: F, db: 'fc2.duty_pct_1h' },
    { ros: '/fc2/bursts_per_hour', type: F, db: 'fc2.bursts_per_hour' },
    { ros: '/fc2/mode', type: 'std_msgs/msg/Int32', db: 'fc2.mode' },
    { ros: '/fc2/weather/temperature', type: F, db: 'fc2.temperature' },
    { ros: '/fc2/weather/humidity', type: F, db: 'fc2.humidity' },
    { ros: '/fc2/weather/wind', type: F, db: 'fc2.wind' },
    { ros: '/fc2/weather/precipitation', type: F, db: 'fc2.precipitation' },
    { ros: '/fc2/weather/et0', type: F, db: 'fc2.et0' },
    { ros: '/fc2/weather/age_sec', type: F, db: 'fc2.weather_age_sec' },
];
const FC2_DB_TOPICS = FC2_TOPICS.map(t => t.db);

function subscribeFc2(node, { insertTelemetry, broadcast, transientLocalQos, now = Date.now }) {
    for (const t of FC2_TOPICS) {
        const handler = async (msg) => {
            const value = t.type === 'std_msgs/msg/Bool' ? (msg.data ? 1 : 0) : msg.data;
            const ts = now();
            try {
                await insertTelemetry(t.db, value, ts, ts * 1e6);
            } catch (e) {
                console.warn(`[bridge] ${t.db} insert failed:`, e.message);
            }
            broadcast({ [t.db]: value, timestamp: ts });
        };
        try {
            if (t.latched) node.createSubscription(t.type, t.ros, { qos: transientLocalQos }, handler);
            else node.createSubscription(t.type, t.ros, handler);
        } catch (e) {
            console.warn(`[fc2] subscribe failed for ${t.ros}: ${e.message}`);
        }
    }
}

module.exports = { FC2_TOPICS, FC2_DB_TOPICS, subscribeFc2 };
