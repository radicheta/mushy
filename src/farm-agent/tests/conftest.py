"""
Shared pytest fixtures for farm-agent tests.

TEST_ENV: a dict with all required TenantConfig env keys using safe test defaults.
pool: session-scoped async pool fixture (activates once Plans 02+03 ship tenancy + persistence).
signal_http: respx-based httpx mock fixture for signal_io unit tests (no DB required).
FakeOutboundRepo: helper class whose insert_outbound can be toggled to raise (for fail-open tests).
FakeCaptureRepo: helper class whose insert_capture can be toggled to raise (for fail-open tests).
fake_transcribe_client: fixture returning an injected {transcribe} dict with a canned async result.
whisper_http: respx-based httpx mock fixture for capture/transcribe_client unit tests.
"""

import asyncio
import os
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

# TEST_ENV: all required TenantConfig keys with safe, non-real test defaults.
# Secrets use placeholder values that are never logged or sent anywhere.
def _test_host() -> str:
    """Build TIMESCALE_HOST for the test pool.

    The throwaway postgres:14 test container listens on port 5434. If
    TEST_TIMESCALE_PORT is not set, we default to 5434 so the pool does not
    accidentally connect to a production postgres on 5432.
    """
    host = os.environ.get("TEST_TIMESCALE_HOST", "localhost")
    port = os.environ.get("TEST_TIMESCALE_PORT", "5434")
    if port and port != "5432":
        return f"{host}:{port}"
    return host


TEST_ENV = {
    "TENANT_ID": "test",
    "TIMESCALE_HOST": _test_host(),
    "TIMESCALE_DB": os.environ.get("TEST_TIMESCALE_DB", "test_farm_agent"),
    "TIMESCALE_USER": os.environ.get("TEST_TIMESCALE_USER", "postgres"),
    "TIMESCALE_PASSWORD": os.environ.get("TEST_TIMESCALE_PASSWORD", "test"),
    # Placeholder secrets -- never real credentials, never logged
    "SIGNAL_SENDER": "+10000000000",
    "ANTHROPIC_API_KEY": "test-key",
    "FARMOS_PASSWORD": "test-pass",
    "FARMOS_URL": "http://localhost:18080",
    "FARMOS_USERNAME": "test-user",
    "SIGNAL_RECIPIENT": "+10000000001",
    "TENANT_YAML_BASE": "",
    "TIMEZONE": "America/Montevideo",
    "LOG_LEVEL": "INFO",
    "DRAFT_NUDGE_FRACTION": "0.8",
    "MAX_EDIT_TURNS": "3",
}


@pytest.fixture
def tenant_config():
    """TenantConfig built from TEST_ENV (throwaway :5434 postgres, placeholder secrets).

    Used by live-fire tests that need a real TenantConfig object (signal_recipient,
    draft_idle_gap_min, etc.) rather than the raw TEST_ENV dict.
    """
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    return load_config(TEST_ENV)


@pytest_asyncio.fixture(scope="session")
async def pool():
    """
    Session-scoped async psycopg3 pool fixture.

    Local imports are used so pytest collection does NOT crash before Plans 02+03
    land farm_agent.tenancy.tenant and farm_agent.persistence.{pool,migrations}.
    This fixture activates once Plans 02+03 ship.

    Skips all callers when no test DB is reachable (TEST_TIMESCALE_HOST must be
    connectable). DB-independent tests (test_migrations_additive_only) do not
    request this fixture and are unaffected.
    """
    import socket  # noqa: PLC0415
    import pytest  # noqa: PLC0415

    host_raw = TEST_ENV.get("TIMESCALE_HOST", "localhost:5434")
    if ":" in host_raw:
        host, port_str = host_raw.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_raw
        port = 5434
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError:
        pytest.skip(f"no test DB reachable at {host}:{port} -- start postgres:14 on that port")
        return

    # Local imports: these modules do not exist until Plans 02+03 land.
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415
    from farm_agent.persistence.pool import build_pool  # noqa: PLC0415
    from farm_agent.persistence.migrations import run_migrations  # noqa: PLC0415

    config = load_config(TEST_ENV)
    p = await build_pool(config)
    await run_migrations(p)
    yield p
    await p.close()


# ---------------------------------------------------------------------------
# Phase 57: httpx mock + FakeOutboundRepo fixtures (no DB required, always available)
# ---------------------------------------------------------------------------


@pytest.fixture
def signal_http():
    """respx-based mock transport for httpx.AsyncClient in signal_io tests.

    Usage in test:
        async with httpx.AsyncClient(transport=signal_http) as client:
            resp = await client.post(...)

    Configure responses before use:
        signal_http.post("http://signal-cli:8080/v2/send").mock(
            return_value=httpx.Response(201, json={"timestamp": 1234567890})
        )
    """
    import respx  # noqa: PLC0415
    import httpx  # noqa: PLC0415

    with respx.mock(assert_all_called=False) as mock_transport:
        yield mock_transport


class FakeOutboundRepo:
    """In-memory outbound repo for signal_io unit tests.

    Toggle should_raise to True to simulate a DB failure and test fail-open behavior.
    Records all calls in self.calls for assertion.
    """

    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[dict] = []

    async def insert_outbound(self, pool: object, row: dict) -> dict:
        """Mimic outbound_repo.insert_outbound signature."""
        self.calls.append(row)
        if self.should_raise:
            raise RuntimeError("FakeOutboundRepo: simulated insert failure")
        return {"ok": True}


@pytest.fixture
def fake_outbound_repo():
    """Return a FakeOutboundRepo instance (default: succeeds).

    To test fail-open: set repo.should_raise = True before calling.
    """
    return FakeOutboundRepo()


# ---------------------------------------------------------------------------
# Phase 58: capture suite fakes (no DB required, always available)
# ---------------------------------------------------------------------------


class FakeCaptureRepo:
    """In-memory capture repo for capture unit tests.

    Toggle should_raise to True to simulate a DB failure and test fail-open behavior.
    Records all calls in self.calls for assertion.
    """

    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[dict] = []
        self.gate_updates: list[tuple[str, str]] = []

    async def insert_capture(self, pool: object, row: dict) -> dict:
        """Mimic capture_repo.insert_capture signature."""
        self.calls.append(row)
        if self.should_raise:
            raise RuntimeError("FakeCaptureRepo: simulated insert failure")
        return {"ok": True}

    async def update_extraction_gate(self, pool: object, capture_id: str, gate: str) -> dict:
        """Mimic capture_repo.update_extraction_gate (MUSHY-78 follow-up UPDATE).

        Applies the gate to the recorded row so assertions on self.calls see the
        same final shape the real signal_capture row ends up with.
        """
        self.gate_updates.append((capture_id, gate))
        for row in self.calls:
            if row.get("id") == capture_id:
                row["extraction_gate"] = gate
        return {"ok": True}


@pytest.fixture
def fake_capture_repo():
    """Return a FakeCaptureRepo instance (default: succeeds).

    To test fail-open: set repo.should_raise = True before calling.
    """
    return FakeCaptureRepo()


# ---------------------------------------------------------------------------
# Phase 61: confirm suite fakes (no DB required, always available)
# ---------------------------------------------------------------------------


class FakeConfirmRepo:
    """In-memory confirm repo for confirm unit tests.

    Records all calls in self.calls for assertion.
    Returns {"ok": True, "rowcount": 1} by default for transition methods.
    find_* candidates return [] / None as appropriate.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _record(self, fn: str, **kwargs) -> None:
        self.calls.append({"fn": fn, **kwargs})

    async def confirm_draft(self, pool: object, draft_id: str) -> dict:
        self._record("confirm_draft", draft_id=draft_id)
        return {"ok": True, "rowcount": 1}

    async def discard_draft(self, pool: object, draft_id: str) -> dict:
        self._record("discard_draft", draft_id=draft_id)
        return {"ok": True, "rowcount": 1}

    async def expire_draft(self, pool: object, draft_id: str, reason: str) -> dict:
        self._record("expire_draft", draft_id=draft_id, reason=reason)
        return {"ok": True, "rowcount": 1}

    async def mark_nudge_sent(self, pool: object, draft_id: str) -> dict:
        self._record("mark_nudge_sent", draft_id=draft_id)
        return {"ok": True, "rowcount": 1}

    async def bump_edit_turn(self, pool: object, draft_id: str) -> dict:
        self._record("bump_edit_turn", draft_id=draft_id)
        return {"ok": True, "edit_turn_count": 1, "rowcount": 1}

    async def find_awaiting_for_sender(self, pool: object, sender_e164: str) -> dict | None:
        self._record("find_awaiting_for_sender", sender_e164=sender_e164)
        return None

    async def find_nudge_candidates(self, pool: object, nudge_min: int) -> list:
        self._record("find_nudge_candidates", nudge_min=nudge_min)
        return []

    async def find_expire_candidates(self, pool: object, timeout_min: int) -> list:
        self._record("find_expire_candidates", timeout_min=timeout_min)
        return []


@pytest.fixture
def fake_confirm_repo():
    """Return a FakeConfirmRepo instance (default: succeeds with rowcount=1)."""
    return FakeConfirmRepo()


async def _fake_transcribe(arg) -> dict:
    """Canned async transcribe result for pipeline unit tests (Option B -- no respx)."""
    return {"ok": True, "text": "fake transcript", "duration_ms": 100, "language": "es"}


@pytest.fixture
def fake_transcribe_client():
    """Return an injected {transcribe} dict with a canned async result.

    Mirrors the create_transcribe_client() factory shape.
    Use for test_capture_pipeline.py tests that inject the transcribe_client directly
    rather than testing the HTTP layer.
    """
    return {"transcribe": _fake_transcribe}


@pytest.fixture
def whisper_http():
    """respx-based mock transport for httpx.AsyncClient in transcribe_client tests.

    Usage in test:
        async with httpx.AsyncClient(transport=whisper_http) as client:
            resp = await client.post(...)

    Configure responses before use:
        whisper_http.post("http://host.docker.internal:8090/transcribe").mock(
            return_value=httpx.Response(200, json={
                "text": "Test transcript", "duration_ms": 1500, "language": "es"
            })
        )
    """
    import respx  # noqa: PLC0415

    with respx.mock(assert_all_called=False) as mock_transport:
        yield mock_transport


# ---------------------------------------------------------------------------
# Phase 59: gate suite fakes (no DB required, always available)
# ---------------------------------------------------------------------------


class FakeAnthropicClient:
    """MagicMock-based Anthropic client fake for event-gate unit tests.

    Mirrors the FakeCaptureRepo / fake_transcribe_client pattern.

    Parameters
    ----------
    tool_input:
        The dict returned as block.input in the fake tool_use response.
        Defaults to a canonical "is an event" result.
    raise_exc:
        If set, async create() raises this exception instead of returning.
    return_no_tool_use:
        If True, content=[] (simulates a response with no tool_use block).
    """

    _DEFAULT_TOOL_INPUT: dict = {
        "is_event": True,
        "kind": "event",
        "confidence": 0.95,
    }

    def __init__(
        self,
        tool_input: dict | None = None,
        raise_exc: Exception | None = None,
        return_no_tool_use: bool = False,
    ) -> None:
        self.tool_input = tool_input if tool_input is not None else self._DEFAULT_TOOL_INPUT
        self.raise_exc = raise_exc
        self.return_no_tool_use = return_no_tool_use
        self.calls: list[dict] = []

    def with_options(self, **kwargs) -> "FakeAnthropicClient":
        """Mirror client.with_options(timeout=...) — returns self."""
        return self

    @property
    def messages(self) -> "FakeAnthropicClient":
        """Mirror client.messages — returns self so create() is callable."""
        return self

    async def create(self, **kwargs) -> MagicMock:
        """Record kwargs; raise or return a fake Anthropic response."""
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        response = MagicMock()
        if self.return_no_tool_use:
            response.content = []
        else:
            block = MagicMock()
            block.type = "tool_use"
            block.name = "classify_capture"
            block.input = self.tool_input  # attribute access, NOT dict key
            usage = MagicMock()
            usage.input_tokens = 100
            usage.output_tokens = 10
            usage.cache_creation_input_tokens = 50
            usage.cache_read_input_tokens = 0
            response.content = [block]
            response.usage = usage
        return response


@pytest.fixture
def fake_anthropic_client() -> FakeAnthropicClient:
    """Return a default FakeAnthropicClient (succeeds, returns is_event=True).

    To customize: FakeAnthropicClient(tool_input={...}, raise_exc=..., return_no_tool_use=True).
    """
    return FakeAnthropicClient()


# ---------------------------------------------------------------------------
# Phase 60: extraction suite fake (no DB required, always available)
# ---------------------------------------------------------------------------


class FakeAnthropicClientForExtractor:
    """Multi-call Anthropic client fake for extraction unit tests.

    Driven by a sequence of response entries consumed one-per-create() call.
    Mirrors the FakeAnthropicClient pattern but supports replaying multiple
    calls and simulating a 2-call retry flow.

    Parameters
    ----------
    responses:
        List of response dicts. Each entry is one of:
          - {"tool_input": {...}}  -- return a tool_use response with that input
          - {"raise": <Exception>} -- raise that exception instead of returning

    Usage
    -----
        fake = FakeAnthropicClientForExtractor([
            {"tool_input": {"drafts": [...], "continuity": "start_new", ...}},
        ])
        result = await fake.messages.create(model=..., messages=...)
        assert fake.calls[0]["model"] == "..."
    """

    def __init__(self, responses: list[dict] | None = None) -> None:
        self.responses: list[dict] = responses if responses is not None else []
        self.calls: list[dict] = []
        self.call_index: int = 0

    def with_options(self, **kwargs) -> "FakeAnthropicClientForExtractor":
        """Mirror client.with_options(timeout=...) -- returns self."""
        return self

    @property
    def messages(self) -> "FakeAnthropicClientForExtractor":
        """Mirror client.messages -- returns self so create() is callable."""
        return self

    async def create(self, **kwargs) -> MagicMock:
        """Record kwargs; consume next response entry and raise or return."""
        self.calls.append(kwargs)
        # Use pre-increment index value as the block id (DISTINCT per call).
        n = self.call_index
        self.call_index += 1
        entry = self.responses[n]
        if "raise" in entry:
            raise entry["raise"]
        block = MagicMock()
        block.type = "tool_use"
        block.name = "submit_extraction"
        block.id = f"tu_call_{n}"
        block.input = entry["tool_input"]
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 20
        usage.cache_creation_input_tokens = 50
        usage.cache_read_input_tokens = 0
        response = MagicMock()
        response.content = [block]
        response.usage = usage
        return response
