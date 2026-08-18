# Handover — Python port cutover rehearsal, 2026-08-18

**Next session focus:** Python port bugfixes. Node is being retired; do not spend
effort on it.

---

## State of the world, right now

**Nothing is serving Signal.** Both agents are stopped, deliberately.

```
mushy-alerter-1      Exited (137)   Node, stopped 19:32:43 for the swap
mushy-alerter-py-1   Exited (0)     Python, stopped 19:45:04 to end a message loop
```

Zero drafts in flight. The one live draft from the rehearsal (`dcfc5a097d14`,
Aug 16 inoc session) was discarded by hand so the watchdog would not nudge the
farmer about a session no agent is serving. Archived first to
`scratchpad/archived-draft-dcfc5a097d14.json`.

`main` is pushed and clean at `878e956`.

**Important:** `878e956` (MUSHY-89, the receipt-loop fix) is committed and pushed
but **no image was built from it**. The fix is real in git and absent in reality.
Rebuilding `alerter-py` is task #1.

---

## Update, later the same evening

Worked the suggested order. MUSHY-90 and MUSHY-91 are **closed**; `main` is
pushed at `8370ea8`.

- `bbd04c3` — MUSHY-90. boot passes `outbound_repo` + `pool` into `SignalClient`.
- `8370ea8` — MUSHY-91. Identical-body suppression at
  `extraction/outbound.py:_send_farmer_preview`, the choke-point for all four
  farmer-facing draft sends, backed by a new `outbound_repo.last_body_for_draft`.
  Fail-open in every direction; pings Don Santiago once per draft.

**The image is rebuilt** and now carries MUSHY-88, -89, -90 and -91 — verified by
reading the files inside the image, not by trusting the branch. The trap this doc
opened with is closed.

Suite is green at **1117 passed / 4 skipped** against a fresh `:5434`, so
MUSHY-79's "never green with a DB" no longer holds. One pre-existing red in
`test_boot.py` was fixed on the way past: its fake extractor had gone stale on
MUSHY-83's new `capture_date_iso` argument.

**Still true:** nothing is serving Signal. Both agents remain stopped and
signal-cli is queuing. Bringing `alerter-py` up is a farmer-visible action and
was left for a human to call.

**Next:** the MUSHY-53/80 fan-out gate on Python. Note that MUSHY-90 makes
quote-reply pinning *possible* but the `signal_outbound` join has not been
exercised end-to-end against a real quoted reply yet — that live check is still
owed before the gate can be called closed.

---

## What happened

Node was stopped and the Python agent ran live against real farmer traffic for
about 12 minutes. This was **not** the planned Phase 65 execution — no runbook
exists yet, and the rollback drill was improvised. The swap itself took 13
seconds and Python booted clean.

Three port defects surfaced within minutes. None of them would be caught by a
fixture-based parity run.

### MUSHY-88 — destructive receive timeout (fixed, deployed)

`receive()` had `timeout=timeout_sec + 5`: a 6s ceiling against a 4.3–5.1s
observed baseline. A poll carrying photos took **8.657s**. httpx aborted at 6s;
signal-cli returned 200 two seconds later to a client that had hung up.

`/v1/receive` is **destructive** — signal-cli dequeues when it answers, so an
abort does not defer messages to the next tick, it destroys them. The farmer's
messages were gone with no capture row, no reply, no visible error.

Node has never bounded this call (`signal.js:212` is a bare `await fetch(url)`).
Port-introduced.

Compounding: the handler logged `str(exc)` only, and httpx timeout exceptions
stringify to `""`. The warning read `[receive] receive() error: ` and named
nothing. **The one failure mode that silently destroys farmer data was the one
the log could not identify.** Now logs `type(exc).__name__` too.

### MUSHY-89 — receipts re-trigger their own ask-back (fixed, NOT deployed)

The receive loop dispatched every whitelisted envelope, including ones with no
`dataMessage.message` and no attachments — delivery receipts, read receipts,
typing indicators.

Each became a `signal_capture` row with `raw_text` NULL, cleared the event gate
(Haiku classified the empty text as an event), and re-ran extraction against the
in-flight draft. Extraction found the starting-seq question unanswered and
re-sent the same ask-back. That send made the farmer's phone emit another
receipt. Self-sustaining.

**Six identical messages reached the farmer at ~20s intervals** before the agent
was stopped by hand.

Node gates the capture branch on `(text || attachments.length)`
(`receive-loop.js:419`). The fix mirrors that. An uncaptioned photo carries
attachments and is real content, so attachments alone pass — there is a test
pinning exactly that, because the obvious over-tight fix silently drops photos.

### MUSHY-90 — no `signal_outbound` rows (open)

`boot.py:90` constructs `SignalClient(config, http, get_max_sends_per_hour)`.
Neither `outbound_repo` nor `pool` is passed, so the persistence hook at
`client.py:289` (`if self._outbound_repo is not None and self._pool is not
None`) is permanently false. Implemented, unit-tested, never wired — the same
shape as MUSHY-76.

It fails **silently**: no `else` branch, no log. An agent with no outbound
persistence looks identical to a working one.

Breaks quote-reply pinning. `confirm_repo.find_draft_by_quoted_msg_ts`
(`confirm_repo.py:406`) resolves a quoted reply by joining `signal_outbound`.
No rows → the join never matches → every reply falls back to "the sender's
single active draft."

That fallback was safe while `idx_signal_draft_in_flight_per_sender` guaranteed
one in-flight draft per sender. **MUSHY-53 dropped that index the same day**, so
up to five can now be in flight. The disambiguator went dead exactly as the
situation it disambiguates became possible.

---

## Suggested order

1. **Rebuild `alerter-py`** — `docker compose build alerter-py`. `878e956` is not
   in any image.
2. **MUSHY-90** — two-line boot change. Blocks MUSHY-53's ship-gate.
3. **MUSHY-91** — bound repeated ask-back sends. Would have contained the flood
   regardless of cause.
4. **MUSHY-53/80 fan-out gate**, on Python, after 90 is closed.

Then verify MUSHY-84 and MUSHY-85 against Python — both were observed on Node
and may not apply.

---

## Verification notes

**A unit test cannot close MUSHY-89.** The loop needs a real phone emitting real
receipts. The check: send a capture that produces an ask-back, confirm exactly
one ask-back is sent, and confirm no `signal_capture` rows appear with
`raw_text` NULL.

**The wider lesson for Phase 64/65.** All three defects need a real signal-cli, a
real device, and real attachments. Phase 64's parity gate runs on an isolated DB
against curated fixtures and would have passed clean through every one of them.
A parity gate is necessary but is not evidence the port can carry live traffic.
The Phase 65 runbook should include a supervised window with a real device
before the swap is called done.

---

## What the port got right, verified live

- Capture → draft. MUSHY-76's seam, first real exercise, worked.
- `origin='python'` stamped correctly.
- MUSHY-83's capture-date anchor resolved a photographed undated page to
  **2026**-08-16, where Node had produced 2025-08-16 earlier the same evening.

---

## Also landed today (not port work)

- **MUSHY-45** closed — Tier A backup now stages the Signal identity (9.3 MB,
  `accounts.json` + `account.db`, attachments excluded). Timer armed.
- **MUSHY-36, MUSHY-79** closed earlier in the day.
- **MUSHY-82** — a Node backport of MUSHY-81's D-1/D-3. Retitled and dropped to
  low priority. It answered a scheduling question MUSHY-81 had deliberately left
  open ("backport to Node or let the cutover carry them"), on a stack being
  retired. Roughly an hour that should have gone to the port. D-2 was not
  backported and is still live in Node.
- The Aug 16 inoc session **did** reach prod farmOS via Node earlier in the
  evening: `260816_DT_1`, `260816_KOS_2`, `260816_WIN_3`, `260816_WIN_4`,
  lineage verified, no duplicate parents.

---

## Gotchas worth not rediscovering

- **Never run both agents.** `/v1/receive` is destructive; two pollers means one
  of them eats the other's messages.
- **Stopping both is safe.** With no poller, signal-cli *queues* messages rather
  than losing them. That is the right posture while fixing.
- Draft IDs derive from the capture ID and `insert_draft` has no upsert, so
  replaying a capture over an existing draft row fails on the primary key
  (reported as `in_flight_conflict`, confusingly).
- The extraction pipeline ends at a handoff and does **not** send the first
  preview — the receive loop normally drives that. Anything bypassing the
  receive loop must build and dispatch the preview itself.
- `MAX_EDIT_TURNS` is 3 and `askback_turns` only advances on a reply the confirm
  loop *understands*. That makes the cap arrive too early for a farmer typing
  plain-language corrections, and unreachable for unparseable input. One
  counter, two opposite failures (MUSHY-85 and MUSHY-91).
