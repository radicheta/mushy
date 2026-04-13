"""
Markdown daily report builder for the FarmOS daily report agent.

Formats TimescaleDB telemetry aggregates into a markdown table with anomaly flags.
"""

from typing import Optional

_DEFAULT_CONFIG_TARGETS = {
    'humidity_target': 82.0,
    'humidity_tolerance': 1.0,
    'co2_warn': 1200,
}

# Human-readable labels and units for each topic
_TOPIC_DISPLAY = {
    'fc.humidity':    ('Humidity (%)',        lambda avg: f'{round(avg, 1)}'),
    'fc.temperature': ('Temperature (C)',     lambda avg: f'{round(avg, 1)}'),
    'fc.co2':         ('CO2 (ppm)',           lambda avg: f'{round(avg, 0):.0f}'),
    'fc.humidifier':  ('Humidifier Duty (%)', lambda avg: f'{round(avg * 100, 1)}%'),
}

_TOPIC_ORDER = ['fc.humidity', 'fc.temperature', 'fc.co2', 'fc.humidifier']


def build_report_markdown(
    summary_dict: dict,
    config_targets: Optional[dict] = None,
) -> str:
    """
    Format daily telemetry aggregates as a markdown table with anomaly section.

    Args:
        summary_dict: output of query_daily_summary — keyed by topic with
                      {'avg', 'min', 'max', 'samples'} values (may be None).
        config_targets: optional override for anomaly thresholds. Keys:
                        humidity_target, humidity_tolerance, co2_warn.

    Returns:
        Markdown string with a metrics table and optional anomaly flags section.

    Humidifier duty cycle is shown as avg*100 %; min/max shown as "—" (binary signal).
    None values are shown as "N/A".
    """
    targets = {**_DEFAULT_CONFIG_TARGETS, **(config_targets or {})}

    lines = []
    lines.append('| Metric | Avg | Min | Max | Samples |')
    lines.append('|--------|-----|-----|-----|---------|')

    for topic in _TOPIC_ORDER:
        data = summary_dict.get(topic, {'avg': None, 'min': None, 'max': None, 'samples': None})
        label, fmt_avg = _TOPIC_DISPLAY.get(topic, (topic, str))

        if data.get('avg') is None:
            lines.append(f'| {label} | N/A | N/A | N/A | N/A |')
            continue

        avg_val = data['avg']
        min_val = data.get('min')
        max_val = data.get('max')
        samples = data.get('samples', 0)

        avg_str = fmt_avg(avg_val)

        if topic == 'fc.humidifier':
            # min/max not meaningful for a binary on/off signal
            min_str = '—'
            max_str = '—'
        else:
            min_str = _fmt_metric(topic, min_val)
            max_str = _fmt_metric(topic, max_val)

        samples_str = str(samples) if samples is not None else 'N/A'
        lines.append(f'| {label} | {avg_str} | {min_str} | {max_str} | {samples_str} |')

    table = '\n'.join(lines)

    # Build anomaly flags
    anomalies = _detect_anomalies(summary_dict, targets)
    if anomalies:
        anomaly_section = '\n\n**ANOMALY FLAGS:**\n' + '\n'.join(
            f'- {flag}' for flag in anomalies
        )
    else:
        anomaly_section = ''

    return table + anomaly_section


def _fmt_metric(topic: str, value) -> str:
    """Format a raw metric value for display."""
    if value is None:
        return 'N/A'
    if topic == 'fc.humidity':
        return f'{round(value, 1)}'
    if topic == 'fc.co2':
        return f'{round(value, 0):.0f}'
    return f'{round(value, 1)}'


def _detect_anomalies(summary_dict: dict, targets: dict) -> list:
    """Return list of anomaly description strings, or empty list if all clear."""
    anomalies = []

    humidity_data = summary_dict.get('fc.humidity', {})
    if humidity_data.get('samples') == 0:
        anomalies.append('WARNING: Humidity sensor offline (0 samples in 24h window)')
    elif humidity_data.get('avg') is not None:
        target = targets['humidity_target']
        tolerance = targets['humidity_tolerance']
        avg = humidity_data['avg']
        if abs(avg - target) > 3 * tolerance:
            anomalies.append(
                f'ANOMALY: Humidity avg {round(avg, 1)}% is outside target {round(target, 1)}% '
                f'± {round(3 * tolerance, 1)}%'
            )

    co2_data = summary_dict.get('fc.co2', {})
    if co2_data.get('samples') == 0:
        anomalies.append('WARNING: CO2 sensor offline (0 samples in 24h window)')
    elif co2_data.get('avg') is not None:
        if co2_data['avg'] > targets['co2_warn']:
            anomalies.append(
                f"ANOMALY: CO2 avg {round(co2_data['avg'], 0):.0f} ppm exceeds "
                f"warning threshold {targets['co2_warn']} ppm"
            )

    # Check other sensors for zero samples
    for topic, label in [('fc.temperature', 'Temperature'), ('fc.humidifier', 'Humidifier')]:
        data = summary_dict.get(topic, {})
        if data.get('samples') == 0:
            anomalies.append(f'WARNING: {label} sensor offline (0 samples in 24h window)')

    return anomalies
