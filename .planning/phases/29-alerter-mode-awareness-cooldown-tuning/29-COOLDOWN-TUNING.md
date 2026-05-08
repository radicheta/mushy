## ⚠ INSUFFICIENT DATA — best-effort tuning, revisit after retention accumulates

**W8 retention escalation gate triggered.** Actual data window is **~13 hours of `[signal] sent` events** (2026-05-07 02:24 → 14:58 UTC), not the 14 days the plan targeted. Container `mushy-alerter-1` was last restarted 2026-05-07T18:55:40 — anything before 2026-05-06T22:45 (the prior boot line) is gone. Json-file driver, no log rotation policy explicitly set, so what's in the running container's stdout buffer is all there is.

**Compounding finding:** the alerter source code does NOT emit a per-rule `[send <alertType>]` or `[recovery <alertType>]` log line. The closest signal we have is the generic `[signal] sent -> +5XX… (NNN chars)` line in `signal.js:49`, which contains no alertType — `alertType` is a property of the `Action` object earlier in `index.js:103` but never makes it to logs. The plan's `awk '/\[send\]/ {print $NF}'` recipe (29-06-PLAN Task 1) **does not match real log shape**. Per-alertType statistics are therefore not derivable from logs alone in v1; would require either (a) Anthony-style alerter instrumentation patch or (b) Phase-29 deferred `alert_history` Timescale table (CONTEXT D-07 deferred).

**Recommendation handed to operator:** the values below are anchored on the *one* signal we DO have (a 30-min clockwork re-fire pattern that matches memory `project_alerter_watchdog_quiet_topic_bug` — false-CRITICAL via sht30_fresh-as-ping plus the band-aid `ALERT_SENSOR_OFFLINE_MIN=1440`) plus farmer-gut + Phase 28/29 architectural constraints. These are best-effort defaults that close ALRT-10 the 1-year-pending carry; revisit them once Phase 29 plan 29-04/05 ship the per-alertType log instrumentation OR a future plan adds the `alert_history` SQL table.

---

# Phase 29 — Cooldown Tuning Analysis (ALRT-10 / Phase 20 carry)

**Analysis date:** 2026-05-08
**Data window:** 2026-05-07 02:24 → 2026-05-07 14:58 UTC (~12.6 h of `[signal] sent` events)
**Source:** `docker logs mushy-alerter-1` on elder-plops (alert_history Timescale table absent — RESEARCH §"Tuning Data Access" verified; alertType field absent from log lines — discovered during this analysis)

## Methodology

1. Pre-flight retention probe per plan recipe — reported window << 14d (W8 gate triggered).
2. Bulk-pulled `docker logs --timestamps mushy-alerter-1 --since 2026-04-24T12:37:40 > /tmp/alerter-14d.log 2>&1` (returned 120 lines total — single boot-cycle's worth).
3. Confirmed log-line grammar by `grep -E '\[(send|recovery|heartbeat|PROBLEM|RECOVERY)\]' /tmp/alerter-14d.log` → only `[heartbeat] fired` lines match. Sweep `grep -rn 'logger\.' src/agents/alerter/src/` confirmed: **no per-rule send/recovery log emission exists in source**. The only per-fire log line is the generic `[signal] sent -> +5XX… (NNN chars)` from `signal.js:49`, with no alertType.
4. Computed inter-fire intervals from `[signal] sent` timestamps as a proxy for total alerter egress; cannot disaggregate by alertType.
5. Mode-swap cross-reference (Pitfall 8): no `set_mode` calls visible in the window — fc_controller currently runs `active_mode: fruiting` (fc_config.yaml line 78); no swap data exists yet because the Phase 28 service plumbing is the only swap path and Phase 28 just shipped 2026-05-07/08 (memory `Phase 28 shipped`).
6. Operator restart cadence (Pitfall 7): single container start visible at 2026-05-06 22:45 within the buffered window; broader cadence inferred from memory `project_2026_05_07_fc1_reboot_unrecoverable` + recent Phase 28/29 deploy activity at ~2-4 restarts/week.

## Per-rule Statistics

| alertType | total_fires | recoveries | mean_inter_fire_min | p95_per_hour | observed_cooldown_floor | proposed_cooldown_min | rationale |
|-----------|-------------|------------|---------------------|--------------|------------------------|----------------------|-----------|
| (aggregate, alertType-blind) | 31 sends in 12.6 h | n/a (no [recovery] log) | 25.1 | ≥4 sends/h (3 bursts of 0-min back-to-back fires + steady 30-min cadence) | 30 min (matches default `cooldownMin`) | see per-mode below | 17 of 31 inter-fire gaps were exactly 30 min ⇒ a single rule (most likely RH-OOB or pi-offline) was re-firing on its `cooldownMin=30` schedule — clockwork pathology pattern (memory `project_alerter_watchdog_quiet_topic_bug`). The 6 zero-minute back-to-back sends are likely PROBLEM+RECOVERY pairs or burst recoveries from a fc1 reconnect. |
| rh_oob | unknown | unknown | unknown | — | — | **45** (fruiting), **75** (pinning) | Per-mode differentiation honored — pinning intentionally swings (CONTEXT D-05). Push fruiting from 30→45 min to break the observed clockwork-30 pattern (the operator was hearing it as noise, not signal); push pinning to 75 to reflect intentional out-of-band excursions during pinning regime (band 0.90-0.99 is wider than fruiting 0.945-0.975). |
| humidifier_stuck | unknown | unknown | unknown | — | — | **30** (fruiting), **75** (pinning) | Fruiting wants tight — a stuck humidifier in fruiting is a fast-moving incident (RH walks off setpoint within minutes once the relay is jammed). Pinning humidifier-stuck is rarely actionable in real time (pinning duty cycles are short and fluctuating by design). 75 min on pinning matches CONTEXT D-05 "intentionally swings" wording. |
| pi_offline | unknown | unknown | unknown | — | — | **15** (Tier C global; was 5 in plan 29-03 bootstrap, was 10 in current `.env`) | Memory `fc1 SSH over Tailscale is DERP-only` + the wg0 transport switch (project memories) say WS reconnect can flap; 5 min is hair-trigger and 10 min was already field-set as more-tolerable. 15 min absorbs short flaps without dragging out genuine outage detection (last incident 2026-05-07 took 11 hours to be noticed by farmer-gut anyway — alerter is not the actual TTR-determining surface). Validator range cap is [1,60] — 15 is comfortably mid-range. |
| sensor_silent | unknown | unknown | unknown | — | — | **20** (Tier C global; was 5 in plan 29-03 bootstrap, was **1440 (24h band-aid)** in current `.env`) | **Band-aid 1440 cannot survive — validator caps `sensor_offline_min` at 60 min (plan 29-03).** This is intentional per Phase 29 D-05 (Tier C runtime-tunable, not env-tunable). The band-aid was working around the `sht30_fresh-as-ping` bug (memory `project_alerter_watchdog_quiet_topic_bug`); D-04 of CONTEXT bundles 999.39 (offline-blindness gating in `rules.js`) into Phase 29-05. **Caveat:** 20-min sensor_offline only becomes safe AFTER 29-04+29-05 ship the freshness gate (`isHumidifierStuck` + `isRhOob` suspended when `wsConnected===false`). If 29-06 lands BEFORE 29-04+29-05 in deploy order, the band-aid risk re-emerges. (Wave 3 dependency: 29-06 depends on 29-04+29-05, so this is structurally fine.) |
| heartbeat | 2 fires (1/day @ 17:00 local in env, 1×@ boot) | — | 24h | — | — | (Tier C `heartbeat_hour=17` — keep) | Farmer-set in `.env` to 17:00 local. Plan 29-03 bootstrapped to 8 — keeping 8 in YAML drops the farmer-set value silently. **Recommend YAML `heartbeat_hour: 17`** to match prior farmer-attested setting (memory: heartbeat is 5 PM local). |

## Per-mode Statistics (segmented by current_mode at fire time)

*Phase 28 mode swaps started ~2026-05-08 (Phase 28 shipped 2026-05-07/08 — memory `project_phase28_layer2_fc_buffer_relay`). Within the analysis window, fc_controller ran `active_mode: fruiting` exclusively. Per-mode segmentation is therefore zero-shot — recommendations for `pinning` are derived from architectural constraints (CONTEXT D-05/D-09) not data.*

| mode | fires (any rule) | mean_inter_fire_min | proposed_cooldown_min | proposed_critical_cooldown_min | rationale |
|------|------------------|---------------------|----------------------|--------------------------------|-----------|
| fruiting | 31 | 25.1 | **45** | **75** | Break the clockwork-30 pattern observed live; HUMID-04 narrow band 0.945-0.975 is signal-rich, so don't go above 60-min on cooldown. Critical cooldown lifted from 60→75 to keep the critical:standard ratio at ~1.67. |
| pinning  | 0 (no swap data yet) | — | **75** | **120** | CONTEXT D-05: pinning intentionally swings, looser default. D-09: cooldowns are alertType-keyed (not (alertType,mode)-keyed), so a fruiting fire 5 min before a fruiting→pinning swap will still suppress a pinning re-fire under pinning's window. Pinning cooldown > fruiting cooldown means swap-spam is structurally suppressed (not just relied-on by D-09). |

## Recommended fc_config.yaml Defaults

```yaml
modes.fruiting.alerter.cooldown_min:          45
modes.fruiting.alerter.critical_cooldown_min: 75
modes.fruiting.alerter.humidifier_stuck_min:  30
modes.fruiting.alerter.oob_n:                 5
modes.fruiting.alerter.oob_window_min:        3
modes.pinning.alerter.cooldown_min:           75
modes.pinning.alerter.critical_cooldown_min:  120
modes.pinning.alerter.humidifier_stuck_min:   75
modes.pinning.alerter.oob_n:                  5
modes.pinning.alerter.oob_window_min:         5
```

### Recommended Tier C Globals (`fc_controller.ros__parameters` top level)

| Key | Plan 29-03 bootstrap | Current `.env` | Recommended | Rationale |
|-----|----------------------|----------------|-------------|-----------|
| `pi_offline_min` | 5 | 10 | **15** | Absorb wg0/DERP reconnect flaps (memories `fc1 SSH over Tailscale is DERP-only`, `Stopping tailscaled on fc1 silently kills PID control`). |
| `sensor_offline_min` | 5 | 1440 (band-aid) | **20** | Validator caps at 60. Band-aid cannot move to YAML; Phase 29-04+29-05 freshness gate (D-04) replaces the band-aid. |
| `heartbeat_hour` | 8 | 17 | **17** | Honor farmer-attested setting from `.env`. |
| `max_sends_per_hour` | 20 | 20 | **20** | No data demands a change; keep. |

## Caveats

- **W8 retention insufficient.** Operator handed best-effort tuning instead of strict data-driven tuning. Future revisit gated on either (a) per-alertType log emission in alerter — would require a 5-line patch to `signal.js`/`index.js` to log `[send] alertType=<x>` — OR (b) the deferred `alert_history` Timescale table.
- **Pitfall 7 (restart cadence):** in the analysis window, only one container start (2026-05-06 22:45) was visible plus a known restart at 2026-05-07 18:55 (post-buffer); broader cadence inferred from project memories at ~2-4 restarts/week. The proposed cooldown_min=45 floor (fruiting) and 75 (pinning) sit comfortably above any plausible 1×/day restart-induced re-fire rhythm. If operator restart cadence increases (e.g., during active development), restart-spam could dominate fruiting metrics; revisit once log retention can attest to it.
- **Pitfall 8 (alertType-keyed dedup, not (alertType,mode)-keyed):** D-09 + the recommendation that `pinning_cooldown > fruiting_cooldown` jointly mean a fruiting→pinning swap immediately after a fruiting OOB fire will NOT cause a pinning re-fire spam — pinning's longer window still applies. The opposite swap (pinning→fruiting) shortly after a pinning fire will potentially miss a fresh fruiting fire for up to 45 min; this is acceptable (intentional dedup; CONTEXT D-09 rationale).
- **SCD41 RH suspect-high** (memory `project_phase26_sht30_happy_path_unverified`): `rh_oob` fires from SCD41 may be over-counted if RH band is centered on SHT30 truth. The current effective sensor is SCD41 (memory `project_v15_milestone_shape` — SHT30 physically disconnected); recommended cooldown_min absorbs ~4% RH offset noise via the wider band already chosen at the controller (humidity_tolerance=0.015 in fc_config.yaml line 23).
- **Validator range collision:** `sensor_offline_min` validator cap [1,60] forces dropping the .env band-aid 1440. The 999.39 freshness-gate work in plan 29-04+29-05 (D-04) is a hard prerequisite for sensor_offline_min=20 not regressing on the 2026-05-06 hourly-clockwork pathology. Wave-3 dependency on Wave-2 makes this safe; flagged here for traceability.
- **Heartbeat hour:** the bootstrap value (8) silently overrode the farmer-attested 17:00 daily heartbeat. Recommendation 17 corrects this — without it, plan 29-06 would silently regress operator preference.

## Suggested Future Work

1. **Cheap (1-2 lines):** patch `signal.js:49` to emit `[signal] sent type=<alertType> -> +5XX…` so the next ALRT-10-style tuning revisit has per-rule data.
2. **Medium:** add `alert_history` Timescale table (deferred per CONTEXT) and write each fire+recovery transition; closes the data-availability gap structurally.
3. **Operator action:** review the recommended values against fresh experience after a few days of Phase 29 live; adjust via `ros2 param set` and Layer 2 persist (Phase 28-06 fc_buffer relay) without redeploy.

---

*Phase 29 plan 29-06 — Cooldown Tuning Analysis*
*Document status: best-effort under W8 retention gate; values committed to `fc_config.yaml` in same plan.*
