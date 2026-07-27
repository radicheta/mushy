"""
tests/test_boot.py -- boot integration tests (FND-01).

Task 1 (TDD RED): tests written before boot.py exists.
These tests prove:
  - boot.py wires config -> pool -> migrations -> "boot complete" in < 5s
  - No secret placeholder values appear in boot log output
"""

import asyncio
import logging
import time
import socket

import pytest


def _db_reachable() -> bool:
    """Return True if the test DB port is connectable."""
    import os
    host_raw = os.environ.get("TIMESCALE_HOST", "localhost:5434")
    if ":" in host_raw:
        host, port_str = host_raw.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_raw
        port = 5434
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# test_boot_completes_in_5s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boot_completes_in_5s(monkeypatch, caplog):
    """
    Boot (config -> pool -> migrations -> 'boot complete') must complete in < 5.0s
    against the test DB AND must emit the 'boot complete' log line.

    The caplog assertion distinguishes a fast boot from a hung boot that gets
    cancelled at the 5s timeout without ever reaching 'boot complete'.

    Skips when no test DB is reachable on localhost:5434 (or TEST_TIMESCALE_HOST:TEST_TIMESCALE_PORT).
    """
    if not _db_reachable():
        pytest.skip("no test DB reachable -- start postgres:14 on port 5434")

    from tests.conftest import TEST_ENV  # noqa: PLC0415
    # Patch os.environ for the duration of main() so load_config() picks up test values.
    import os
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)

    from farm_agent.boot import main  # noqa: PLC0415

    t0 = time.monotonic()

    # Run main() as a task; cancel it immediately after "boot complete" is logged
    # (or after a short timeout so the test does not hang).
    # We do this by running in the existing event loop and cancelling after a brief
    # idle period -- main() idles on stop.wait() after logging "boot complete".
    with caplog.at_level(logging.INFO, logger="farm_agent"):
        task = asyncio.create_task(main())

        # Give main() up to 5 seconds to reach the "boot complete" log line.
        # We cancel shortly after -- this is sufficient because the idle wait follows immediately.
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except asyncio.TimeoutError:
            # This is the expected path: main() blocks on stop.wait() after booting.
            # The boot phase itself completed within the timeout.
            elapsed = time.monotonic() - t0
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            assert elapsed < 6.0, f"boot did not reach idle within 5s (elapsed={elapsed:.2f}s)"
        except asyncio.CancelledError:
            elapsed = time.monotonic() - t0
            assert elapsed < 6.0, f"boot did not complete within 5s (elapsed={elapsed:.2f}s)"
        else:
            # main() returned normally (shouldn't happen in production -- it idles).
            elapsed = time.monotonic() - t0
            assert elapsed < 5.0, f"boot took {elapsed:.2f}s >= 5.0s"

    # Assert the "boot complete" line was actually emitted.
    # This distinguishes a real completed boot from a DB stall that just happened
    # to get cancelled within the 5s window (WR-01 guard).
    boot_messages = [r.getMessage() for r in caplog.records]
    assert any("boot complete" in m for m in boot_messages), (
        f"'boot complete' not found in logs -- boot may have hung or crashed. "
        f"Log records: {boot_messages}"
    )


# ---------------------------------------------------------------------------
# test_boot_logs_no_secrets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boot_logs_no_secrets(monkeypatch, caplog):
    """
    No boot log line may contain a secret placeholder value (T-56-06-01).

    The test secrets from TEST_ENV that must NOT appear in any log record:
      - TIMESCALE_PASSWORD  = "test"   (short but unambiguous in context)
      - ANTHROPIC_API_KEY   = "test-key"
      - SIGNAL_SENDER       = "+10000000000"
      - FARMOS_PASSWORD     = "test-pass"

    Skips when no test DB is reachable (secrets test requires a real boot to run).
    """
    if not _db_reachable():
        pytest.skip("no test DB reachable -- start postgres:14 on port 5434")

    from tests.conftest import TEST_ENV  # noqa: PLC0415
    import os
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)

    SECRET_VALUES = [
        TEST_ENV["TIMESCALE_PASSWORD"],  # "test"
        TEST_ENV["ANTHROPIC_API_KEY"],   # "test-key"
        TEST_ENV["SIGNAL_SENDER"],       # "+10000000000"
        TEST_ENV["FARMOS_PASSWORD"],     # "test-pass"
    ]

    from farm_agent.boot import main  # noqa: PLC0415

    with caplog.at_level(logging.DEBUG, logger="farm_agent"):
        task = asyncio.create_task(main())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        except (asyncio.CancelledError, Exception):
            pass

    for record in caplog.records:
        for secret in SECRET_VALUES:
            assert secret not in record.getMessage(), (
                f"Secret value '{secret}' found in log record: {record.getMessage()!r}"
            )


# ---------------------------------------------------------------------------
# test_boot_commit_watchdog_created_when_farmos_integration_true
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boot_commit_watchdog_created_when_farmos_integration_true(monkeypatch, caplog):
    """
    When FARMOS_INTEGRATION=1, boot starts the commit_watchdog_loop task
    and logs the '[commit_watchdog] started' line.

    Requires a reachable test DB (the watchdog ticks immediately on boot
    and calls release_stale_locks + find_confirmed_candidates against the DB).
    """
    if not _db_reachable():
        pytest.skip("no test DB reachable -- start postgres:14 on port 5434")

    from tests.conftest import TEST_ENV  # noqa: PLC0415
    import os
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("FARMOS_INTEGRATION", "1")

    from farm_agent.boot import main  # noqa: PLC0415

    with caplog.at_level(logging.INFO, logger="farm_agent"):
        task = asyncio.create_task(main())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        except (asyncio.CancelledError, Exception):
            pass

    messages = [r.getMessage() for r in caplog.records]
    assert any("commit_watchdog" in m and "started" in m for m in messages), (
        f"[commit_watchdog] started not found in logs: {messages}"
    )
    assert any("boot complete" in m for m in messages), (
        f"boot complete not logged -- boot may have hung"
    )


# ---------------------------------------------------------------------------
# test_boot_commit_watchdog_not_created_when_farmos_integration_false
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boot_commit_watchdog_not_created_when_farmos_integration_false(monkeypatch, caplog):
    """
    When FARMOS_INTEGRATION is not set (default False), no commit_watchdog task
    is started and '[commit_watchdog] started' does NOT appear in logs.
    """
    if not _db_reachable():
        pytest.skip("no test DB reachable -- start postgres:14 on port 5434")

    from tests.conftest import TEST_ENV  # noqa: PLC0415
    import os
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)
    # Ensure FARMOS_INTEGRATION is explicitly 0 (default False)
    monkeypatch.setenv("FARMOS_INTEGRATION", "0")

    from farm_agent.boot import main  # noqa: PLC0415

    with caplog.at_level(logging.INFO, logger="farm_agent"):
        task = asyncio.create_task(main())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        except (asyncio.CancelledError, Exception):
            pass

    messages = [r.getMessage() for r in caplog.records]
    assert not any("commit_watchdog" in m and "started" in m for m in messages), (
        f"[commit_watchdog] started found in logs but should NOT be (farmos_integration=False): {messages}"
    )
    assert any("boot complete" in m for m in messages), (
        f"boot complete not logged -- boot may have hung"
    )
