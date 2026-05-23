# Phase 50 Live-Fire -- Signal-native quote threading

**Status:** OPERATOR-DEFERRED until prod deploy + manual exercise
**Hermetic ship-gate:** PASS (npx jest test/ green across Plans 50-01..04; Plan 50-04 added 32 new cases; full alerter suite 1036/1045 pass, 9 skipped, 0 fail)
**Operator runbook last revised:** 2026-05-23 (paired with 50-05 SUMMARY)

This document mirrors the [48-LIVE-FIRE.md](../48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md) + [47-LIVE-FIRE.md](../47-multi-source-extraction-fusion-groups-shape-inoc-draft/47-LIVE-FIRE.md) paper-trail format. Phase 50's hermetic suite covers the full producer-to-consumer chain (schema -> outbound persist+send -> dispatch quote-bearing acks -> capture-side quote persistence -> inbound quote routing + numbered ask-back fallback + spoof guard) with mock signal-cli and a fake pool. The live-fire path below is the mock-vs-real proof on the farmer's actual Signal client.

## Why operator-deferred

Per `[[feedback_unit_tests_dont_catch_wiring]]` and the Phase 47/48/49 precedent, live-fire is the proof that the hermetic mocks and the real signal-cli + real Signal client agree on:

- the `quote: {timestamp, author, message}` payload shape that the spike accepted (signal-cli 0.14.2),
- the visual rendering of the ack as a quote-reply bubble on the farmer's phone (Android / iOS Signal client),
- the inbound round-trip of `dataMessage.quote.{id|timestamp, author|authorNumber}` from a real farmer quote-reply through receive-loop -> capture row -> `findDraftByQuotedMsgTs` -> the correct draft (NOT most-recent-active),
- the polite-terminal `send_quote_closed` branch on a real committed draft,
- the numbered ask-back fallback when >1 draft is active AND the farmer's reply carries no quote,
- the fail-open posture when the source capture's `signal_msg_ts` is NULL.

The hermetic tests cannot catch mock drift; only a real farmer phone in the loop can. The Phase 47-05 live-fire already turned up an ask-back path the hermetic tests had over-specified (Gray Area 3). The Phase 50 live-fire is the single irreducible signal that the visual quote-threading mechanism works as designed.

## Prerequisites

1. **Plans 50-01..04 merged + deployed to prod alerter.** From repo root:

   ```bash
   cd /mnt/slime-kingdom/opt/mushy
   git pull
   docker compose up -d --build alerter
   docker logs alerter 2>&1 | tail -200 | grep -E "(initDb|signal_msg_ts|quote_msg_ts|idx_signal_outbound_msg_ts|ALTER TABLE|listening)"
   ```

   Expect: clean boot; the `ADD COLUMN IF NOT EXISTS signal_msg_ts` / `quote_msg_ts` / `quote_author_e164` migrations are idempotent (no error if previously applied). No exception traces.

2. **signal-cli REST 0.14.2 on the bot host.** Spike (2026-05-23) confirmed this version accepts the nested `quote` payload on `/v2/send`. Verify:

   ```bash
   curl -s "http://localhost:8080/v1/about" | jq -r '.version'
   # Expect: 0.14.2 (or higher; do NOT downgrade)
   ```

   If a different version is running, halt: this runbook is only valid against 0.14.2+.

3. **Bot phone reachable.** `+59891840205` (per `[[project_farmer_phone_map]]`) authed in the bot's signal-cli store, online, syncing.

4. **Farmer phone reachable.** Santi's phone (farmer1 / radicheta / Don Santiago per `[[user_santi_radicheta_farmer1_trinity]]`) authed in Signal, online. UI language English (per `[[project_farmer_language_stacks]]` -- Santi en/es/fr; runbook copy is English-only this phase, matching CONTEXT D-08).

5. **`PG_PROD_CONN_STRING` env var set** to prod timescale. Verify by running:

   ```bash
   psql "$PG_PROD_CONN_STRING" -c "SELECT now();"
   ```

6. **Operator has SSH to elder-plops** (alerter logs) + read access to the phase planning dir for the cross-references.

7. **Phase 47/48/49 ship-gates green.** Phase 47 closed 2026-05-23 (commit `0cd3f98`); Phase 48 live-fire runbook merged 2026-05-23 (commit `ebd1f98`). Both are upstream of the commit_outcome_ack pipeline this phase decorates.

8. **DB column presence sanity check.** Confirm Plan 50-01 schema landed in prod:

   ```bash
   psql "$PG_PROD_CONN_STRING" -c "\d signal_outbound" | grep -E "(signal_msg_ts|idx_signal_outbound_msg_ts)"
   psql "$PG_PROD_CONN_STRING" -c "\d signal_capture"  | grep -E "(signal_msg_ts|quote_msg_ts|quote_author_e164)"
   ```

   Expect: `signal_msg_ts bigint` on `signal_outbound`; partial index `idx_signal_outbound_msg_ts`; `signal_msg_ts`, `quote_msg_ts`, `quote_author_e164` columns on `signal_capture`. If any are missing the `initDb()` migration did not run -- recheck Step 1.

## Operator steps

### Step 1 -- Sanity: hermetic suite still green

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
npx jest test/ --no-coverage
```

Expect: full suite green (1036/1045 pass, 9 skipped, 0 fail). If red, do NOT proceed; fix the hermetic regression first.

### Step 2 -- Deploy + boot smoke

```bash
cd /mnt/slime-kingdom/opt/mushy
git log --oneline -10 | grep -E "50-0[1234]"
```

Expect: the four 50-01..04 commits are reachable on the branch deployed to prod. Then:

```bash
docker compose up -d --build alerter
sleep 10
docker logs alerter 2>&1 | tail -100 | grep -E "(initDb|signal_msg_ts|quote_msg_ts|ALTER TABLE|listening|error|exception)"
```

Expect: idempotent ALTER messages OR a clean boot with no errors; `listening` line present.

### Step 3 -- Trigger a fresh commit_failed (the no-asset-ref pattern)

Send a Signal message from Santi's phone (the farmer DM) to the bot (`+59891840205`) that the LLM will extract as an observation BUT cannot commit because the target asset_ref is missing. Use the Phase 45 live-fire repro pattern: a freeform note that names no block.

Example body:

```
harvest of nothing -- shelf was empty today, just a check-in
```

Then wait up to 30 seconds for the bot's commit_outcome_ack to arrive.

Expected:
- A Signal message arrives on Santi's phone from the bot.
- The message is RENDERED AS A SIGNAL QUOTE-REPLY visually attached to the original "harvest of nothing" message bubble. On Android Signal: a small quote-bubble preview appears above the ack body. On iOS Signal: same; if the quoted body is long Signal clips it to "Original message" -- still counts as a hit if the quote round-trips at the data layer.

**Operator action:** take a phone screenshot of the ack bubble showing the quote attachment. Crop to remove any unrelated chats. Save as `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE_ack-quote.png` alongside this runbook. Per T-50-05-02 the screenshot must show ONLY the bot-thread, not other Signal conversations.

### Step 4 -- Verify outbound persistence (QUOT-01 + QUOT-04)

```bash
psql "$PG_PROD_CONN_STRING" -c "SELECT id, signal_msg_ts, intent, related_draft_id, recipient, sent_at FROM signal_outbound WHERE intent='commit_outcome_ack' ORDER BY sent_at DESC LIMIT 5;"
```

Expect:
- Top row has `signal_msg_ts` NOT NULL -- this is the Signal-native ts the farmer will quote back to in Step 5.
- `intent='commit_outcome_ack'`.
- `related_draft_id` is the draft Step 3 created (record this UUID; call it `$DRAFT_A`).

Cross-check the outbound row carried a quote payload by inspecting the alerter logs for the dispatch site that built the quote:

```bash
docker logs alerter 2>&1 | tail -300 | grep -E "(commit_outcome_ack|signal_msg_ts|getCaptureQuoteTarget|quote-target)"
```

Expect: a log line corresponding to the resolved quote target for `$DRAFT_A` (the Plan 50-03 `getCaptureQuoteTarget` resolver path). Attest QUOT-01 (signal_msg_ts persisted) + QUOT-04 (outbound carried the quote payload, evidenced by the screenshot from Step 3 + the resolved-target log line).

### Step 5 -- Farmer quote-reply EDIT (QUOT-02 + QUOT-03)

On Santi's phone, in the bot DM thread:

1. Long-press the bot's ack bubble (the one with the quote attached, from Step 3).
2. Tap **Reply** (the Signal swipe-to-reply gesture also works).
3. Type a real EDIT body using a block name that exists in farmOS at test time. Example:

   ```
   EDIT block 260415_LIMA_1
   ```

4. Send.

Wait ~15s for capture + extraction + routing.

Then verify capture-side persistence:

```bash
psql "$PG_PROD_CONN_STRING" -c "SELECT id, captured_at, sender, signal_msg_ts, quote_msg_ts, quote_author_e164, substr(raw_text,1,80) AS raw_head FROM signal_capture ORDER BY captured_at DESC LIMIT 3;"
```

Expect on the top row:
- `signal_msg_ts` NOT NULL (every inbound now carries this -- QUOT-02).
- `quote_msg_ts` NOT NULL and equal to the `signal_msg_ts` value recorded in Step 4 for the bot's ack row (this is the round-trip).
- `quote_author_e164` equal to the bot's e164 (`+59891840205`) -- the farmer quoted the bot.
- `raw_text` begins with `EDIT block 260415_LIMA_1`.

Then verify the routing matched the EXACT quoted draft, not the most-recent-active:

```bash
docker logs alerter 2>&1 | tail -200 | grep -E "(findDraftByQuotedMsgTs|quote-resolve|spoof guard|quote_msg_ts|routing|EDIT)"
```

Expect:
- A log line from `receive-loop.js` confirming the quote resolved to a draft (no `quote-resolve failed`, no `quote spoof guard`).
- The resolved `draftRow.id` equals `$DRAFT_A` (from Step 4).
- The EDIT path proceeded against `$DRAFT_A`, NOT against any other awaiting draft.

Attest QUOT-02 (capture wrote `signal_msg_ts` + `quote_msg_ts`) + QUOT-03 (routing matched the quoted draft).

### Step 6 -- Polite-terminal path (QUOT-03 terminal branch)

Continue from Step 5. Let the EDIT extract + commit successfully (or YES through the resulting confirm prompt). The draft `$DRAFT_A` is now in `committed` status.

Confirm:

```bash
psql "$PG_PROD_CONN_STRING" -c "SELECT id, status, updated_at FROM signal_draft WHERE id='$DRAFT_A';"
```

Expect: `status='committed'` (or `discarded` if the operator went down the NO branch -- both are terminal).

Now on Santi's phone, long-press the **same original ack bubble from Step 3** (the one for `$DRAFT_A`), Reply, type:

```
NO
```

Send. Wait ~10s.

Expected:
- The bot responds with a polite "that one is already closed" ack. Body shape (per Plan 50-04 SUMMARY) uses the Phase 45 Plan-06 disambiguator:

  ```
  That {date} {log_type} ({summary}) is already saved. n/a
  ```

  Status word `committed` maps to `saved`; `discarded` -> `discarded`.
- The draft `$DRAFT_A` status stays `committed` (or `discarded`). No new mutation. No second commit attempt.

Verify via logs + DB:

```bash
docker logs alerter 2>&1 | tail -100 | grep -E "(send_quote_closed|quote_closed|already closed|already saved)"
psql "$PG_PROD_CONN_STRING" -c "SELECT id, status, updated_at FROM signal_draft WHERE id='$DRAFT_A';"
```

Expect:
- `[outbound-confirm] send_quote_closed sent draft=... status=committed` (or `=discarded`) -- the exact log line from `outbound-confirm.js:291`.
- Draft `$DRAFT_A` `updated_at` did NOT change since the commit; no new state transition.

Attest QUOT-03 polite-terminal branch.

### Step 7 -- Numbered ask-back fallback (QUOT-06)

Engineer two simultaneously-active drafts:

(a) On Santi's phone, send a capture that produces a confirm prompt. Example:

```
seeded a tray of SHI today, 12 jars
```

Wait for the bot's confirm prompt. Do NOT YES/NO yet.

(b) Send a second capture, different shape:

```
relocated block 260118_KOY_12 to shelf 3
```

Wait for the bot's second confirm prompt. Do NOT YES/NO yet.

Verify both drafts are simultaneously active:

```bash
psql "$PG_PROD_CONN_STRING" -c "SELECT id, status, log_type, updated_at FROM signal_draft WHERE sender_e164='<santi-e164>' AND status IN ('awaiting_farmer','commit_failed') ORDER BY updated_at DESC;"
```

Replace `<santi-e164>` with Santi's actual e164 (per `[[project_farmer_phone_map]]`). Expect: at least 2 rows in actionable statuses.

Now send a PLAIN-TEXT EDIT to the bot (do NOT use Signal's swipe-to-reply or long-press-Reply; just type a fresh message):

```
EDIT something
```

Send.

Expected:
- The bot responds with a numbered ask-back, body shape per Plan 50-04:

  ```
  Which one are you replying about?
  1. {date} {log_type} ({summary})
  2. {date} {log_type} ({summary})
  Reply with the number, or quote the original message.
  ```

- NO draft mutation this turn.

Verify via logs:

```bash
docker logs alerter 2>&1 | tail -100 | grep -E "(send_ask_back|ask_back|Which one)"
```

Expect: `[outbound-confirm] send_ask_back sent n=2 sender=...` (exact log line from `outbound-confirm.js:276`).

Attest QUOT-06.

**Cleanup:** clear both engineered drafts so prod doesn't accumulate orphans. Either YES/NO each one through the bot (preferred), or DELETE via psql if the YES path would write garbage to farmOS:

```bash
# Preferred: walk each draft through the confirm flow on the phone.
# Fallback if needed:
psql "$PG_PROD_CONN_STRING" -c "UPDATE signal_draft SET status='discarded', updated_at=now() WHERE id IN ('<draft-b-id>','<draft-c-id>');"
```

### Step 8 -- Fail-open posture (QUOT-05)

Engineer a draft whose source capture is intentionally missing `signal_msg_ts`. This proves the ack still fires when the quote target is null -- no exception, no silent failure (per `[[feedback_no_silent_failure_after_farmer_confirm]]`).

(a) Send a fresh capture that will produce a commit_failed (use the Step 3 pattern). Wait for the ack. Note the new draft id (`$DRAFT_D`) and its first `source_capture_ids[0]` value (`$CAP_D`):

```bash
psql "$PG_PROD_CONN_STRING" -c "SELECT id, source_capture_ids FROM signal_draft ORDER BY updated_at DESC LIMIT 1;"
```

(b) NULL the capture's `signal_msg_ts`:

```bash
psql "$PG_PROD_CONN_STRING" -c "UPDATE signal_capture SET signal_msg_ts = NULL WHERE id='$CAP_D';"
```

(c) Re-trigger an ack for `$DRAFT_D`. The simplest path: do nothing on the farmer side -- the next outbound dispatch tied to this draft (e.g. via the commit-watchdog re-evaluation) will resolve a NULL quote target. Alternative: manually trigger by sending an EDIT to the bot that lands on `$DRAFT_D`, forcing a new ack.

(d) Verify the ack arrived on Santi's phone UNQUOTED but still containing the Plan-06 disambiguator template (date + summary):

   - On the phone: ack bubble has NO quote attachment but reads e.g. `Saved May 23 observation (...). n/a` (or the commit_failed equivalent).

(e) Verify logs:

```bash
docker logs alerter 2>&1 | tail -100 | grep -E "(no quote target|getCaptureQuoteTarget|signal_msg_ts NULL)"
```

Expect: a warn line indicating the quote target lookup returned null for `$DRAFT_D`; the ack still dispatched without exception.

(f) Confirm `signal_outbound` recorded the ack:

```bash
psql "$PG_PROD_CONN_STRING" -c "SELECT id, signal_msg_ts, intent, related_draft_id FROM signal_outbound WHERE related_draft_id='$DRAFT_D' ORDER BY sent_at DESC LIMIT 3;"
```

Expect: a row with `intent='commit_outcome_ack'`; `signal_msg_ts` NOT NULL (the bot's own outbound ts is still recorded even though no inbound quote target was attached). This is the Plan-02 persistence path.

Attest QUOT-05.

**Cleanup:** restore `signal_msg_ts` on the engineered capture if needed (so future quote lookups against `$CAP_D` resolve correctly):

```bash
# Only if the original value is recoverable from logs; otherwise leave NULL --
# the row is now functionally orphan-quote-able, which matches what Step 8 was testing.
```

### Step 9 -- Append the Result

Fill the Result section below. Per T-50-05-03 the paper trail is mandatory. Include:

- Date, Operator
- Elapsed wall-clock time for Steps 3-8
- Screenshot file references (Step 3 ack-quote; optionally Step 7 ask-back)
- Draft UUIDs touched (`$DRAFT_A`, B, C, `$DRAFT_D`)
- Capture UUIDs touched (`$CAP_D` for Step 8)
- psql output excerpts: top `signal_outbound` row from Step 4, top `signal_capture` row from Step 5, `signal_draft.status` from Step 6
- Per-requirement verdict: QUOT-01..06 PASS / FAIL
- Deviations observed (any failure mode -- file as Phase 50.x follow-up per Deviation policy below)
- Overall verdict

### Step 10 -- Cleanup

Phase 50 writes NO farmOS assets (unlike Phase 48). The only persistent state changed:

- Engineered drafts from Step 7 -- cleaned up in Step 7.
- `signal_capture.signal_msg_ts = NULL` on `$CAP_D` from Step 8 -- leave as-is (the row is paper trail for the fail-open attestation).
- Screenshots from Steps 3 + (optional) 7 stay committed to `.planning/phases/50-signal-native-quote-threading/` as evidence.

No farmOS cleanup is required.

## Deviation policy

Any failure of QUOT-01..06 FAILS the gate. The runbook is amended with the failure mode; a follow-up phase (Phase 50.x) is opened to address it. Do NOT silently patch in Phase 50-05.

Common failure modes to be alert for (drawn from spike + memory + Plan-04 hermetic surface):

1. **signal-cli responds 4xx on quote-bearing `/v2/send`** -- indicates version drift; spike pinned 0.14.2. If the bot host has been upgraded since merge, downgrade or pin before re-running.

2. **Signal client renders the quote as "Original message" rather than a full bubble** -- CONTEXT D-09 acknowledges Signal sometimes clips long quotes. NOT a failure if the message_id round-trips correctly (Step 5 psql shows `quote_msg_ts` populated). Operator should screenshot both Android and iOS if available to capture the rendering difference.

3. **Numbered ask-back fires when only 1 draft is active** -- regression of QUOT-06. FAIL. The `activeDrafts.length > 1` guard in `receive-loop.js:280` is the only gate; if this fires with 1 active, the gate is broken.

4. **`findDraftByQuotedMsgTs` returns most-recent-active when a quote target IS present** -- regression of QUOT-03. FAIL. The expected behavior is "quote wins"; if the routing fell through to the active-drafts list despite a populated `quote_msg_ts`, the JOIN logic in `confirm-db.js` is broken or the partial index is missing.

## Result

(empty -- to be filled in by the operator who runs Steps 2-9 against prod)

```
### Run <N>
Date:
Operator:
Elapsed:
Screenshots:
  Step 3 ack-quote:
  Step 7 ask-back (optional):
Drafts touched:
  $DRAFT_A:
  Step 7 draft B:
  Step 7 draft C:
  $DRAFT_D:
Captures touched:
  $CAP_D:
psql excerpts:
  Step 4 signal_outbound top row:
  Step 5 signal_capture top row:
  Step 6 signal_draft.status after polite-terminal:
Per-requirement verdict:
  QUOT-01 (signal_outbound.signal_msg_ts populated):
  QUOT-02 (signal_capture.signal_msg_ts populated):
  QUOT-03 (quote-resolved routing wins; terminal branch polite-acks):
  QUOT-04 (outbound ack carries the quote payload):
  QUOT-05 (fail-open: NULL quote target still sends ack, no exception):
  QUOT-06 (numbered ask-back fires only when >1 active AND no quote):
Deviations:
Verdict (PASS / FAIL):
```

## Files

- Schema migrations: `src/agents/alerter/src/outbound-db.js` (`signal_msg_ts` + index), `src/agents/alerter/src/capture-db.js` (`signal_msg_ts`, `quote_msg_ts`, `quote_author_e164`)
- Outbound send + persist: `src/agents/alerter/src/signal.js`, `src/agents/alerter/src/outbound-db.js`
- Outbound quote dispatch: `src/agents/alerter/src/confirm/outbound-confirm.js`
- Capture-side quote persistence: `src/agents/alerter/src/capture.js`, `src/agents/alerter/src/receive-loop.js`
- Quote resolver + list-shape sibling: `src/agents/alerter/src/confirm/confirm-db.js` (`findDraftByQuotedMsgTs`, `findActiveDraftsForSender`)
- Disambiguator helper: `src/agents/alerter/src/farmos/commit-outcome-preview.js` (`buildDisambiguator`, `labelFor`)
- Receive-loop routing: `src/agents/alerter/src/receive-loop.js:225-289` (quote-first + spoof guard + numbered ask-back fallback)
- Hermetic tests: `src/agents/alerter/test/{capture-db,capture}.test.js`, `src/agents/alerter/test/confirm/{confirm-db,outbound-confirm,receive-loop-confirm}.test.js`
- Test fixtures: `src/agents/alerter/test/fixtures/envelopes/text-quote-reply{,-authornumber-only}.json`

## Cross-references

- [45-05-SUMMARY.md](../45-north-star-commit-failed-ack-replay-outstanding-silent-failu/45-05-SUMMARY.md) -- the live-fire that surfaced the ambiguity this phase closes
- [47-LIVE-FIRE.md](../47-multi-source-extraction-fusion-groups-shape-inoc-draft/47-LIVE-FIRE.md) -- live-fire shape reference (paper-trail precedent)
- [48-LIVE-FIRE.md](../48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md) -- live-fire shape reference (closest structural template)
- [49-SHIP-GATE.md](../49-real-session-eval-corpus-may-22-ship-gate-reprocess/49-SHIP-GATE.md) -- operator-deferred runbook precedent
- [50-CONTEXT.md](./50-CONTEXT.md) -- phase decisions + spike findings
- [50-04-SUMMARY.md](./50-04-SUMMARY.md) -- the routing + ask-back mechanism this runbook exercises
- Memory: `[[feedback_unit_tests_dont_catch_wiring]]`, `[[feedback_no_silent_failure_after_farmer_confirm]]`, `[[feedback_verify_signal_send_attribution]]`, `[[project_phase45_followon_edit_no_disambiguation]]`
