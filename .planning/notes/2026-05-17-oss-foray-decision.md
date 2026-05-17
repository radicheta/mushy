# OSS-from-now-on -- "Foray" extraction strategic decision

**Date:** 2026-05-17
**Status:** locked (Don Santiago, 2026-05-17 session)
**Frame:** Option α from the "farm as product" exploration

---

## The decision

The Signal-multimodal-farmOS layer of this codebase will be open-sourced as a
standalone project (working name: **Foray**, Apache 2.0). Mossrock-the-farm
remains the dogfood instance; Foray-the-bot is the artifact other farms install.

**From 2026-05-17 forward, every PR is designed as if a non-Mossrock farm could
run it.** Specifically:

- New schema tables ship with `tenant_id` from day one
- New configuration is keyed by tenant, not global
- Mossrock-specific values (farmer phone map, strain codes, farmOS endpoint,
  Anthropic key) move into a `tenants/mossrock/` config tree
- Documentation explains *what the bot does*, not *what Mossrock does*

## Why this over Option β (Mossrock-first, extract later)

- v1.8 is already about durable `signal_outbound`. Adding `tenant_id` to that
  table on day one is ~zero cost; ALTERing it in 9 months on Mossrock-prod
  Timescale would be a real ops event.
- The "extract later" milestone almost never happens in practice. Frame β
  collapses to "build Mossrock forever," which is fine if you want that and
  catastrophic if you wanted the karma deposit.
- The constraint cost is lowest at the seam between v1.7 (done) and v1.8
  (unstarted). Six months from now the seam is gone.

## What does NOT get open-sourced (at least not in v0.1)

- `fc_core` (PID + mode primitive + scheduler) -- Mossrock-the-chamber, not
  Mossrock-the-bot
- The MissionControl / OpenMCT bridge + Timescale stack -- chamber-specific
- The camera / time-lapse stack -- chamber-specific
- VPS hub + uptime-kuma + heartbeat receiver -- ops infra, not product

Foray v0.1 is a thin slice: alerter + signal-cli + extractor + farmOS writer +
the state machine that ties them. Everything else stays in `mushy/` private.

## v1.8 implications (locked previously, now re-shaped)

The 2026-05-17 findings discussion already locked v1.8 as event-gate + durable
`signal_outbound` bundle. Under Option α this becomes:

- `signal_outbound` table: `tenant_id` column, indexed
- Event-gate config: per-tenant, not env-global
- NORTH-STAR ack fix (deferred but planned): operates per-tenant
- 100-capture hand-classification smoke (Plan-01): tagged with tenant=mossrock
  so the corpus is reusable when a second tenant exists

Cost vs the pre-α v1.8 plan: probably ~10-15% more scope. Cheap.

## Next two-three milestone arc, re-framed

- **v1.8 -- Event-gate + signal_outbound (tenant-aware).** Same locked scope,
  +tenant_id constraint. ~2-3 weeks.
- **v1.9 -- Harvest Loop Closure (tenant-aware).** Candidate A from
  2026-05-13-v1.8-candidates.md. Harvest extraction prompts + write path,
  designed once for any tenant. ~3-5 weeks. Pairs with Phase 42 calendar.
- **v2.0 -- Foray Extraction.** Carve `foray/` repo out of `mushy/`. Strip
  Mossrock-isms (they should already be tenant-keyed by now). Apache 2.0,
  README + demo video + docker compose. Soft launch to one friendly farm,
  then FarmOS Discourse + r/MushroomGrowers, then HN/Lobste.rs. ~4-6 weeks.

This makes v2.0 a *clean extraction*, not a *fork-and-pray*. Whether v2.0
ships before or after multi-chamber (old Candidate D) is a question for after
v1.9 closes.

## Open questions deferred to v2.0 planning

1. Signal-only or Signal-+-WhatsApp Business API? (Signal market share is small
   outside privacy-aligned crowds; commercially, WhatsApp may matter)
2. Opinionated farmOS schema (ship `farmos_asset_link` + our taxonomy) vs
   adaptive (accommodate whatever schema the tenant already has)
3. Hosted-tier convenience offering or pure-OSS-only?
4. Final name -- "Foray" is the working pick, namestorm before v2.0 ship

## Cross-refs

- `.planning/notes/2026-05-13-v1.8-candidates.md` (Candidate A=harvest, D=multi-chamber)
- `.planning/notes/2026-05-17-is-this-an-event-gate.md` (finding 7)
- `.planning/notes/2026-05-17-llm-outbound-amnesia.md` (finding 1b)
- Memory: `[[2026-05-17-findings-discussion-decisions]]` (prior v1.8 lock)
- Memory: `[[2026-05-17-oss-foray-alpha-lock]]` (this decision)
