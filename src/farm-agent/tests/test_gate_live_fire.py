"""
tests/test_gate_live_fire.py -- Real-Haiku full-100 corpus accuracy validation.

OPERATOR-RUN ONLY.  Skipped by default (requires ANTHROPIC_API_KEY + GATE_LIVE_FIRE=1).
Never runs in CI.

Purpose:
  Replay ALL 100 fixture rows (including the 10 holdout rows excluded from the
  deterministic Plan-03 corpus tests) through the REAL claude-haiku-4-5-20251001
  classifier and assert the two ROADMAP parity metrics:

  SC-1  0% false-positive on labeled negatives (every 'skip' row must be denied)
  SC-2  >=95% event recall (>=95% of 'extract' rows must be allowed)

  Plus a prompt-cache liveness check: the direct-classifier first call must show
  cache_creation_input_tokens > 0 (or cache_read_input_tokens > 0 on a warm cache)
  confirming the 21765-char SYSTEM_PROMPT cleared the 4096-token Haiku 4.5 threshold.
  The gate facade does NOT propagate `usage`, so this check goes through the
  classifier directly (not through create_event_gate).

Cost / opt-in:
  100 real API calls.  Each call uses max_tokens=100 with a ~21KB cached system
  prompt.  Set GATE_LIVE_FIRE=1 only when you intend to spend the tokens.

Usage:
  export ANTHROPIC_API_KEY=<live key>
  export GATE_LIVE_FIRE=1
  cd src/farm-agent && uv run pytest -q tests/test_gate_live_fire.py -v -m live_fire

Reference:
  .planning/phases/59-event-gate/59-04-PLAN.md
  .planning/phases/58-capture-transcription/58-LIVE-FIRE.md (the Phase 58 operator-run
  live-fire this mirrors)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import anthropic
import pytest

from farm_agent.gate.classifier import create_haiku_classifier
from farm_agent.gate.event_gate import create_event_gate

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "gate" / "44-hand-classified-100.jsonl"
)

# ---------------------------------------------------------------------------
# Live-fire test
# ---------------------------------------------------------------------------


@pytest.mark.live_fire
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("GATE_LIVE_FIRE"),
    reason="live-fire: requires ANTHROPIC_API_KEY + GATE_LIVE_FIRE=1",
)
@pytest.mark.asyncio
async def test_real_haiku_100_corpus() -> None:
    """Full-100-corpus accuracy + prompt-cache liveness validation.

    Asserts:
      - Cache liveness:  first direct-classifier call has cache_creation_input_tokens > 0
                         (or cache_read_input_tokens > 0 on a warm cache)
      - SC-1: 0 labeled-negative rows allowed through (0% false-positive)
      - SC-2: >=95% event recall across all 100 rows (incl. holdout)
    """
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)

    try:
        # -----------------------------------------------------------------------
        # Load full 100-row corpus (NO holdout filter -- holdout rows are the point)
        # -----------------------------------------------------------------------
        rows = [json.loads(line) for line in _FIXTURE_PATH.read_text().splitlines() if line.strip()]
        assert len(rows) == 100, f"Expected 100 fixture rows, got {len(rows)}"

        # -----------------------------------------------------------------------
        # Cache-liveness check (via classifier directly -- gate facade drops usage)
        # -----------------------------------------------------------------------
        classifier = create_haiku_classifier(client=client)
        first_row = rows[0]
        first_env_ctx = {
            "text": first_row.get("raw_text"),
            "transcript": first_row.get("transcript"),
            "attachmentCount": first_row.get("attachment_count") or 0,
        }
        cls_result = await classifier["classify"](first_env_ctx)

        assert cls_result.get("ok") is True, (
            f"First direct-classifier call failed: {cls_result.get('reason')} -- "
            "cannot verify prompt-cache liveness"
        )
        usage = cls_result.get("usage")
        assert usage is not None, "Classifier success result missing 'usage' field"

        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        assert cache_creation > 0 or cache_read > 0, (
            f"Prompt cache NOT active on first call "
            f"(cache_creation_input_tokens={cache_creation}, "
            f"cache_read_input_tokens={cache_read}). "
            "The SYSTEM_PROMPT may have been truncated below the 4096-token Haiku 4.5 "
            "cache threshold (Pitfall 2). Check farm_agent/gate/prompts.py CACHEABLE_SYSTEM_BLOCKS."
        )

        # -----------------------------------------------------------------------
        # Full-100 gate replay (through create_event_gate for real SC-1/SC-2)
        # -----------------------------------------------------------------------
        gate = create_event_gate(create_haiku_classifier(client=client))
        now_ms = int(time.time() * 1000)

        false_positives: list[dict] = []  # labeled skip but allowed
        extract_allowed = 0
        extract_total = 0
        skip_total = 0

        for row in rows:
            capture_id = row.get("capture_id", "<unknown>")
            expected_action = row.get("expected_gate_action")  # 'extract' | 'skip'
            row_class = row.get("class", "")

            env_ctx = {
                "text": row.get("raw_text"),
                "transcript": row.get("transcript"),
                "attachmentCount": row.get("attachment_count") or 0,
            }

            result = await gate["classify"](env_ctx, None, now_ms)
            allow_extract = result.get("allow_extract", False)

            if expected_action == "skip":
                skip_total += 1
                if allow_extract:
                    false_positives.append({
                        "capture_id": capture_id,
                        "class": row_class,
                        "gate": result.get("gate"),
                        "notes": row.get("notes", ""),
                    })
            elif expected_action == "extract":
                extract_total += 1
                if allow_extract:
                    extract_allowed += 1

        # -----------------------------------------------------------------------
        # SC-1: 0% false-positive on labeled negatives
        # -----------------------------------------------------------------------
        fp_count = len(false_positives)
        if fp_count > 0:
            fp_details = "\n".join(
                f"  capture_id={fp['capture_id']}  class={fp['class']}  gate={fp['gate']}  notes={fp['notes']}"
                for fp in false_positives
            )
            pytest.fail(
                f"SC-1 FAILED: {fp_count} labeled-negative row(s) passed through the gate "
                f"(expected 0 false-positives).\n"
                f"Failing rows:\n{fp_details}\n"
                "This is a real classifier-accuracy signal -- do NOT relax the threshold."
            )

        # -----------------------------------------------------------------------
        # SC-2: >=95% event recall on all 100 rows
        # -----------------------------------------------------------------------
        if extract_total == 0:
            pytest.fail("SC-2 ERROR: no 'extract' rows found in fixture -- fixture may be corrupt")

        recall = extract_allowed / extract_total
        missed_count = extract_total - extract_allowed

        assert recall >= 0.95, (
            f"SC-2 FAILED: event recall={recall:.1%} "
            f"({extract_allowed}/{extract_total} extract rows allowed, {missed_count} missed). "
            "Threshold is 95%. "
            "This is a real classifier-accuracy signal -- do NOT relax the threshold. "
            "Record the missed capture_ids as a finding."
        )

        # -----------------------------------------------------------------------
        # Report (visible in pytest -v output)
        # -----------------------------------------------------------------------
        print(
            f"\n[live-fire] Cache liveness: cache_creation={cache_creation}  cache_read={cache_read}"
            f"\n[live-fire] SC-1 passed: 0/{skip_total} labeled-negative rows allowed"
            f"\n[live-fire] SC-2 passed: recall={recall:.1%} ({extract_allowed}/{extract_total} extract rows)"
            f"\n[live-fire] Usage first call: {usage}"
        )

    finally:
        await client.close()
