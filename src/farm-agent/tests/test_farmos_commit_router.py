"""Tests for commit_router.py (Phase 62-10, Task 1).

Port of commit-router.test.js behavior:
- dispatch routes to the correct handler after normalize()
- unsupported / missing log_type returns unsupported_log_type envelope
- handler exception returns ok=False with reason + latency_ms
- envelope always contains asset_ids, log_ids, file_ids, attachments_failed, latency_ms
- normalize() is applied before dispatch; input draft is not mutated

No real farmOS calls. All handlers mocked.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from farm_agent.farmos.commits.commit_router import commit, DISPATCH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_draft(log_type: str, extra_draft_json: dict | None = None) -> dict:
    return {
        "id": "draft-uuid-1",
        "log_type": log_type,
        "draft_json": {"timestamp": 1700000000, **(extra_draft_json or {})},
    }


def _ok_result(**kwargs) -> dict:
    return {
        "ok": True,
        "asset_ids": kwargs.get("asset_ids", ["a1"]),
        "log_ids": kwargs.get("log_ids", ["l1"]),
        "file_ids": kwargs.get("file_ids", []),
        "attachments_failed": kwargs.get("attachments_failed", []),
        "reason": None,
    }


# ---------------------------------------------------------------------------
# DISPATCH table completeness
# ---------------------------------------------------------------------------

def test_dispatch_has_six_entries():
    assert len(DISPATCH) == 6
    for key in ("seeding", "activity", "input", "observation", "harvest", "seeding_session"):
        assert key in DISPATCH, f"DISPATCH missing key: {key}"


# ---------------------------------------------------------------------------
# Unsupported / missing log_type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_log_type_returns_unsupported():
    result = await commit({}, {})
    assert result["ok"] is False
    assert result["reason"] == "unsupported_log_type"
    assert result["asset_ids"] == []
    assert result["log_ids"] == []
    assert result["file_ids"] == []
    assert "latency_ms" in result


@pytest.mark.asyncio
async def test_none_draft_returns_unsupported():
    result = await commit({}, None)
    assert result["ok"] is False
    assert result["reason"] == "unsupported_log_type"


@pytest.mark.asyncio
async def test_unknown_log_type_returns_unsupported():
    result = await commit({}, {"log_type": "invalid_type"})
    assert result["ok"] is False
    assert result["reason"] == "unsupported_log_type"
    assert result["asset_ids"] == []


# ---------------------------------------------------------------------------
# Dispatch: each log_type routes to the correct handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("log_type,handler_path", [
    ("seeding", "farm_agent.farmos.commits.commit_seeding.commit_seeding"),
    ("activity", "farm_agent.farmos.commits.commit_activity.commit_activity"),
    ("input", "farm_agent.farmos.commits.commit_input.commit_input"),
    ("observation", "farm_agent.farmos.commits.commit_observation.commit_observation"),
    ("harvest", "farm_agent.farmos.commits.commit_harvest.commit_harvest"),
    ("seeding_session", "farm_agent.farmos.commits.commit_seeding_session.commit_seeding_session"),
])
async def test_dispatch_calls_correct_handler(log_type, handler_path):
    mock_handler = AsyncMock(return_value=_ok_result())
    with patch(handler_path, mock_handler):
        # Re-import to get patched version via DISPATCH lookup
        import importlib
        import farm_agent.farmos.commits.commit_router as router_mod
        # Patch the DISPATCH dict entry directly
        original = router_mod.DISPATCH[log_type]
        router_mod.DISPATCH[log_type] = mock_handler
        try:
            draft = _make_draft(log_type)
            result = await commit({"client": True}, draft)
        finally:
            router_mod.DISPATCH[log_type] = original

    assert mock_handler.called, f"Handler for {log_type} was not called"
    assert result["ok"] is True
    assert isinstance(result["latency_ms"], int)


# ---------------------------------------------------------------------------
# Normalize is applied before dispatch; input draft is not mutated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normalize_applied_and_draft_not_mutated():
    """Verify that normalize() runs before the handler and the original draft is unchanged."""
    captured_arg = {}

    async def fake_handler(client, draft, ctx=None):
        captured_arg["draft"] = draft
        return _ok_result()

    # Draft with event_timestamp (normalize converts it to timestamp)
    original_draft = {
        "id": "d1",
        "log_type": "activity",
        "draft_json": {"event_timestamp": "2024-01-01T00:00:00+00:00"},
    }
    original_dj_copy = dict(original_draft["draft_json"])

    import farm_agent.farmos.commits.commit_router as router_mod
    original = router_mod.DISPATCH["activity"]
    router_mod.DISPATCH["activity"] = fake_handler
    try:
        await commit({}, original_draft)
    finally:
        router_mod.DISPATCH["activity"] = original

    # Handler received the normalized draft (has timestamp, not event_timestamp)
    normalized_dj = captured_arg["draft"]["draft_json"]
    assert "timestamp" in normalized_dj, "normalize() should have added timestamp"

    # Original draft was NOT mutated
    assert original_draft["draft_json"] == original_dj_copy, "Input draft was mutated"


# ---------------------------------------------------------------------------
# Handler exception -> failure envelope with latency_ms
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_exception_returns_failure_envelope():
    async def exploding_handler(client, draft, ctx=None):
        raise RuntimeError("farmOS exploded")

    import farm_agent.farmos.commits.commit_router as router_mod
    original = router_mod.DISPATCH["seeding"]
    router_mod.DISPATCH["seeding"] = exploding_handler
    try:
        result = await commit({}, _make_draft("seeding"))
    finally:
        router_mod.DISPATCH["seeding"] = original

    assert result["ok"] is False
    assert "farmOS exploded" in result["reason"]
    assert result["asset_ids"] == []
    assert result["log_ids"] == []
    assert result["file_ids"] == []
    assert "latency_ms" in result
    assert isinstance(result["latency_ms"], int)


# ---------------------------------------------------------------------------
# Envelope shape: all fields present on success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_success_envelope_has_all_fields():
    async def good_handler(client, draft, ctx=None):
        return {"ok": True, "asset_ids": ["a1"], "log_ids": ["l1"], "file_ids": ["f1"],
                "attachments_failed": [], "reason": None}

    import farm_agent.farmos.commits.commit_router as router_mod
    original = router_mod.DISPATCH["input"]
    router_mod.DISPATCH["input"] = good_handler
    try:
        result = await commit({}, _make_draft("input"))
    finally:
        router_mod.DISPATCH["input"] = original

    for key in ("ok", "asset_ids", "log_ids", "file_ids", "attachments_failed", "latency_ms"):
        assert key in result, f"Missing key in envelope: {key}"
    assert result["asset_ids"] == ["a1"]
    assert result["log_ids"] == ["l1"]
    assert result["file_ids"] == ["f1"]


@pytest.mark.asyncio
async def test_handler_missing_id_lists_default_to_empty():
    """Handler returning partial envelope: missing id lists default to []."""
    async def sparse_handler(client, draft, ctx=None):
        return {"ok": True}  # no id lists

    import farm_agent.farmos.commits.commit_router as router_mod
    original = router_mod.DISPATCH["observation"]
    router_mod.DISPATCH["observation"] = sparse_handler
    try:
        result = await commit({}, _make_draft("observation"))
    finally:
        router_mod.DISPATCH["observation"] = original

    assert result["asset_ids"] == []
    assert result["log_ids"] == []
    assert result["file_ids"] == []
    assert result["attachments_failed"] == []
