"""signal_io -- Signal I/O package for farm_agent.

Provides:
  SignalClient: send/receive/fetch_attachment/accounts via httpx against
  the signal-cli REST container (MODE=normal). Rate-cap guarded by asyncio.Lock.
  Fail-open durable persist via outbound_repo.insert_outbound.
"""

from farm_agent.signal_io.client import SignalClient

__all__ = ["SignalClient"]
