---
phase: 37
plan: 04
subsystem: alerter
type: execute
wave: 3
tags: [compose, env, integration, runbook, integration-test, partial]
requirements: [ROUTE-01, ROUTE-02, ROUTE-03]
depends_on: ["37-02", "37-03"]
status: PARTIAL — Tasks 1+2 complete; Task 3 (live human-verify attestations) deferred to operator
provides:
  - alerter boot threads config.signalGroupId into createSignalClient defaultTarget (D-04)
  - alerter boot threads config.signalFarmerMap into createCapturePipeline (D-11/D-13)
  - docker-compose.override.yml plumbs SIGNAL_GROUP_ID + SIGNAL_FARMER_MAP envs
  - 37-RUNBOOK.md — operator deploy + 4-attestation verification recipe + Phase 33 non-regression
requires:
  - 37-02 signal.js {to} + defaultTarget API, config.signal* fields
  - 37-03 capture.js + receive-loop.js group-context wiring
affects:
  - alerter container — DM-only behavior when SIGNAL_GROUP_ID unset (back-compat); group-default when set
tech-stack:
  added: []
  patterns:
    - "compose-env to config to constructor: SIGNAL_GROUP_ID flows envvar → docker-compose.override.yml → config.signalGroupId → createSignalClient({defaultTarget: {groupId}})"
    - "boot-log mitigation surface for T-37-04-01/03: [boot] signal defaultTarget + [boot] farmer-map entries lines let operator visually verify envs reached runtime"
key-files:
  created:
    - .planning/phases/37-multi-farmer-routing/37-RUNBOOK.md (261 lines)
  modified:
    - src/agents/alerter/src/index.js (239 → 256 lines, +17)
    - docker-compose.override.yml (132 → 136 lines, +4)
decisions:
  - "[37-04] SIGNAL_GROUP_ID is the bare internal_id form (e.g. 'hKw0KX1g...'), NOT the prefixed 'group.<...>' id form. signal.js wraps internally. 37-SMOKE.md Probe A documented the wrong-form 400 failure; runbook §2 calls it out explicitly to prevent the next operator from repeating it."
  - "[37-04] Boot-log lines are mitigation-by-visibility for T-37-04-01 (wrong-group leak) and T-37-04-03 (slug-typo mis-attribution). Operator MUST visually verify both lines before declaring deploy complete; 37-RUNBOOK §5 makes this a hard pre-attestation gate."
  - "[37-04] Plan 04 Task 3 (live attestations) executed by orchestrator/operator, not by executor agent. This SUMMARY records the code-change deltas only; the attestation table will be appended by /gsd:verify-work after the operator runs §6 of 37-RUNBOOK.md."
metrics:
  duration: "~10min"
  tasks_completed: 2
  tasks_deferred: 1
  files_modified: 2
  files_created: 1
  completed: "2026-05-11 (Tasks 1+2 only)"
---

# Phase 37 Plan 04: Multi-farmer Routing Final Wiring — Summary (PARTIAL)

**STATUS:** Tasks 1 and 2 complete. Task 3 (live human-verify attestations A/B/C/D + E) is deferred to the orchestrator/operator — it requires three live farmer participants, an alerter rebuild against operator-authored `.env` values, and Signal-side round trips that cannot be automated by the executor.

The code path is now wired end-to-end. The deploy + attestation handoff is the runbook 37-RUNBOOK.md authored under Task 2.

## What Shipped (Tasks 1+2)

### 1. index.js boot wire-up (Task 1) — commit `7b7256c`

`createSignalClient` now receives `defaultTarget`:

```javascript
defaultTarget: config.signalGroupId
  ? { groupId: config.signalGroupId }
  : config.signalRecipient,
```

`createCapturePipeline` now receives `signalFarmerMap: config.signalFarmerMap`. Two new boot-log lines provide operator-visible env-reached-runtime verification:

```
[boot] signal defaultTarget = group:<8chars>…    | DM:<masked phone>
[boot] farmer-map entries = <N>
```

A D-04 comment near `applyEvent` makes the default-target inheritance explicit for non-reply sends (heartbeat, snooze_ack, recovery).

Back-compat preserved: with `SIGNAL_GROUP_ID` unset in `.env`, `config.signalGroupId === null` and `defaultTarget` falls through to `config.signalRecipient` — byte-identical to pre-Phase-37 DM behavior.

### 2. docker-compose.override.yml env plumbing (Task 1) — commit `7b7256c`

Two new env lines under the alerter env block, placed immediately after the Phase 36 `SIGNAL_ADDITIONAL_SENDERS` line (matching the c8e9ac1 template):

```yaml
- SIGNAL_GROUP_ID=${SIGNAL_GROUP_ID}
- SIGNAL_FARMER_MAP=${SIGNAL_FARMER_MAP}
```

No default values — absence in repo-root `.env` → config.js reads `''` → null/empty Map → alerter falls back to legacy DM behavior. Operator-set in `.env`.

`docker compose config` parses without error.

### 3. 37-RUNBOOK.md (Task 2) — commit `7bff438`

Eight sections + appendix:

1. Prerequisites
2. Obtain `SIGNAL_GROUP_ID` (with the `internal_id` vs `id` pitfall from 37-SMOKE.md Probe A called out)
3. Author `SIGNAL_FARMER_MAP` (E.164 + farmOS-slug format, malformed-entry behavior documented)
4. Update repo-root `.env` (with sub-shell sanity check)
5. Deploy alerter (with the two expected `[boot]` lines as the hard pre-attestation gate)
6. Four live attestations (A: 999.20 proof-of-fix DM-to-zoy-only; B: D-04 group default visibility; C: ROUTE-03 unmapped-sender with `(unassigned)` sentinel; D: D-09 envelope dedupe on `@mention + command`)
7. Rollback (comment out `SIGNAL_GROUP_ID`, redeploy)
8. Phase 33 invariant non-regression (VPS outage path stays direct-to-f1)

Each attestation has a falsifiable pass criterion + a DB row check (except B where the criterion is visual group-thread placement).

## Deferred — Task 3 (live attestations)

Task 3 is a `checkpoint:human-verify gate=blocking` that requires:

- Operator on `elder-plops` to author `.env` values (the `+phone:slug` mappings need real farmer phones the executor doesn't have)
- Live participation from f2 (zoy) for attestation A
- Live `@mention + command` send from f2 for attestation D
- An adequate window to run attestation B (next scheduled heartbeat or a controlled RH-band excursion)
- A test phone or temporary `SIGNAL_ADDITIONAL_SENDERS` addition for attestation C
- A controlled alerter-stop window for attestation E (Phase 33 non-regression)

None of these are automatable from the executor's seat. The orchestrator surfaces this checkpoint to the operator after this agent returns; the operator then runs 37-RUNBOOK.md §4–§8 and records outcomes by appending the following section to this SUMMARY.md:

```markdown
## Attestation Outcomes (filled by operator)

| Attestation | Outcome | Timestamp | Notes |
|---|---|---|---|
| A — 999.20 DM proof-of-fix | PASS / FAIL | … | exact ping string + observed reply body |
| B — D-04 group default | PASS / FAIL | … | heartbeat timestamp + group thread anchor |
| C — ROUTE-03 unmapped | PASS / FAIL | … | DB row (sender, farmos_person, reply_target_kind) |
| D — D-09 envelope dedupe | PASS / FAIL | … | bot reply count + DB row |
| E — Phase 33 non-regression | PASS / FAIL | … | DM target confirmation |
```

After all five record PASS, the plan can be marked complete in STATE.md and the closeout line "ROUTE-01/02/03 closed live YYYY-MM-DD; 999.20 retired" added.

## Verification

- Task 1 grep checks: all 4 patterns matched (`SIGNAL_GROUP_ID=${SIGNAL_GROUP_ID}` and `SIGNAL_FARMER_MAP=${SIGNAL_FARMER_MAP}` in docker-compose.override.yml; `defaultTarget: config.signalGroupId` and `signalFarmerMap: config.signalFarmerMap` in index.js).
- `docker compose config` exits 0.
- `npx jest` from `src/agents/alerter`: **268 passed / 269 total**. The 1 failure (`test/config.test.js Test A: returns object with all fields populated from defaults` — `dashboardUrl` default drift) is pre-existing and documented in 37-SMOKE.md L88–93 as deferred to a 999.x. No new failures introduced by Plan 04 Task 1.
- Task 2 runbook structurally complete: 4 attestation headers present (A/B/C/D) plus Phase 33 invariant (E) in §8.

## Deviations from Plan

None. Plan executed exactly as written for Tasks 1+2. Task 3 was scoped out by the orchestrator at agent dispatch — not a deviation, an intentional partial-run boundary.

## Known Stubs

None — Plan 04 ships no stub data; all envs flow from operator `.env` to runtime, and absence is handled by intentional back-compat fallback paths (documented in code comments).

## Self-Check: PASSED

- File `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/index.js` — FOUND, contains `defaultTarget: config.signalGroupId` at line 71 and `signalFarmerMap: config.signalFarmerMap,` at line 101.
- File `/mnt/slime-kingdom/opt/mushy/docker-compose.override.yml` — FOUND, contains both `SIGNAL_GROUP_ID=${SIGNAL_GROUP_ID}` (line 79) and `SIGNAL_FARMER_MAP=${SIGNAL_FARMER_MAP}` (line 81).
- File `/mnt/slime-kingdom/opt/mushy/.planning/phases/37-multi-farmer-routing/37-RUNBOOK.md` — FOUND, 261 lines, 4 `### Attestation [A-D]` headers + §8 Phase 33 non-regression.
- Commit `7b7256c` (feat 37-04 wire) — FOUND in `git log --oneline`.
- Commit `7bff438` (docs 37-04 runbook) — FOUND in `git log --oneline`.
