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

## Deferred Attestation

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
