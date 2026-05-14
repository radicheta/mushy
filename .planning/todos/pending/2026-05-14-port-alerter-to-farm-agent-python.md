---
created: 1778774968
title: Port alerter -> farm-agent (JS -> Python)
area: planning
files:
  - src/agents/alerter/
  - docker-compose.yml
  - docker-compose.override.yml
---

## Problem

The alerter service has outgrown its v1.0 "Signal push on out-of-band" shape. Post-Phase 25/38/39/40 it now does:

- Bidirectional Signal capture (Phase 25)
- Multimodal LLM extraction (Sonnet 4.6 + Whisper, Phase 38)
- Farmer-confirmation loop (Phase 39)
- farmOS write-path with commit-* modules (Phase 40)
- Routing + capture state machine

It is the agent-shaped half of the system. The name "alerter" is now a misnomer; "farm-agent" reflects what it actually is.

JS is a historical accident: when the service was a 50-line WS-subscriber sibling of the bridge, sharing the bridge's stack made sense. That premise is dead. Python's LLM/multimodal ecosystem (anthropic SDK first-class support, audio libs, Pydantic for schema validation, real eval tooling like inspect-ai / promptfoo / langfuse) is materially richer than Node's for what this service has become. Continuing in JS compounds the gap on every new AI-facing phase.

## Solution

Big-ticket migration. Treat as its own milestone (v1.9 or v2.0), NOT v1.8.

Scope:

- Rename container + image + compose service + repo path (`src/agents/alerter/` -> `src/agents/farm-agent/`)
- Port: WS subscriber, signal-cli HTTP client, extractor (LLM + Whisper), confirm/preview loop, commit modules (`commits/commit-seeding`, `commit-harvest`, `commit-router`, `commit-activity`, `commit-input`, `commit-observation`), audit logger, commit-watchdog, farmOS client, capture/state, dedupe, snooze, watchdog
- Migrate Jest test suite (~130+ tests across extraction/confirm/farmos/integration) to pytest
- Re-do Phase 38 eval harness in Python (inspect-ai or similar)
- Pydantic schemas for B1-B7 instead of ad-hoc JSON validation
- Cutover plan: parallel-run period (both stacks consume from same WS, only one writes to farmOS via env flag), then flip, then archive JS code in a sibling directory per `feedback_keep_paper_trail_of_intermediates`

Sequencing gates (all must be true before starting):

1. Phase 40 ship-gate GREEN (Option A hybrid smoke-validated live against dev-farmOS with seeded vocabs)
2. Phase 42 SHI pilot stable in production for at least 2 weeks
3. v1.7 milestone closed
4. No active phase mid-stabilization in the alerter

**Why not now:** Phase 40 commit-* modules just landed (2026-05-14 Option A hybrid). Porting now would relitigate the work. v1.7 is mid-validation arc; v1.8 candidates exist that build on the current JS stack. Disruption budget is wrong.

Cross-refs:

- `feedback_keep_paper_trail_of_intermediates` — preserve old JS during cutover; don't overwrite-in-place
- `.planning/notes/2026-05-13-v1.8-candidates.md` — confirms v1.8 is busy
- Historical context for "why JS originally" answered in 2026-05-14 chat
