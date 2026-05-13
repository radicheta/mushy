# Phase 39 LIVE UAT runbook

**Operator:** Don Santiago
**Target sender (dry-run):** Don Santiago's own phone
**Target sender (promotion):** farmer #1 / farmer #2 once dry-run passes
**Date executed:** _TBD_

## Preflight

Run these checks before the first scenario; abort and fix if any fail.

- [ ] alerter container running on elder-plops: `docker compose ps mushy-alerter` returns healthy
- [ ] Phase 39 env vars set or defaulted: `docker compose exec mushy-alerter env | grep -E 'DRAFT_PENDING|DRAFT_NUDGE|DRAFT_WATCHDOG|MAX_EDIT'` shows all four
- [ ] signal_draft has the new columns: `psql -c '\d signal_draft' | grep -E 'edit_turn_count|nudge_sent_at|confirmed_at|discarded_at|expired_at|terminal_reason'` shows six rows
- [ ] signal_draft_event table exists: `psql -c '\d signal_draft_event'` succeeds
- [ ] Watchdog started: `docker compose logs mushy-alerter --tail 200 | grep '\[watchdog\] started'` returns a line with `timeout=30min nudge=24min`

## Scenarios

### 1. YES happy path (CONF-01, CONF-02)

1. From Don Santiago's phone, send a clean seeding message via Signal DM to the bot:
   `seeded 7 blocks of shiitake into 260513_SHI_1 just now`
2. Wait for the bot's awaiting_farmer preview. Should contain `Reply YES to commit, NO to discard, EDIT <text> to amend.`
3. Reply `YES`.
4. Expect: `Locked in. Writing now. (draft <truncId>)`
5. Validate: `psql -c "SELECT status, confirmed_at, terminal_reason FROM signal_draft WHERE id='<id>'"` returns `confirmed | <ts> | farmer_yes`
6. Validate: `psql -c "SELECT event FROM signal_draft_event WHERE draft_id='<id>' ORDER BY seq"` includes one `yes` event.

### 2. Duplicate YES no-op (CONF-02)

1. Reply `YES` to the same preview a second time.
2. Expect: `Already locked in. Check the previous message.`
3. Validate: only one `yes` event row in signal_draft_event for the draft.

### 3. NO discard (CONF-03)

1. Send a fresh seeding message.
2. Reply `NO` to the preview.
3. Expect: `Discarded. Nothing written.`
4. Validate: `SELECT status FROM signal_draft WHERE id='<id>'` returns `discarded`. Original signal_capture row(s) for the source captures remain intact.

### 4. EDIT loop with cap at 3 tries (CONF-04)

1. Send a seeding message with an intentional ambiguity, e.g. `seeded blocks of shiitake into 260513_SHI_1` (qty omitted or wrong).
2. After the preview, reply `EDIT qty was 12`.
3. Expect: new preview with `qty: 12`.
4. Reply `EDIT actually species is OYS`.
5. Expect: new preview with `species: OYS`.
6. Reply `EDIT timestamp was 10am not 2pm`.
7. Expect: new preview with adjusted event_timestamp.
8. Reply `EDIT one more thing`.
9. Expect cap message: `I cannot get this right after 3 tries. Try splitting the message into smaller updates, or send NO to discard.`
10. Validate: `SELECT edit_turn_count, status, terminal_reason FROM signal_draft WHERE id='<id>'` returns `3 | needs_review | edit_cap_exceeded`.

### 5. Timeout + nudge (CONF-05)

For a fast dry-run, temporarily lower the timeout in elder-plops `.env`:
```
DRAFT_PENDING_TIMEOUT_MIN=5
```
restart alerter, then:

1. Send a fresh seeding message. Note the time.
2. Do NOT reply.
3. After ~4 minutes (0.8 * 5), expect a nudge: `Still want to lock in this draft? Reply YES / NO / EDIT or it auto-expires in 1 min.`
4. After ~5 minutes total, expect: `Draft expired. Nothing was written. Send a fresh message if you still want to log this.`
5. Validate: `SELECT status, nudge_sent_at, expired_at, terminal_reason FROM signal_draft WHERE id='<id>'` returns `expired | <ts> | <ts> | timeout_expired`.
6. Validate: NO Phase 40 farmOS write occurred for this draft (CONF-05 critical: stale drafts never auto-commit).
7. Revert the timeout env back to 30 and restart alerter.

## Observability checklist

- [ ] `docker compose logs mushy-alerter --tail 200 | grep -E '\[receive\]|\[watchdog\]|\[outbound-confirm\]'` shows one log line per state transition.
- [ ] `psql -c "SELECT event, count(*) FROM signal_draft_event GROUP BY event"` reflects the UAT activity (yes / no / edit / nudge_sent / expired / edit_cap_exceeded).

## Rollback

```
docker compose stop mushy-alerter
git revert <merge-commit-for-phase-39>
docker compose up -d --build mushy-alerter
```

Schema columns and signal_draft_event table remain (idempotent, harmless). The
receive-loop reverts to Phase 38 behavior; the alerter stops driving the
confirm state machine on inbound replies.

## Sign-off

| Date | Operator | Outcome |
|------|----------|---------|
| _TBD_ | Don Santiago | _PASS / FAIL / PARTIAL_ |
