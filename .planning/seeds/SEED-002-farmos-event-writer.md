---
id: SEED-002
status: dormant
planted: 2026-04-20
planted_during: v1.4 (Phase 25 SPEC)
trigger_when: Phase 25 has shipped and farmer has ≥2 weeks of captured content in the store
scope: Medium-to-Large
owners: mushy-side (LLM draft + write path), farmOS-side / Zoy (schema mapping + confirm UI if done inside farmOS)
---

# SEED-002: FarmOS event writer from captured Signal content

## Why This Matters

Phase 25 ("Bidirectional Signal — farmer↔robot capture channel; farmer-app surface: **Field Notes**", SPEC at
`.planning/phases/999.15-signal-cli-receive-side-for-linked-secondary-device/999.15-SPEC.md`)
explicitly defers farmOS event creation. That was the right scope call —
Phase 25 proves the receive + transcribe + LLM-reply pipeline works, and
buys a corpus of real field notes (inoculation sessions, harvest logs,
contamination observations) for the follow-up phase to train against.

The farmer's long-game ask (from the 2026-04-19 scoping conversation) is
*"fire messages at the robot — free form — have them process and log into
farmOS events."* That's what this seed becomes.

## When to Surface

**Trigger:** Phase 25 has shipped AND the capture store has ≥2 weeks of
real content from normal farm activity (inoc sessions, harvests, tray
flips). Without the corpus the LLM prompt design is speculation.

Also surface if/when:
- Zoy raises the farmOS schema question ("what event types should mushy
  write?") from the farmOS side.
- The farmer complains that captured notes "go into a black hole" —
  strong signal that the receipt-only reply is no longer sufficient.
- The farmer's inoculation session notes reveal a clear structured
  template that the LLM could reliably extract.

## Scope Estimate

**Medium-to-Large.** Splits across two codebases:

**Mushy side (this repo):**
- Extend the capture pipeline with an LLM draft step: transcript + image
  metadata + session tag → farmOS event draft (type, date, assets,
  quantities, notes).
- Confirm-before-write loop: robot replies "draft event — reply YES to
  commit, NO to discard, EDIT <text> to amend". Write only on YES.
- FarmOS API client (mushy already talks to farmOS for daily report via
  the Phase 13 agent — reuse that credential path if possible).
- Retry + idempotency (Signal replies can arrive twice; don't double-write).

**FarmOS side (Zoy):**
- Schema confirmation: which event types can the mushy_agent write
  (inoculation, harvest, observation, contamination)? Asset linkage
  (FC-1 location, substrate bags, trays)?
- Permissions for the mushy_agent user (scoped write access — no admin).
- Optional: a farmOS-side review queue UI for drafts-pending-confirm if
  the Signal confirm loop proves too brittle.

## Pre-gates

- Phase 25 shipped and producing captures reliably for ≥2 weeks.
- FarmOS people directory seed (`project_farmos_people_directory_seed.md`)
  resolved OR explicitly punted again — determines whether event
  authorship attributes to a farmOS person record or to a generic
  mushy_agent user.
- Phase 19 status clarified (FarmOS admin actions was deferred to v1.5;
  this phase would pre-empt or complement it).

## Breadcrumbs

Code and decisions that inform this phase:

- `src/agents/farmos-daily-report/` — existing farmOS API client pattern
  (read-only today; this phase adds write).
- Phase 25 capture store schema — once Phase 25 lands, the query path for
  "all captures since last draft" is the input to this phase.
- Memory: `project_farmos_people_directory_seed.md` — contact/authorship
  source of truth.
- Memory: `project_farmos_scope.md` — farm-wide instance, farm team
  managing; schema changes require Zoy/farm-team collaboration.
- Backlog 19 (FarmOS admin actions) — deferred to v1.5; may merge into
  this phase's admin prereqs.

## Open questions for Zoy (farmOS side)

1. Is there a preferred farmOS event type taxonomy for mushroom ops
   (inoculation / flush / harvest / contamination / environmental
   intervention), or should mushy propose one?
2. Where should draft-pending-confirm events live — in farmOS as drafts
   with a status flag, or in mushy's capture store until confirmed?
3. Asset model for FC-1 substrate bags and trays — does farmOS already
   track individual bags, or is "chamber + batch date" sufficient?
4. Authorship: mushy_agent as a single farmOS user, or per-farmer
   identity via the people directory?

## Notes

The capture channel (Phase 25) is deliberately a one-way street during
v1.4: farmer → robot → store + reply. This seed is what closes the loop
into the farm's canonical record. Don't promote it until Phase 25 has
produced enough real content to design against; designing the schema
before the data exists is a recipe for a mapping the farmer won't use.
