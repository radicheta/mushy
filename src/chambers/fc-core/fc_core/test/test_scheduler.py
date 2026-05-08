#!/usr/bin/env python3
"""Phase 30 — pure-Python unit tests for `fc_core.scheduler`.

Plan 30-01 Task 1 (RED→GREEN). Tests run with bare pytest; no rclpy fixtures
required because `scheduler` is a pure helper module (no rclpy import).

See:
- .planning/phases/30-time-of-day-mode-scheduling/30-01-PLAN.md (Task 1)
- .planning/phases/30-time-of-day-mode-scheduling/30-CONTEXT.md (D-01..D-11, D-19)
"""
import pytest

from fc_core import scheduler


# --- parse_schedule -----------------------------------------------------------

def test_parse_schedule_empty_array():
    assert scheduler.parse_schedule('[]') == []


def test_parse_schedule_one_window():
    out = scheduler.parse_schedule(
        '[{"start":"06:00","end":"22:00","mode":"fruiting"}]'
    )
    assert out == [{'start': '06:00', 'end': '22:00', 'mode': 'fruiting'}]


def test_parse_schedule_malformed_json():
    with pytest.raises(ValueError, match=r'JSON'):
        scheduler.parse_schedule('{not json')


def test_parse_schedule_not_an_array():
    with pytest.raises(ValueError, match=r'array'):
        scheduler.parse_schedule('{"start":"00:00"}')


# --- validate_window ----------------------------------------------------------

def test_validate_window_missing_key():
    with pytest.raises(ValueError, match=r'mode'):
        scheduler.validate_window(
            {'start': '06:00', 'end': '22:00'}, {'fruiting', 'pinning'}
        )


def test_validate_window_bad_time():
    with pytest.raises(ValueError, match=r'HH:MM'):
        scheduler.validate_window(
            {'start': '6:00', 'end': '22:00', 'mode': 'fruiting'},
            {'fruiting', 'pinning'},
        )


def test_validate_window_bad_minutes():
    with pytest.raises(ValueError):
        scheduler.validate_window(
            {'start': '06:60', 'end': '22:00', 'mode': 'fruiting'},
            {'fruiting', 'pinning'},
        )


def test_validate_window_unknown_mode():
    with pytest.raises(ValueError, match=r'declared'):
        scheduler.validate_window(
            {'start': '06:00', 'end': '22:00', 'mode': 'composting'},
            {'fruiting', 'pinning'},
        )


# --- compute_desired_mode -----------------------------------------------------

_W_FRUITING_DAY = {'start': '06:00', 'end': '22:00', 'mode': 'fruiting'}
_W_PINNING_NIGHT = {'start': '22:00', 'end': '06:00', 'mode': 'pinning'}


def test_compute_desired_mode_normal_within_window():
    desired, matched = scheduler.compute_desired_mode(
        '10:00', [_W_FRUITING_DAY, _W_PINNING_NIGHT], 'pinning'
    )
    assert desired == 'fruiting'
    assert matched == _W_FRUITING_DAY


def test_compute_desired_mode_wraparound_late_night():
    desired, matched = scheduler.compute_desired_mode(
        '23:30', [_W_FRUITING_DAY, _W_PINNING_NIGHT], 'fruiting'
    )
    assert desired == 'pinning'
    assert matched == _W_PINNING_NIGHT


def test_compute_desired_mode_wraparound_early_morning():
    desired, matched = scheduler.compute_desired_mode(
        '03:00', [_W_FRUITING_DAY, _W_PINNING_NIGHT], 'fruiting'
    )
    assert desired == 'pinning'
    assert matched == _W_PINNING_NIGHT


def test_compute_desired_mode_boundary_inclusive_start():
    # half-open [start, end): exact start is IN the window.
    desired, matched = scheduler.compute_desired_mode(
        '06:00', [_W_FRUITING_DAY, _W_PINNING_NIGHT], 'pinning'
    )
    assert desired == 'fruiting'
    assert matched == _W_FRUITING_DAY


def test_compute_desired_mode_boundary_exclusive_end():
    # half-open [start, end): exact end is OUT. With only the day window, 22:00
    # falls in a gap → keep current mode.
    desired, matched = scheduler.compute_desired_mode(
        '22:00', [_W_FRUITING_DAY], 'fruiting'
    )
    assert desired == 'fruiting'
    assert matched is None


def test_compute_desired_mode_gap():
    desired, matched = scheduler.compute_desired_mode(
        '10:00',
        [{'start': '00:00', 'end': '06:00', 'mode': 'pinning'}],
        'fruiting',
    )
    assert desired == 'fruiting'
    assert matched is None


def test_compute_desired_mode_overlap_last_wins():
    w_all_day = {'start': '00:00', 'end': '24:00', 'mode': 'fruiting'}
    w_inner = {'start': '08:00', 'end': '12:00', 'mode': 'pinning'}
    desired, matched = scheduler.compute_desired_mode(
        '10:00', [w_all_day, w_inner], 'fruiting'
    )
    assert desired == 'pinning'
    assert matched == w_inner


def test_compute_desired_mode_empty_array():
    desired, matched = scheduler.compute_desired_mode(
        '10:00', [], 'fruiting'
    )
    assert desired == 'fruiting'
    assert matched is None
