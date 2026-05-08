---
id: SEED-006
status: dormant
planted: 2026-05-08
planted_during: v1.5 (Phase 31 executing)
trigger_when: Next major milestone (v1.6+) — agentic / farmer-UX themed milestone
scope: Large
---

# SEED-006: Farmer freeform stream → automatic farmOS bookkeeping

## Why This Matters

The end-state UX the farmer keeps describing: walk the farm, take pictures,
send text and audio messages to mushy-bot as the work happens. An agent on
the other end parses the freeform multimodal stream and does **all** data
entry and book-keeping in farmOS automatically — no forms, no admin time,
no end-of-day catch-up.

Two wins at once:

1. **Eliminate data-entry friction** — the farmer just lives the work; the
   agent does the bookkeeping. Today every farmOS log is a tax the farmer
   pays after the real work is done, so most of it doesn't get paid.
2. **Capture data that's currently lost** — the informal observations
   ("third tray on rack 2 looks slow", "humidity feels off in the back
   chamber", "saw a green spot on bag #14") never make it into farmOS at
   all today. This stream becomes structured records, queryable history,
   and training data for future automation.

This is the long arc behind Phase 25 (bidirectional Signal) and SEED-002
(farmOS event writer). Phase 25 proved the capture channel works. SEED-002
narrows in on the LLM-drafted event writer for Signal text. **SEED-006 is
the bigger UX vision both feed into**: a single freeform stream — text,
audio, photos — becomes the farmer's entire farmOS interface.

## When to Surface

**Trigger:** Next major milestone (v1.6+), especially when scope touches:

- Agentic or assistant-themed work
- farmOS write integration / automated bookkeeping
- Multimodal Signal ingest (photos + audio + text routed together)
- Computer vision on farmer-captured photos (contamination, growth stage,
  yield estimation)

This seed should be presented during `/gsd-new-milestone` when any of
those conditions match.

## Scope Estimate

**Large** — full milestone. Component pieces:

- Multimodal intake: text (Phase 25 ✓), audio transcription (Phase 25 ✓
  Whisper path), photo ingest + storage, EXIF/GPS context
- Event extraction agent: freeform → structured farmOS event candidates
  (log type, asset, location, quantity, timestamp, confidence)
- farmOS write path: SEED-002 / Phase 19 deferred admin actions
- Confirmation UX: low-friction "yep / fix this" loop so the farmer can
  correct the agent without it becoming a form in disguise
- Vision pipeline: contamination flags, growth-stage tagging, harvest
  count from photos (ties into v1.4 CV work)
- Identity/asset resolution: "the third tray on rack 2" → farmOS asset ID

Likely sequenced as 4–6 phases within a single agentic-UX milestone.

## Breadcrumbs

Related code, decisions, and seeds in the current project:

- `.planning/seeds/SEED-002-farmos-event-writer.md` — narrower precursor
  (Signal text → farmOS events via LLM)
- `.planning/seeds/SEED-003-farmer-app-mission-control-section.md` —
  farmer-app surface where confirmations could live
- `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/`
  — capture channel (text + audio + Whisper) shipped 2026-04-28
- `.planning/phases/26-*` — SHT30 happy path; relevant only as the lab
  side of the same Signal pipeline
- `farmos_agent` (project memory: v1.2 shipped with farmos_agent as
  autonomous-agent seed) — earliest framing of agentic farmOS write
- v1.4 CV milestone (project memory `project_v14_cv_milestone_planned`)
  — supplies the vision-side capabilities this seed depends on
- Project memory `project_farmos_people_directory_seed` — farmOS people
  dir as identity source for "who sent what"
- Project memory `project_phase18_22_farmos_proxy_architecture` — the
  farmOS-proxy pattern this writer would extend
- `project_co2_unexpected_win` — bias toward CO2 / sensor-aware framing
  when the agent suggests events

## Notes

- Don't start until SEED-002 has shipped and produced ≥1 month of
  text-only event-writer accuracy data — that data tells you whether the
  agentic loop is grounded enough to expand to multimodal.
- Confirmation UX is the make-or-break: if the farmer has to correct the
  agent more than ~10% of the time, the friction-reduction promise
  collapses and we've just built a fancier form.
- Photo-as-input changes the privacy/storage shape vs. text-only — needs
  a retention story before launch.
- The farmer's role here is *operator* not *grower* (per
  `user_operator_and_grower` memory) — the agent is replacing the
  bookkeeping tax, not the growing decisions.
