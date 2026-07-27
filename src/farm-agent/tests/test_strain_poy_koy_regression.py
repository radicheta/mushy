"""
test_strain_poy_koy_regression.py -- Named regression guard: POY is never silently
resolved to KOY (D-08 / T-62-09 / FWR-03).

The v1.11 fidelity bug: the curated-14 resolver's Levenshtein nearest() found KOY as
the closest match to POY and auto-remapped it, committing the wrong strain to farmOS.
T-61-09 locked nearest_known() to display-only; this test guards the regression.

Assert: resolve_strain("POY", CURATED_14) -> {known: False, code: "POY"} (never KOY).
"""
from __future__ import annotations

import pytest

from farm_agent.confirm.strain_ask_back import CURATED_14, resolve_strain


# ---------------------------------------------------------------------------
# Regression guard: POY is NEVER silently resolved to KOY
# ---------------------------------------------------------------------------


def test_poy_is_not_known():
    """POY is not in CURATED_14 -- resolve_strain must NOT return known=True."""
    result = resolve_strain("POY", CURATED_14)
    assert result["known"] is False, (
        "POY must not be a known curated strain -- curated-14 does not include POY"
    )


def test_poy_code_stays_poy():
    """resolve_strain must return code='POY' -- never silently remapped to KOY."""
    result = resolve_strain("POY", CURATED_14)
    assert result["code"] == "POY", (
        f"Expected code='POY', got code={result['code']!r} -- silent remap detected"
    )


def test_poy_does_not_return_koy_as_code():
    """Explicit: the returned code field must not be 'KOY'."""
    result = resolve_strain("POY", CURATED_14)
    assert result.get("code") != "KOY", (
        "REGRESSION: POY silently resolved to KOY via curated-14 resolver"
    )


def test_poy_nearest_may_be_koy_but_is_display_only():
    """nearest may be KOY (edit distance 1) but must ONLY appear in 'nearest', not 'code'.

    This test documents the display-only contract (T-61-09): nearest is allowed to be
    KOY, but it must never propagate to 'code' and must never trigger an auto-remap.
    """
    result = resolve_strain("POY", CURATED_14)
    # nearest is allowed to point to KOY for display purposes
    nearest = result.get("nearest")
    # But the authoritative 'code' field must stay POY
    assert result["code"] == "POY"
    assert result["known"] is False
    # Confirm nearest is a display-only field (not 'code')
    if nearest == "KOY":
        # Acceptable -- KOY is edit-distance 1 from POY; display suggestion is fine
        assert "code" in result
        assert result["code"] != "KOY", (
            "nearest=KOY must not contaminate the 'code' field (T-61-09)"
        )


def test_poy_lowercase_input_stays_poy():
    """Lowercase 'poy' must also resolve to code='POY' (uppercase), not KOY."""
    result = resolve_strain("poy", CURATED_14)
    assert result["known"] is False
    assert result["code"] == "POY"


def test_koy_itself_is_known():
    """Sanity: KOY IS a known curated strain (guards against CURATED_14 corruption)."""
    result = resolve_strain("KOY", CURATED_14)
    assert result["known"] is True
    assert result["code"] == "KOY"
