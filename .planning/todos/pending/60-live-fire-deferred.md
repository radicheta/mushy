# DEFERRED — Phase 60 real-Sonnet live-fire (extraction accuracy)

**Deferred:** 2026-06-26 (autonomous run)
**Status:** code + harness complete (4/4 hermetic verified, 254 tests green); real-model run pending

```
export ANTHROPIC_API_KEY=<key> EXTRACTION_LIVE_FIRE=1
cd src/farm-agent && uv run pytest -q tests/test_extraction_live_fire.py -m live_fire -v
```
Expect: seeding_session / 5 groups / 11 children / 260522_SHI_1..3 + KOY_4..11 (assert CHILD names, not KOY parent attribution) / per-field provenance / cache_creation_input_tokens > 0. Record token+cache usage for the milestone ledger; file any name mismatch as a finding.
