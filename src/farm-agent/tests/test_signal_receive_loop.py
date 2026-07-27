"""
test_signal_receive_loop.py -- Unit tests for farm_agent.signal_io.receive_loop.

Coverage:
- tick() dispatches all whitelisted envelopes in order (attribution, no asyncio.gather)
- tick() skips non-whitelisted senders (logs warning, no dispatch)
- tick() skips envelopes with no source
- loop-never-dies: dispatch exception on envelope #2 does not prevent envelope #3 dispatch
- start()/stop() create and cleanly cancel the poll task
"""

import asyncio
import logging

import pytest

from tests.conftest import TEST_ENV


# ---------------------------------------------------------------------------
# Helpers — minimal TenantConfig + fake signal client
# ---------------------------------------------------------------------------


def _config(**overrides):
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    env = {
        **TEST_ENV,
        "SIGNAL_ADDITIONAL_SENDERS": "+10000000002",
    }
    env.update(overrides)
    return load_config(env)


def _envelope(source, text="hello"):
    return {"envelope": {"source": source, "dataMessage": {"message": text}}}


class FakeSignalClient:
    """Fake signal client that returns pre-configured envelopes on .receive()."""

    def __init__(self, envelopes_batch=None):
        # envelopes_batch: list returned on receive(); defaults to []
        self._envelopes = envelopes_batch if envelopes_batch is not None else []
        self.receive_calls = 0

    async def receive(self, timeout_sec=1, ignore_attachments=False):
        self.receive_calls += 1
        return list(self._envelopes)


# ---------------------------------------------------------------------------
# 1. Sequential dispatch — 3 whitelisted envelopes, all dispatched in order
# ---------------------------------------------------------------------------


async def test_tick_dispatches_all_whitelisted_in_order():
    """tick() calls dispatch for each whitelisted envelope, in arrival order."""
    from farm_agent.signal_io.receive_loop import ReceiveLoop  # noqa: PLC0415

    cfg = _config()
    call_order = []

    async def dispatch(env):
        call_order.append(env["envelope"]["source"])

    sender = cfg.signal_sender      # "+10000000000"
    recipient = cfg.signal_recipient  # "+10000000001"
    extra = "+10000000002"           # in SIGNAL_ADDITIONAL_SENDERS

    envelopes = [
        _envelope(sender),
        _envelope(recipient),
        _envelope(extra),
    ]
    client = FakeSignalClient(envelopes)
    loop = ReceiveLoop(signal_client=client, dispatch=dispatch, config=cfg)
    await loop.tick()

    assert call_order == [sender, recipient, extra], (
        f"Expected sequential dispatch order; got {call_order}"
    )


# ---------------------------------------------------------------------------
# 2. Non-whitelisted sender is rejected (not dispatched)
# ---------------------------------------------------------------------------


async def test_tick_rejects_non_whitelisted_sender(caplog):
    """Envelopes from non-whitelisted senders are not dispatched; warning logged."""
    from farm_agent.signal_io.receive_loop import ReceiveLoop  # noqa: PLC0415

    cfg = _config()
    dispatched = []

    async def dispatch(env):
        dispatched.append(env)

    unknown = "+19999999999"
    client = FakeSignalClient([_envelope(unknown)])
    loop = ReceiveLoop(signal_client=client, dispatch=dispatch, config=cfg)

    with caplog.at_level(logging.WARNING):
        await loop.tick()

    assert dispatched == [], "Non-whitelisted sender must not be dispatched"
    assert any("whitelist" in r.message.lower() or "rejected" in r.message.lower()
               for r in caplog.records), "Expected a whitelist-reject warning log"


# ---------------------------------------------------------------------------
# 3. Envelope with no source is skipped silently
# ---------------------------------------------------------------------------


async def test_tick_skips_no_source():
    """Envelopes with no source are skipped (no dispatch, no exception)."""
    from farm_agent.signal_io.receive_loop import ReceiveLoop  # noqa: PLC0415

    cfg = _config()
    dispatched = []

    async def dispatch(env):
        dispatched.append(env)

    env_no_source = {"envelope": {"dataMessage": {"message": "hi"}}}  # no 'source'
    client = FakeSignalClient([env_no_source])
    loop = ReceiveLoop(signal_client=client, dispatch=dispatch, config=cfg)
    await loop.tick()

    assert dispatched == []


# ---------------------------------------------------------------------------
# 4. Loop-never-dies: dispatch raises on envelope #2, envelope #3 still dispatched
# ---------------------------------------------------------------------------


async def test_tick_continues_after_dispatch_exception():
    """loop-never-dies: dispatch exception on one envelope does not kill tick().

    envelope #1 dispatched, #2 raises, #3 still dispatched. tick() does NOT raise.
    """
    from farm_agent.signal_io.receive_loop import ReceiveLoop  # noqa: PLC0415

    cfg = _config()
    dispatched = []

    async def dispatch(env):
        source = env["envelope"]["source"]
        dispatched.append(source)
        if source == cfg.signal_recipient:
            raise RuntimeError("simulated dispatch failure")

    sender = cfg.signal_sender      # "+10000000000"
    recipient = cfg.signal_recipient  # "+10000000001" — will raise
    extra = "+10000000002"

    envelopes = [_envelope(sender), _envelope(recipient), _envelope(extra)]
    client = FakeSignalClient(envelopes)
    loop = ReceiveLoop(signal_client=client, dispatch=dispatch, config=cfg)

    # tick() must not raise despite dispatch raising on #2
    await loop.tick()

    assert sender in dispatched, "envelope #1 should be dispatched"
    assert recipient in dispatched, "envelope #2 should be attempted (then catch)"
    assert extra in dispatched, "envelope #3 should be dispatched after #2 exception"


# ---------------------------------------------------------------------------
# 5. start() / stop() lifecycle — task is created and cancelled cleanly
# ---------------------------------------------------------------------------


async def test_start_stop_no_warning():
    """start()/stop() create and cleanly cancel the poll task without warnings."""
    from farm_agent.signal_io.receive_loop import ReceiveLoop  # noqa: PLC0415

    cfg = _config()

    async def dispatch(env):
        pass

    # Client that never returns envelopes (loop just sleeps between ticks)
    client = FakeSignalClient([])
    loop = ReceiveLoop(signal_client=client, dispatch=dispatch, config=cfg, poll_sec=9999)
    await loop.start()
    # Give one event-loop turn for the task to spin up
    await asyncio.sleep(0)
    await loop.stop()
    # If we get here without exception, the task cancelled cleanly.


async def test_stop_without_start_is_noop():
    """stop() on a never-started loop is a no-op (does not raise)."""
    from farm_agent.signal_io.receive_loop import ReceiveLoop  # noqa: PLC0415

    cfg = _config()

    async def dispatch(env):
        pass

    loop = ReceiveLoop(signal_client=FakeSignalClient(), dispatch=dispatch, config=cfg)
    await loop.stop()  # must not raise


# ---------------------------------------------------------------------------
# 6. receive() error does not kill the poll task (Pitfall 4 / loop-never-dies)
# ---------------------------------------------------------------------------


async def test_tick_survives_receive_exception(caplog):
    """A receive() exception is caught; tick() logs a warning and does not propagate."""
    from farm_agent.signal_io.receive_loop import ReceiveLoop  # noqa: PLC0415

    cfg = _config()
    dispatched = []

    async def dispatch(env):
        dispatched.append(env)

    class ErrorClient:
        async def receive(self, timeout_sec=1, ignore_attachments=False):
            raise RuntimeError("network failure")

    loop = ReceiveLoop(signal_client=ErrorClient(), dispatch=dispatch, config=cfg)

    with caplog.at_level(logging.WARNING):
        # tick() must not raise
        await loop.tick()

    assert dispatched == []
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "Expected a warning log for receive() failure"
    )
