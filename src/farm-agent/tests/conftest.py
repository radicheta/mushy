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

import os

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
}


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

    async def insert_capture(self, pool: object, row: dict) -> dict:
        """Mimic capture_repo.insert_capture signature."""
        self.calls.append(row)
        if self.should_raise:
            raise RuntimeError("FakeCaptureRepo: simulated insert failure")
        return {"ok": True}


@pytest.fixture
def fake_capture_repo():
    """Return a FakeCaptureRepo instance (default: succeeds).

    To test fail-open: set repo.should_raise = True before calling.
    """
    return FakeCaptureRepo()


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
