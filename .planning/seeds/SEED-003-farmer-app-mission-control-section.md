---
id: SEED-003
status: dormant
planted: 2026-04-20
planted_during: v1.4 (Phase 25 scoping conversation)
trigger_when: farmer app (Drupal/farmOS) sectioning work starts on Zoy-side OR farmer asks for "see more details" / engineer-view access from the app
scope: Small
owners: farmOS-side / Zoy (primary — nav + iframe/link); mushy-side (OpenMCT deep-link targets, optional farmOS-chrome-friendly view)
---

# SEED-003: Farmer app "Mission Control" section — forward/iframe to OpenMCT

## Why This Matters

The MC widgets (system health lights, camera feed, humidity charts, actuator
state) are cool and the farmer wants access to them from the farmer app — but
rebuilding them in Drupal is a DRY tax and rebuilding them with farmer polish
is the wrong product move: MC is the *operator/engineer* surface, the farmer
app is the *grower* surface. They serve different audiences.

Cleaner product story: two tiers with a clear door between them.

- **Farmer app (Drupal/farmOS):** grower-flavored — Signal capture (Phase 25),
  daily summary, "am I OK" status, captured field notes.
- **"Mission Control →" section within the farmer app:** forwards to OpenMCT.
  The advanced/engineer view, embedded as an iframe or deep-linked, not
  reimplemented.

This keeps OpenMCT as the single source of truth for the engineering view,
lets the farmer app stay farmer-focused, and eliminates the widget-sync tax
that a shared widget library would incur.

## When to Surface

**Trigger:** any of the following:
- Zoy starts sectioning/IA work on the farmer app.
- Farmer explicitly asks for "more detail" / engineer-view access from the app.
- Phase 25 ships and it's time to give the farmer app a proper nav (Capture,
  Daily Summary, Mission Control are the three obvious sections).

## Scope Estimate

**Small.** Most of the work is on the farmOS/Drupal side — add a nav item,
drop an iframe or external-link card. Mushy-side work is at most:

- Confirm OpenMCT accepts deep links to specific views (browse paths).
- Allow the farmOS origin in OpenMCT's `X-Frame-Options` / CSP
  (`frame-ancestors`) if iframing — otherwise new-tab link is trivially free.
- Optional: a "farmOS-chrome-friendly" landing URL that hides OpenMCT's
  top-bar for a cleaner embed. Low priority.

## Design decisions worth locking during discuss-phase

1. **Iframe vs. external link.** Iframe keeps the user inside the farmer app
   shell; external link is dirt-simple but feels disjointed. Recommended:
   iframe if `X-Frame-Options` / CSP can be aligned, external link otherwise.
2. **Which OpenMCT views are the "farmer-safe" entry points?** Not all MC
   views belong as the default landing — pick 1–2 (chamber overview,
   historical humidity) and deep-link those, letting the farmer navigate
   deeper if curious.
3. **Access control boundary.** OpenMCT stays Tailscale/LAN-only — no
   internet-facing auth layer added for this phase. Farmer is told upfront:
   "Mission Control only works when you're on the farm network (Tailscale)."
   If the farmer app itself is internet-facing, that creates a UX cliff
   where the MC section breaks off-farm — worth a friendly fallback state
   ("You're off-farm. Mission Control needs a farm network connection.")
   rather than a broken iframe.
4. **Mobile.** OpenMCT is desktop-first. Iframing it on a phone may be
   ugly. Acceptable if the farmer uses MC rarely from phone; revisit if
   it becomes a complaint.

## Pre-gates

- Farmer app has real sectioning / nav (beyond a single daily-summary page).
  Until there's a nav to hang this on, premature.
- Tailscale coverage for the farmer's phone is confirmed reliable — the
  "net-restricted" access model only works if the farmer is actually on
  Tailscale from the field.

## Breadcrumbs

- OpenMCT served from `elder-plops` on port 8080 (`docker-compose.yml`
  openmct service).
- Bridge's `GET /farmer/summary` (`src/mission-control/bridge/src/index.js:320`)
  already serves the simplified farmer-flavored payload — that's the
  *farmer-surface* data contract; MC section is the *engineer-surface*
  escape hatch for when summary isn't enough.
- Phase 18 established "farmOS-owns-the-farmer-UI" pattern. This seed
  extends it: farmOS owns the farmer UI *and* provides the door to MC.
- Memory `feedback_naming.md` — call OpenMCT "Mission Control" in
  conversation/docs. Nav item label should be "Mission Control" to
  match existing vocabulary.

## Notes

This seed composes with SEED-002 (farmOS event writer from Signal captures):
together they define the three farmer-app sections — **Field Notes** (from
Phase 25; do NOT call it "Log" — collides with farmOS log type and with the
farmers' wood-log grow substrate), Daily Summary + Events (existing + SEED-002),
Mission Control (this seed).

Non-goal for this phase: rebuilding MC widgets as shared web components.
That was discussed and rejected 2026-04-20 — the MC widgets are operator-
flavored and don't belong in the farmer UI with their native aesthetic.
If specific MC widgets *do* belong in the farmer UI later, do them as
bespoke farmOS blocks rather than shared components.
