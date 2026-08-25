#!/usr/bin/env python3
"""Merge-logic checks for build-control-epochs.py (MUSHY-58).

Runs on hand-built fixtures -- no database, no git. The point is the merge:
that telemetry force windows carve git epochs correctly, that a commit which
never reached the chamber is flagged rather than dropped, and that the result
tiles its window without gaps or overlaps.

  python3 scripts/test_build_control_epochs.py
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'bce', Path(__file__).resolve().parent / 'build-control-epochs.py')
bce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bce)


def t(day, hour=0, minute=0):
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


def minute_series(start, count, value):
    return [(start + timedelta(minutes=i), value, value) for i in range(count)]


def test_parse_config_ignores_comments_and_blanks():
    cfg = bce.CONFIG_LINE.match('    pid_kp: 0.36  # 0.5 -> 0.35 then 0.36 live')
    assert cfg.group(1) == 'pid_kp'
    assert cfg.group(2) == '0.36', cfg.group(2)
    # A key with no value (a yaml block header) must not become a parameter.
    assert bce.CONFIG_LINE.match('  ros__parameters:').group(2) == ''


def test_band_falls_back_to_target_plus_tolerance_before_modes_block():
    # Pre-5ea5cfee there was no modes block; band was implicit.
    p = bce.declared_params({'target_humidity': '0.96', 'humidity_tolerance': '0.015'})
    assert (round(p['band_low'], 3), round(p['band_high'], 3)) == (0.945, 0.975)
    # With the modes block present, per-mode keys win.
    p = bce.declared_params({'target_humidity': '0.96', 'humidity_tolerance': '0.015',
                             'modes.fruiting.target_humidity': '0.90',
                             'modes.fruiting.band_low': '0.885',
                             'modes.fruiting.band_high': '0.915'})
    assert (p['band_low'], p['band_high'], p['target']) == (0.885, 0.915, 0.90)


def test_force_window_splits_an_epoch_into_three():
    epoch = {'effective_from': t(1), 'effective_to': t(4), 'mode': 'fruiting',
             'target': 0.90, 'band_low': 0.885, 'band_high': 0.915,
             'source': 'git', 'confidence': 'high', 'anchor': 'restart'}
    windows = [{'mode': 'force-condensation', 'start': t(2), 'end': t(3)}]

    out = bce.carve_force_windows([epoch], windows)

    assert len(out) == 3, [(bce.iso(e['effective_from']), e['mode']) for e in out]
    assert [e['mode'] for e in out] == ['fruiting', 'force-condensation', 'fruiting']
    assert (out[1]['band_low'], out[1]['band_high'], out[1]['target']) == (0.0, 1.0, 1.0)
    assert out[1]['source'] == 'telemetry'
    # The law is unchanged by a runtime set_mode -- only the band moved.
    assert all(e.get('law_sha') == epoch.get('law_sha') for e in out)


def test_force_window_outside_the_epoch_changes_nothing():
    epoch = {'effective_from': t(1), 'effective_to': t(2), 'mode': 'fruiting',
             'band_low': 0.885, 'band_high': 0.915, 'target': 0.90}
    out = bce.carve_force_windows([epoch], [{'mode': 'force-evaporation',
                                             'start': t(5), 'end': t(6)}])
    assert len(out) == 1 and out[0]['mode'] == 'fruiting'


def test_short_force_blips_are_noise_not_windows():
    minutes = (minute_series(t(1), 60, 0.90)
               + minute_series(t(1, 1), 2, 1.0)        # 2 min: below threshold
               + minute_series(t(1, 1, 2), 60, 0.90))
    assert bce.force_windows(minutes) == []

    minutes = (minute_series(t(1), 60, 0.90)
               + minute_series(t(1, 1), 10, 1.0)       # 10 min: a real window
               + minute_series(t(1, 1, 10), 60, 0.90))
    windows = bce.force_windows(minutes)
    assert len(windows) == 1
    assert windows[0]['mode'] == 'force-condensation'
    assert windows[0]['start'] == t(1, 1)


def test_out_of_range_target_is_invalid_not_a_force_mode():
    # The week of 2026-05-04 carried values up to 71.39. Those must never be
    # read as "force-condensation ran", which is what a naive >= 0.999 does.
    assert bce.classify(71.39) == 'invalid'
    assert bce.classify(1.0) == 'force-condensation'
    assert bce.classify(0.0) == 'force-evaporation'
    assert bce.classify(0.90) == 'normal'
    assert bce.force_windows(minute_series(t(1), 30, 71.39)) == []


def test_restart_is_detected_only_where_the_ramp_exists():
    def band_high_at(_ts):
        return 0.915

    # Post-2026-06-27 window: an excursion to 0.9585 is a boot ramp.
    minutes = (minute_series(t(1), 30, 0.90)
               + [(t(1, 0, 30), 0.9585, 0.9585)]
               + minute_series(t(1, 0, 31), 30, 0.90))
    assert bce.restart_events(minutes, band_high_at) == [t(1, 0, 30)]

    # The same shape before the band moved is invisible; nothing is claimed.
    old = [(ts.replace(month=6, day=1), v, m) for ts, v, m in minutes]
    assert bce.restart_events(old, band_high_at) == []


def test_consecutive_ramp_minutes_are_one_restart_not_many():
    def band_high_at(_ts):
        return 0.915
    minutes = (minute_series(t(1), 10, 0.90)
               + minute_series(t(1, 0, 10), 3, 0.9585)   # one boot, 3 min of ramp
               + minute_series(t(1, 0, 13), 10, 0.90)
               + minute_series(t(1, 2), 2, 0.9585)       # a second boot, 2h later
               + minute_series(t(1, 2, 2), 10, 0.90))
    assert bce.restart_events(minutes, band_high_at) == [t(1, 0, 10), t(1, 2)]


def test_commit_with_no_following_restart_is_flagged_not_dropped():
    commits = [
        {'sha': 'a' * 40, 'time': t(1)},
        {'sha': 'b' * 40, 'time': t(20)},    # pushed, never restarted after
    ]
    minutes = (minute_series(t(1), 5, 0.90)
               + minute_series(t(2), 1, 0.9585)          # the only restart
               + minute_series(t(2, 0, 1), 5, 0.90))
    epochs, restarts, unreached = build_with_stub_config(commits, minutes, t(30))

    assert unreached == ['b' * 8]
    flagged = [e for e in epochs if e['law_sha'] == 'b' * 8]
    assert flagged and flagged[0]['confidence'] == 'unreached'


def test_epochs_tile_the_window_with_no_gaps_or_overlaps():
    commits = [{'sha': 'a' * 40, 'time': t(1)},
               {'sha': 'b' * 40, 'time': t(5)}]
    minutes = (minute_series(t(1), 5, 0.90)
               + minute_series(t(6), 2, 0.9585)          # restart picks up 'b'
               + minute_series(t(6, 0, 2), 5, 0.90)
               + minute_series(t(8), 10, 1.0)            # a force window mid-epoch
               + minute_series(t(8, 0, 10), 5, 0.90))
    epochs, _, _ = build_with_stub_config(commits, minutes, t(30))

    assert epochs
    for earlier, later in zip(epochs, epochs[1:]):
        assert earlier['effective_to'] == later['effective_from'], (
            f"gap/overlap at {bce.iso(earlier['effective_to'])}")
    assert epochs[-1]['effective_to'] == t(30)
    assert any(e['mode'] == 'force-condensation' for e in epochs)


def build_with_stub_config(commits, minutes, now):
    """build_epochs with parse_config stubbed -- these fixtures have no git."""
    real = bce.parse_config
    bce.parse_config = lambda sha: {
        'active_mode': 'fruiting', 'pid_kp': '0.36', 'pid_ki': '0.001',
        'modes.fruiting.target_humidity': '0.90',
        'modes.fruiting.band_low': '0.885', 'modes.fruiting.band_high': '0.915',
    }
    try:
        return bce.build_epochs(commits, minutes, {}, now)
    finally:
        bce.parse_config = real


def test_duty_bias_needs_enough_unsaturated_samples():
    saturated = {t(1) + timedelta(minutes=i): (1.0, 1.0) for i in range(100)}
    assert bce.measure_duty_bias(saturated, t(1), t(2)) == (None, 0)

    biased = {t(1) + timedelta(minutes=i): (0.5, 0.6) for i in range(100)}
    value, n = bce.measure_duty_bias(biased, t(1), t(2))
    assert n == 100 and abs(value - 0.1) < 1e-9


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f'  ok   {fn.__name__}')
        except AssertionError as exc:
            failed += 1
            print(f'  FAIL {fn.__name__}: {exc}')
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    sys.exit(1 if failed else 0)
