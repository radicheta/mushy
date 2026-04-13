"""Unit tests for farmos_agent.report_builder."""

import pytest

from farmos_agent.report_builder import build_report_markdown


# ---------------------------------------------------------------------------
# Table structure
# ---------------------------------------------------------------------------

def test_build_report_all_metrics(sample_summary_dict):
    """Markdown table contains a row for all 4 metrics."""
    output = build_report_markdown(sample_summary_dict)
    assert 'Humidity (%)' in output
    assert 'Temperature (C)' in output
    assert 'CO2 (ppm)' in output
    assert 'Humidifier Duty (%)' in output


# ---------------------------------------------------------------------------
# Humidity — percentage scale (the key fix being verified)
# ---------------------------------------------------------------------------

def test_humidity_percentage_scale(sample_summary_dict):
    """Humidity avg=82.3 displays as '82.3', NOT '8230.0' or '8230'."""
    output = build_report_markdown(sample_summary_dict)
    assert '82.3' in output
    assert '8230' not in output


def test_humidity_min_max_percentage(sample_summary_dict):
    """Humidity min=78.1 and max=86.5 appear directly, not multiplied by 100."""
    output = build_report_markdown(sample_summary_dict)
    assert '78.1' in output
    assert '86.5' in output
    assert '7810' not in output
    assert '8650' not in output


# ---------------------------------------------------------------------------
# Anomaly detection — percentage-scale thresholds
# ---------------------------------------------------------------------------

def test_anomaly_humidity_out_of_range():
    """avg=94.0 with target=82.0, tol=1.0 is outside 82 ± 3.0 — anomaly fires."""
    summary = {
        'fc.humidity':    {'avg': 94.0,  'min': 90.0, 'max': 97.0, 'samples': 1440},
        'fc.temperature': {'avg': 21.4,  'min': 19.8, 'max': 23.1, 'samples': 1440},
        'fc.co2':         {'avg': 845.0, 'min': 620.0, 'max': 1180.0, 'samples': 1440},
        'fc.humidifier':  {'avg': 0.45,  'min': 0.0,  'max': 1.0,  'samples': 1440},
    }
    output = build_report_markdown(summary, config_targets={'humidity_target': 82.0, 'humidity_tolerance': 1.0})
    assert 'ANOMALY' in output
    assert '94.0' in output


def test_anomaly_humidity_in_range():
    """avg=82.5 with target=82.0, tol=1.0 is inside 82 ± 3.0 — no anomaly."""
    summary = {
        'fc.humidity':    {'avg': 82.5,  'min': 80.0, 'max': 85.0, 'samples': 1440},
        'fc.temperature': {'avg': 21.4,  'min': 19.8, 'max': 23.1, 'samples': 1440},
        'fc.co2':         {'avg': 845.0, 'min': 620.0, 'max': 1180.0, 'samples': 1440},
        'fc.humidifier':  {'avg': 0.45,  'min': 0.0,  'max': 1.0,  'samples': 1440},
    }
    output = build_report_markdown(summary, config_targets={'humidity_target': 82.0, 'humidity_tolerance': 1.0})
    assert 'ANOMALY: Humidity' not in output


# ---------------------------------------------------------------------------
# Humidifier duty cycle — still stored as 0-1 fraction, multiply by 100 is correct
# ---------------------------------------------------------------------------

def test_duty_cycle_percentage(sample_summary_dict):
    """Humidifier avg=0.45 displays as '45.0%'."""
    output = build_report_markdown(sample_summary_dict)
    assert '45.0%' in output


# ---------------------------------------------------------------------------
# Missing sensor
# ---------------------------------------------------------------------------

def test_missing_sensor_shows_na():
    """A topic with None values displays N/A in every column."""
    summary = {
        'fc.humidity':    {'avg': None, 'min': None, 'max': None, 'samples': None},
        'fc.temperature': {'avg': 21.4, 'min': 19.8, 'max': 23.1, 'samples': 1440},
        'fc.co2':         {'avg': 845.0, 'min': 620.0, 'max': 1180.0, 'samples': 1440},
        'fc.humidifier':  {'avg': 0.45, 'min': 0.0,  'max': 1.0,  'samples': 1440},
    }
    output = build_report_markdown(summary)
    # Humidity row should have N/A entries
    lines = output.split('\n')
    humidity_line = next(l for l in lines if 'Humidity (%)' in l)
    assert humidity_line.count('N/A') >= 1
