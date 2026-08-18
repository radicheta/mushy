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
import re
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


# ---------------------------------------------------------------------------
# Boundary: pack_result must return plain dicts, never pydantic models
# ---------------------------------------------------------------------------


def test_pack_result_returns_plain_json_safe_dicts():
    """A REAL Submission through pack_result must come out as plain dicts.

    Regression for the first real-model live-fire failure: pack_result handed
    `SeedingSession` model instances downstream, and every consumer (pipeline,
    batch_mode, starting_seq, preview_builder, state_machine, seq_helper) does
    dict access -> "'SeedingSession' object has no attribute 'get'". Every
    hermetic test fed hand-written dicts, so nothing caught it. jsonb
    persistence (Jsonb(draft_json)) would have failed next regardless.
    """
    from farm_agent.extraction.extractor import pack_result  # noqa: PLC0415
    from farm_agent.extraction.schemas.submission import Submission  # noqa: PLC0415

    # The genuine article: a real Submission built through the real schemas.
    submission = Submission.model_validate(_valid_submission_dict())
    assert submission.drafts[0].draft.type == "seeding_session"  # models on the way in

    result = pack_result(submission, {"input_tokens": 1, "output_tokens": 2})

    assert result["ok"] is True
    assert isinstance(result["draft"], dict)
    assert isinstance(result["per_field_confidence"], dict)
    assert isinstance(result["drafts"], list)
    for item in result["drafts"]:
        assert isinstance(item, dict)
        assert isinstance(item["draft"], dict)
        assert isinstance(item["per_field_confidence"], dict)

    # Nested structures too -- a half-converted result would just move the crash.
    first = result["draft"]
    assert first["type"] == "seeding_session"
    assert first.get("groups")
    for group in first["groups"]:
        assert isinstance(group, dict)
        assert isinstance(group["parent"], dict)
        assert isinstance(group["child_block_names"]["value"], list)

    # Scalars pass through unchanged, and the whole thing is jsonb-safe.
    assert result["continuity_decision"] == "start_new"
    assert result["capture_kind"] == "voice_note"
    json.dumps(result["draft"])
    json.dumps(result["drafts"])
    json.dumps(result["per_field_confidence"])


# ---------------------------------------------------------------------------
# Continuity path: the in-flight draft is a RAW DB ROW, not a hand-written dict
# ---------------------------------------------------------------------------

_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


async def _real_in_flight_row(pool, sender: str) -> dict:
    """Insert a draft and read it back through the REAL DAO, so the fixture cannot drift.

    Returns exactly what pipeline.py hands the extractor on the continuity path:
    extraction_db.get_in_flight_for_sender(), i.e. dict(zip(cursor.description, row)) --
    timestamptz -> datetime, jsonb -> dict, text[] -> list.
    """
    from farm_agent.extraction import extraction_db  # noqa: PLC0415

    # Only this test's own sender; D-02c allows at most one in-flight draft per sender.
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM signal_draft WHERE sender_e164 = %s", (sender,))

    draft = json.loads((FIXTURE_DIR / "expected-draft.json").read_text())
    ins = await extraction_db.insert_draft(pool, {
        "id": extraction_db.compute_draft_id([f"cap-{sender}"]),
        "sender_e164": sender,
        "farmos_person": "santi",
        "source_capture_ids": [f"cap-{sender}"],
        "status": "awaiting_farmer",
        "log_type": "seeding_session",
        "draft_json": draft,
        "per_field_confidence": {"event_date": 0.98},
        "farmer_facing_preview": "preview",
        "reply_target_kind": "dm",
    })
    assert ins["ok"] is True, ins

    row = await extraction_db.get_in_flight_for_sender(pool, sender)
    assert row is not None, "DAO returned no in-flight row -- fixture setup is broken"
    return row


async def test_extract_serializes_a_real_in_flight_db_row(pool):
    """MUSHY-76: the continuity path must survive a raw DB row's datetimes.

    The farmer's follow-up to an open draft (the common multi-message
    inoculation shape) hands the extractor a RAW signal_draft row, where
    created_at/updated_at are datetimes. json.dumps raised on them, so the
    call never reached the model and every follow-up degraded to
    {ok:False} silently. Every hermetic test passed a hand-written dict with
    no datetime in it, which is why 1084 green tests missed it.

    Drives the real extract() with a row read back through the real DAO
    against the throwaway :5434 postgres, so the fixture cannot drift from
    the real row shape again.
    """
    import datetime as dt  # noqa: PLC0415

    sender = "+19995500076"  # unique to this test
    row = await _real_in_flight_row(pool, sender)

    # The row really is the hazard: datetimes, a jsonb dict, a text[] list.
    assert isinstance(row["created_at"], dt.datetime)
    assert row["created_at"].tzinfo is not None
    assert isinstance(row["updated_at"], dt.datetime)
    assert isinstance(row["draft_json"], dict)
    assert isinstance(row["source_capture_ids"], list)

    fake = FakeAnthropicClientForExtractor([{"tool_input": _valid_submission_dict()}])
    extractor = _make_extractor(fake)

    result = await extractor["extract"](
        captures=[{"text": "add one more bag", "transcript": None, "images": []}],
        in_flight_draft=row,
    )

    assert result["ok"] is True, result  # not {'ok': False, 'reason': '...not JSON serializable'}
    assert len(fake.calls) == 1, "the model was never called -- the request did not assemble"

    blocks = fake.calls[0]["messages"][-1]["content"]
    texts = [b["text"] for b in blocks if b.get("type") == "text"]
    in_flight_text = next(t for t in texts if t.startswith("In-flight draft: "))
    assert _ISO_TS_RE.search(in_flight_text), (
        f"no ISO-8601 timestamp in the serialized in-flight draft: {in_flight_text[:200]!r}"
    )
    # It is real JSON the model can parse, and the datetime came through as ISO-8601.
    payload = json.loads(in_flight_text[len("In-flight draft: "):])
    assert payload["created_at"] == row["created_at"].isoformat()
    assert payload["draft_json"]["type"] == "seeding_session"

    async with pool.connection() as conn:
        await conn.execute("DELETE FROM signal_draft WHERE sender_e164 = %s", (sender,))


def test_json_default_raises_on_genuinely_unknown_types():
    """default= must NOT be a str() catch-all -- garbage the model reasons over is worse."""
    from farm_agent.extraction.extractor import json_default  # noqa: PLC0415

    with pytest.raises(TypeError):
        json_default(b"\x00\x01")
    with pytest.raises(TypeError):
        json_default(object())
