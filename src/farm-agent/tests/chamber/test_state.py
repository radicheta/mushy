"""
tests/chamber/test_state.py -- the alert FSM (port of state.js).

state.js is the highest-risk file in the port and it is internally inconsistent
(see the call-site matrix in 63-07-PLAN.md). Tests named *_parity_quirk_* pin
behaviour that looks wrong and is reproduced deliberately.
"""

import pytest

from farm_agent.chamber import rules, state

MIN = 60_000
BOOT = 1_700_000_000_000


def _mode(name="fruiting", target=0.90, low=0.88, high=0.92, defend="low"):
    return {"name": name, "target_humidity": target,
            "band_low": low, "band_high": high, "defend_side": defend}


# ---------------------------------------------------------------------------
# initial_state
# ---------------------------------------------------------------------------


def test_initial_state_has_all_six_types_ok():
    st = state.initial_state(BOOT)
    assert set(st.per_type) == {"rh", "sensor", "pi", "humidifier", "sht30", "scd41"}
    assert all(e.state == "OK" for e in st.per_type.values())


def test_initial_state_seeds_sensor_last_seen_to_boot_not_none():
    """Phase 26 Plan 03: a never-seen sensor must not fire before the grace window.

    None would make (now - last_seen) meaningless; seeding to boot means the
    watchdog starts counting from startup.
    """
    st = state.initial_state(BOOT)
    assert st.sht30_last_seen_ms == BOOT
    assert st.scd41_last_seen_ms == BOOT
    assert st.booted_at_ms == BOOT


def test_alert_types_and_severity_are_exact():
    assert state.ALERT_TYPES == ["rh", "sensor", "pi", "humidifier", "sht30", "scd41"]
    assert state.SEVERITY == {
        "rh": "WARN", "sensor": "CRITICAL", "pi": "CRITICAL",
        "humidifier": "WARN", "sht30": "CRITICAL", "scd41": "CRITICAL",
    }


def test_cooldown_is_severity_conditional(chamber_config):
    cfg = chamber_config(ALERT_COOLDOWN_MIN="30", ALERT_CRITICAL_COOLDOWN_MIN="60")
    assert state.cooldown_ms("rh", cfg) == 30 * MIN          # WARN
    assert state.cooldown_ms("pi", cfg) == 60 * MIN          # CRITICAL


def test_is_snoozed_boundary():
    e = state.AlertEntry(snoozed_until=1_000)
    assert state.is_snoozed(e, 999) is True
    assert state.is_snoozed(e, 1_000) is False      # js:84 uses `now < snoozedUntil`
    assert state.is_snoozed(state.AlertEntry(), 999) is False


# ---------------------------------------------------------------------------
# has_mode_context -- the cold-boot gate (js:244)
# ---------------------------------------------------------------------------


def test_has_mode_context_false_before_any_mode_event():
    assert state.has_mode_context(state.initial_state(BOOT)) is False


@pytest.mark.parametrize(
    "field", ["mode_received_at_ms", "overrides_received_at_ms", "globals_received_at_ms"]
)
def test_has_mode_context_true_after_any_of_the_three(field):
    st = state.initial_state(BOOT)
    setattr(st, field, BOOT + 1_000)
    assert state.has_mode_context(st) is True


# ---------------------------------------------------------------------------
# resolve_effective_config -- Tier A/B/C matrix (js:192-237)
# ---------------------------------------------------------------------------


def _st_with_mode(cfg_now, **over):
    st = state.initial_state(BOOT)
    st.current_mode = _mode()
    st.mode_received_at_ms = cfg_now
    st.ws_connected = True
    for k, v in over.items():
        setattr(st, k, v)
    return st


def test_tier_a_applies_when_mode_is_fresh(chamber_config):
    """rh_target/rh_band come from the live ROS mode, not env (js:216-217)."""
    cfg = chamber_config(ALERT_RH_TARGET="90", ALERT_RH_BAND="3", ALERT_MODE_STALE_MIN="5")
    now = BOOT + 10 * MIN
    st = _st_with_mode(now - 1 * MIN)
    eff = state.resolve_effective_config(st, cfg, now)

    assert eff.freshness.state == "fresh"
    assert eff.freshness.source == "mode"
    assert eff.rh_target == 90.0                 # 0.90 * 100
    assert eff.rh_band == pytest.approx(2.0)     # ((0.92-0.88)/2)*100
    assert eff.band_low == pytest.approx(88.0)
    assert eff.band_high == pytest.approx(92.0)
    assert eff.mode_name == "fruiting"


def test_tier_a_drops_out_when_mode_is_stale(chamber_config):
    cfg = chamber_config(ALERT_RH_TARGET="90", ALERT_RH_BAND="3", ALERT_MODE_STALE_MIN="5")
    now = BOOT + 60 * MIN
    st = _st_with_mode(now - 6 * MIN)            # older than mode_stale_min
    eff = state.resolve_effective_config(st, cfg, now)

    assert eff.freshness.state == "stale"
    assert eff.freshness.source == "env"
    assert eff.rh_band == 3.0                    # env fallback, not the mode's 2.0


def test_tier_a_drops_out_when_ws_disconnected(chamber_config):
    cfg = chamber_config(ALERT_MODE_STALE_MIN="5")
    now = BOOT + 10 * MIN
    st = _st_with_mode(now - 1 * MIN, ws_connected=False)
    eff = state.resolve_effective_config(st, cfg, now)
    assert eff.freshness.state == "stale"


def test_ws_connected_none_counts_as_connected(chamber_config):
    """js:195 -- `state.wsConnected !== false`. None is tolerated as connected."""
    cfg = chamber_config(ALERT_MODE_STALE_MIN="5")
    now = BOOT + 10 * MIN
    st = _st_with_mode(now - 1 * MIN, ws_connected=None)
    assert state.resolve_effective_config(st, cfg, now).freshness.state == "fresh"


def test_cold_start_grace_when_mode_never_arrived(chamber_config):
    """js:232 -- within the boot grace, absence of a mode is 'cold', not 'stale'."""
    cfg = chamber_config(ALERT_MODE_BOOT_GRACE_SEC="60")
    st = state.initial_state(BOOT)
    eff = state.resolve_effective_config(st, cfg, BOOT + 30_000)
    assert eff.freshness.state == "cold"
    assert eff.freshness.source == "env"


def test_cold_becomes_stale_past_the_grace(chamber_config):
    cfg = chamber_config(ALERT_MODE_BOOT_GRACE_SEC="60")
    st = state.initial_state(BOOT)
    eff = state.resolve_effective_config(st, cfg, BOOT + 90_000)
    assert eff.freshness.state == "stale"


def test_tier_b_per_mode_overrides_apply_when_fresh(chamber_config):
    cfg = chamber_config(ALERT_OOB_N="5", ALERT_COOLDOWN_MIN="30")
    now = BOOT + 10 * MIN
    st = _st_with_mode(now - 1 * MIN)
    st.alerter_overrides = {"fruiting": {"oob_n": 2, "cooldown_min": 7}}
    eff = state.resolve_effective_config(st, cfg, now)
    assert eff.oob_n == 2
    assert eff.cooldown_min == 7


def test_tier_b_ignored_for_a_different_mode_name(chamber_config):
    cfg = chamber_config(ALERT_OOB_N="5")
    now = BOOT + 10 * MIN
    st = _st_with_mode(now - 1 * MIN)
    st.alerter_overrides = {"pinning": {"oob_n": 2}}      # not the active mode
    assert state.resolve_effective_config(st, cfg, now).oob_n == 5


def test_tier_c_applies_even_when_mode_is_stale(chamber_config):
    """THE point of Tier C (js:199-207): pi_offline_min must hold precisely when
    fc1 is offline -- which is exactly when the mode has gone stale."""
    cfg = chamber_config(ALERT_PI_OFFLINE_MIN="5", ALERT_SENSOR_OFFLINE_MIN="5")
    st = state.initial_state(BOOT)
    st.alerter_globals = {"pi_offline_min": 12, "sensor_offline_min": 9}
    eff = state.resolve_effective_config(st, cfg, BOOT + 90 * MIN)   # stale

    assert eff.freshness.state == "stale"
    assert eff.pi_offline_min == 12        # global override survived
    assert eff.sensor_offline_min == 9


def test_tier_c_applies_in_all_three_freshness_branches(chamber_config):
    cfg = chamber_config(ALERT_HEARTBEAT_HOUR="8")
    globals_ = {"heartbeat_hour": 21}
    now = BOOT + 10 * MIN

    fresh = _st_with_mode(now - 1 * MIN); fresh.alerter_globals = globals_
    cold = state.initial_state(BOOT); cold.alerter_globals = globals_
    stale = state.initial_state(BOOT); stale.alerter_globals = globals_

    assert state.resolve_effective_config(fresh, cfg, now).heartbeat_hour == 21
    assert state.resolve_effective_config(cold, cfg, BOOT + 10_000).heartbeat_hour == 21
    assert state.resolve_effective_config(stale, cfg, BOOT + 90 * MIN).heartbeat_hour == 21


def test_stale_effective_config_suspends_the_rh_rule(chamber_config):
    """The 2026-05-07 guard, end to end: resolver -> rules.is_rh_oob.

    A frozen cached RH of 10% during an outage must NOT page the farmer.
    """
    cfg = chamber_config()
    st = state.initial_state(BOOT)
    eff = state.resolve_effective_config(st, cfg, BOOT + 90 * MIN)
    assert eff.freshness.state == "stale"
    assert rules.is_rh_oob(10.0, eff) is False


def test_cold_effective_config_does_not_suspend_rh(chamber_config):
    """Only 'stale' suspends -- 'cold' still evaluates (Pitfall 1)."""
    cfg = chamber_config(ALERT_MODE_BOOT_GRACE_SEC="60")
    st = state.initial_state(BOOT)
    eff = state.resolve_effective_config(st, cfg, BOOT + 10_000)
    assert eff.freshness.state == "cold"
    assert rules.is_rh_oob(10.0, eff) is True


# ---------------------------------------------------------------------------
# drive_alert_type -- the generic FSM (js:94-178)
# ---------------------------------------------------------------------------


def _cfg(chamber_config, **over):
    return chamber_config(**over)


def test_ok_to_pending_on_first_oob(chamber_config):
    cfg = _cfg(chamber_config, ALERT_OOB_N="5", ALERT_OOB_WINDOW_MIN="3")
    e, actions = state.drive_alert_type(state.AlertEntry(), "rh", True, {}, BOOT, cfg)
    assert e.state == "PENDING"
    assert e.oob_count == 1
    assert e.first_oob_at == BOOT
    assert actions == []


def test_pending_to_firing_needs_both_count_and_window(chamber_config):
    """js:106-107 -- oob_count >= oob_n AND the window has elapsed. Both."""
    cfg = _cfg(chamber_config, ALERT_OOB_N="3", ALERT_OOB_WINDOW_MIN="3")
    e = state.AlertEntry()
    now = BOOT
    for i in range(3):
        e, actions = state.drive_alert_type(e, "rh", True, {}, now + i * 1_000, cfg)
    assert e.state == "PENDING"          # count reached, window has NOT
    assert actions == []

    e, actions = state.drive_alert_type(e, "rh", True, {}, now + 4 * MIN, cfg)
    assert e.state == "FIRING"
    assert len(actions) == 1
    assert actions[0]["kind"] == "send"


def test_firing_repeats_only_after_cooldown(chamber_config):
    cfg = _cfg(chamber_config, ALERT_OOB_N="1", ALERT_OOB_WINDOW_MIN="0",
               ALERT_COOLDOWN_MIN="30")
    e, actions = state.drive_alert_type(state.AlertEntry(), "rh", True, {}, BOOT, cfg)
    assert e.state == "FIRING" and len(actions) == 1

    e, actions = state.drive_alert_type(e, "rh", True, {}, BOOT + 10 * MIN, cfg)
    assert actions == []                                   # inside cooldown

    e, actions = state.drive_alert_type(e, "rh", True, {}, BOOT + 31 * MIN, cfg)
    assert len(actions) == 1                               # cooldown elapsed


def test_snoozed_entry_transitions_but_does_not_send(chamber_config):
    """js:110 -- the FSM still advances; only the send is suppressed."""
    cfg = _cfg(chamber_config, ALERT_OOB_N="1", ALERT_OOB_WINDOW_MIN="0")
    e = state.AlertEntry(snoozed_until=BOOT + MIN)
    e, actions = state.drive_alert_type(e, "rh", True, {}, BOOT, cfg)
    assert e.state == "FIRING"
    assert actions == []


def test_pending_resets_to_ok_when_back_in_band(chamber_config):
    cfg = _cfg(chamber_config, ALERT_OOB_N="5", ALERT_OOB_WINDOW_MIN="3")
    e, _ = state.drive_alert_type(state.AlertEntry(), "rh", True, {}, BOOT, cfg)
    e, actions = state.drive_alert_type(e, "rh", False, {}, BOOT + 1_000, cfg)
    assert e.state == "OK"
    assert e.oob_count == 0 and e.first_oob_at is None
    assert actions == []                     # no recovery message from PENDING


def test_firing_recovers_after_oob_n_in_band_samples(chamber_config):
    """js:159-160 -- recovery counts in-band samples against config.oob_n."""
    cfg = _cfg(chamber_config, ALERT_OOB_N="3", ALERT_OOB_WINDOW_MIN="0")
    e = state.AlertEntry(state="FIRING", first_oob_at=BOOT, last_fired_at=BOOT)
    for i in range(2):
        e, actions = state.drive_alert_type(e, "rh", False, {}, BOOT + i * 1_000, cfg)
        assert actions == []
    e, actions = state.drive_alert_type(e, "rh", False, {}, BOOT + 5 * MIN, cfg)
    assert e.state == "OK"
    assert actions[0]["kind"] == "recovery"
    assert actions[0]["duration_ms"] == 5 * MIN


def test_drive_alert_type_does_not_mutate_the_input_entry(chamber_config):
    """Node cloned before mutating (js:96). Callers rely on the old entry surviving."""
    cfg = _cfg(chamber_config, ALERT_OOB_N="1", ALERT_OOB_WINDOW_MIN="0")
    original = state.AlertEntry()
    returned, _ = state.drive_alert_type(original, "rh", True, {}, BOOT, cfg)
    assert original.state == "OK"
    assert returned is not original


# ---------------------------------------------------------------------------
# Fast-fire -- Pitfall 3, per CALL SITE (see the plan's matrix)
# ---------------------------------------------------------------------------


def test_fast_fire_config_zeroes_the_debounce(chamber_config):
    cfg = _cfg(chamber_config, ALERT_OOB_N="5", ALERT_OOB_WINDOW_MIN="3")
    ff = state._fast_fire(cfg)
    assert ff.oob_n == 1
    assert ff.oob_window_min == 0
    assert ff.cooldown_min == cfg.cooldown_min        # everything else preserved


def test_pi_liveness_fires_on_first_detection(chamber_config):
    """js:546-547 -- pi bypasses the debounce on the pi_liveness path.

    The 3-minute threshold inside is_pi_offline IS the flap protection; layering
    oob_n=5 / oob_window_min=3 on top would push FIRING out to ~11 minutes and
    defeat Phase 46's whole design intent.
    """
    cfg = _cfg(chamber_config, ALERT_OOB_N="5", ALERT_OOB_WINDOW_MIN="3",
               ALERT_PI_OFFLINE_MIN="5")
    st = state.initial_state(BOOT)
    st.ws_connected = False
    st.ws_last_connected_ms = BOOT
    now = BOOT + 90 * MIN     # past the startup grace, ws down well past threshold

    st, actions = state.transition(
        st, {"type": "pi_liveness", "ws_connected": False, "ros_connected": True}, now, cfg
    )
    assert st.per_type["pi"].state == "FIRING"
    assert any(a["kind"] == "send" and a["alert_type"] == "pi" for a in actions)


def test_parity_quirk_tick_pi_does_not_fast_fire(chamber_config):
    """PINNED QUIRK -- js:580 passes `effective`, NOT the fast-fire copy.

    js:547 (pi_liveness) builds piCfg with oob_n=1/oob_window_min=0; js:580 (tick)
    does not. So the same outage fires immediately when the health poll reports it
    and is debounced when only the periodic tick sees it.

    63-RESEARCH.md Pitfall 3 states both call sites use the override and advises
    applying one helper 'consistently'. That is wrong -- verified against state.js
    on 2026-07-25. Making them consistent CHANGES SC1 timing and fails Phase 64.
    Reproduce the asymmetry; raise it as a delta candidate, do not fix it here.
    """
    cfg = _cfg(chamber_config, ALERT_OOB_N="5", ALERT_OOB_WINDOW_MIN="3",
               ALERT_PI_OFFLINE_MIN="5")
    st = state.initial_state(BOOT)
    st.ws_connected = False
    st.ws_last_connected_ms = BOOT
    now = BOOT + 90 * MIN

    st, actions = state.transition(st, {"type": "tick"}, now, cfg)
    assert st.per_type["pi"].state == "PENDING"      # NOT FIRING
    # No PI action. (The same tick legitimately fires the sht30/scd41 watchdogs,
    # which DO fast-fire from raw config -- js:609-623 -- so the action list is
    # not globally empty. Filtering to pi is what pins this quirk.)
    assert [a for a in actions if a.get("alert_type") == "pi"] == []


def test_parity_quirk_sensor_fires_on_one_error_recovers_on_five(chamber_config):
    """PINNED QUIRK -- js:354 vs js:359.

    The error branch passes a fast-fire config (oob_n=1); the in-band branch passes
    raw config (oob_n=5). drive_alert_type counts recovery against config.oob_n, so
    a sensor alert fires on ONE error event but needs FIVE clean ones to clear.
    """
    cfg = _cfg(chamber_config, ALERT_OOB_N="5")
    st = state.initial_state(BOOT)

    st, actions = state.transition(
        st, {"type": "sensor_health", "level": 2, "message": "I2C read failed"},
        BOOT + 2 * MIN, cfg,
    )
    assert st.per_type["sensor"].state == "FIRING"
    assert len([a for a in actions if a.get("alert_type") == "sensor"]) == 1

    for i in range(4):
        st, actions = state.transition(
            st, {"type": "sensor_health", "level": 0, "message": "ok"},
            BOOT + (3 + i) * MIN, cfg,
        )
        assert st.per_type["sensor"].state == "FIRING", "recovered too early"

    st, actions = state.transition(
        st, {"type": "sensor_health", "level": 0, "message": "ok"}, BOOT + 8 * MIN, cfg
    )
    assert st.per_type["sensor"].state == "OK"
    assert actions[0]["kind"] == "recovery"


def test_parity_quirk_sensor_watchdogs_ignore_tier_c_overrides(chamber_config):
    """PINNED QUIRK -- js:610, 621 build sensorCfg from raw `config`, not `effective`.

    A Tier C global sensor_offline_min override therefore never reaches the
    sht30/scd41 watchdogs, despite D-01's 'detectors consume the effective config'
    framing. Verified against state.js on 2026-07-25.
    """
    cfg = _cfg(chamber_config, ALERT_SENSOR_OFFLINE_MIN="5")
    st = state.initial_state(BOOT)
    st.alerter_globals = {"sensor_offline_min": 600}     # 10h -- would suppress
    st.globals_received_at_ms = BOOT
    st.sht30_last_seen_ms = BOOT
    now = BOOT + 30 * MIN                                # > env 5min, < global 600min

    st, _ = state.transition(st, {"type": "tick"}, now, cfg)
    # env threshold wins because the override never reaches this call site
    assert st.per_type["sht30"].state == "FIRING"


# ---------------------------------------------------------------------------
# mode_update -- Pitfall 6
# ---------------------------------------------------------------------------


def test_mode_update_resets_dedup_for_rh_and_humidifier(chamber_config):
    cfg = _cfg(chamber_config, ALERT_OOB_N="5", ALERT_OOB_WINDOW_MIN="3")
    st = state.initial_state(BOOT)
    st.per_type["rh"] = state.AlertEntry(
        state="PENDING", oob_count=4, first_oob_at=BOOT, ctx={"in_band_count": 2}
    )

    st, _ = state.transition(
        st, {"type": "mode_update", "mode": _mode()}, BOOT + MIN, cfg
    )
    assert st.per_type["rh"].oob_count == 0
    assert st.per_type["rh"].first_oob_at is None
    assert st.per_type["rh"].ctx.get("in_band_count") == 0


def test_mode_update_preserves_cooldown(chamber_config):
    """Pitfall 6 (js:309) -- last_fired_at is deliberately NOT reset.

    Otherwise a mode swap would re-page the farmer about an alert they were just
    told about.
    """
    cfg = _cfg(chamber_config, ALERT_OOB_N="1", ALERT_OOB_WINDOW_MIN="0",
               ALERT_COOLDOWN_MIN="30")
    st = state.initial_state(BOOT)
    # ws must be UP or resolve_effective_config returns stale freshness, which
    # suspends the RH rule entirely (js:195 + rules.js:17) -- the humidity sample
    # below would then read as in-band and emit a RECOVERY instead of exercising
    # the cooldown. initial_state seeds ws_connected=False, matching js:46.
    st.ws_connected = True
    st.per_type["rh"] = state.AlertEntry(state="FIRING", first_oob_at=BOOT,
                                         last_fired_at=BOOT)

    st, _ = state.transition(st, {"type": "mode_update", "mode": _mode()}, BOOT + MIN, cfg)
    assert st.per_type["rh"].last_fired_at == BOOT       # survived

    st, actions = state.transition(
        st, {"type": "humidity", "value": 10.0}, BOOT + 5 * MIN, cfg
    )
    assert actions == []                                  # still inside cooldown


def test_mode_update_leaves_other_types_untouched(chamber_config):
    cfg = _cfg(chamber_config)
    st = state.initial_state(BOOT)
    st.per_type["pi"] = state.AlertEntry(state="PENDING", oob_count=3, first_oob_at=BOOT)

    st, _ = state.transition(st, {"type": "mode_update", "mode": _mode()}, BOOT + MIN, cfg)
    assert st.per_type["pi"].oob_count == 3               # js:302 loops rh+humidifier only


# ---------------------------------------------------------------------------
# Suppression + grace windows
# ---------------------------------------------------------------------------


def test_pi_firing_suppresses_rh_evaluation(chamber_config):
    """Phase 46 D-07 (js:270) -- chamber-dark subsumes per-sensor noise."""
    cfg = _cfg(chamber_config, ALERT_OOB_N="1", ALERT_OOB_WINDOW_MIN="0")
    st = state.initial_state(BOOT)
    st.per_type["pi"] = state.AlertEntry(state="FIRING", first_oob_at=BOOT, last_fired_at=BOOT)

    st, actions = state.transition(
        st, {"type": "humidity", "value": 10.0}, BOOT + 90 * MIN, cfg
    )
    assert st.per_type["rh"].state == "OK"
    assert actions == []


def test_startup_grace_suppresses_pi_for_60s(chamber_config):
    """js:514 -- a literal 60s, not mode_boot_grace_ms."""
    cfg = _cfg(chamber_config, ALERT_PI_OFFLINE_MIN="5")
    st = state.initial_state(BOOT)
    st.ws_connected = False
    st.ws_last_connected_ms = BOOT - 90 * MIN

    st, actions = state.transition(
        st, {"type": "pi_liveness", "ws_connected": False, "ros_connected": False},
        BOOT + 30_000, cfg,
    )
    assert actions == []
    assert st.per_type["pi"].state == "OK"


def test_warming_up_suppresses_rh(chamber_config):
    """js:270 -- sensor_health level 1 sets warming_up, which gates the RH rule."""
    cfg = _cfg(chamber_config, ALERT_OOB_N="1", ALERT_OOB_WINDOW_MIN="0")
    st = state.initial_state(BOOT)
    st, _ = state.transition(
        st, {"type": "sensor_health", "level": 1, "message": "warming"}, BOOT + 2 * MIN, cfg
    )
    assert st.warming_up is True

    st, actions = state.transition(st, {"type": "humidity", "value": 10.0}, BOOT + 3 * MIN, cfg)
    assert actions == []


# ---------------------------------------------------------------------------
# snooze + heartbeat
# ---------------------------------------------------------------------------


def test_snooze_all_sets_every_type(chamber_config):
    cfg = _cfg(chamber_config)
    st = state.initial_state(BOOT)
    until = BOOT + 24 * 60 * MIN
    st, _ = state.transition(
        st, {"type": "snooze", "alert_type": "all", "until_ms": until}, BOOT, cfg
    )
    assert all(st.per_type[t].snoozed_until == until for t in state.ALERT_TYPES)


def test_snooze_single_type(chamber_config):
    cfg = _cfg(chamber_config)
    st = state.initial_state(BOOT)
    st, _ = state.transition(
        st, {"type": "snooze", "alert_type": "rh", "until_ms": BOOT + MIN}, BOOT, cfg
    )
    assert st.per_type["rh"].snoozed_until == BOOT + MIN
    assert st.per_type["pi"].snoozed_until is None


def test_heartbeat_fires_after_the_hour_not_only_on_it(chamber_config):
    """SANCTIONED DELTA (MUSHY-44 item 4) -- js:662 gates on `hour ===
    heartbeat_hour`, but Plan 05's scheduler dispatches at `hour >=` and marks
    the day consumed, so an alerter restarted at 10:00 with heartbeat_hour=8
    burned the day silently. The reducer now uses `>=` too.

    Still at most one heartbeat per local day: the second tick is a no-op.
    """
    import datetime
    from zoneinfo import ZoneInfo

    cfg = _cfg(chamber_config, ALERT_HEARTBEAT_HOUR="8")
    tz = ZoneInfo(cfg.timezone)
    at_10 = int(datetime.datetime(2026, 7, 13, 10, 0, tzinfo=tz).timestamp() * 1000)
    at_08 = int(datetime.datetime(2026, 7, 13, 8, 30, tzinfo=tz).timestamp() * 1000)
    summary = {"rh": 91.0, "temp": 21.0, "co2": 800,
               "humidifier": "OFF", "humidifier_cycles": 2, "pi_last_seen_sec": 3}

    st = state.initial_state(BOOT)
    st, actions = state.transition(
        st, {"type": "heartbeat_tick", "summary": summary}, at_10, cfg
    )
    assert actions[0]["kind"] == "heartbeat"   # restarted at 10:00, day not burned
    assert st.last_heartbeat_day == "2026-07-13"

    # Same local day, on the hour: already consumed, so no second heartbeat.
    st, actions = state.transition(
        st, {"type": "heartbeat_tick", "summary": summary}, at_08, cfg
    )
    assert actions == []

    # A tick before the hour on a fresh day stays silent.
    at_07_next = int(datetime.datetime(2026, 7, 14, 7, 0, tzinfo=tz).timestamp() * 1000)
    st, actions = state.transition(
        st, {"type": "heartbeat_tick", "summary": summary}, at_07_next, cfg
    )
    assert actions == []


def test_heartbeat_bypasses_snooze(chamber_config):
    """js:664 -- the heartbeat is the farmer's proof the watchdog is alive."""
    import datetime
    from zoneinfo import ZoneInfo

    cfg = _cfg(chamber_config, ALERT_HEARTBEAT_HOUR="8")
    tz = ZoneInfo(cfg.timezone)
    at_08 = int(datetime.datetime(2026, 7, 13, 8, 0, tzinfo=tz).timestamp() * 1000)

    st = state.initial_state(BOOT)
    for t in state.ALERT_TYPES:
        st.per_type[t].snoozed_until = at_08 + 24 * 60 * MIN

    st, actions = state.transition(
        st, {"type": "heartbeat_tick",
             "summary": {"rh": 91.0, "temp": 21.0, "co2": 800,
                         "humidifier": "OFF", "humidifier_cycles": 0,
                         "pi_last_seen_sec": 1}},
        at_08, cfg,
    )
    assert actions[0]["kind"] == "heartbeat"
