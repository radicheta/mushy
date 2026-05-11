# Phase 37 Wave 0 Smoke Probe

**Date:** 2026-05-11
**Host:** elder-plops
**signal-cli image:** `bbernhard/signal-cli-rest-api:0.200-dev` (REST `/v1/about` → `{"version":"0.200","capabilities":{"v2/send":["quotes","mentions"]}}`)
**deviceId:** 1 (current, post-Phase 36)
**Bot phone:** `+5XXXXXX0205` (masked; last 4 = 0205)
**Group:** "Mush Farm"
**Group internal_id:** `hKw0KX1gte8Mnjw7fMlMCsPc7s/g3drpkpVsBwPcxwE=`
**Group `id`:** `group.aEt3MEtYMWd0ZThNbmp3N2ZNbE1Dc1BjN3MvZzNkcnBrcFZzQndQY3h3RT0=`

> Send path required `id` field (already prefixed `group.<b64>`), not `internal_id`. Probe A's first attempt used `group.<internal_id>` and signal-cli returned `400 Invalid identifier`. Second attempt with the `id` value succeeded. Plan 37-04 RUNBOOK should call this out (or 37-02/03 can normalize internally).

## Probe A — bot → group send (A3)

```
POST /v2/send {"message":"Phase 37 smoke A — please ignore","number":"+5XXXXXX0205","recipients":["group.aEt3MEtYMWd0ZThNbmp3N2ZNbE1Dc1BjN3MvZzNkcnBrcFZzQndQY3h3RT0="]}
```

**Response:** `HTTP 201` `{"timestamp":"1778531911121"}` — **A3 PASS** (deviceId=1 supports group sends).

## Probe B — silent group message (groupInfo shape)

Source: f1 (`+5XXXXXX3012`). Message: `B (silent)`.

```json
"groupInfo": {
  "groupId": "hKw0KX1gte8Mnjw7fMlMCsPc7s/g3drpkpVsBwPcxwE=",
  "groupName": "Mush Farm",
  "revision": 7,
  "type": "DELIVER"
}
```

> Real envelope carries `groupName` and `revision` in addition to `{groupId, type}` from the planner's spec. Bonus fields — Plan 37-03's group detector only needs `groupId` (+ `type === "DELIVER"` for safety), the rest are ignored.

## Probe C — @mention of bot (A2 / Risk #10)

Source: f1. Message text: `C ￼ status` (the ￼ object-replacement char is Signal's placeholder for the inline mention).

```json
"mentions": [
  { "name": "+5XXXXXX0205",
    "number": "+5XXXXXX0205",
    "uuid": "c7a02a9d-70df-465b-82a1-264246481976",
    "start": 2,
    "length": 1 }
]
```

**A2 PASS** — REST mode emits `mentions[]` with `{name, number, uuid, start, length}`. Per D-04 the matcher uses `number`, not `name`/`uuid`. Note `name` defaulted to the bot's phone (bot has no Signal profile name set on this account), not a display name — matcher must not rely on `name` semantics.

## Probe D — reply-to-bot quote (A1 / Risk #9)

Source: f1. Message: `D reply`. Quoted: the bot's "Phase 37 smoke A" message from Probe A.

```json
"quote": {
  "id": 1778531911121,
  "author": "+5XXXXXX0205",
  "authorNumber": "+5XXXXXX0205",
  "authorUuid": "c7a02a9d-70df-465b-82a1-264246481976",
  "text": "Phase 37 smoke A — please ignore",
  "attachments": []
}
```

**A1 PASS — BOTH fields populated.** `author` AND `authorNumber` carry the bot E.164. `authorUuid` is also present. Plan 03's reply-to-bot detector should accept any of `quote.author`, `quote.authorNumber`, or `quote.authorUuid === bot.uuid` for defensive coverage. Fixture `group-reply-to-bot.json` populates both phone fields (matching observed shape).

**QUOTE_AUTHOR_FIELD observation for fixture-authoring:** BOTH `author` and `authorNumber` — populate both.

## Verdict

**Wave 0 gate: PASS.**

- A1 ✓ — quote present, BOTH `author` and `authorNumber` carry bot E.164.
- A2 ✓ — `mentions[]` populated in REST mode with `number` field.
- A3 ✓ — bot→group send returned HTTP 201 on deviceId=1.

## Deferred / follow-ups

- **Send-path identifier shape (`id` vs `internal_id`):** the REST endpoint `/v1/groups/.../` returns both. Send accepts only the `id` (already-prefixed) form. Plan 37-02's `signal.js` group-send wrapper should accept a bare internal_id and prepend `group.` itself, or document the prefixed-form requirement clearly. Not a blocker — captured here so 37-02 picks it up.
- **Mention `name` field:** matched the phone (account has no profile name). Real farmers' mentions may carry a display name. D-04 says ignore `name` anyway; this just confirms it.
- Capture process required stopping `mushy-alerter-1` for ~2 minutes (the running alerter drains the receive queue before any external curl can). Plan 37-03's tests use fixtures, so this is a one-time inconvenience. Not worth a follow-up unless we need live group capture again.

## Jest baseline

`npx jest` (from `src/agents/alerter`): **215 passed / 216 total / 10.4s**. **1 pre-existing failure** (not fixture-related):

- `test/config.test.js › config.load › Test A: returns object with all fields populated from defaults`
  - Expected `cfg.dashboardUrl === 'http://elder-plops-ts:8081/farmer'`
  - Received `'http://100.96.10.66:8080/'` — matches `src/config.js:67` current default
  - Cause: test assertion predates a config default change (no `DASHBOARD_URL` in repo `.env`, so the failure is from defaults). Verified pre-existing by running jest with the 6 new fixtures stashed — same failure. **Deferred → file as 999.x to either update the default in `config.js` or update the assertion.**

All 18 other test suites green. The six new fixture files coexist with the existing suite (no glob-based loader trips on them).
