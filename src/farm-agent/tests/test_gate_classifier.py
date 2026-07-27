"""
Unit tests for farm_agent.gate.classifier -- create_haiku_classifier factory.

Covers:
  - success path: {ok:True, is_event, kind, confidence, usage}
  - fail-open: no_tool_use_in_response
  - fail-open: schema_invalid (confidence > 1.0 violates Field(le=1.0))
  - fail-open: api_error (anthropic.APIConnectionError)
  - call shape: tool_choice, user-message JSON keys, with_options timeout
  - WARNING log on every fail-open path
"""

from __future__ import annotations

import json
import logging

import anthropic
import pytest

from tests.conftest import FakeAnthropicClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_classifier(client: FakeAnthropicClient, **kwargs) -> dict:
    from farm_agent.gate.classifier import create_haiku_classifier

    return create_haiku_classifier(client=client, **kwargs)


_ENV_CTX = {"text": "SHI batch is ready", "transcript": None, "attachmentCount": 0}


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_success(fake_anthropic_client: FakeAnthropicClient):
    """Default FakeAnthropicClient returns is_event=True, kind=event, confidence=0.95."""
    classifier = _make_classifier(fake_anthropic_client)
    result = await classifier["classify"](_ENV_CTX)

    assert result["ok"] is True
    assert result["is_event"] is True
    assert result["kind"] == "event"
    assert result["confidence"] == pytest.approx(0.95)
    assert "usage" in result


# ---------------------------------------------------------------------------
# Fail-open: no_tool_use_in_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_no_tool_use(fake_anthropic_client: FakeAnthropicClient):
    """Response with no tool_use block -> {ok:False, reason:no_tool_use_in_response, fallthrough:forced}."""
    fake_anthropic_client.return_no_tool_use = True
    classifier = _make_classifier(fake_anthropic_client)
    result = await classifier["classify"](_ENV_CTX)

    assert result["ok"] is False
    assert result["reason"] == "no_tool_use_in_response"
    assert result["fallthrough"] == "forced"


# ---------------------------------------------------------------------------
# Fail-open: schema_invalid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_schema_invalid(fake_anthropic_client: FakeAnthropicClient, caplog):
    """confidence > 1.0 violates Field(le=1.0) -> {ok:False, reason:schema_invalid} + WARNING."""
    # confidence=1.5 is a definite pydantic v2 ValidationError (le=1.0 violated).
    # Do NOT use a coercible string like "notabool" -- v2 may coerce it.
    fake_anthropic_client.tool_input = {"is_event": True, "kind": "greeting", "confidence": 1.5}
    classifier = _make_classifier(fake_anthropic_client)

    with caplog.at_level(logging.WARNING, logger="farm_agent.gate.classifier"):
        result = await classifier["classify"](_ENV_CTX)

    assert result["ok"] is False
    assert result["reason"] == "schema_invalid"
    assert result["fallthrough"] == "forced"
    assert any("schema_invalid" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Fail-open: API error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_api_error_never_raises(
    fake_anthropic_client: FakeAnthropicClient, caplog
):
    """APIConnectionError -> {ok:False, fallthrough:forced} and does NOT raise + WARNING logged."""
    fake_anthropic_client.raise_exc = anthropic.APIConnectionError(request=None)
    classifier = _make_classifier(fake_anthropic_client)

    with caplog.at_level(logging.WARNING, logger="farm_agent.gate.classifier"):
        result = await classifier["classify"](_ENV_CTX)

    assert result["ok"] is False
    assert result["fallthrough"] == "forced"
    assert "reason" in result
    # Must not have raised -- reaching here proves it
    assert any("degraded" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Call shape assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_shape_tool_choice(fake_anthropic_client: FakeAnthropicClient):
    """tool_choice must be {type:tool, name:classify_capture}."""
    classifier = _make_classifier(fake_anthropic_client)
    await classifier["classify"](_ENV_CTX)

    assert len(fake_anthropic_client.calls) == 1
    kwargs = fake_anthropic_client.calls[0]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "classify_capture"}


@pytest.mark.asyncio
async def test_call_shape_user_message_json(fake_anthropic_client: FakeAnthropicClient):
    """User message content[0].text is compact JSON with text/transcript/attachmentCount keys."""
    classifier = _make_classifier(fake_anthropic_client)
    await classifier["classify"](_ENV_CTX)

    kwargs = fake_anthropic_client.calls[0]
    messages = kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    payload = json.loads(content[0]["text"])
    assert "text" in payload
    assert "transcript" in payload
    assert "attachmentCount" in payload


@pytest.mark.asyncio
async def test_call_shape_system_block_passed(fake_anthropic_client: FakeAnthropicClient):
    """system= is the CACHEABLE_SYSTEM_BLOCKS list (not concatenated into user message)."""
    from farm_agent.gate.prompts import CACHEABLE_SYSTEM_BLOCKS

    classifier = _make_classifier(fake_anthropic_client)
    await classifier["classify"](_ENV_CTX)

    kwargs = fake_anthropic_client.calls[0]
    assert kwargs["system"] == CACHEABLE_SYSTEM_BLOCKS


@pytest.mark.asyncio
async def test_call_shape_no_timeout_in_body(fake_anthropic_client: FakeAnthropicClient):
    """Timeout is NOT passed as a body kwarg (Pitfall 1: would cause BadRequestError).

    Verifies that the create() call kwargs do not contain 'timeout'.
    The timeout goes through with_options(), not through messages.create() body.
    """
    classifier = _make_classifier(fake_anthropic_client, timeout_ms=2000)
    await classifier["classify"](_ENV_CTX)

    kwargs = fake_anthropic_client.calls[0]
    assert "timeout" not in kwargs, (
        "timeout must NOT appear in messages.create() body kwargs -- use with_options()"
    )


@pytest.mark.asyncio
async def test_classify_null_text_in_payload(fake_anthropic_client: FakeAnthropicClient):
    """Absent text/transcript -> None in JSON payload (not omitted)."""
    classifier = _make_classifier(fake_anthropic_client)
    await classifier["classify"]({"attachmentCount": 0})

    payload = json.loads(fake_anthropic_client.calls[0]["messages"][0]["content"][0]["text"])
    assert payload["text"] is None
    assert payload["transcript"] is None
    assert payload["attachmentCount"] == 0


@pytest.mark.asyncio
async def test_classify_attachment_count_default_zero(fake_anthropic_client: FakeAnthropicClient):
    """attachmentCount defaults to 0 when absent."""
    classifier = _make_classifier(fake_anthropic_client)
    await classifier["classify"]({"text": "hello"})

    payload = json.loads(fake_anthropic_client.calls[0]["messages"][0]["content"][0]["text"])
    assert payload["attachmentCount"] == 0


# ---------------------------------------------------------------------------
# WARNING log on schema_invalid confirms PII is NOT logged (T-59-02-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_invalid_warning_does_not_log_env_ctx(
    fake_anthropic_client: FakeAnthropicClient, caplog
):
    """The WARNING on schema_invalid logs the reason, NOT farmer text (T-59-02-01)."""
    fake_anthropic_client.tool_input = {"is_event": True, "kind": "event", "confidence": 1.5}
    classifier = _make_classifier(fake_anthropic_client)

    with caplog.at_level(logging.WARNING, logger="farm_agent.gate.classifier"):
        await classifier["classify"]({"text": "FARMER_PII_TEXT_SENTINEL", "attachmentCount": 0})

    for record in caplog.records:
        assert "FARMER_PII_TEXT_SENTINEL" not in record.message
