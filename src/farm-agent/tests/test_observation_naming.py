"""MUSHY-95: an observation log names its subject.

Observation logs were titled "observation <date>" and nothing else, so two
observations committed on the same day rendered as identical rows -- the Aug 18
gate produced 260519_DT_1 and 260519_DT_2 as two rows both reading
"observation 2026-08-18". The distinction lived only in the asset reference,
which the list view does not show prominently.

The seeding path already does this correctly ("Inoc 260816_WIN_3"), so this
applies an existing convention rather than inventing one.

Both facts needed are already on the draft: qr_codes (normalized from
asset_ref, with the <UNKNOWN> sentinel filtered) and state.
"""
from __future__ import annotations

from farm_agent.farmos.commits.commit_observation import _observation_name

# 2026-08-18T00:00:00Z
TS = 1787011200


def test_name_carries_the_asset_and_the_state():
    dj = {"qr_codes": ["260519_DT_1"], "state": "fully colonized"}
    assert _observation_name(dj, TS) == "Obs 260519_DT_1: fully colonized"


def test_the_two_gate_observations_no_longer_collide():
    """The exact rows that motivated this: same day, same type, different bags."""
    a = _observation_name({"qr_codes": ["260519_DT_1"], "state": "fully colonized"}, TS)
    b = _observation_name({"qr_codes": ["260519_DT_2"], "state": "contaminated"}, TS)
    assert a != b


def test_asset_only_when_no_state_was_extracted():
    """No dangling separator when the extractor got a bag but no state."""
    assert _observation_name({"qr_codes": ["260519_DT_1"]}, TS) == "Obs 260519_DT_1"
    assert _observation_name({"qr_codes": ["260519_DT_1"], "state": ""}, TS) == "Obs 260519_DT_1"
    assert _observation_name({"qr_codes": ["260519_DT_1"], "state": None}, TS) == "Obs 260519_DT_1"


def test_multi_asset_observation_names_the_first_and_counts_the_rest():
    dj = {"qr_codes": ["260519_DT_1", "260519_DT_2", "260519_DT_3"], "state": "colonized"}
    assert _observation_name(dj, TS) == "Obs 260519_DT_1 +2: colonized"


def test_falls_back_to_the_old_date_name_when_there_is_no_asset():
    """Never render a title with an empty subject."""
    assert _observation_name({}, TS) == "observation 2026-08-18"
    assert _observation_name({"qr_codes": []}, TS) == "observation 2026-08-18"
    assert _observation_name({"state": "colonized"}, TS) == "observation 2026-08-18"


def test_name_is_ascii_and_carries_no_em_dash():
    """Farmer-facing artifact: em-dashes are an LLM tell and the module is ASCII-only."""
    name = _observation_name({"qr_codes": ["260519_DT_1"], "state": "fully colonized"}, TS)
    name.encode("ascii")  # raises if not ASCII
    assert "—" not in name and "–" not in name


def test_a_long_state_does_not_produce_an_unbounded_title():
    dj = {"qr_codes": ["260519_DT_1"], "state": "x" * 500}
    assert len(_observation_name(dj, TS)) <= 255, "farmOS name is a bounded field"
