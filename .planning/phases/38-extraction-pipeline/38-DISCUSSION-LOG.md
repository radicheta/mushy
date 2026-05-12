# Phase 38: Extraction Pipeline — Discussion Log

**Date:** 2026-05-11

## Pre-loaded context (not re-asked)

- **Schema LOCKED** in `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md` — C1–C5 (farm-wide), B1–B7 (mushroom-specifics), P1–P5 (pilot). Phase 38 is the named P3 driver for v1.6/v1.7.
- **LLM**: `claude-sonnet-4-6` already wired in `src/agents/alerter/src/llm-client.js` (Phase 25).
- **Whisper**: pipeline already wired (`transcribe-client.js`, elder-plops GPU ~3GB reserved).
- **Eval corpus**: mushdatadump v1.6 — 73 JPEGs + CSV ground truth at `/mnt/mossrock/shared/mushdatadump/`.
- **NORTH-STAR**: no farmer bookkeeping tax (memory `feedback_no_farmer_bookkeeping_tax`).
- **Style constraints**: no em-dashes in farmer-facing artifacts; rounded numbers via `fmtNum()` (memories).
- **Phase 38 emits drafts only.** Phase 39 confirms; Phase 40 writes farmOS.

## Gray areas user selected (all four offered)

1. Multimodal fusion window
2. Draft storage + state model
3. Confidence + ask-back UX
4. Eval harness scope

---

## Area 1: Multimodal fusion window

**Question:** How should the bot decide that multiple Signal messages belong to ONE draft event?

**Options:**
1. Time window (e.g. 3min idle gap)
2. Reply-thread (Signal quote/reply)
3. LLM judges continuity
4. Hybrid: time window + farmer override

**Selected:** LLM judges continuity (D-01)

**Claude's follow-up note:** Added planner guard D-01a — hard 30min idle-gap cap + force-start-new after Phase 39 confirm/discard, so a hung session can't silently swallow the next event.

---

## Area 2: Draft storage + state model

**Question:** Where should in-flight drafts live, and what's the storage shape?

**Options:**
1. Timescale (new schema)
2. SQLite in alerter container
3. In-memory map + WAL to disk
4. Reuse capture-db (Phase 25) ← **selected**

**Selected:** Reuse capture-db.js — new `signal_draft` table, FK array to `signal_capture.id` (D-02)

**Derived decisions:**
- D-02a — deterministic draft id from capture set (replay-safe)
- D-02b — status enum + ownership split across Phases 38/39/40
- D-02c — at most one in-flight draft per sender E.164

---

## Area 3: Confidence + ask-back UX (3 sub-questions, asked in one batch)

### 3a. Ask-back trigger

**Options:**
1. Per-field required-set
2. Per-field + LLM self-rated confidence ← **selected**
3. Overall draft confidence score

**Selected:** Per-field required-set AND LLM self-rated per-field confidence < 0.7 default (D-03, env-tunable as `EXTRACTION_CONFIDENCE_THRESHOLD`).

### 3b. Ask-back shape

**Options:**
1. Full draft preview with [?] markers
2. One targeted question per turn
3. Hybrid: preview + top question ← **selected**

**Selected:** Full draft preview with `[?]` markers + one-line top question (D-04). Farmer can answer either; LLM merges on next turn.

### 3c. Turn cap

**Options:**
1. Hard cap at 3 ask-back turns ← **selected**
2. Hard cap at 5 turns
3. No hard cap; idle-timeout only

**Selected:** Hard cap = 3 turns. On cap, status → `needs_review`, farmer-facing message "I can't lock this one — marked for manual review" (D-05).

---

## Area 4: Eval harness scope

### 4a. Eval scope

**Options:**
1. Offline harness + pass-bar gate ← **selected**
2. Smoke-only in Phase 38; full eval is its own phase
3. Offline harness + observational only
4. Defer entirely — evaluate live with farmer-in-loop

**Selected:** Offline harness + pass-bar gate (D-06). Phase 38 doesn't ship a SUMMARY.md until pass bar is met against mushdatadump v1.6.

### 4b. Pass bar

**Options:**
1. Strict: ≥95% schema-valid AND ≥85% required-field exact-match
2. Balanced: ≥90% schema-valid AND ≥75% required-field exact-match
3. Pragmatic: ≥90% schema-valid AND ≥75% required-field exact-match OR appropriate ask-back ← **selected**

**Selected:** Pragmatic bar (D-07). Ask-back counted as PASS when the bot correctly declined to guess on a genuinely-ambiguous field. Aligns with EXT-04 and the NORTH-STAR.

---

## Planner routing recommendation

Phase 38 is an AI system with eval gating + production-monitoring concerns. The right planner entry is likely `/gsd-ai-integration-phase 38` (produces AI-SPEC.md with Framework/Eval/Guardrails/Monitoring sections) rather than standard `/gsd-plan-phase 38`. Surface this to the user at next-step time.

## Deferred ideas (also captured in CONTEXT.md)

- Vision-derived context beyond QR (defer to Phase 24/v1.8)
- Cross-stream consistency tests → Phase 41
- Multi-farmer event collision (single-pilot v1.7 scope)
- Farmer-tunable thresholds via Signal command
- Auto-merge of `needs_review` drafts
- Lineage shorthand temporal reasoning
