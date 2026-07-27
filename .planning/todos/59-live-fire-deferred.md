# DEFERRED — Phase 59 real-Haiku live-fire (gate accuracy)

**Deferred:** 2026-06-24 (autonomous run)
**Status:** code + harness complete (4/5 verified, 195 tests green); real-model accuracy run pending

The deterministic CI gate proves rule-coverage + wiring + fail-open. The real-Haiku full-100
accuracy run (SC-1 0% false-positive incl. holdout, SC-2 >=95% recall, prompt-cache liveness)
is operator-run:
```
export ANTHROPIC_API_KEY=<live key> GATE_LIVE_FIRE=1
cd src/farm-agent && uv run pytest -q tests/test_gate_live_fire.py -v -m live_fire
```
Record token cost for the milestone ledger. If recall <95% or a labeled-negative slips through,
file the failing capture_ids as a classifier-accuracy finding — do NOT relax the threshold.
