"""Unit tests for farm_agent.extraction.extractor -- create_extractor factory.

Covers:
  - SC-1: happy path -- single valid tool_use -> {ok:True, drafts, continuity_decision}
  - SC-2: retry resolves -- first call schema-invalid, second call valid -> {ok:True, 2 calls}
  - SC-3: terminal failure -- both calls invalid -> {ok:False, reason:schema_invalid, raw_first, raw_retry}
  - SC-4: SDK error -- create() raises -> {ok:False, reason contains error, no exception}
  - SC-5: no tool_use -- empty content -> {ok:False, reason:no_tool_use_in_response}
  - call shape: tool_choice, timeout not in body, system cache_control, tu_fewshot_6 first block
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import FakeAnthropicClientForExtractor

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "extraction" / "seeding-session-may22"


def _valid_submission_dict() -> dict:
    """Build a minimal valid Submission dict from the May-22 expected-draft fixture."""
    draft = json.loads((FIXTURE_DIR / "expected-draft.json").read_text())
    return {
        "drafts": [
            {
                "draft": draft,
                "per_field_confidence": {"event_date": 0.98, "groups": 0.95},
            }
        ],
        "continuity": "start_new",
        "continuity_reason": "New session",
        "capture_kind": "voice_note",
    }


def _invalid_submission_dict() -> dict:
    """A dict that fails Submission.model_validate (missing required 'continuity_reason')."""
    return {
        "drafts": [
            {
                "draft": {"type": "seeding_session", "event_date": "2026-05-22", "groups": []},
                "per_field_confidence": {},
            }
        ],
        "continuity": "start_new",
        # 'continuity_reason' intentionally omitted -> ValidationError
    }


def _make_extractor(client, **kwargs) -> dict:
    from farm_agent.extraction.extractor import create_extractor  # noqa: PLC0415
    return create_extractor(client=client, **kwargs)


# ---------------------------------------------------------------------------
# SC-1: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path():
    """Single valid tool_use -> {ok:True, drafts, continuity_decision, exactly 1 call}."""
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([{"tool_input": valid}])
    extractor = _make_extractor(client)
    result = await extractor["extract"](captures=[{"text": "test", "transcript": None, "images": []}])

    assert result["ok"] is True
    assert len(result["drafts"]) == 1
    assert "continuity_decision" in result
    assert result["continuity_decision"] == "start_new"
    assert len(client.calls) == 1


# ---------------------------------------------------------------------------
# SC-2: retry resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_resolves():
    """First call schema-invalid, second call valid -> {ok:True, 2 calls, retry had is_error=True}."""
    invalid = _invalid_submission_dict()
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([
        {"tool_input": invalid},
        {"tool_input": valid},
    ])
    extractor = _make_extractor(client)
    result = await extractor["extract"](captures=[{"text": "test", "transcript": None, "images": []}])

    assert result["ok"] is True
    assert len(client.calls) == 2

    # The retry call's messages must include a tool_result block with is_error=True
    # and tool_use_id == "tu_call_0" (the first call's block.id)
    retry_messages = client.calls[1]["messages"]
    # Find the user turn with the tool_result error block
    retry_user_turn = None
    for msg in retry_messages:
        if msg["role"] == "user":
            # Look for a tool_result with is_error=True
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    retry_user_turn = block
    assert retry_user_turn is not None, "Retry user turn must have tool_result with is_error=True"
    # tool_use_id must match the first call's block.id = "tu_call_0"
    assert retry_user_turn["tool_use_id"] == "tu_call_0"


# ---------------------------------------------------------------------------
# SC-3: terminal failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_failure():
    """Both calls schema-invalid -> {ok:False, reason:'schema_invalid', raw_first, raw_retry, 2 calls}."""
    invalid = _invalid_submission_dict()
    client = FakeAnthropicClientForExtractor([
        {"tool_input": invalid},
        {"tool_input": invalid},
    ])
    extractor = _make_extractor(client)
    result = await extractor["extract"](captures=[{"text": "test", "transcript": None, "images": []}])

    assert result["ok"] is False
    assert result["reason"] == "schema_invalid"
    assert "raw_first" in result
    assert "raw_retry" in result
    assert len(client.calls) == 2


# ---------------------------------------------------------------------------
# SC-4: SDK error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sdk_error():
    """SDK raises -> {ok:False, reason contains error text, no exception propagated}."""
    client = FakeAnthropicClientForExtractor([{"raise": RuntimeError("network error")}])
    extractor = _make_extractor(client)
    result = await extractor["extract"](captures=[{"text": "test", "transcript": None, "images": []}])

    assert result["ok"] is False
    assert "network error" in result["reason"]


# ---------------------------------------------------------------------------
# SC-5: no tool_use
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tool_use():
    """Response with no submit_extraction block -> {ok:False, reason:'no_tool_use_in_response'}."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    class FakeNoToolUse:
        def __init__(self):
            self.calls = []
            self.call_index = 0

        def with_options(self, **kwargs):
            return self

        @property
        def messages(self):
            return self

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            self.call_index += 1
            resp = MagicMock()
            resp.content = []
            return resp

    client = FakeNoToolUse()
    extractor = _make_extractor(client)
    result = await extractor["extract"](captures=[{"text": "test", "transcript": None, "images": []}])

    assert result["ok"] is False
    assert result["reason"] == "no_tool_use_in_response"


# ---------------------------------------------------------------------------
# sum_usage tests (CR-02)
# ---------------------------------------------------------------------------


def test_sum_usage_all_null_returns_none():
    """sum_usage returns None when all usages are null (mirrors Node sumUsage)."""
    from farm_agent.extraction.extractor import sum_usage  # noqa: PLC0415

    assert sum_usage([None, None]) is None
    assert sum_usage([]) is None
    assert sum_usage([None]) is None


def test_sum_usage_with_data_returns_dict():
    """sum_usage returns a summed dict when at least one usage is non-null."""
    from unittest.mock import MagicMock  # noqa: PLC0415
    from farm_agent.extraction.extractor import sum_usage  # noqa: PLC0415

    u = MagicMock()
    u.input_tokens = 100
    u.output_tokens = 20
    u.cache_creation_input_tokens = 50
    u.cache_read_input_tokens = 0
    result = sum_usage([None, u])
    assert result is not None
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 20


def test_sum_usage_mixed_sums_correctly():
    """sum_usage sums non-null usages and ignores nulls."""
    from unittest.mock import MagicMock  # noqa: PLC0415
    from farm_agent.extraction.extractor import sum_usage  # noqa: PLC0415

    u1 = MagicMock()
    u1.input_tokens = 100
    u1.output_tokens = 10
    u1.cache_creation_input_tokens = 0
    u1.cache_read_input_tokens = 0
    u2 = MagicMock()
    u2.input_tokens = 50
    u2.output_tokens = 5
    u2.cache_creation_input_tokens = 0
    u2.cache_read_input_tokens = 0
    result = sum_usage([u1, None, u2])
    assert result["input_tokens"] == 150
    assert result["output_tokens"] == 15


# ---------------------------------------------------------------------------
# Call shape tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_shape_tool_choice():
    """tool_choice must be {"type":"tool","name":"submit_extraction"}."""
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([{"tool_input": valid}])
    extractor = _make_extractor(client)
    await extractor["extract"](captures=[{"text": "x", "transcript": None, "images": []}])

    call = client.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "submit_extraction"}


@pytest.mark.asyncio
async def test_call_shape_timeout_not_in_body():
    """timeout must NOT appear in any messages.create() kwargs (Pitfall 9)."""
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([{"tool_input": valid}])
    extractor = _make_extractor(client)
    await extractor["extract"](captures=[{"text": "x", "transcript": None, "images": []}])

    for call in client.calls:
        assert "timeout" not in call, f"timeout leaked into messages.create body: {list(call.keys())}"


@pytest.mark.asyncio
async def test_call_shape_system_cache_control():
    """system[0]['cache_control'] must be {'type':'ephemeral'}."""
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([{"tool_input": valid}])
    extractor = _make_extractor(client)
    await extractor["extract"](captures=[{"text": "x", "transcript": None, "images": []}])

    system = client.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_call_shape_tu_fewshot_6_closer():
    """First block of the first user-turn content must be the tu_fewshot_6 tool_result closer."""
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([{"tool_input": valid}])
    extractor = _make_extractor(client)
    await extractor["extract"](captures=[{"text": "x", "transcript": None, "images": []}])

    # Find the first "user" turn in messages (after the few-shot turns)
    user_turns = [m for m in client.calls[0]["messages"] if m["role"] == "user"]
    assert len(user_turns) >= 1, "Must have at least one user turn"
    # The last user turn is the real extraction request
    last_user_turn = user_turns[-1]
    first_block = last_user_turn["content"][0]
    assert first_block["type"] == "tool_result"
    assert first_block["tool_use_id"] == "tu_fewshot_6"


# ---------------------------------------------------------------------------
# corpus_context guard tests (WR-03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corpus_context_dict_is_included():
    """corpus_context dict is serialized into the user turn."""
    from farm_agent.extraction.extractor import build_initial_user_content  # noqa: PLC0415

    blocks = build_initial_user_content(captures=[], corpus_context={"session_count": 3})
    texts = [b["text"] for b in blocks if b.get("type") == "text" and "corpus_context" in b.get("text", "")]
    assert len(texts) == 1
    assert '"session_count"' in texts[0]


@pytest.mark.asyncio
async def test_corpus_context_non_dict_is_excluded():
    """corpus_context that is not a dict is silently excluded (mirrors Node typeof === 'object')."""
    from farm_agent.extraction.extractor import build_initial_user_content  # noqa: PLC0415

    for bad_value in ["some string", 42, ["a", "list"]]:
        blocks = build_initial_user_content(captures=[], corpus_context=bad_value)
        cc_blocks = [b for b in blocks if b.get("type") == "text" and "corpus_context" in b.get("text", "")]
        assert cc_blocks == [], f"corpus_context should be excluded for non-dict value: {bad_value!r}"


# ---------------------------------------------------------------------------
# on_llm_call observer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_llm_call_sync_observer():
    """Sync on_llm_call observer is invoked once per call with (req, resp, exc)."""
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([{"tool_input": valid}])
    observer_calls = []

    def observer(req, resp, exc):
        observer_calls.append((req, resp, exc))

    extractor = _make_extractor(client, on_llm_call=observer)
    result = await extractor["extract"](captures=[{"text": "x", "transcript": None, "images": []}])

    assert result["ok"] is True
    assert len(observer_calls) == 1
    _req, _resp, _exc = observer_calls[0]
    assert _exc is None  # no error on happy path


@pytest.mark.asyncio
async def test_on_llm_call_async_observer():
    """Async on_llm_call observer is awaited with (req, resp, exc)."""
    valid = _valid_submission_dict()
    client = FakeAnthropicClientForExtractor([{"tool_input": valid}])
    observer_calls = []

    async def async_observer(req, resp, exc):
        observer_calls.append((req, resp, exc))

    extractor = _make_extractor(client, on_llm_call=async_observer)
    result = await extractor["extract"](captures=[{"text": "x", "transcript": None, "images": []}])

    assert result["ok"] is True
    assert len(observer_calls) == 1
    _req, _resp, _exc = observer_calls[0]
    assert _exc is None  # no error on happy path


@pytest.mark.asyncio
async def test_on_llm_call_observer_fires_on_error():
    """Observer fires in finally even when SDK raises (mirrors Node callWithObserver).

    The backfill harness uses on_llm_call to persist every paid-API call to
    responses.jsonl. A timeout that still costs tokens must be recorded.
    """
    observer_calls = []

    def observer(req, resp, exc):
        observer_calls.append((req, resp, exc))

    client = FakeAnthropicClientForExtractor([{"raise": RuntimeError("timeout")}])
    extractor = _make_extractor(client, on_llm_call=observer)
    result = await extractor["extract"](captures=[{"text": "x", "transcript": None, "images": []}])

    assert result["ok"] is False
    assert "timeout" in result["reason"]
    # Observer must have fired exactly once with resp=None and exc set
    assert len(observer_calls) == 1
    _req, _resp, _exc = observer_calls[0]
    assert _resp is None
    assert isinstance(_exc, RuntimeError)
    assert "timeout" in str(_exc)
