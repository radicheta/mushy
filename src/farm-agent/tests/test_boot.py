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


# ---------------------------------------------------------------------------
# Task 8c (MUSHY-76): boot wires the confirm-reply router into the live dispatch
# handle, and a farmer's YES actually reaches confirm_draft -- not merely that
# create_confirm_reply_router was constructed.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boot_dispatch_handle_routes_yes_to_confirm_path(monkeypatch, caplog, pool):
    """Prove the seam is live end-to-end through boot.py's real composition.

    Before task 8c, route_confirm_reply had no caller anywhere in farm_agent --
    boot.py started the confirm watchdog (nudge/expire) but nothing routed an
    inbound reply, so every draft expired unacked. A passing unit test on the
    router alone does not prove the wiring (the same class of bug that shipped
    the seam in the first place would still pass one). This test:

      1. Boots the REAL daemon (farm_agent.boot.main), intercepting only the
         ReceiveLoop construction (to avoid needing a live signal-cli poller)
         -- everything else (pool, capture pipeline, confirm router, chamber
         composite dispatch) is real, wired exactly as production wires it.
      2. Inserts a real awaiting_farmer draft directly into the same test DB
         boot.py connects to.
      3. Feeds a raw envelope carrying "YES" straight into the dispatch handle
         boot.py actually constructed and would have handed to ReceiveLoop.
      4. Asserts the draft's status flipped to 'confirmed' in the DB -- proof
         the handle really is confirm_router -> route_confirm_reply ->
         confirm_repo.confirm_draft, not a mock returning a canned answer.
    """
    if not _db_reachable():
        pytest.skip("no test DB reachable -- start postgres:14 on port 5434")

    import json  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    from tests.conftest import TEST_ENV  # noqa: PLC0415
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)

    import farm_agent.boot as boot_mod  # noqa: PLC0415

    captured: dict = {}

    class CapturingReceiveLoop:
        """Stand-in for ReceiveLoop that captures the composed dispatch handle
        instead of polling a live signal-cli. Everything upstream of this
        (confirm_router, chamber_dispatch, capture pipeline) is the real thing.
        """

        def __init__(self, signal_client, dispatch, config) -> None:
            captured["dispatch"] = dispatch

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(boot_mod, "ReceiveLoop", CapturingReceiveLoop)

    # Insert a real awaiting_farmer draft in the same test DB boot.py will use.
    sender = f"+1999{uuid.uuid4().hex[:8]}"
    draft_id = uuid.uuid4().hex
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO signal_draft
              (id, status, sender_e164, edit_turn_count, nudge_sent_at,
               draft_json, per_field_confidence, farmer_facing_preview,
               reply_target_kind, created_at, updated_at)
            VALUES (%s, 'awaiting_farmer', %s, 0, NULL, %s::jsonb, %s::jsonb, %s, 'dm', NOW(), NOW())
            """,
            (
                draft_id,
                sender,
                json.dumps({"species_code": "SHI"}),
                json.dumps({"species_code": 0.95}),
                "SHI on straw -- confirm?",
            ),
        )

    from farm_agent.boot import main  # noqa: PLC0415

    task = asyncio.create_task(main())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    except asyncio.TimeoutError:
        pass  # expected -- main() idles on stop.wait() after boot completes
    except Exception:  # noqa: BLE001 -- surfaced via the assertion below if boot never wired
        pass

    assert "dispatch" in captured, (
        "boot.py never constructed a ReceiveLoop -- boot did not complete wiring"
    )

    # Feed the raw envelope through the EXACT dispatch handle boot.py built and
    # would have handed to ReceiveLoop (chamber snooze -> confirm -> capture).
    envelope = {
        "envelope": {
            "source": sender,
            "dataMessage": {"message": "YES", "timestamp": 1_700_000_000_000},
        }
    }
    with caplog.at_level(logging.INFO, logger="farm_agent"):
        await captured["dispatch"](envelope)

    async with pool.connection() as conn:
        result = await conn.execute("SELECT status FROM signal_draft WHERE id=%s", (draft_id,))
        row = await result.fetchone()

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    assert row is not None, "draft row disappeared"
    assert row[0] == "confirmed", (
        f"boot's composed dispatch handle did not route the farmer's YES to "
        f"confirm_draft -- draft status={row[0]!r} (expected 'confirmed'). "
        "This is the exact seam MUSHY-76 task 8c closes: route_confirm_reply "
        "reachable from the real receive path, not just unit-testable in isolation."
    )


# ---------------------------------------------------------------------------
# Task 9 (MUSHY-76): boot actually constructs a real extraction pipeline and
# threads it into create_capture_pipeline. Before this task,
# create_capture_pipeline accepted an `extractor` kwarg and never used it --
# the daemon captured messages and stopped; no draft was ever created. A
# passing unit test on create_capture_pipeline's extraction_pipeline kwarg in
# isolation does not prove boot.py actually wires a real pipeline in -- the
# exact class of bug that shipped the dead parameter would still pass one.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boot_dispatch_handle_carries_capture_to_a_draft_row(monkeypatch, caplog, pool):
    """Prove the extraction seam is live end-to-end through boot.py's real composition.

      1. Boots the REAL daemon (farm_agent.boot.main), intercepting only the
         ReceiveLoop construction (no live signal-cli poller needed) and
         create_extractor (no live Anthropic call needed) -- everything else
         (pool, gate, capture pipeline, extraction pipeline, outbound
         dispatcher) is real, wired exactly as production wires it.
      2. Feeds a raw envelope from a sender resolvable via SIGNAL_FARMER_MAP,
         with text that trips the gate's rule_positive fast-path (a bare
         strain code -- no LLM call, no network dependency in the test).
      3. Asserts a real signal_draft row landed in the same test DB boot.py
         connects to, with the fields the fake extractor returned -- proof
         the handle really is capture.handle -> extraction_pipeline.enqueue ->
         extraction_db.insert_draft, not a mock returning a canned answer.
    """
    if not _db_reachable():
        pytest.skip("no test DB reachable -- start postgres:14 on port 5434")

    import uuid  # noqa: PLC0415

    from tests.conftest import TEST_ENV  # noqa: PLC0415
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)

    sender = f"+1888{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("SIGNAL_FARMER_MAP", f"{sender}:f1")

    import farm_agent.boot as boot_mod  # noqa: PLC0415

    extract_calls: list = []

    # **kwargs so a new extractor kwarg (e.g. MUSHY-83's capture_date_iso) does not
    # break this fake and turn a wiring test red for an unrelated reason.
    async def _fake_extract(captures, in_flight_draft=None, corpus_context=None, **kwargs):
        extract_calls.append(captures)
        return {
            "ok": True,
            "draft": {
                "type": "harvest",
                "harvest_batch_id": "B1",
                "source_block_refs": ["blk1"],
                "qty_g": 500,
                "event_timestamp": "2026-08-17T12:00:00Z",
            },
            "per_field_confidence": {
                "harvest_batch_id": 0.9,
                "source_block_refs": 0.9,
                "qty_g": 0.9,
                "event_timestamp": 0.9,
            },
            "continuity_decision": "start_new",
        }

    monkeypatch.setattr(
        boot_mod, "create_extractor", lambda **kwargs: {"extract": _fake_extract}
    )

    captured: dict = {}

    class CapturingReceiveLoop:
        def __init__(self, signal_client, dispatch, config) -> None:
            captured["dispatch"] = dispatch

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(boot_mod, "ReceiveLoop", CapturingReceiveLoop)

    from farm_agent.boot import main  # noqa: PLC0415

    task = asyncio.create_task(main())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    except asyncio.TimeoutError:
        pass  # expected -- main() idles on stop.wait() after boot completes
    except Exception:  # noqa: BLE001 -- surfaced via the assertion below if boot never wired
        pass

    assert "dispatch" in captured, (
        "boot.py never constructed a ReceiveLoop -- boot did not complete wiring"
    )

    # "SHI" is a bare 2-4 uppercase-letter strain code -- rule_positive fires
    # (kind=strain_code), so the gate never touches the network.
    envelope = {
        "envelope": {
            "source": sender,
            "dataMessage": {"message": "harvested 500g SHI", "timestamp": 1_700_000_000_000,
                             "attachments": []},
        }
    }
    with caplog.at_level(logging.INFO, logger="farm_agent"):
        await captured["dispatch"](envelope)

    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT draft_json, status, origin FROM signal_draft WHERE sender_e164=%s",
            (sender,),
        )
        rows = await result.fetchall()

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    assert extract_calls, (
        "the fake extractor was never called -- extraction_pipeline.enqueue never "
        "fired, so boot.py's capture pipeline is not wired to a real extraction "
        "pipeline (the exact seam this task closes)"
    )
    assert len(rows) == 1, (
        f"expected exactly one signal_draft row for sender, found {len(rows)}. "
        "boot's composed dispatch handle did not carry the capture through to "
        "extraction_db.insert_draft."
    )
    draft_json = rows[0][0]
    assert draft_json["harvest_batch_id"] == "B1", (
        f"draft row exists but draft_json does not match the fake extractor's "
        f"output: {draft_json!r}"
    )
    # I-3 / top design risk: the LIVE Node commit watchdog selects
    # WHERE status='confirmed' AND origin != 'python'. A Python draft left at the
    # column default would be committed to the real farm's production farmOS by
    # the other agent. Asserted here against a real row, not against SQL text.
    assert rows[0][2] == "python", (
        f"signal_draft.origin is {rows[0][2]!r}, not 'python' -- the Node commit "
        "watchdog would pick this draft up and write it to production farmOS"
    )


# ---------------------------------------------------------------------------
# MUSHY-90: boot must wire outbound persistence into the SignalClient it builds.
#
# boot.py constructed SignalClient without outbound_repo/pool, so the persist
# hook at client.py:289 was permanently false -- every send returned ok and wrote
# no signal_outbound row, silently (no else branch, no log). That kills
# confirm_repo.find_draft_by_quoted_msg_ts, which resolves a quoted reply by
# joining signal_outbound, right as MUSHY-53 made multiple in-flight drafts per
# sender possible.
#
# Asserted against a REAL row, not against the constructor kwargs: a kwargs
# assertion would pass on a repo object that cannot actually write.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boot_signal_client_persists_outbound_row(monkeypatch, pool):
    """A send through boot's own SignalClient must land a signal_outbound row."""
    if not _db_reachable():
        pytest.skip("no test DB reachable -- start postgres:14 on port 5434")

    import uuid  # noqa: PLC0415

    from tests.conftest import TEST_ENV  # noqa: PLC0415
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)

    import farm_agent.boot as boot_mod  # noqa: PLC0415

    captured: dict = {}

    class CapturingReceiveLoop:
        """Captures the real SignalClient boot composed, instead of polling."""

        def __init__(self, signal_client, dispatch, config) -> None:
            captured["signal_client"] = signal_client

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(boot_mod, "ReceiveLoop", CapturingReceiveLoop)

    from farm_agent.boot import main  # noqa: PLC0415

    task = asyncio.create_task(main())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    except asyncio.TimeoutError:
        pass  # expected -- main() idles on stop.wait() after boot completes
    except Exception:  # noqa: BLE001 -- surfaced by the assertion below
        pass

    assert "signal_client" in captured, (
        "boot.py never constructed a ReceiveLoop -- boot did not complete wiring"
    )
    signal_client = captured["signal_client"]

    # Stub only the wire POST. Everything else (repo, pool, row shape) is real.
    msg_ts = 1_700_000_000_000 + int(uuid.uuid4().int % 1_000_000)

    class _FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self) -> dict:
            return {"timestamp": msg_ts}

    async def _fake_post(*args, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr(signal_client.http, "post", _fake_post)

    body = f"outbound wiring probe {uuid.uuid4().hex[:8]}"
    result = await signal_client.send(body, intent="test_probe")

    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT intent, signal_msg_ts FROM signal_outbound WHERE body=%s",
            (body,),
        )).fetchall()

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    assert result["ok"] is True, f"send() did not succeed: {result!r}"
    assert len(rows) == 1, (
        f"expected exactly one signal_outbound row for the sent body, found "
        f"{len(rows)}. boot.py built SignalClient without outbound_repo/pool, so "
        "the persist hook is a no-op and quote-reply pinning has nothing to join "
        "against (MUSHY-90)."
    )
    assert rows[0][0] == "test_probe"
    assert rows[0][1] == msg_ts, (
        "signal_msg_ts was not persisted -- find_draft_by_quoted_msg_ts joins on "
        "this column, so a NULL here is as dead as a missing row"
    )
