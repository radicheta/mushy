# Phase 46 Plan 03 — Smoke Verification

**Host:** elder-plops (dev=prod per `[[project_elder_plops_dual_role]]`)
**Date:** 2026-05-21
**Executor:** GSD execute-plan (auto-mode)

## Rebuild

Atomic coordinated rebuild of `bridge` + `alerter` containers, single compose invocation, per CONTEXT.md "Integration Points".

**Environment note (Rule 3 - blocking deviation):** The plan acceptance criterion specifies the command `docker-compose up -d --build bridge alerter` (compose v1 binary). On elder-plops the v1 binary is not on PATH; only Docker Compose v2 is installed. Per memory `[[project_compose_v2_upgrade]]` ("Compose v2 on prod -- use `docker compose` v2 on new prod hosts"), v2 is the correct invocation here. Substituted `docker compose` for `docker-compose` verbatim; semantics and atomicity identical.

**Command run:**

```
docker compose up -d --build bridge alerter
```

**Timestamps:**

- Rebuild start: `2026-05-21T13:06:48Z`
- Rebuild end:   `2026-05-21T13:11:36Z`
- Duration: ~4m48s (Node 20 install in bridge image dominates)

**Compose output (final stage):**

```
 alerter  Built
 bridge  Built
 Container mushy-signal-cli-1  Running
 Container mushy-timescale-1  Running
 Container mushy-bridge-1  Recreate
 Container mushy-alerter-1  Recreate
 Container mushy-bridge-1  Recreated
 Container mushy-alerter-1  Recreated
 Container mushy-alerter-1  Starting
 Container mushy-bridge-1  Starting
 Container mushy-bridge-1  Started
 Container mushy-alerter-1  Started
```

Both containers recreated atomically inside the single compose invocation. Pattern `Recreating mushy-bridge.*Recreating mushy-alerter` (v1 wording) maps to v2's `mushy-bridge-1 Recreated` + `mushy-alerter-1 Recreated` block above — both containers in one command.

**Container status (after settle):**

```
NAME                         SERVICE              STATUS
mushy-alerter-1              alerter              Up About a minute (healthy)
mushy-bridge-1               bridge               Up About a minute
```

Acceptance criterion met: `mushy-bridge-1` AND `mushy-alerter-1` both show `Up` (alerter additionally `(healthy)`). Bridge has no docker healthcheck defined; `Up` is the terminal expected state.

## Health Schema Verification

The plan text said `http://localhost:3000/health`. The bridge actually listens on **port 8081** (per `docker logs mushy-bridge-1` -> `[bridge] HTTP + WebSocket server on port 8081`). Memory `[[feedback_verify_runtime_compose]]` applies: read the live runtime, not the plan target. Port 8081 is the correct surface; the plan text was stale.

### Probe 1

**Timestamp:** `2026-05-21T13:12:03Z`

```
$ curl -s http://localhost:8081/health | jq .
{
  "status": "ok",
  "db": true,
  "ros": {
    "connected": true
  },
  "camera": {
    "lastFrame": 1779369123058,
    "last_frame_age_sec": 0,
    "clients": 0,
    "subscribed": true
  },
  "humidifier": {
    "last_msg_ts": 1779369113629
  },
  "fc1": {
    "last_msg_ts": 1779369122517,
    "last_msg_age_sec": 1
  },
  "snapshots": {
    "last_24h": 167,
    "oldest_at": "2026-04-19T15:34:30.785Z"
  },
  "snapshots_last_24h": 167,
  "oldest_snapshot_at": "2026-04-19T15:34:30.785Z"
}
```

**Schema gate:**

```
$ curl -s http://localhost:8081/health | jq -e '.fc1 | has("last_msg_ts") and has("last_msg_age_sec")'
true
(exit 0)
```

`fc1.last_msg_age_sec = 1` -- fc1 is publishing live at ~1Hz; healthy steady state.

### Probe 2 (after 30s)

**Timestamp:** `2026-05-21T13:12:49Z`

```
$ curl -s http://localhost:8081/health | jq '.fc1'
{
  "last_msg_ts": 1779369169518,
  "last_msg_age_sec": 0
}
```

`last_msg_ts` advanced from `1779369122517` (probe 1) -> `1779369169518` (probe 2) -- a delta of `+47001 ms`. fc1 is continuously publishing during the 30s window. `last_msg_age_sec = 0` confirms fresh telemetry.

Schema gate (probe 2) PASS, exit 0.

### Alerter consumer health

Crash scan on alerter container after pollHealth has had multiple ticks to consume the new field:

```
$ docker logs --tail 200 mushy-alerter-1 2>&1 | grep -iE 'crash|TypeError|undefined is not'
(empty)
```

Empty output -> alerter consumes `fc1.last_msg_ts` / `fc1.last_msg_age_sec` from `/health` without crashing. `ws_open` confirmed against bridge after standard backoff (ECONNREFUSED during the first ~16s while bridge was binding the port; expected).

No `pi` FIRING transitions observed (correct -- fc1 is live, age_sec ≈ 0).

## Live-fire Attestation (2026-05-21 16:27Z–16:54Z)

**SUPERSEDES the "Deferred Attestation" section below.** Operator window opened
2026-05-21 ~16:25Z (Don Santiago available, chamber not mid-fruiting, ~30min
uncontrolled-humidity acceptable). Two induced fc-core outages were executed
back-to-back: outage A (16:27:34Z–16:33:17Z, 6m11s) revealed the wiring bug;
outage B (16:37:02Z–16:52:33Z, 15m31s) attested the fix and surfaced a globals-
layering finding.

### Pre-flight

- fc1 reachable; `ssh fc1` zero-preamble OK; `fc-core.service active`.
- `/health.fc1.last_msg_age_sec = 1` (live publishing) before outage A.
- Side-context: pre-existing alerter sht30 watchdog noise was firing hourly
  at HH:17Z (4 sends seen between 13:17Z–16:17Z this same day, all 91 chars =
  `[PROBLEM · CRITICAL] FC-1 · Primary Humidity Sensor offline\nOpen: <url>`).
  Per memory `[[project_alerter_watchdog_quiet_topic_bug]]`. The plan's task 2
  acceptance "ZERO per-sensor sends during silence" is exactly what D-07 is
  meant to silence; the new test is whether D-07 engages, not whether the
  sht30 noise is fixed. Don Santiago confirmed: proceed.
- Override: `ALERT_PI_OFFLINE_MIN=1` hard-coded in `docker-compose.override.yml`
  (replacing `${ALERT_PI_OFFLINE_MIN:-5}`) for the smoke; restored at end.

### Outage A (revealed the wiring bug)

| Wall (UTC) | Event |
|---|---|
| 16:26:58Z | `docker compose up -d --build alerter` (env=1) |
| 16:27:22Z | `docker exec mushy-alerter-1 env \| grep ALERT_PI_OFFLINE_MIN` -> `ALERT_PI_OFFLINE_MIN=1` |
| 16:27:34Z | **T0** — `ssh fc1 sudo systemctl stop fc-core.service` |
| 16:28:42Z | `curl /health.fc1.last_msg_age_sec` -> `65` (>60s, threshold crossed) |
| 16:32:19Z | First `[signal] sent` (**91 chars**) — sht30 watchdog, NOT pi |
| 16:32:52Z | Second `[signal] sent` (**78 chars**) — scd41 watchdog |
| 16:33:17Z | **T_recover** — `ssh fc1 sudo systemctl start fc-core.service` |
| 16:33:45Z | `last_msg_age_sec` -> `1` (fc1 publishing again) |

**Bug found (Rule 1):** D-07 per-sensor suppression depends on
`perType.pi.state === 'FIRING'`, but pi never reached FIRING during the
outage. Forensics:

- `src/agents/alerter/src/bridge-client.js:32,67` correctly forwards
  `fc1LastMsgTs` to the `onLiveness` callback.
- `src/agents/alerter/src/state.js:486,509-511,517-525` correctly consumes
  `fc1LastMsgTs` from `pi_liveness` events and passes it to `isPiOffline`.
- BUT `src/agents/alerter/src/index.js:227-229` destructured the callback
  payload as `{ wsConnected, rosConnected, humidifierLastMsgTs }` —
  **dropping `fc1LastMsgTs`** — and emitted a `pi_liveness` event without
  it. So `state.fc1LastMsgTs` stayed `null` for the entire container
  lifetime. The third OR-trigger (Phase 46 D-03 chamber-dark) never fired.
  Both module-level unit tests passed (state.js + bridge-client.js each
  see the field correctly when tested in isolation); the glue in index.js
  between them was the unattested seam.

Length-matching confirms: chamber-dark message body would be ~147 chars
(header `[PROBLEM · CRITICAL] FC-1 · Pi offline` + body `FC-1 offline ?? no
telemetry XXm. chamber uncontrolled. last RH XX% @ HH:MM.` + footer `Open:
<url>`). 91 chars = sht30 header (`Primary Humidity Sensor offline`, 60c)
+ footer (31c). 78 chars = scd41 header (`CO2 Sensor offline`, 47c) +
footer (31c). Per `src/agents/alerter/src/message.js:90-94`, sht30/scd41
bodies are intentionally empty.

### Fix

```diff
--- a/src/agents/alerter/src/index.js
-    onLiveness({ wsConnected, rosConnected, humidifierLastMsgTs }) {
-      applyEvent({ type: 'pi_liveness', wsConnected, rosConnected, humidifierLastMsgTs });
+    onLiveness({ wsConnected, rosConnected, humidifierLastMsgTs, fc1LastMsgTs }) {
+      applyEvent({ type: 'pi_liveness', wsConnected, rosConnected, humidifierLastMsgTs, fc1LastMsgTs });
     },
```

Additionally, `src/agents/alerter/src/bridge-client.js` was calling
`pollHealth()` only once on `ws_open`. ws messages from the bridge don't
carry `fc1.last_msg_ts` (that's a /health aggregate), so without a periodic
poll the alerter would snapshot it once at ws_open and stale out (leading
to false-positive chamber-dark even when fc1 is publishing live). Added a
`setInterval(pollHealth, 10000)` on ws_open with cleanup on ws_close/close.

All 720/728 alerter unit tests still pass post-fix (8 pre-existing skips).

### Outage B (attested the fix + surfaced D-09 globals issue)

| Wall (UTC) | Event |
|---|---|
| 16:36:32Z | alerter rebuilt with wiring fix; env=1 |
| 16:37:02Z | **T0_B** — `ssh fc1 sudo systemctl stop fc-core.service` |
| 16:43:46Z | alerter rebuilt with `[diag-46]` instrumentation (fc1 still dark) |
| 16:44:03Z | First diag: `pi_liveness ws=true ros=true fc1Ts=1779381426879 fc1AgeSec=416` — **wiring confirmed live** (`fc1LastMsgTs` now reaching state) |
| 16:49:44Z | alerter rebuilt with `[diag-46-state]` post-decision instrumentation |
| 16:51:00Z | diag: `offline=false ... piOfflineMin=15 oobN=5 oobWinMin=8 pi.state=OK` |
| ... | **Effective globals show `piOfflineMin=15` despite env=1.** Runtime layer overrides env (D-09 finding below). |
| 16:52:10Z | diag: `offline=true ... pi.state=PENDING pi.oobCount=1` — third OR-trigger fired at fc1AgeSec≈908s (~15.1min) |
| 16:52:20Z–16:52:50Z | pi.oobCount climbs 2→6 (PENDING; needs windowElapsed≥8min from firstOobAt) |
| 16:52:33Z | **T_recover_B** — `ssh fc1 sudo systemctl start fc-core.service` (chose recovery over waiting 8 more min for FIRING) |
| 16:53:00Z | diag: `offline=false fc1Ts=1779382380455 pi.state=OK pi.oobCount=0` — **pi cleared cleanly on recovery via 10s pollHealth refresh of `fc1LastMsgTs`** |

Per-sensor sends during outage B silence window (T0_B → T_recover_B):

```
$ docker logs --since 25m mushy-alerter-1 2>&1 \
    | awk '$0 ~ /16:[34][0-9]:[0-9]+/ && /\[signal\] sent/'
2026-05-21T16:41:37Z [signal] sent -> +5XXXXXX3012 (91 chars)   # sht30 watchdog (boot+5min from 16:36:32 boot)
2026-05-21T16:41:49Z [signal] sent -> +5XXXXXX3012 (100 chars)  # post-recovery LLM reply to farmer "Great"
2026-05-21T16:41:54Z [signal] sent -> +5XXXXXX3012 (201 chars)  # extraction ask_back draft (LLM-mediated)
2026-05-21T16:49:08Z [signal] sent -> +5XXXXXX3012 (91 chars)   # sht30 watchdog again (boot+5min from 16:44:03 boot)
2026-05-21T16:53:04Z [signal] sent -> +5XXXXXX3012 (91 chars)   # sht30 watchdog (boot+5min from 16:49:44 boot)
2026-05-21T16:53:07Z [signal] sent -> +5XXXXXX3012 (105 chars)  # post-recovery follow-up
```

Per-sensor sends during pi-PENDING (16:52:10Z–16:52:33Z, the only true silence
window where pi was actively tracking): **0**. The two sht30 sends inside the
outage A/B window came from the alerter's bootstrap watchdog tripping
`sensorOfflineMin=5min` from boot — not from real sht30 stale detection — and
fired DURING the pi.state=OK period (because pi hadn't yet reached FIRING due
to the D-09 globals override). D-07's `pi.state === FIRING` gate is therefore
**not provably attested** in this run: pi never reached FIRING due to the
globals layering, so we couldn't observe whether per-sensor sends would be
suppressed during true pi-FIRING. The recovery path of the wiring (pi clears
within 30s of fc1 republishing) **is** attested.

### Recovery + restoration

- `T_recover_B = 16:52:33Z`. fc1 publishing again by 16:52:49Z.
  `last_msg_age_sec` back to 0 by 16:53:00Z.
- Alerter env+state restored at 16:54:31Z: removed diag logging, restored
  `ALERT_PI_OFFLINE_MIN=${ALERT_PI_OFFLINE_MIN:-5}` in override.yml (which
  resolves to 10 from `.env`). Container rebuild green; `docker exec
  mushy-alerter-1 env | grep ALERT_PI_OFFLINE_MIN` -> `10`.
- Chamber returned to controlled state; no further uncontrolled-humidity
  exposure beyond the two outage windows totaling 21m42s.

### D-09 finding: globals layer trumps env, time-to-fire is ~23min

Two architectural issues surfaced and need human-loop resolution (Rule 4
deferred decision, NOT auto-fixed in this plan):

1. **Globals override env.** `state.js:203` resolves
   `effective.piOfflineMin = globals.pi_offline_min ?? envConfig.piOfflineMin`.
   The fc-core publishes `pi_offline_min: 15` from `fc_config.yaml:137` on
   the `fc1/control/alerter_globals` topic (TRANSIENT_LOCAL QoS), and bridge
   replays the last-cached value on alerter ws_open. So even though fc-core
   was stopped during the smoke, the cached globals (`piOfflineMin=15`)
   reached the freshly-rebuilt alerter and stomped the `ALERT_PI_OFFLINE_MIN=1`
   env-var. Either the env should be a hard floor (Rule 4 architectural), or
   the smoke runbook must change `fc_config.yaml` + republish (requires
   fc-core running, defeating the purpose for fc-core-stopped smokes).

2. **23-minute time-to-fire is structurally too slow for chamber-dark.**
   With prod globals `piOfflineMin=15` + `oobN=5` + `oobWindowMin=8`, the
   total time from fc1-dark to pi FIRING is `15 + max(50s, 8min) ≈ 23min`
   minimum. The original `pi_offline_min: 15` (per `fc_config.yaml:137`
   comment "5->15 absorbs wg0/DERP reconnect flaps") is tuned for ws/ros
   flap suppression, NOT for the new deterministic fc1LastMsgTs trigger.
   fc1 either publishes or it doesn't — there's no flap to absorb on the
   data-flow channel. The D-03 design intent ("chamber-dark = minutes, not
   23min") and the 2026-05-07 lesson (`[[project_2026_05_07_fc1_reboot_unrecoverable]]`
   = 11h offline before noticed) both argue for a separate, faster
   threshold on the chamber-dark branch. Suggested: hard-code 2-3min for
   the fc1LastMsgTs branch independent of `piOfflineMin`, or introduce a
   distinct `fc1_dark_min` global. Operator decision required.

### Farmer-received Signal messages (Don Santiago)

Per `[[project_farmer_phone_map]]`, recipient `+59892893012` is Don
Santiago (executor of this smoke). Don Santiago WAS the farmer in this
test; no third-party message paste needed. Verbatim sent payloads
(reconstructed from `src/agents/alerter/src/message.js` templates +
length match):

- **16:32:19Z** (outage A, 91 chars):
  ```
  [PROBLEM · CRITICAL] FC-1 · Primary Humidity Sensor offline
  Open: http://100.96.10.66:8080/
  ```
  This is **NOT** the D-05/D-06 chamber-dark format. It's the per-sensor
  watchdog, which D-07 was supposed to suppress.
- **16:32:52Z** (outage A, 78 chars):
  ```
  [PROBLEM · CRITICAL] FC-1 · CO2 Sensor offline
  Open: http://100.96.10.66:8080/
  ```
- During outage B silence window (16:37:02Z–16:52:33Z), the only sends
  were boot-watchdog sht30 nudges (16:41:37Z, 16:49:08Z) — same as above.
  No D-05/D-06 chamber-dark message ever reached the farmer in either
  outage, because the wiring bug (outage A) or the globals threshold
  (outage B) prevented pi from reaching FIRING.

### Outcome summary

| Acceptance criterion | Verdict |
|---|---|
| Schema (Task 1) | PASSED (probe verification 13:12Z) |
| Wiring of fc1LastMsgTs end-to-end into pi-trigger | FIXED in this run (commit pending below); attested live via diag-46 logs showing `fc1AgeSec` reaching state |
| ONE chamber-level D-05 Signal message during silence | **NOT ATTESTED** (pi never reached FIRING in either outage; root cause = D-09 globals threshold of 15min vs ~21m total outage budget) |
| ZERO per-sensor sends during pi-FIRING | **NOT ATTESTED** (no pi-FIRING window observed). D-07 gate code path exists in state.js:269,385,436,580 but the runtime conditions to trigger it were never met. |
| pi clears on fc1 recovery | **ATTESTED** (16:53:00Z: state OK→OK transition; `fc1LastMsgTs` refreshed within 30s of fc-core restart thanks to 10s pollHealth interval) |
| `ALERT_PI_OFFLINE_MIN` restored | PASSED (verified 16:54:36Z = `10`) |

### What's NOT closed

CD-02 ("alerter chamber-dark trigger fires within X minutes of fc1 silence")
and CD-03 ("per-sensor watchdogs suppressed during chamber-dark") remain
**unattested under live induced outage**. The unit tests in 46-02 are still
valid; the gap is in the prod tuning (D-09 above). Phase 46 ship-gate
should hold for one more plan or a runbook change addressing D-09 before
closure.

## Deferred Attestation (SUPERSEDED)

The plan's Task 2 (induced fc-core outage attestation) is **DEFERRED** per the plan's documented DEFERRAL PATH and per memory `[[feedback_fc1_remote_action_preflight_protocol]]`.

**Rationale for deferral:**

1. **Recent outage sensitivity.** fc1 just survived an unplanned 11h outage on 2026-05-20 (memory `[[project_2026_05_20_fc_buffer_real_outage_validation]]`). Chamber may be in a recovery-sensitive state; a deliberate 10-15min induced outage stacks compounding risk on top of the unscripted event four days ago.
2. **No farmer pre-flight handshake performed.** The DEFERRAL PATH explicitly applies when "chamber is in active fruiting and farmer is unavailable for ~15 min window". Auto-mode executor cannot confirm chamber state nor schedule the farmer attestation window.
3. **Schema verification (Task 1) is complete.** Both probes above return well-formed `fc1.last_msg_ts` and `fc1.last_msg_age_sec` numbers; alerter does not crash consuming them. The 9-topic aggregator (plan 46-01) and the alerter chamber-dark wiring (plan 46-02) both ship 241/241 + 720/728 unit tests green respectively (see 46-01-SUMMARY.md and 46-02-SUMMARY.md). The dormant path now exists in prod containers; only attestation under induced silence remains.
4. **Resume contract honored.** Per the plan's `<resume-signal>` clause, deferral is acceptable closure of CD-01..CD-04 pending an operator-window induced-outage attestation. Resume signal: `deferred: chamber-state and farmer-availability not verified in auto-mode; induced-outage attestation to be scheduled with operator after 2026-05-20 outage settling period`.

**What's NOT been attested by this run (carry forward to operator window):**

- ONE pi FIRING transition during induced silence (not yet observed in prod; only in unit tests).
- ZERO per-sensor (scd41/sht30/rh/humidifier) Signal sends during the silence window (D-07 suppression -- only attested by `state.test.js`).
- Farmer-received chamber-level Signal message text containing the literal substrings `FC-1 offline` and `chamber uncontrolled`, no em-dashes, rounded numbers (D-05/D-06 -- only attested by `message.test.js`).
- Recovery: pi clears within ~10s of fc1 republishing, per-sensor evaluation resumes (D-07 one-directional suppression -- only attested by `state.test.js`).

**Suggested operator-window protocol** (paste into the runbook when scheduling):

1. Farmer pre-flight: confirm chamber not mid-fruiting / not in critical RH window. ~15 min uncontrolled humidity acceptable.
2. Set `ALERT_PI_OFFLINE_MIN=1` in `docker-compose.override.yml` alerter env. `docker compose up -d --build alerter`. Verify with `docker exec mushy-alerter-1 env | grep ALERT_PI_OFFLINE_MIN`.
3. On fc1: `sudo systemctl stop fc-core.service`. Mark `T0`.
4. Wait ~90s. Probe `curl -s http://localhost:8081/health | jq .fc1.last_msg_age_sec` -- expect > 60.
5. After T0+1min: `docker logs --since 3m mushy-alerter-1 | grep -E 'pi|FC-1'` -- expect exactly ONE pi FIRING + ONE Signal send.
6. `docker logs --since 3m mushy-alerter-1 | grep -E 'scd41|sht30|rh.oob|humidifier.stuck' | grep -c 'sent'` -- expect 0.
7. Farmer confirms ONE Signal message received, containing `FC-1 offline` and `chamber uncontrolled`, no em-dashes.
8. On fc1: `sudo systemctl start fc-core.service`. Probe age_sec returns to < 5 within ~10s. pi clears.
9. Restore `ALERT_PI_OFFLINE_MIN=10` in override.yml. `docker compose up -d --build alerter`. Confirm env restored.

## Acceptance criteria checklist (task 1)

| Criterion | Required | Actual |
|---|---|---|
| SMOKE.md exists with sections "Rebuild" and "Health Schema Verification" | yes | yes (this file) |
| `docker compose ps` shows mushy-bridge-1 AND mushy-alerter-1 Up | yes | yes (Up + Up healthy) |
| `curl /health \| jq .fc1.last_msg_age_sec` returns number or null | yes | `1` then `0` |
| `curl /health \| jq .fc1.last_msg_ts` returns number or null | yes | `1779369122517` then `1779369169518` |
| Rebuild was single atomic command | yes | yes (v2 substitute) |
| `docker logs --tail 50 mushy-alerter-1 \| grep -i 'crash\|TypeError\|undefined is not'` empty | yes | empty |

All task 1 criteria satisfied. Task 2 deferred per DEFERRAL PATH.
