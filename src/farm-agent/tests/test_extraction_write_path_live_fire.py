"""
tests/test_extraction_write_path_live_fire.py -- Real-Sonnet, real-DB ship-gate
for the extraction write path (MUSHY-76).

OPERATOR-RUN ONLY.  Skipped by default (requires ANTHROPIC_API_KEY + EXTRACTION_LIVE_FIRE=1).
Never runs in CI.

Purpose:
  Hermetic tests (Tasks 1-9) prove the wiring. This proves the whole write
  path -- enqueue -> extractor -> state machine -> persistence -> outbound --
  against the REAL claude-sonnet-4-6 model and a REAL (throwaway) postgres,
  using the real 2026-05-22 session (audio transcript + downscaled photo +
  text follow-up) that Phase 60's test_extraction_live_fire.py also uses.

  Asserts a real signal_draft row lands with:
    - origin='python'        (the guard that stops the live Node commit
                               watchdog from picking up this draft and
                               writing it to production farmOS)
    - log_type='seeding_session'
    - status in a plausible post-enqueue set
    - D-1 end to end: if status='awaiting_farmer', something was actually
      sent to the farmer (RecordingSignalClient) -- the behaviour prod Node
      does not have, and the point of this whole phase.

DATABASE SAFETY (load-bearing, not a comment):
  This test uses the session-scoped `pool` fixture from tests/conftest.py,
  which is HARD-WIRED to the throwaway postgres:14 container on port 5434
  (TEST_TIMESCALE_HOST/TEST_TIMESCALE_PORT, defaulting to 5434 -- see
  tests/conftest.py:_test_host). It refuses to run at all unless that
  throwaway DB is reachable (pool fixture skips otherwise). This test does
  NOT construct its own pool and does NOT accept a TIMESCALE_HOST override --
  there is no code path in this file that can reach the shared TimescaleDB
  on :5432. That constraint is enforced below, not just documented: see
  _assert_not_prod_port() at the top of the test body.

  Never point this test at the shared TimescaleDB. Any draft that reaches
  'confirmed' there is picked up by the live Node commit watchdog and
  written to the real farm's production farmOS.

Cost / opt-in:
  One real Sonnet API call (extraction) against a real audio transcript +
  real photo. Set EXTRACTION_LIVE_FIRE=1 only when you intend to spend the
  tokens.

Usage:
  export ANTHROPIC_API_KEY=<live key>
  export EXTRACTION_LIVE_FIRE=1
  cd src/farm-agent && uv run pytest tests/test_extraction_write_path_live_fire.py -v -s

Reference:
  .planning/phases/64.1-extraction-write-path/64.1-VERIFICATION.md
  .superpowers/sdd/64.1-PLAN/task-10-brief.md
  tests/test_extraction_live_fire.py    (Phase 60's model-accuracy live-fire; same fixture)
  tests/test_gate_live_fire.py          (the Phase-59 live-fire this mirrors)
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import pytest

from farm_agent.extraction import preview_builder
from farm_agent.extraction.extractor import create_extractor
from farm_agent.extraction.outbound import create_outbound_dispatcher
from farm_agent.extraction.pipeline import create_extraction_pipeline

pytestmark = [
    pytest.mark.live_fire,
    pytest.mark.skipif(
        not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("EXTRACTION_LIVE_FIRE") == "1"),
        reason="live-fire: set ANTHROPIC_API_KEY and EXTRACTION_LIVE_FIRE=1",
    ),
]

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "extraction" / "seeding-session-may22"


class RecordingSignalClient:
    """Fake signal_client that records every send() instead of hitting the network."""

    def __init__(self):
        self.sent = []

    async def send(self, body, **kwargs):
        self.sent.append((body, kwargs))
        return {"ok": True}


def _assert_not_prod_port(pool) -> None:
    """Load-bearing safety check: refuse to run against anything but :5434.

    The pool fixture (tests/conftest.py) already hard-defaults to :5434, but
    this test never trusts a comment to do a database-safety job. If the
    pool's connection info ever resolves to :5432 (the shared production
    TimescaleDB port), abort before sending a single byte -- a confirmed
    draft there is picked up by the live Node commit watchdog and written
    to the real farm's production farmOS.
    """
    conninfo = getattr(pool, "conninfo", "") or ""
    assert "5432" not in conninfo, (
        f"REFUSING to run live-fire: pool conninfo looks like it points at the "
        f"production TimescaleDB port (5432): {conninfo!r}. This test must only "
        f"ever run against the throwaway :5434 postgres."
    )


async def test_may22_session_lands_a_real_draft(pool, tenant_config):
    _assert_not_prod_port(pool)

    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)
    signal_client = RecordingSignalClient()
    try:
        pipeline = create_extraction_pipeline(
            pool=pool,
            extractor=create_extractor(client=client),
            config=tenant_config,
            outbound_dispatcher=create_outbound_dispatcher(
                signal_client=signal_client,
                config=tenant_config,
                preview_builder=preview_builder,
                operator_recipient=None,
            ),
        )

        transcript = (FIXTURE_DIR / "transcript.txt").read_text(encoding="utf-8")
        text_followup = (FIXTURE_DIR / "text-followup.txt").read_text(encoding="utf-8")

        res = await pipeline["enqueue"]({
            "capture_id": "live-fire-may22",
            "sender": tenant_config.signal_recipient,
            "farmos_person": "santi",
            "text": text_followup,
            "transcripts": [transcript],
            "attachment_paths": [str(FIXTURE_DIR / "paper-log.jpg")],
            "reply_target_kind": "dm",
            "group_id": None,
            "captured_at_ms": 1_747_900_000_000,
            "corpus_context": None,
        })

        assert res["ok"] is True, res

        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, status, log_type, origin, farmer_facing_preview, draft_json "
                "FROM signal_draft WHERE %s = ANY(source_capture_ids)",
                ("live-fire-may22",),
            )
            rows = await cur.fetchall()

        assert len(rows) >= 1, "no signal_draft row was created -- MUSHY-76 is not fixed"
        row = rows[0]
        assert row[3] == "python", "origin must be 'python' or the Node watchdog commits it"
        assert row[2] == "seeding_session"
        assert row[1] in ("awaiting_farmer", "pending", "needs_review")

        # D-1 end to end: if the draft is awaiting the farmer, the farmer was
        # actually told about it. This is the behaviour prod Node does not have.
        if row[1] == "awaiting_farmer":
            assert signal_client.sent, "draft awaits the farmer but nothing was sent"

        print(f"\nstatus={row[1]} log_type={row[2]} origin={row[3]}")
        print(f"preview:\n{row[4]}")
        for body, _ in signal_client.sent:
            print(f"--- sent ---\n{body}")
    finally:
        await client.close()
