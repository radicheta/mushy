// Phase 23: env config loader. Fail-fast on missing TIMESCALE_PASSWORD.
function load(env = process.env) {
    if (!env.TIMESCALE_PASSWORD) {
        console.error('[config] TIMESCALE_PASSWORD is required');
        process.exit(1);
    }
    return {
        timescaleHost:     env.TIMESCALE_HOST || 'timescale',
        timescaleDb:       env.TIMESCALE_DB   || 'postgres',
        timescaleUser:     env.TIMESCALE_USER || 'postgres',
        timescalePassword: env.TIMESCALE_PASSWORD,
        snapshotDir:       env.SNAPSHOT_DIR   || '/data/snapshots',
        timelapseDir:      env.TIMELAPSE_DIR  || '/data/timelapse',
        cameraId:          env.CAMERA_ID      || 'fc1',
        fps:               parseInt(env.TIMELAPSE_FPS || '12', 10),
        // MUSHY-188: days, names, stamps and cron are all in the farm's zone.
        timezone:          env.TZ             || 'America/Montevideo',
        tzLabel:           env.TZ_LABEL       || 'UYT',
        // Mean luma (0-255) below which a frame counts as lights-off and is dropped. 0 = keep all.
        minLuma:           parseFloat(env.TIMELAPSE_MIN_LUMA ?? '50'),
        port:              parseInt(env.PORT  || '8888', 10),
        cronSchedule:      env.TIMELAPSE_CRON || '30 0 * * *',
    };
}
module.exports = { load };
