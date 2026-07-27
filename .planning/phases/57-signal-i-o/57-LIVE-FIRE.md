# Phase 57 Live-Fire Operator Runbook

**Plan:** 57-04
**Gate:** SC#1 (signal_msg_ts non-null bigint) + SC#3 (native quote bubble)
**Type:** Manual -- operator must run against real signal-cli container with prod secrets.

---

## SC#1 Interpretation (explicit -- not silent)

ROADMAP SC#1's "receives a reply" clause is satisfied by **two conditions together**:

1. **Self-send landing:** The bot->bot message (harness Step 1) lands on the bot device
   (the operator can see it in the bot's own Signal client). The `signal_outbound.signal_msg_ts`
   column is non-null bigint for both rows, proving the send returned a real Signal timestamp
   and it was stored correctly.

2. **Plan-02 receive() unit coverage:** `SignalClient.receive()` is covered at the unit level
   (mocked httpx), proving the receive leg parses envelopes correctly.

**The live inbound drain (a running receive loop consuming farmer traffic) is DEFERRED to
Phase-58 live-fire.** This is consistent with RESEARCH A4 and the dual-poller `/v1/receive`
drain hazard (A3). Phase 57 MUST NOT start a second poller on the farmer-facing account.

This is the loose-but-intended reading of SC#1, recorded here so the gate is explicit.

---

## Pre-Flight

Before running the harness:

1. **Check dual-poller contention (RESEARCH A3).**
   The live Node `alerter` polls `/v1/receive` on the shared `signal-cli` container every 30s.
   The harness does NOT poll `/v1/receive` (T-57-04-01) -- it only POSTs `/v2/send`.
   The self-send bot->bot pattern means neither the test send NOR the bot device's inbound
   will be consumed by the live alerter's receive loop (the live alerter ignores self-to-self).
   No action required -- the harness is safe to run while the alerter is live.

2. **Confirm real env is sourced.**
   The harness reads `SIGNAL_SENDER`, `TIMESCALE_PASSWORD`, `SIGNAL_API_URL`, etc. via
   `TenantConfig.load()`. These must be present in-process.
   Typical approach: `set -a; source tenants/mossrock/secrets.env; set +a` before running.

3. **Confirm the `signal-cli` container is up.**
   ```bash
   docker compose ps signal-cli
   ```

---

## SC#1: Round-trip signal_msg_ts Verification

**Run the harness:**
```bash
cd src/farm-agent && uv run python scripts/live_fire_57.py
```

**Expected terminal output (abridged):**
```
INFO  Live-fire harness starting -- self-send bot->bot to +59891840205
INFO  No /v1/receive poller started (T-57-04-01: no dual-poller hazard).
INFO  [Step 1] Sending plain message (intent=live_fire_57) ...
INFO  [Step 1] SENT  timestamp=<bigint>
INFO  [Step 2] Sending quote-threaded message (quotes Step 1) ...
INFO  [Step 2] SENT  timestamp=<bigint>
INFO  [Step 3] Querying signal_outbound for both rows ...

--- signal_outbound rows (intent='live_fire_57', latest 2) ---
    id    signal_msg_ts  pg_typeof  intent
------------------------------------------------------------
 <id>     <timestamp>     bigint  live_fire_57  [OK]
 <id>     <timestamp>     bigint  live_fire_57  [OK]

SC#1 PASS: signal_msg_ts is non-null bigint for both rows.
```

**Manual SQL confirmation (optional):**
```sql
SELECT id, signal_msg_ts, pg_typeof(signal_msg_ts), intent
FROM signal_outbound
WHERE intent = 'live_fire_57'
ORDER BY sent_at DESC
LIMIT 2;
```
Both rows must return `non-null bigint` for `pg_typeof`.

**Acceptance:** SC#1 PASS printed by harness, confirmed by SQL query.

---

## SC#3: Native Quote Bubble Verification

After the harness exits with PASS:

1. On the bot's own Signal client (the `+59891840205` device / any linked viewer),
   open the bot's own conversation thread.

2. Locate the two new messages (most recent, tagged with the harness text
   "Phase 57 live-fire").

3. **Confirm the SECOND message renders as a NATIVE QUOTE BUBBLE** quoting the
   first message -- a visual indented/highlighted box showing the Step 1 message
   content above the Step 2 body.

4. Compare to `50-LIVE-FIRE_ack-quote.jpg` (Phase 50 spike screenshot) for the
   expected visual shape.

5. **Screenshot** the quote bubble and attach it to this file or a sibling
   `57-04-sc3-quote.jpg`.

**If the quote does NOT render natively on 0.200-dev (RESEARCH A2 risk):**
- Capture the raw `/v2/send` request payload and response from harness logs.
- Flag a shape-drift finding: the `{quote:{timestamp,author,message}}` payload
  that was accepted by signal-cli `0.14.2` (Phase-50 spike) may need adjustment
  for `0.200-dev`.
- Document the finding here and open a follow-up before declaring SC#3.

**Acceptance:** native quote bubble visible in Signal client (screenshot attached),
OR a documented shape-drift finding with the raw payload for follow-up.

---

## No-Farmer-Traffic Guarantee

- The harness sends bot->bot only (self-send to `+59891840205`).
- No `/v1/receive` poller is started.
- The live Node alerter's farmer message queue is NOT touched.
- The two `signal_outbound` rows are tagged `intent='live_fire_57'` and are cleanable
  via `DELETE FROM signal_outbound WHERE intent='live_fire_57'` if needed.

---

## Resume Signal (for the /gsd orchestrator)

Once both SC#1 and SC#3 are verified, return to the /gsd executor with:

```
approved
SC#1: PASS (signal_msg_ts non-null bigint for both rows -- harness exited 0)
SC#3: [native quote bubble confirmed / shape-drift finding: <description>]
```

Or describe any failure for triage.

---

## Result (2026-06-21)

**Verdict: PASS** (after a blocking shape-drift fix the gate caught).

- **SC#1: PASS** — self-send bot->bot, both `/v2/send` returned 201; `signal_outbound`
  rows `1782054669365` / `1782054675982` were non-null `bigint` (`pg_typeof` confirmed).
  Harness exited with `SC#1 PASS`.
- **SC#3: PASS (after fix)** — first run: 201 but NO native quote bubble. Root cause:
  live `signal-cli-rest-api:0.200-dev` `/v2/send` takes FLAT `quote_timestamp`/
  `quote_author`/`quote_message` (per `/swagger/doc.json` `api.SendMessageV2`), not the
  nested `quote:{...}` object the ported client sent (rendered only on 0.14.2 — RESEARCH
  A2). Fixed `client.py` to flat fields; re-fired with `LIVE_FIRE_TARGET` pointed at the
  operator phone; message 2 rendered as a native quote bubble. Operator confirmed visually.

**Operator notes:**
- The runbook's `tenants/mossrock/secrets.env` source is incomplete — `TIMESCALE_PASSWORD`
  lives in the repo-root `.env`. Source `.env` instead.
- Host-run requires overriding container-internal defaults:
  `SIGNAL_API_URL=http://127.0.0.1:8085`, `TIMESCALE_HOST=127.0.0.1:5432`.
- Self-send lands in the bot's Note-to-Self (no operator client there); set
  `LIVE_FIRE_TARGET=<operator phone>` to render SC#3 where it can be seen.

**New finding (out of scope, backlogged):** the live Node `alerter` shares this 0.200-dev
container and builds the same nested `quote` object (`src/agents/alerter/src/signal.js:118-131`),
so Phase-50 quote-threading is likely silently broken in prod.
