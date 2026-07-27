"""gate -- event-gate gray-zone classifier for farm_agent.

Foray island: no imports from farm_agent.signal_io, farm_agent.capture,
farm_agent.persistence, or any other chamber-coupled subpackage.

Provides:
  create_event_gate: factory returning an async classify(env_ctx, last_bot_outbound, now_ms)
                     callable that applies the Node event-gate decision flow.
"""

from farm_agent.gate.event_gate import create_event_gate

__all__ = ["create_event_gate"]
