"""MUSHY-97: bridge frames must be translated into FSM events.

The Python chamber alerter was DEAF. `service._on_ws_message` said "a bridge
frame is already the FSM's event shape" and dropped anything without a `type`
key -- but the bridge sends measurement-keyed frames with no `type` at all:

    {"humidity": 0.913, "timestamp": 1787179328207}
    {"sensor_health": {"level": 0, ...}, "timestamp": ...}

Sniffed live 2026-08-19 over 30s: 173 frames, **zero** the FSM recognised. So
since the 2026-08-18 cutover the alerter received no RH, temperature, CO2,
sensor-health or humidifier events at all. No out-of-band alert, no stuck
humidifier alert, no sensor alert, and an empty heartbeat summary every day.

Node did this translation in index.js:229-257 and the port dropped it. Exactly
the wiring-seam class the repo has been bitten by before -- both sides unit
tested, the glue between them missing (MUSHY-90, and index.js's own comment
about a field dropped on destructure).

pi_liveness is unaffected: it arrives through on_liveness, which IS wired.

ASCII-only. No em-dashes.
"""
from __future__ import annotations

import pytest

from farm_agent.chamber.frame_adapter import bridge_frame_to_event

NOW = 1_787_179_328_207


class TestMeasurements:
    def test_humidity_becomes_a_humidity_event(self):
        assert bridge_frame_to_event({"humidity": 0.913, "timestamp": NOW}, NOW) == {
            "type": "humidity", "value": 0.913,
        }

    def test_temperature(self):
        assert bridge_frame_to_event({"temperature": 9.72, "timestamp": NOW}, NOW) == {
            "type": "temperature", "value": 9.72,
        }

    def test_co2(self):
        assert bridge_frame_to_event({"co2": 812, "timestamp": NOW}, NOW) == {
            "type": "co2", "value": 812,
        }

    def test_humidifier(self):
        assert bridge_frame_to_event({"humidifier": True, "timestamp": NOW}, NOW) == {
            "type": "humidifier", "value": True,
        }

    def test_a_zero_reading_is_still_a_reading(self):
        """`if msg.humidity` would drop 0.0 and 0 ppm. Node used !== undefined."""
        assert bridge_frame_to_event({"humidity": 0.0}, NOW) == {
            "type": "humidity", "value": 0.0,
        }
        assert bridge_frame_to_event({"co2": 0}, NOW) == {"type": "co2", "value": 0}
        assert bridge_frame_to_event({"humidifier": False}, NOW) == {
            "type": "humidifier", "value": False,
        }


class TestStructuredFrames:
    def test_sensor_health_carries_level_message_and_values(self):
        frame = {"sensor_health": {"level": 2, "message": "I2C read failed",
                                   "values": {"sht30_fresh": "false"}}, "timestamp": NOW}
        assert bridge_frame_to_event(frame, NOW) == {
            "type": "sensor_health", "level": 2, "message": "I2C read failed",
            "values": {"sht30_fresh": "false"},
        }

    def test_current_mode_becomes_mode_update(self):
        mode = {"name": "fruiting", "target_humidity": 0.9}
        assert bridge_frame_to_event({"current_mode": mode}, NOW) == {
            "type": "mode_update", "mode": mode,
        }

    def test_alerter_overrides(self):
        ov = {"fruiting": {"oob_n": 5}}
        assert bridge_frame_to_event({"alerter_overrides": ov}, NOW) == {
            "type": "overrides_update", "overrides": ov,
        }

    def test_alerter_globals(self):
        gl = {"heartbeat_hour": 17, "sensor_offline_min": 20}
        assert bridge_frame_to_event({"alerter_globals": gl}, NOW) == {
            "type": "globals_update", "globals": gl,
        }


class TestSlotTwoFreshness:
    @pytest.mark.parametrize("frame", [
        {"temperature_2": 9.5, "timestamp": NOW},
        {"humidity_2": 0.88, "timestamp": NOW},
    ])
    def test_slot_two_arrival_is_an_scd41_freshness_signal(self, frame):
        """Phase 26 Plan 03 Option C: arrival itself is the signal, not the value."""
        assert bridge_frame_to_event(frame, NOW) == {
            "type": "sensor_freshness", "sensor": "scd41", "last_seen_ms": NOW,
        }


class TestOrderingAndRejection:
    def test_primary_humidity_wins_over_a_slot_two_key(self):
        """Node's if/else-if chain checks humidity first; order is behaviour."""
        assert bridge_frame_to_event(
            {"humidity": 0.9, "humidity_2": 0.8}, NOW)["type"] == "humidity"

    @pytest.mark.parametrize("frame", [
        {"humidifier_duty": 0, "timestamp": NOW},
        {"humidity_target": 0.915, "timestamp": NOW},
        {"pid_output": 0, "timestamp": NOW},
        {"vpd": 0.3, "water_vapor": 8.1, "timestamp": NOW},
        {"timestamp": NOW},
        {},
    ])
    def test_frames_the_fsm_has_no_use_for_are_ignored(self, frame):
        """These are the majority of live traffic. Ignoring must not throw."""
        assert bridge_frame_to_event(frame, NOW) is None

    @pytest.mark.parametrize("junk", [None, "text", 42, [], ["humidity"]])
    def test_non_dict_input_is_ignored(self, junk):
        assert bridge_frame_to_event(junk, NOW) is None

    def test_an_already_typed_event_passes_through(self):
        """Defensive: if the bridge ever sends FSM shapes, do not double-wrap."""
        ev = {"type": "humidity", "value": 0.9}
        assert bridge_frame_to_event(ev, NOW) == ev


class TestAgainstRealLiveTraffic:
    """The exact frames sniffed off prod on 2026-08-19."""

    LIVE = [
        ({"humidifier_duty": 0, "timestamp": 1787179326647}, None),
        ({"humidity_target": 0.9150000214576721, "timestamp": 1787179326654}, None),
        ({"pid_output": 0, "timestamp": 1787179326654}, None),
        ({"temperature": 9.72571908140688, "timestamp": 1787179328207}, "temperature"),
        ({"alerter_globals": {"heartbeat_hour": 17, "max_sends_per_hour": 20,
                              "pi_offline_min": 15, "sensor_offline_min": 20},
          "timestamp": 1786939696873}, "globals_update"),
    ]

    def test_each_live_frame_routes_as_expected(self):
        for frame, expected in self.LIVE:
            got = bridge_frame_to_event(frame, NOW)
            assert (got or {}).get("type") == expected, f"{frame} -> {got}"

    def test_the_alerter_would_no_longer_be_deaf(self):
        """At least one real frame must produce a usable telemetry event."""
        events = [bridge_frame_to_event(f, NOW) for f, _ in self.LIVE]
        assert any(e and e["type"] in ("humidity", "temperature", "co2") for e in events)
