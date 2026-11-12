#!/usr/bin/env python3
"""Build a timelapse MP4 from the bridge's raw camera snapshots.

Frames come from /data/snapshots/<camera>/<UTC date>/<ISO>Z.jpg (one per
SNAPSHOT_INTERVAL_MIN). Times on the command line and in the overlay are
local (America/Montevideo). The overlay is rendered with libass after any
rotation, so it always reads upright.

    # local-time stamp only
    scripts/timelapse/make-timelapse.py 2026-11-11T17:00 2026-11-11T20:00 -o out.mp4
    # stamp + RH / T / CO2 from Timescale, image rotated 180
    scripts/timelapse/make-timelapse.py 2026-11-11T15:00 2026-11-11T21:00 \
        --telemetry --rotate 180 -o out.mp4
    # then e.g.: scp out.mp4 gumbald:Desktop/

Needs ffmpeg built with libass. --telemetry needs the mushy-timescale-1
container (run on elder-plops).
"""
import argparse
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo('America/Montevideo')
TZ_LABEL = 'UYT'
SENSORS = [('fc.humidity', 'RH {:.1f}%'),
           ('fc.temperature', 'T {:.1f}°C'),
           ('fc.co2', 'CO₂ {:.0f} ppm')]


def list_frames(root, start, end):
    """Return [(utc_datetime, path)] for frames in [start, end)."""
    frames = []
    day = start.astimezone(timezone.utc).date()
    while day <= end.astimezone(timezone.utc).date():
        for p in sorted((root / day.isoformat()).glob('*.jpg')):
            # 2026-11-11T21-00-18-222Z.jpg
            t = datetime.strptime(p.stem, '%Y-%m-%dT%H-%M-%S-%fZ').replace(tzinfo=timezone.utc)
            if start <= t < end:
                frames.append((t, p))
        day += timedelta(days=1)
    return frames


def fetch_telemetry(times, lookback_min=5):
    """Last value at-or-before each frame time, per sensor. None if older than lookback."""
    values = ','.join(f"('{t.isoformat()}'::timestamptz)" for t in times)
    cols = ',\n'.join(
        f"(select value from telemetry where topic='{topic}' and time<=f.t "
        f"and time>f.t-interval '{lookback_min} min' order by time desc limit 1)"
        for topic, _ in SENSORS)
    sql = (f"set max_parallel_workers_per_gather=0;\n"
           f"select {cols} from (values {values}) f(t) order by f.t;")
    out = subprocess.run(
        ['docker', 'exec', '-i', 'mushy-timescale-1', 'psql', '-U', 'postgres',
         '-d', 'postgres', '-At', '-F,', '-q'],
        input=sql, capture_output=True, text=True, check=True).stdout
    rows = [[float(v) if v else None for v in line.split(',')]
            for line in out.strip().splitlines()]
    assert len(rows) == len(times), f'got {len(rows)} telemetry rows for {len(times)} frames'
    return rows


def ass_time(sec):
    return f'{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{sec % 60:05.2f}'


def write_ass(path, labels, fps, width, height):
    lines = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {width}', f'PlayResY: {height}', '',
             '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, '
             'BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV',
             # BorderStyle 3 = opaque box; &H70 alpha = ~55% black, bottom-left
             f'Style: D,DejaVu Sans Mono,{round(height / 24)},&H00FFFFFF,&H70000000,&H70000000,'
             '1,3,5,0,1,12,12,12', '',
             '[Events]', 'Format: Layer, Start, End, Style, Text']
    for i, text in enumerate(labels):
        lines.append(f'Dialogue: 0,{ass_time(i / fps)},{ass_time((i + 1) / fps)},D,{text}')
    path.write_text('\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('start', help='local start, e.g. 2026-11-11T15:00 (inclusive)')
    ap.add_argument('end', help='local end, e.g. 2026-11-11T21:00 (exclusive)')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--camera', default='fc1')
    ap.add_argument('--snapshots', default='/data/snapshots')
    ap.add_argument('--fps', type=int, default=15)
    ap.add_argument('--rotate', type=int, choices=[0, 90, 180, 270], default=0)
    ap.add_argument('--telemetry', action='store_true', help='add RH / T / CO2 to the overlay')
    ap.add_argument('--no-stamp', action='store_true', help='no overlay at all')
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=LOCAL)
    end = datetime.fromisoformat(args.end).replace(tzinfo=LOCAL)
    frames = list_frames(Path(args.snapshots) / args.camera, start, end)
    if not frames:
        raise SystemExit('no frames in range')
    print(f'{len(frames)} frames, {len(frames) / args.fps:.1f}s at {args.fps} fps')

    labels = [t.astimezone(LOCAL).strftime(f'%Y-%m-%d %H:%M {TZ_LABEL}') for t, _ in frames]
    if args.telemetry:
        for i, row in enumerate(fetch_telemetry([t for t, _ in frames])):
            parts = ['—' if v is None else fmt.format(v) for v, (_, fmt) in zip(row, SENSORS)]
            labels[i] += '  ' + '  '.join(parts)
        missing = sum(l.count('—') for l in labels)
        if missing:
            print(f'warning: {missing} missing sensor values shown as —')

    rot = {0: [], 90: ['transpose=1'], 180: ['transpose=2,transpose=2'], 270: ['transpose=2']}[args.rotate]
    w, h = map(int, subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
         '-of', 'csv=p=0', str(frames[0][1])], capture_output=True, text=True, check=True).stdout.split(','))
    if args.rotate in (90, 270):
        w, h = h, w

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'list.txt').write_text(''.join(f"file '{p}'\n" for _, p in frames))
        vf = [f'setpts=N/{args.fps}/TB'] + rot
        if not args.no_stamp:
            write_ass(tmp / 'overlay.ass', labels, args.fps, w, h)
            vf.append(f"subtitles={tmp / 'overlay.ass'}")
        vf.append('format=yuv420p')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                        '-i', str(tmp / 'list.txt'), '-vf', ','.join(vf), '-r', str(args.fps),
                        '-c:v', 'libx264', '-crf', '20', args.output], check=True)
    print(args.output)


if __name__ == '__main__':
    main()
