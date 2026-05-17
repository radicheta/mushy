# SEED-010: Foray -- OSS extraction of the Signal-multimodal-farmOS layer

**Status:** seeded 2026-05-17; trigger condition will fire after v1.9 closes
**Trigger:** v1.9 (Harvest Loop Closure) shipped AND `tenant_id` constraint has
held through at least one full milestone cycle
**Scope:** Large (3-5 weeks; new repo, README/docs, soft launch, public launch)
**Working name:** Foray (namestorm before v2.0 ship)

## Frame

Strategic Option α was locked 2026-05-17 (see
`.planning/notes/2026-05-17-oss-foray-decision.md`). From v1.8 forward every PR
is designed to be extractable. This seed captures the *extraction* event when
it eventually fires.

## What gets extracted

A thin slice of `mushy/`:

- `src/agents/alerter/` (signal-cli + extractor + state machine + commit path)
- The shared schema migrations for `signal_draft`, `signal_outbound`, etc.
- The farmOS write-path client
- Tenant config primitive (`tenants/<id>/`)

What stays in `mushy/`:

- `fc_core` (PID, mode primitive, scheduler)
- MissionControl + OpenMCT bridge + Timescale chamber-telemetry stack
- Camera / time-lapse / vision
- VPS hub + uptime-kuma + heartbeat receiver

## v0.1 release shape

- Apache 2.0
- `docker compose up -d` one-shot
- Bring your own: farmOS, Anthropic key, Signal-cli registration
- `tenants/example/` directory; clone for tenant #2
- README with 60-second demo gif/video
- LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, ISSUE_TEMPLATE
- Scope: inoc + observation events only (no harvest in v0.1 -- pull from v1.9
  in v0.2)

## Launch plan (post-extraction)

1. **Soft:** One friendly farm runs it end-to-end (not Mossrock). All friction
   becomes GitHub issues.
2. **Medium:** Post to FarmOS Discourse, r/MushroomGrowers, Shroomery commercial
   cultivation, NAMA mailing list.
3. **Big:** HN/Lobste.rs launch post: "I built a Signal bot for my mushroom
   farm. Here's the code, here's what I learned about LLMs in production."

## Open questions (resolved at v2.0 plan-phase)

1. Signal-only or WhatsApp Business API too?
2. Opinionated farmOS schema vs adaptive?
3. Pure OSS or OSS + hosted-tier convenience offering?
4. Final name + brand

## Why "seed" not "phase yet"

Because v1.8 + v1.9 need to ship under the tenant-aware constraint first --
the extraction is much cheaper after they do, and possibly premature before.
Don't promote until v1.9 verification passes AND the codebase passes a
"could I clone this and run it without Mossrock secrets?" smell test.

## Cross-refs

- `.planning/notes/2026-05-17-oss-foray-decision.md`
- `.planning/notes/2026-05-13-v1.8-candidates.md`
- SEED-006 (farmer freeform stream -> farmOS) -- Foray is half the SEED-006
  vision, productized
