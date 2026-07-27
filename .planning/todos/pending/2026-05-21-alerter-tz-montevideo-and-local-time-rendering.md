---
created: 1779387600
title: Fix alerter timezone — America/Toronto → America/Montevideo + local-time rendering
area: alerter
files:
  - docker-compose.yml
  - docker-compose.override.yml
  - src/agents/alerter/src/message.js
resolves_phase: 63
---

## Problem

Two independent timezone issues surfaced during the 2026-05-21 Phase 46 live-fire smoke (commit `6a33dc2`, see `46-03-SMOKE.md` Round 2):

**1. Container TZ hardcoded to Toronto.** `docker-compose.yml:60-61` sets `TZ=America/Toronto` + `REPORT_TIMEZONE=America/Toronto`; `docker-compose.override.yml:110` repeats it. Origin: commit `b17ef0a` Phase 13 farmOS-agent wiring — almost certainly a Claude-default from when the agent was first scaffolded. The farm is in Uruguay (UYT, UTC-3); see `[[project_farmer_phone_map]]` (+598 numbers).

Impacted by this setting:
- `docker logs` timestamps (cosmetic)
- `node-cron` schedules — `retention cron "15 3 * * *" tz=America/Toronto` runs at 04:15 UYT instead of 03:15 UYT; `ALERT_HEARTBEAT_HOUR=17` fires at 18:00 UYT instead of 17:00 UYT
- Anything calling `Date.toLocaleString()` etc.

**2. `hhmm()` in chamber-dark message renders UTC, not local time.** `src/agents/alerter/src/message.js:50-52`:

```js
function hhmm(tsMs) {
  return new Date(tsMs).toISOString().slice(11, 16);
}
```

`toISOString()` is always UTC regardless of the container `TZ`. The Phase 46 D-05 chamber-dark message `FC-1 offline ?? no telemetry 4m. chamber uncontrolled. last RH 94.8% @ 18:02.` shows the `@ 18:02` as UTC — meaning 15:02 UYT — which farmer has to mentally convert. Surfaced 2026-05-21 18:06:56Z when Don Santiago asked "is that Toronto/UTC/UYT?".

## Solution

One small commit:

1. `docker-compose.yml` lines 60, 61, 80 + `docker-compose.override.yml:110` — `America/Toronto` → `America/Montevideo`.
2. `src/agents/alerter/src/message.js` — replace `toISOString().slice(11,16)` with timezone-aware formatting (e.g. `Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: config.timezone })`). Pass `config.timezone` into `hhmm()` (it's already loaded into `config` per `index.js:50`).
3. Add unit test in `message.test.js`: assert a known UTC `tsMs` formats to the expected UYT `HH:MM`.

**Side-effects to validate before shipping:**
- Heartbeat cron shifts by 1h (Toronto = UTC-4 currently, Montevideo = UTC-3). `ALERT_HEARTBEAT_HOUR=17` will fire 1h earlier in farmer local clock. Check whether the farmer wants 17:00 UYT (current Toronto-17 effective) or 17:00 Toronto (= 18:00 UYT) — almost certainly the former, but ask.
- Retention cron `"15 3 * * *"` shifts similarly. Low impact.
- Toronto observes DST; Montevideo does not. Today (2026-05-21) Toronto is EDT (UTC-4), Montevideo is UYT (UTC-3); so the shift today is 1h forward. After Toronto's DST ends in November, the offset matches and no shift occurs. The fix removes this seasonal drift entirely.

## Why backlog and not fix-now

Don Santiago opted to backlog after the 2026-05-21 live-fire so Phase 46 ships clean. The wrong timestamp is annoying but not safety-critical — the farmer can still parse `@ 18:02` as "about 4 minutes ago" from message age. Worth bundling with the next farmer-facing message touch-up plan (e.g., a v1.8 farmer-language pass).

## Acceptance

- Test: chamber-dark message with known UTC sample timestamp renders the `@ HH:MM` in UYT.
- Live: rebuild alerter, induce a fresh 4-min chamber-dark outage (or wait for one to occur naturally), confirm message shows UYT time and farmer paste-back matches.
- No regression on heartbeat / retention cron firing times (acknowledge the shift in the commit message).
