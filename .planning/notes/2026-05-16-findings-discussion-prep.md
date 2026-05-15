---
date: 2026-05-16
session_type: discussion-prep
prev_session: 2026-05-15 evening (7 commits, 5 farmer comms, Phase 40 happy-path UAT closed via bridge)
discussion_focus: the 8 findings collected during 2026-05-15 + the live-incident lessons
status: breadcrumbs-only -- pick up by reading this + companion notes; no code state to restore
---

# Next-session opener: discuss the 8 findings

This is the breadcrumb doc to lead the next session. The 2026-05-15 session shipped a lot but explicitly parked decisions on 8 findings for Don Santiago discussion. Pick this doc up first; everything else is a reference.

## Quick session-state restore

- Working tree: clean as of commit `a1705ac`.
- Test suite: 626/626 PASS in alerter.
- Alerter image: rebuilt + healthy with the 2026-05-15 prompt fixes.
- v1.7 milestone status: `gaps_found`, gap-list shrunk from 3 to 2 between 2026-05-13 audit and 2026-05-15 re-audit. Only blockers left are Phase 42 calendar (4-8wk biological) and a few small operator items.
- Pending farmer threads: Vikki Rambo draft `b8a1e586` still in `commit_failed` (intentionally not bridged -- it's the live evidence); Santi UX-feedback draft `6934760c` in `awaiting_farmer` (phantom from chit-chat -- finding #7).

## Companion docs (read in order)

1. **[[2026-05-15-rambo-th-window-unscripted-run.md]]** -- Vikki's animal-broke-the-greenhouse-window event; findings 1a, 2, 3.
2. **[[2026-05-15-lion-mane-bridged-uat.md]]** -- Santi's lion's mane move bridged manually; findings 4, 5.
3. **[[36-04-attestation.md]]** -- T+24h Plan 36-04 closeout; surfaced findings 1b, 1c live evidence.
4. **[[deferred-items.md]]** (Phase 37) -- formal filings for 1b, 1c (resolved), OBJ-char (resolved).
5. **[[v1.7-MILESTONE-AUDIT.md]]** -- re-audit reflecting Phase 40 prod cutover.

## The 8 findings, summarized for fast skim

| # | Surface | Severity | One-line | Status |
|---|---|---|---|---|
| 1a | Phase 37 LLM convo | low | Conflates random words with block names ("Rambo" -> "is this a block?") | parked |
| 1b | Phase 37 LLM convo | medium | LLM has no memory of its own outbound -- asked Santi to clarify "Ok" it had requested itself | parked; fix sketches a/b/c filed |
| 1c | Phase 37 LLM convo | -- | Recurrent em-dash leak | **RESOLVED 2026-05-15 (commit 3c7c723)** -- live-validated by Santi UX-feedback reply at 23:50; first clean style reply |
| 1d | Phase 38 preview | medium | "asset_ref" is jargon; farmer pushed back: "speak in farmer to me" | parked; 2 live data points (Vikki + Santi) |
| 2 | Phase 40 commit-router | medium | No fallback for unregistered observation/activity targets (TH greenhouse; missing LIMA blocks) | parked; options A/B/C/D filed |
| 3 | Phase 40 commit-watchdog | **HIGH (NORTH-STAR)** | commit_failed silent -- farmer confirmed YES, system dropped, no reply | parked; 2 live data points (Vikki + Santi). **Cheapest urgent fix on the list.** |
| 4 | Phase 38 <-> Phase 40 | medium | Schema mismatch for activity log_type: qr_codes vs asset_ref; activity_subtype vs name; timestamp unix vs event_timestamp ISO | parked; fix sketches a/b/c filed |
| 5 | Phase 40 + paper-log backfill | medium | Strain blocks missing in prod-farmOS (LIMA/MAI/CAS/etc) -- every activity referencing them fails | parked; v1.8 scope |
| 6 | Phase 40 ack template | low | farmOS asset/log references in farmer-facing acks are not clickable links | **NEW** from Santi UX feedback 23:50; trivial fix |
| 7 | Phase 38 + 37 capture-pipeline | low-medium | Phase 38 extractor runs on every capture incl. chit-chat -> phantom drafts that expire silently | **NEW** from Santi UX-feedback chit-chat creating draft `6934760c` |

## Recommended discussion structure

1. **NORTH-STAR fix (finding 3) first.** Smallest blast radius, biggest farmer-trust dividend. Single small reply path in commit-watchdog; system prompt update; can ship same-week. The other findings can wait; this one is exposed every time a farmer YES-confirms a draft that hits the commit-failed path.
2. **Schema mismatch (finding 4) next.** Code-quality bug; will keep firing until fixed. Recommendation in the bridged-uat note: add a `commit-router` normalizer pre-step + integration tests per log_type.
3. **Jargon translation (finding 1d).** Same module (preview-builder.js) that already strips em-dashes. Bundle as a single farmer-vocabulary PR.
4. **Phase 40 commit-router target fallback (finding 2).** Decision point: option A (farm-level fallback), B (register non-fungi assets), C (farmer-facing nudge), D (defer scope). The 2026-05-15 sessions revealed this hits two distinct surfaces: non-fungi structures (TH greenhouse, Vikki) AND missing strain blocks (LIMA, Santi). Same root, two failure modes.
5. **LLM outbound amnesia (finding 1b).** Bigger scope -- ring buffer vs DB persist vs hybrid. Decision-time, then size.
6. **Clickable farmOS links (finding 6).** Trivial; bundle with whatever ack-template work the NORTH-STAR fix produces.
7. **Phantom drafts from chit-chat (finding 7).** Probably needs a Phase 38 "is-this-an-event" gate. Lowest priority -- they expire harmlessly today, just clutter the queue.
8. **Strain coverage gap (finding 5).** Sizing question more than design question. Backfill sweep vs create-on-demand. May fall out of finding 2.

## Live evidence to bring to the discussion

| Finding | Evidence |
|---|---|
| 1c FIXED | Santi capture 01KRQ0RTNV3CE5YV6G299PVKN1 23:50, LLM reply: "Noted, and fair point about the farmOS links not being clickable. That is a Signal limitation on my end, nothing I can fix right now..." -- zero em-dashes, plain prose, honest. First clean reply since deploy. |
| 1d | Santi capture 23:31:54 EDIT: "I dont understand what asset-ref means. Please speak in farmer to me." Verbatim verbal pushback. |
| 3 | Vikki Rambo draft b8a1e586 (intentionally NOT bridged), Santi lion-mane draft 1fb28e70 (bridged to PASS), both went 4+ min silent post-YES until operator intervention. |
| 4 | Lion-mane bridge required reshaping qr_codes / activity_subtype / timestamp; full diff in `2026-05-15-lion-mane-bridged-uat.md` Finding 4 section. |
| 5 | Probe of prod-farmOS 2026-05-15 23:46: only SHI/DT/WIN/KOY blocks exist; LIMA/MAI/etc absent. Created 260415_LIMA_1 by hand. |
| 6 | Same Santi capture as 1c evidence -- the feedback IS the finding. |
| 7 | Draft 6934760c in awaiting_farmer with notes "Farmer commented on UX: farmOS asset references are not clickable" -- pure conversational chit-chat mistakenly drafted as an observation log. |

## Autonomous overnight research

Two research agents kicked off as background tasks at session close. Outputs land in `.planning/notes/2026-05-16-*.md` and should be in tree by morning:

- **Agent A: Phase 38 <-> Phase 40 schema audit** (finding 4 prep). Read every commit-*.js, every extraction prompt + tool schema, every fixture; produce a per-log_type comparison matrix. Output: `2026-05-16-schema-audit.md`.
- **Agent B: farmOS no-target patterns + strain coverage** (findings 2 + 5 prep). farmOS API docs + alerter farmos/*.js + signal_capture history. What bundles support null asset relationship? What's the canonical farm-level observation pattern? Which strain codes appear in farmer history vs prod-farmOS asset set? Output: `2026-05-16-farmos-no-target-and-strain-coverage.md`.

Both agents are read-only (filesystem + databases + web). Neither touches code, deploys, or sends Signal messages.

## Loose ends NOT addressed in next-session discussion

- Vikki SC#2 retroactive close (Plan 36-04). Opportunistic; do it next time she's in a quiet window.
- Phase 42 SHI pilot kickoff. Calendar-bound; long pole is 3-4wk colonize. Should start in parallel with the discussion, not after.

EOF -- read companion docs, then dive in.
