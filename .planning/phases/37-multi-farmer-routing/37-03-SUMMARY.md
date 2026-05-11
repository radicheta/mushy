---
phase: 37
plan: 03
subsystem: alerter
type: execute
wave: 2
tags: [signal, alerter, capture, receive-loop, group-triggers, dedupe]
requirements: [ROUTE-01, ROUTE-02, ROUTE-03]
depends_on: ["37-01", "37-02"]
provides:
  - capture.js handle(env, ctx) — replyTarget + farmer-map + new row fields
  - receive-loop.js group-context gate + collectGroupTriggers + envelope dedupe
requires:
  - 37-02 signal.js {to} API, config.signalFarmerMap, capture-db schema fields
affects:
  - signal_capture row writes now stamp group_id, farmos_person, reply_target_kind
  - receive-loop pipeline.handle() signature changed (additive ctx arg; safe default)
tech-stack:
  added: []
  patterns:
    - "pure helper + integration test pair for receive-loop branch (collectGroupTriggers mirrors parseSnoozeCommand shape)"
    - "ctx-as-options bag for cross-module pipeline coordination (suppressReply flag)"
    - "envelope-level dedupe via Set<TriggerKind> + commandBranchAllowed gate"
key-files:
  created:
    - .planning/phases/37-multi-farmer-routing/deferred-items.md
  modified:
    - src/agents/alerter/src/receive-loop.js (178 → 236 lines, +58)
    - src/agents/alerter/src/capture.js (164 → 190 lines, +26)
    - src/agents/alerter/test/receive-loop.test.js (381 → 666 lines, +285)
    - src/agents/alerter/test/capture.test.js (120 → 236 lines, +116)
decisions:
  - "[37-03] Dropped 'status' from command-keyword regex — listed in PATTERNS.md but no handler exists in snooze.js (planner conjecture). Aligns matcher with actual handlers and lets group-mention fixture remain mention-only as intended."
  - "[37-03] Added optional `@mention<space>` prefix to command regex AND strip same prefix from text before passing to snooze/experiment parsers. This makes '@bot mute' parse identically to 'mute' in group context while leaving DM behavior byte-stable."
  - "[37-03] suppressReply flag passed via ctx (not boolean returned from triggers) — keeps coordination unidirectional (receive-loop decides, capture obeys); audit trail still lands in reply_target_kind row column."
metrics:
  duration: "~25min"
  tasks_completed: 3
  files_modified: 4
  files_created: 1
  completed: "2026-05-11"
---

# Phase 37 Plan 03: Multi-farmer Routing Wire-up — Summary

ROUTE-01/02/03 are now closed in the alerter code path: DM replies route to envelope.source, group messages route to the group via {groupId}, every captured row stamps farmos_person + reply_target_kind for audit, and D-09 envelope-level dedupe is enforced. The 999.20 embarrassment vector is technically closed — production flip waits on Plan 04 wiring SIGNAL_GROUP_ID + SIGNAL_FARMER_MAP into compose.

## What Shipped

### 1. receive-loop.js — group gate + collectGroupTriggers + envelope dedupe (Task 1)

**New pure helper:** `collectGroupTriggers(env, botPhone) -> Set<'mention'|'command'|'quote'>`
- Defensive against both wrapper shapes (`env.envelope.dataMessage` AND `env.dataMessage`).
- Mention: `dataMessage.mentions[].number === botPhone` (E.164, NOT display name — D-06).
- Command: keyword regex `/^\s*(?:@\S+\s+)?(mute|snooze|quiet)\b/i` OR `/^\/(force-|cancel-)/i`. Accepts optional `@<token>` prefix so `@bot mute` triggers `command`.
- Quote: `(quote.author || quote.authorNumber) === botPhone` (Risk #9 defensive against signal-cli field-name drift).
- Exported alongside `createReceiveLoop` for direct unit-test access.

**Per-envelope group gate** (after the existing whitelist gate):
- `groupId = dm.groupInfo?.groupId`, `groupType = dm.groupInfo?.type`.
- `isGroup = !!groupId && groupType !== 'UPDATE' && groupType !== 'QUIT'` (Risk #11).
- `triggers = isGroup ? collectGroupTriggers(env, botPhone) : Set(['dm'])`.
- `shouldReply = triggers.size > 0`.
- `replyTargetKind = isGroup ? (shouldReply ? 'group' : 'none') : 'dm'`.
- `captureCtx = { replyTargetKind, groupId, suppressReply: isGroup && !shouldReply }`.

**Branch gates (D-09 dedupe):**
- `commandBranchAllowed = !isGroup || triggers.has('command')` — gates BOTH `parseExperimentCommand` and `parseSnoozeCommand` blocks.
- `commandText` strips optional `@<token>` prefix in group context only; DM text passes through unchanged.
- The capture branch receives the ctx so capture.js can pick its reply target and skip the send when needed.

**D-05 invariant comment** added at the gate site documenting that VPS heartbeat is direct-to-f1, never via this loop.

### 2. capture.js — replyTarget threading + farmer-map + new row fields (Task 2)

**New factory option:** `signalFarmerMap = new Map()` (default empty Map preserves back-compat).

**handle signature:** `handle(envWrapper, ctx = {})` where `ctx = { replyTargetKind, groupId, suppressReply }`.

**Routing logic** (after envelope unwrap):
```js
const groupId = ctx.groupId ?? (dm.groupInfo?.groupId ?? null);  // standalone fallback
const replyTarget = groupId ? { groupId } : source;
const farmosPerson = signalFarmerMap.get(source) ?? '(unassigned)';
const replyTargetKind = ctx.replyTargetKind ?? (groupId ? 'group' : 'dm');
const suppressReply = ctx.suppressReply === true;
```

**insertCapture** now stamps `group_id`, `farmos_person`, `reply_target_kind` on every row (D-14).

**Send call** (the load-bearing 999.20 line at l.146/170):
```js
if (!suppressReply) {
  await signalClient.send(replyText, { to: replyTarget }).catch(...);
}
```

**Debug logging** of every routing decision (no-op when `logger.debug` is absent — Phase 25/26 logger contract compatibility).

### 3. Full alerter jest suite — verification (Task 3)

**Outcome:** 267 pass / 2 fail / 269 total. Both failures pre-existing and unrelated to Plan 03 scope:
- `config.test.js Test A` — dashboardUrl drift, carried from Plan 37-01 (documented there as deferred).
- `integration.test.js heartbeat_fires_and_bypasses_cap` — introduced by mid-Plan-02-to-03 hotfix `3bc11cb` (`fix(alerter): defer heartbeat when bridge summary is empty`). Test starts alerter and expects immediate heartbeat send without first delivering bridge sample data; the hotfix correctly defers in that state. Both logged in `deferred-items.md`.

No new failures attributable to Plan 03.

## Tests

| File | Pre | New | After | Status |
|------|-----|-----|-------|--------|
| receive-loop.test.js | 10 | 18 | 28 | 28/28 green |
| capture.test.js | 6 | 8 | 14 | 14/14 green |
| (full alerter suite) | — | — | 269 | 267/269 green (2 pre-existing, unrelated) |

Runtime: 13.8s full suite.

## Commits

| Commit | Type | Message |
|--------|------|---------|
| 6ec7397 | test | RED: collectGroupTriggers + group routing integration |
| 2ebc1b7 | feat | GREEN: receive-loop group gate + dedupe |
| 308f4e5 | test | RED: capture.js replyTarget + farmer-map + row fields |
| 0d565c3 | feat | GREEN: capture.js replyTarget threading |
| e01b5a4 | chore | log pre-existing test failures as deferred items |

Five commits, two RED/GREEN pairs + one chore. No --no-verify used.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Command-keyword regex didn't match `@bot mute` fixture**
- **Found during:** Task 1 RED → first GREEN run (`collectGroupTriggers › group-mention-and-command → Set has both` failed).
- **Issue:** PATTERNS.md regex `/^\s*(mute|snooze|quiet|status)\b/i` requires keyword at START. Fixture text `"@bot mute"` starts with `@`. Without a fix, D-09 dedupe target is untestable.
- **Fix:** Added optional `@<token><space>` prefix: `/^\s*(?:@\S+\s+)?(mute|snooze|quiet)\b/i`. Also stripped same prefix from `commandText` before passing to snooze/experiment parsers so `@bot mute` actually dispatches.
- **Files modified:** src/agents/alerter/src/receive-loop.js
- **Commit:** 2ebc1b7

**2. [Rule 3 - Blocking] Dropped `status` from command keyword regex**
- **Found during:** Task 1 RED → group-mention fixture (text `"@bot status"`) tripped both `mention` AND `command` triggers, breaking the "Set.size === 1" assertion.
- **Issue:** PATTERNS.md listed `status` as a command keyword, but snooze.js SIMPLE regex is `(snooze|mute|quiet)` — no `status` handler exists. Planner conjecture, not real behavior.
- **Fix:** Removed `status` from `collectGroupTriggers` regex. Documented in comment.
- **Files modified:** src/agents/alerter/src/receive-loop.js
- **Commit:** 2ebc1b7

Both fixes are surgical: regex pattern adjustments in the new helper + one parse-input substitution. No DM behavior change; verified by re-running existing Tests A–E + capture-fanout cases (all green).

### Acceptance Criteria Status

- Task 1: ✓ All 28 receive-loop tests pass; ✓ `collectGroupTriggers` exported (`grep -c` = 3 — definition + call + module.exports); ✓ `group-mention-and-command` asserts 1 signal send (D-09); ✓ `group-silent` asserts 0 signal sends + 1 capture call with kind=none; ✓ `group-command` from F2 asserts mute dispatched (D-10); ✓ no new VPS heartbeat code paths (only a doc comment added).
- Task 2: ✓ All 14 capture tests pass; ✓ `grep -n "signalClient.send(replyText, { to:" capture.js` returns 1 hit (l.170); ✓ `farmos_person` grep hits ≥2 (assignment l.131 + farmosPerson variable usages); ✓ `reply_target_kind` grep returns 1 (l.132); ✓ `'(unassigned)'` grep returns 2 (comment + code); ✓ DM with map → slug; DM without map → '(unassigned)' + reply still fires.
- Task 3: ✓ jest suite runs end-to-end; ✓ 267/269 passing; ✓ 2 pre-existing failures isolated and documented; ✓ Phase 33 VPS path grep clean (no new matches).

## Threat-model Status

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-37-03-01 (DM leak to group default) | mitigate | ✓ capture.js sets `to: source` explicitly for DM; test asserts shape |
| T-37-03-02 (reply storm via N triggers) | mitigate | ✓ commandBranchAllowed + suppressReply; group-mention-and-command test = 1 send |
| T-37-03-03 (display-name spoofing) | mitigate | ✓ mention matcher uses E.164 number, not name |
| T-37-03-04 (quote field drift) | mitigate | ✓ matcher accepts both `author` and `authorNumber` |
| T-37-03-05 (farmos_person mis-attribution) | mitigate | ✓ static map at boot; unknown → '(unassigned)' literal |
| T-37-03-06 (silent-drop audit gap) | mitigate | ✓ reply_target_kind stamped on every row including 'none' |
| T-37-03-07 (any-farmer mute = global mute) | accept | ✓ unchanged; whitelist gate still enforced |

No new threat flags discovered during execution.

## Back-compat

- DM envelopes: unchanged behavior. Existing snooze, experiment, capture-fanout, R7-whitelist tests all still green.
- Pre-Phase-37 callers of `capturePipeline.handle(env)` continue to work — ctx defaults to `{}`, capture falls back to dm.groupInfo for routing.
- `signalFarmerMap` is optional; empty Map default makes every sender resolve to '(unassigned)' which is the documented unknown-farmer behavior.
- No PII contract change (maskNumber still applied in logs).

## Hand-off to Plan 04

Plan 04 must:

1. **Thread `signalFarmerMap` from index.js into `createCapturePipeline`.** Current boot wiring at `src/agents/alerter/src/index.js` does NOT pass it; capture.js will resolve every sender to '(unassigned)' until this line is added.
2. **Set `defaultTarget` on the signal-client constructor** to `config.signalGroupId ? { groupId: config.signalGroupId } : config.signalRecipient`. Once SIGNAL_GROUP_ID is in `.env`, alerts/heartbeat/snooze acks all flip to group automatically (D-04).
3. **Add env plumbing in docker-compose.override.yml** — `SIGNAL_GROUP_ID` + `SIGNAL_FARMER_MAP` per PATTERNS.md §override block.
4. **Populate operator-attested `.env`** values (the group base64 from `signal-cli --list-groups` and the four-farmer map). Per 37-01-SUMMARY deferred note, requires operator attestation before deploy.

## Threat Flags

None — no new security-relevant surface introduced.

## Self-Check: PASSED

- ✓ All five commits visible in `git log --oneline -10`: 6ec7397, 2ebc1b7, 308f4e5, 0d565c3, e01b5a4
- ✓ All four modified files exist with expected line counts (236 / 190 / 666 / 236)
- ✓ deferred-items.md created at `.planning/phases/37-multi-farmer-routing/deferred-items.md`
- ✓ Full alerter jest run: 267 pass / 2 fail (pre-existing, documented)
- ✓ `grep "signalClient.send(replyText, { to:" src/agents/alerter/src/capture.js` returns 1 hit
- ✓ `grep "collectGroupTriggers" src/agents/alerter/src/receive-loop.js` returns 3 hits (definition + call + export)
- ✓ Phase 33 VPS path grep clean (one comment-only addition documenting D-05)
