"""
tests/test_extraction_live_fire.py -- Real-Sonnet May-22 extraction accuracy validation.

OPERATOR-RUN ONLY.  Skipped by default (requires ANTHROPIC_API_KEY + EXTRACTION_LIVE_FIRE=1).
Never runs in CI.

Purpose:
  Drive create_extractor against the REAL claude-sonnet-4-6 model on the live
  2026-05-22 fixture (real audio transcript + real downscaled photo + text follow-up),
  assert the model produces the correct seeding_session draft, and report token/cache usage.

  The hermetic tests (plans 02/03) prove the WIRING (retry, schema, seq-minting,
  multimodal assembly). This harness proves the model EXTRACTION ACCURACY, which
  costs real API tokens and must stay operator-gated.

  Asserts:
    - Cache liveness: cache_creation_input_tokens > 0 OR cache_read_input_tokens > 0
      (confirms the large system prompt cleared the Sonnet cache threshold -- Pitfall 4)
    - Draft shape:    1 seeding_session / 5 groups / 11 children
    - Child names:    exactly 260522_SHI_1..3 + 260522_KOY_4..11
                      (child block names ONLY, NOT KOY parent attribution)
    - Provenance:     per-field provenance present on each group field

Cost / opt-in:
  One real Sonnet API call.  Each call uses max_tokens=16384 with a cached system
  prompt.  Set EXTRACTION_LIVE_FIRE=1 only when you intend to spend the tokens.

Usage:
  export ANTHROPIC_API_KEY=<live key>
  export EXTRACTION_LIVE_FIRE=1
  cd src/farm-agent && uv run pytest -q tests/test_extraction_live_fire.py -m live_fire -v

Reference:
  .planning/phases/60-extraction-pipeline/60-04-PLAN.md
  .planning/phases/60-extraction-pipeline/60-03-SUMMARY.md (hermetic fixture replay)
  tests/test_gate_live_fire.py (the Phase-59 live-fire this mirrors)
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import pytest

from farm_agent.extraction.extractor import create_extractor
from farm_agent.extraction.multimodal import read_image_to_base64

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "extraction" / "seeding-session-may22"
)

# Expected child block names -- assert child names, NOT KOY parent attribution
_EXPECTED_CHILD_NAMES = [
    "260522_SHI_1",
    "260522_SHI_2",
    "260522_SHI_3",
    "260522_KOY_4",
    "260522_KOY_5",
    "260522_KOY_6",
    "260522_KOY_7",
    "260522_KOY_8",
    "260522_KOY_9",
    "260522_KOY_10",
    "260522_KOY_11",
]

# ---------------------------------------------------------------------------
# Live-fire test
# ---------------------------------------------------------------------------


@pytest.mark.live_fire
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("EXTRACTION_LIVE_FIRE"),
    reason="live-fire: requires ANTHROPIC_API_KEY + EXTRACTION_LIVE_FIRE=1",
)
@pytest.mark.asyncio
async def test_real_sonnet_may22_extraction() -> None:
    """Real-Sonnet May-22 fixture extraction accuracy + prompt-cache liveness.

    Asserts:
      - Image read: read_image_to_base64 on paper-log.jpg succeeds (confirms Pillow path)
      - Cache liveness: first call has cache_creation_input_tokens > 0
                        (or cache_read_input_tokens > 0 on a warm cache)
      - Draft shape:    ok=True, type=seeding_session, 5 groups, 11 children
      - Child names:    exactly 260522_SHI_1..3 + 260522_KOY_4..11
      - Provenance:     per-field provenance present on each group field
    """
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)

    try:
        # -----------------------------------------------------------------------
        # Load fixture text files
        # -----------------------------------------------------------------------
        transcript = (_FIXTURE_DIR / "transcript.txt").read_text(encoding="utf-8")
        text_followup = (_FIXTURE_DIR / "text-followup.txt").read_text(encoding="utf-8")

        # -----------------------------------------------------------------------
        # Resolve paper-log.jpg via read_image_to_base64 (confirms real Pillow downscale path)
        # -----------------------------------------------------------------------
        image_result = await read_image_to_base64(str(_FIXTURE_DIR / "paper-log.jpg"))
        assert image_result.get("ok") is True, (
            f"read_image_to_base64 failed on paper-log.jpg: {image_result.get('reason')} -- "
            "Pillow downscale path broken"
        )

        # -----------------------------------------------------------------------
        # Build captures list (one capture with text, transcript, and image)
        # -----------------------------------------------------------------------
        captures = [
            {
                "text": text_followup,
                "transcript": transcript,
                "images": [image_result],
            }
        ]

        # -----------------------------------------------------------------------
        # Run the real extractor
        # -----------------------------------------------------------------------
        extractor = create_extractor(client)
        result = await extractor["extract"](captures)

        # -----------------------------------------------------------------------
        # Cache liveness check (Pitfall 4 -- large system prompt must clear threshold)
        # -----------------------------------------------------------------------
        usage = result.get("usage")
        assert usage is not None, (
            "Extractor result missing 'usage' field -- "
            "cannot verify prompt-cache liveness"
        )
        cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
        cache_read = usage.get("cache_read_input_tokens", 0) or 0
        assert cache_creation > 0 or cache_read > 0, (
            f"Prompt cache NOT active "
            f"(cache_creation_input_tokens={cache_creation}, "
            f"cache_read_input_tokens={cache_read}). "
            "The system prompt may have been truncated below the Sonnet cache threshold. "
            "Check farm_agent/extraction/prompts.py CACHEABLE_SYSTEM_BLOCKS."
        )

        # -----------------------------------------------------------------------
        # Draft shape assertions
        # -----------------------------------------------------------------------
        assert result.get("ok") is True, (
            f"Extractor returned ok=False: {result.get('reason')} -- "
            "real model-accuracy signal; do NOT relax the assertion; record as a finding."
        )

        drafts = result.get("drafts") or []
        assert len(drafts) >= 1, "No drafts returned"
        seeding_session = drafts[0]["draft"]

        assert seeding_session["type"] == "seeding_session", (
            f"Expected type=seeding_session, got {seeding_session['type']!r}"
        )
        assert len(seeding_session["groups"]) == 5, (
            f"Expected 5 groups, got {len(seeding_session['groups'])} -- "
            "real model-accuracy signal; do NOT relax the assertion; record mismatched count as a finding."
        )

        # -----------------------------------------------------------------------
        # Child block name assertions (NOT KOY parent attribution)
        # -----------------------------------------------------------------------
        all_child_names = []
        for group in seeding_session["groups"]:
            names = group["child_block_names"]["value"]
            all_child_names.extend(names)

        assert len(all_child_names) == 11, (
            f"Expected 11 children, got {len(all_child_names)}: {all_child_names} -- "
            "real model-accuracy signal; do NOT relax the assertion; record mismatch as a finding."
        )

        if all_child_names != _EXPECTED_CHILD_NAMES:
            pytest.fail(
                f"Child block names mismatch.\n"
                f"Expected: {_EXPECTED_CHILD_NAMES}\n"
                f"Got:      {all_child_names}\n"
                "Real model-accuracy signal -- do NOT relax the assertion; "
                "record mismatched names as a finding."
            )

        # -----------------------------------------------------------------------
        # Per-field provenance assertions
        # -----------------------------------------------------------------------
        for i, group in enumerate(seeding_session["groups"]):
            assert "value" in group["parent"], f"Group {i}: parent.value missing"
            assert "confidence" in group["parent"], f"Group {i}: parent.confidence missing"
            assert "sources" in group["parent"], f"Group {i}: parent.sources missing"
            assert "value" in group["species"], f"Group {i}: species.value missing"
            assert "value" in group["qty"], f"Group {i}: qty.value missing"
            assert "value" in group["child_block_names"], (
                f"Group {i}: child_block_names.value missing"
            )

        # -----------------------------------------------------------------------
        # Report (visible in pytest -v output)
        # -----------------------------------------------------------------------
        print(
            f"\n[live-fire] Cache liveness: "
            f"cache_creation={cache_creation}  cache_read={cache_read}"
            f"\n[live-fire] Draft shape: "
            f"type={seeding_session['type']}  groups={len(seeding_session['groups'])}  "
            f"children={len(all_child_names)}"
            f"\n[live-fire] Child names: {all_child_names}"
            f"\n[live-fire] Usage: {usage}"
        )

    finally:
        await client.close()
