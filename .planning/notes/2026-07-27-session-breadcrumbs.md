# Session breadcrumbs — 2026-07-27

Picks up from the 2026-07-26 audit. Everything below is pushed to `origin/main`.

## Done

1. **Heartbeat `==` → `>=` fixed in the Python port** (`9167c5d`, MUSHY-44 item 4) as a
   **sanctioned delta**, not a preserved quirk. Verified it was a two-stage mismatch,
   not a single operator: `chamber/heartbeat.py:54` dispatches at `>=` and consumes its
   day marker, `chamber/state.py:687` only emitted at `==`. Test flipped to
   `test_heartbeat_fires_after_the_hour_not_only_on_it`. Quirks 1-3 stay pinned.
   **Phase 64's parity gate must score this hour comparison as an INTENDED divergence** —
   annotated in `63-07-SUMMARY.md` item 4.

2. **Phases 56-63 landed on main as 9 squashed commits** (`57e8b46`..`e9c5135`),
   MUSHY-46 closed. Nine, not eight: the 7 pre-56 commits are milestone scaffolding.
   Trap avoided — main had **2 commits the branch lacked** (Mission Control VPD +
   rounding); the branch tree had no `fc_derived.js`, so a naive land would have
   silently deleted a shipped feature. Merged main in first, then applied each phase as
   a cumulative **diff** (not a tree snapshot) so main's disjoint paths survive every
   intermediate commit. Proof the squash lost nothing: identical tree hash
   `7c14881ca4bf812711c155f4637cac3ca5489f7f`.

3. **Branch triage.** `hotfix/pwm-cap-0.9` deleted (fully superseded — the 0.90 cap was
   already everywhere; it diffed against a 0.40 that no longer exists).
   `fix/mute-signal-convo-spam` kept: 25 of its 26 commits are Phase 54.2 work the port
   already covers, but the 999.55 mute kill switch is unported → **MUSHY-51**.

4. **MUSHY-8 alerter TZ fixed in prod.** `override.yml` → `TZ=${TZ:-America/Montevideo}`,
   container recreated `--no-build` to avoid pulling 2 weeks of `src/` drift. Verified:
   node-cron 3.0.3, retention cron now 03:15 UYT (was 04:15), ICU resolving local time.

5. **Todo triage** — all 17 in `pending/`, see `.planning/todos/TRIAGE-2026-07-27.md`.

6. **New tickets:** MUSHY-51 (mute), 52 (digital twin), 53 (batch-mode
   `in_flight_conflict`), 54 (heartbeat).

## Open — start here

- **MUSHY-54 is the live one.** Daily heartbeat reaches the farmer ~12% of days,
  silently. Root cause confirmed and reproduced; **the fix went into the Python port
  only and prod runs Node**, so it persists until Phase 65 unless Node is patched.
  Patching Node = alerter image rebuild = pulls `src/agents/alerter/` drift. Decide
  deliberately. A second, unproven cause is in the ticket (reducer reads bootstrap
  config, scheduler reads effective/globals-shadowed).
- **Three filed bugs were ported to Python unchanged** — MUSHY-9 (strain regex
  `[A-Z]{2,4}`, 3 sites), MUSHY-11 (observation reject, now **pinned by a passing
  test**), MUSHY-53 (partial unique index). Phase 65 fixes none of them and Phase 64
  would score all three as parity matches. These were *copied*, not deliberately
  pinned — unlike `63-07-SUMMARY.md` quirks 1-3.
- **MUSHY-45** — remote, guards a known 7.8-day outage recurrence. Repo backup script
  has the signal-cli volume block; the *deployed* copy does not. Needs the offline age
  key to decrypt-verify. Not a lab visit.
- **Phase 63 manual leg** — stop fc-core, confirm f1's phone gets the pi-offline alert
  (`ALERT_PI_OFFLINE_MIN=5`, so a ~5-8 min window). Doable over SSH under the fc1
  preflight protocol; being at the chamber is risk reduction, not a requirement.
- **MUSHY-8 residuals** — `tzdata` absent from the alerter image (libc `date` / log
  timestamps still UTC, needs a Dockerfile change); Node `hhmm()` at `message.js:50-52`
  still renders UTC. Also `docker-compose.yml:60,61` (farmos-agent, the only
  `REPORT_TIMEZONE` reader) and `:80` (timelapse) are still Toronto — different
  services, deliberately left alone.
- **MUSHY-14** — code already live in the running container; needs one handset
  confirmation that the quote bubble renders.

## Branches left standing (deliberately)

- `feat/phase-63-chamber-alerter` — the **only** copy of the unsquashed 303-commit
  history, local-only, no origin upstream. Content is fully represented in main (tree
  hash proven), so deletable, but the granular history is unrecoverable. Left for
  Don Santiago to call.
- `docs/phase-63-sp-plan-rewrite`, `feat/phase-55-full-corpus`,
  `feat/phase-56-foundation`, `fix/inoc-starting-seq-dispatch` (MUSHY-32),
  `fix/mute-signal-convo-spam` (MUSHY-51) — separate triage items, untouched.
- `land/v1.12-squash` — deleted, was fully merged into main.

## Two corrections worth remembering

- I reported MUSHY-10 and MUSHY-14 as undeployed. **Both were already live.** One bad
  probe caused it: `/app/src/fc_derived.js` when the bridge WORKDIR is `/opt/bridge`.
  It also triggered an unnecessary prod bridge rebuild (harmless; now built from
  current main, all 11 topics verified flowing). `fc.vpd` / `fc.water_vapor` hold
  7.84M rows each back to 2026-04-11.
- I wrote in MUSHY-51 that the Signal mute was never live. It ran in prod
  **2026-06-04 → 06-10** (84 `muted:*` rows). Corrected on the ticket.
- Recreating the alerter container **destroyed 2 weeks of logs** that later turned out
  to hold the decisive evidence for MUSHY-54. Dump logs before any recreate.
