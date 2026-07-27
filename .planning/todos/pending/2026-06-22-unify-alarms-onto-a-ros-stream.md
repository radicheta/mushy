---
created: 2026-06-22T00:16:18.306Z
title: Unify alarms onto a ROS stream (decouple from signal-cli)
area: general
files:
  - src/whisper-transcribe/main.py
  - src/agents/alerter/
---

## Problem

Alarm/notification dispatch is duplicated across services, each reaching into
signal-cli directly:
- `whisper-transcribe/main.py` — model-load failure alert (added 2026-06-21, the
  retry-backoff-then-notify hardening)
- the chamber alerter — RH out-of-band, pi-offline, chamber-dark, sensor staleness,
  humidifier-stuck
- the bridge — `/heartbeat-alert`

Every new service that wants to page someone grows its own Signal-sending code,
recipient routing, and (ad hoc) rate-limiting. There is no single place to reason
about who-gets-paged, dedup, or a meta-watchdog self-check. Santi flagged this
2026-06-21 ("our alarms system should be a ROS stream instead of calling signal
agent directly... todo later").

## Solution

TBD (architecture, revisit as an infra/alarms phase — not now).

Sketch: services *publish* alarm events to a ROS alarm topic (severity, source,
message, recipient-class). A single subscriber owns the Signal transport and the
cross-cutting concerns:
- recipient routing (operator vs farmer group — e.g. GPU/infra alerts go to Santi
  only, chamber alerts to the farmer group)
- rate-limiting + dedup (no alert storms)
- the meta-watchdog self-check (see memory `alerter-needs-meta-watchdog`)

Benefit: decouples alarm *producers* from the Signal *transport*; one place to
change channels (Signal -> something else) and one place to reason about paging.
Relates to: `[[alerter_needs_meta_watchdog]]`. Likely a v1.12+ infra phase, after
the Python port settles (the alerter itself ports in Phase 63).
