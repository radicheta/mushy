---
phase: 36-signal-pre-gate
plan: 02
status: complete-no-op
completed_utc: 2026-05-11
outcome: PRE-01 already met; live re-registration NOT performed
---

# Plan 36-02 — Author runbook + live re-registration — SUMMARY

## TL;DR

**Live re-registration was NOT performed because Phase 36 SC#1 was already empirically satisfied.** Plan 36-02 Task 1 (the runbook) shipped fully. Task 2 (live re-reg execution) was aborted after pre-flight discovery proved unnecessary. Task 3 (kickoff sends) was rolled into an ad-hoc receive-channel verification instead.

## What was built

| Task | Status | Output |
|------|--------|--------|
| Task 1 — Author `36-RUNBOOK.md` | ✅ Shipped | `.planning/phases/36-signal-pre-gate/36-RUNBOOK.md` (245 lines, 9 sections, no E.164 leaks). Stays in repo as the abort-path runbook in case re-reg becomes needed later (e.g. SIM swap, image regression that re-breaks linked-secondary receive). |
| Task 2 — Live re-registration | ❌ Skipped (no-op) | Pre-flight evidence proved `/v1/receive` already returns HTTP 200 + alerter receives whitelisted DMs end-to-end. The "deviceId=2 linked-secondary → broken receive" premise from Phase 25 is not currently true on `bbernhard/signal-cli-rest-api:0.200-dev`. |
| Task 3 — Kickoff sends to farmers | ⚠ Pivoted | Replaced with ad-hoc ping/pong tests to f1 + f2 to verify SC#1 + SC#2 empirically. Tests passed (see Pre-flight findings below). |

## Pre-flight findings — why we skipped re-registration

### Evidence trail

1. **First captcha-token attempt at 18:03 UTC** returned `HTTP 400: Account is already registered (IOException)` — signal-cli local state IS a registered linked-secondary; not a clean fresh-install state.

2. **18h log analysis (2026-05-11 00:00 → 18:00 UTC):** `/v1/receive/+<BOT>` returned **HTTP 200 — 2171 times, zero 400s.** The Phase 25 receive-400 symptom is gone.

3. **Real inbound proof at 15:24 UTC:** alerter logged `[receive] rejected sender (not in whitelist)` — meaning a real inbound envelope arrived from signal-cli `/v1/receive`. Transport layer works.

4. **Live ping/pong test at 18:11 UTC** with token `P36-181143`:
   - Bot → f1 (`+5...93012`): HTTP 201 send, msg_ts `1778523106354`
   - Bot → f2 (`+5...18597`): HTTP 201 send, msg_ts `1778523126738`
   - **f1 pong "Pong2"** → captured at 18:22:17 → LLM-replied at 18:22:25 (DB row `01KRC4D3RFBMVAFDQZKFZWPF8E`)
   - **f2 pong "pong P36-181143"** → captured at 18:23:18 → LLM-reply fired (DB confirmed)
   - **All 3 reply sends went to f1** (`+5...93012`) — known 999.20 routing bug, NOT a Phase 36 bug

### Conclusion

The PRE-01 success criterion ("make `/v1/receive` return 200") is **empirically satisfied without re-registration**. SC#2 (round-trip from f1 + f2) is also already met. Live re-reg would have been destructive (rotates the bot's identity key → forces every farmer through a "safety number changed" warning → 999.20 reply-routing bug would have made the kickoff message MORE confusing, not less). No-op was the correct call.

## Two real bugs fixed along the way

### Bug 1: `SIGNAL_ADDITIONAL_SENDERS` not plumbed through to alerter container

**Discovery:** f2's pong arrived at signal-cli but was rejected by alerter's whitelist gate (`receive-loop.js:102`). Live container env inspection showed only `SIGNAL_SENDER` + `SIGNAL_RECIPIENT` were set — `SIGNAL_ADDITIONAL_SENDERS` was in `.env` but absent from `docker-compose.override.yml`'s alerter env block.

**Fix:** added `- SIGNAL_ADDITIONAL_SENDERS=${SIGNAL_ADDITIONAL_SENDERS}` at `docker-compose.override.yml:77`. Commit `c8e9ac1`.

**Impact:** unblocks f2 + f3 inbound DM capture for current production (they were silently invisible before). 999.20 reply-routing still needs separate fix.

### Bug 2: Plan 36-03 script field-name + bash `read` edge case

**Discovery:** while running the post-rebuild-trust-check.sh smoke test, the script crashed with `verdict=recovery_failed status=""`. Trace revealed two issues:
- Field name mismatch: bbernhard/signal-cli-rest-api v1 `/v1/identities` returns `.status`, not `.trust_level` (the plan documented `.trust_level` — appears to be from a different signal-cli output mode).
- `IFS=$'\t' read -r number status` collapsed leading empty fields when an identity row had empty `number` (the unnamed sync-target entry with uuid `3fc44380...`).

**Fix:** in Plan 36-03's commit (`0c05807`): renamed field throughout + switched IFS to `|` with jq pre-filter to skip empty-number rows. Bats + live smoke both green.

## Artifacts retained for future re-reg scenarios

- `36-RUNBOOK.md` — full operator recipe; still valid if SIM swap, image regression, or a real hard_mismatch ever requires re-registration
- `/mnt/slime-kingdom/mushy-backups/signal-cli-data-20260511.tar.gz` (99M) — rollback tarball; restore recipe in `36-01-preflight-snapshot.md` § Restore Recipe
- `snapshots/devices-20260511.json` + `snapshots/identities-20260511.json` — pre-this-session state for diffing (`devices` shows id=1 + id=2; `identities` shows 5 entries with redacted E.164/UUIDs)
- 999.52 backlog item — Phase 35 Tier A doesn't bundle signal-cli volume; the local tarball is still the only off-site-eligible rollback path until 999.52 lands

## Captcha token disposition

The captcha token captured at 18:03 UTC was consumed by Signal's server even though signal-cli rejected the request locally. It's now invalid; future re-reg attempts (if ever needed) require a fresh capture from https://signalcaptchas.org/registration/generate.html.

## Decisions made during execution

- **No-op re-reg.** Decided after live evidence accumulated. Logged as a deviation from the original Plan 36-02 Task 2 spec.
- **f3 NOT bothered for the verification cycle** per operator instruction (iOS device less-easily-coordinated; existing whitelist plumbing means f3 will work the same way).
- **Plan 36-03 Task 2 baseline source changed** from "post-reg identity snapshot" to "current live identity" (since no re-reg means no post-reg snapshot).

## What's still pending

- **Plan 36-04 farmer attestation** — D-13 requires the same round-trip RE-RUN 24h later (~2026-05-12 18:00 UTC) + D-14 rebuild attestation. The rebuild half was incidentally completed during this session (alerter rebuild at 18:29 UTC ran the new healthcheck → verdict=ok). T+24h re-run is still on the calendar.
- **999.20 reply-routing bug** — empirically reproduced twice today (f2 → reply landed on f1). Should priority-bump in the backlog before the next farmer-facing feature.

## Verification

```
$ grep -c "## " .planning/phases/36-signal-pre-gate/36-RUNBOOK.md
10
$ docker logs --since 24h mushy-signal-cli-1 2>&1 | awk -F'|' '/GET/ && /v1\/receive/ {gsub(/ /,"",$2); print $2}' | sort | uniq -c
   2171 200
$ docker exec mushy-timescale-1 psql -U postgres -tA -c "SELECT sender FROM signal_capture WHERE captured_at > now() - interval '10 min'"
+59892893012
+59892893012
+59898018597
```

PRE-01 satisfied empirically. Receive transport is healthy.
