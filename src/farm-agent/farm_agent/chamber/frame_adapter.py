"""farm_agent/chamber/frame_adapter.py -- bridge WS frame -> FSM event (MUSHY-97).

The bridge publishes measurement-keyed frames with no `type` field:

    {"humidity": 0.913, "timestamp": 1787179328207}
    {"sensor_health": {"level": 0, "message": "ok", "values": {...}}, ...}

state.py dispatches on `event["type"]`. Something has to translate, and in Node
that was index.js:229-257. The port dropped it and `service._on_ws_message`
instead asserted "a bridge frame is already the FSM's event shape", dropping
every frame that lacked a `type` -- which is all of them.

Sniffed live 2026-08-19: 173 frames in 30s, zero recognised. The chamber alerter
had been deaf since the 2026-08-18 cutover.

Port of index.js onMessage. The if/else-if ORDER is behaviour, not style: a
frame carrying both `humidity` and `humidity_2` is a primary reading, and only
falls through to the slot-2 freshness branch when no primary key is present.

`is not None` rather than truthiness throughout: 0.0 %RH, 0 ppm and a humidifier
that is OFF are all real readings that `if msg.get(k)` would silently discard.

ASCII-only. No em-dashes. Never-throws.
"""

from __future__ import annotations

# Simple scalar measurements: bridge key -> FSM event type. Order matters only
# in that these are all checked before the slot-2 freshness fallback.
_SCALARS = (
    ("humidity", "humidity"),
    ("temperature", "temperature"),
    ("co2", "co2"),
    ("humidifier", "humidifier"),
)

# Structured envelopes: bridge key -> (event type, field name to carry it under).
_ENVELOPES = (
    ("current_mode", "mode_update", "mode"),
    ("alerter_overrides", "overrides_update", "overrides"),
    ("alerter_globals", "globals_update", "globals"),
)


def bridge_frame_to_event(frame, now_ms: int) -> dict | None:
    """Translate one bridge frame. None when the FSM has no use for it.

    Most live traffic is None: humidifier_duty, humidity_target, pid_output and
    vpd/water_vapor are Mission Control's business, not the alerter's.
    """
    if not isinstance(frame, dict):
        return None

    # Defensive: if the bridge ever starts emitting FSM shapes, pass them
    # through rather than wrapping them a second time.
    if frame.get("type"):
        return frame

    for key, event_type in _SCALARS:
        if frame.get(key) is not None:
            return {"type": event_type, "value": frame[key]}

    health = frame.get("sensor_health")
    if isinstance(health, dict):
        return {
            "type": "sensor_health",
            "level": health.get("level"),
            "message": health.get("message"),
            "values": health.get("values"),
        }

    # Phase 26 Plan 03 Option C: a slot-2 frame ARRIVING is the SCD41 freshness
    # signal. The value is irrelevant, which is why this branch ignores it.
    # SHT30 freshness travels inside sensor_health.values instead.
    if frame.get("temperature_2") is not None or frame.get("humidity_2") is not None:
        return {"type": "sensor_freshness", "sensor": "scd41", "last_seen_ms": now_ms}

    for key, event_type, field in _ENVELOPES:
        value = frame.get(key)
        if value is not None:
            return {"type": event_type, field: value}

    return None
