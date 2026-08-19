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

**`alerter-py` is now UP**, alone, on an image carrying MUSHY-88/89/90/91 and
MUSHY-84. Node stays stopped. It drained the queued farmer message on the first
poll and sent one ask-back (draft `bbf34ce39b`).

MUSHY-90 is verified **live**, not just by test: the first Python-era
`signal_outbound` row landed at `23:55:01Z` with `signal_msg_ts` populated,
where the previous newest row was the `22:10:37Z` Node one. Quoted-reply pinning
now has rows to join.

`idx_signal_draft_in_flight_per_sender` is confirmed absent under the Python
agent too — MUSHY-53's schema half is deployed on this stack, not only the Node
one it was verified on. The rollback caution in
[[project_in_flight_draft_index_dropped]] is now live.

**MUSHY-84 fixed** (`3dee8ad`) after verifying it does port. A control word with
no live draft is answered honestly instead of extracted into a phantom. Its
third symptom (a stranded `needs_review` draft the farmer cannot close) is NOT
fixed; ticket left In Progress.

**MUSHY-85 verified, not fixed.** It splits: the turn-economics half is Node-only
(`parser.js:39`'s implicit-EDIT catch-all makes every non-YES/NO reply an edit;
Python has no catch-all), and dies with the cutover. The keyword half ports
*inverted* — on Python a plain-language correction is not recognised at all and
falls through to the capture pipeline as a new capture. Fixing that means
classifying farmer intent, which is a product call, so it was left.

**MUSHY-53/80 ship-gate PASSED**, live, 2026-08-19 03:03-03:06Z. Both closed.

One farmer message ("18 Aug 2026: checked 260519_DT_1 and 260519_DT_2, both
fully colonized") produced two drafts and **two independent confirm prompts** 8s
apart — the behaviour those tickets are named for, never observed before.

All three farmer replies **pinned by quote**, and were answered **out of order**
(the second entry was corrected before the first was confirmed). That is
MUSHY-90's payoff: quote pinning is what routes an answer to the right draft
once several are in flight, and it was inoperative on Python until that morning.

Both entries reached prod farmOS as separate observations:
`640dbb1f-1203-4d83-99b3-547996caa4ac` (DT_1) and
`9e9c18c6-f18a-4846-b3cf-e3b3944cb64d` (DT_2, carrying the correction as
`state: contaminated`). No `in_flight_conflict`, no dropped sibling.

**One defect surfaced, filed as MUSHY-92, not worked.** The `edit:` reply never
reached the edit path: `_parse_yes_no_edit` matches the first whitespace token
and the colon is part of it, so `edit:` never equals `edit`. It fell through to
the capture pipeline and re-extracted instead. The correction still landed, which
is what makes it easy to miss — the only evidence in the data is
`edit_turn_count = 0` with no edit event. This is the *keyword* half of MUSHY-85
with a much narrower trigger than that ticket assumed.

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

---

## Update — 2026-08-19 morning session

`main` pushed at `3f9f4e6`. `alerter-py` rebuilt from it and recreated at
11:14:46Z; boot clean, receive loop polling, Node still stopped.

**MUSHY-92 fixed and deployed** (`3f9f4e6`). Test-first: six new tests in
`tests/confirm/test_edit_handler.py`, five watched fail before the change.

The control verb is now the leading run of *letters*, not the first
whitespace-delimited token, with attached punctuation treated as a separator.
`_split_leading_verb` is shared by `_parse_yes_no_edit` and
`_extract_edit_text`, which settles the open question the ticket left: the
correction handed to the model no longer starts with a stray colon. `edit:`,
`edit: 750g` and the glued `edit:750g` all reach the edit path now.

Two things worth knowing beyond the ticket:

- The same defect was on **every** verb, not just `edit`. `yes.`, `No!` and
  `ok,` were all unparseable. Those are more likely from a farmer than `edit:`
  is, and each one fell through to the capture pipeline as a fresh capture.
- The obvious prefix-match fix is wrong and there are pinning tests for it.
  `fixed the fan in FC1` and `yesterday we harvested 2kg` are real log entries
  that start with a control verb; a lookahead requires end-of-string,
  whitespace or punctuation after the verb so they stay log entries.

Side effect on `_is_bare_control_word` (reply_router, MUSHY-84's fix): a
single-word `yes.` is now confirm-thread traffic instead of an extraction.
Intended direction; router tests green.

**MUSHY-89 closed on live evidence.** This doc said a unit test could not close
it. Receipt-shaped rows on prod `signal_capture` (`raw_text IS NULL AND
cardinality(attachment_paths) = 0`) over the last 20h: **6 rows, all between
22:43:22Z and 22:45:00Z on Aug 18**, at the ~20s intervals — the original
flood, before the fixed image started at `00:01:49Z`. **Zero since**, across
~14h of live traffic including the 03:03-03:06Z fan-out gate, which produced
four farmer replies and six outbound sends and so generated exactly the
receipt traffic that drove the loop.

**Suite is 1133 passed / 4 skipped** against a fresh `:5434`.

### Gotcha — the test DB credentials are not the obvious ones

A `postgres:14` on `:5434` with the default `POSTGRES_PASSWORD=postgres` and
db `postgres` does not fail fast: the DB-gated tests **hang** rather than skip,
and `pytest -q` buffers, so the run looks alive with an empty output file. The
conftest defaults (`tests/conftest.py:39-41`) are db `test_farm_agent`, user
`postgres`, password `test`:

```
docker run -d --rm --name mushy-test-pg -p 5434:5432 \
  -e POSTGRES_PASSWORD=test -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=test_farm_agent postgres:14
```

Wrong creds cost ~15 minutes of a run that was never going to finish.

### Still open, unchanged

MUSHY-84 (stranded `needs_review` draft the farmer cannot close) and MUSHY-85's
keyword half (a plain-language correction with no verb is not recognised at
all) are both product calls and were not touched. MUSHY-92 was only the
mechanical half.

---

## Update — 2026-08-19 afternoon

`main` pushed at `d69ebe6`. Four tickets closed today, one filed.

**MUSHY-48 closed** (`4697c81`). `tenants/mossrock/config.yaml` named
`farmos_agent`, an account that does not exist; it is now `mushy-bot`.

The ticket's mechanism was inverted and that is the part worth keeping. It said
the Phase 62 live-fire passed "with FARMOS_USERNAME=mushy-bot overriding the
config". Env cannot override the config: `_pick` is YAML -> env -> default, so
YAML wins. It passed because **`TENANTS_BASE` resolves to `/tenants` inside the
container and that directory is not mounted** (verified: `TENANTS_BASE.exists()`
is False in the running agent). The tenant YAML is dead config in prod today.

So the hazard is not a gap being filled, it is a correct environment being
silently overridden the moment anyone mounts that directory. `FARMOS_URL` in the
same file still points at dev `:18080` while prod runs `:8082` -- same hazard,
worse in kind, since a wrong username fails closed on a 400 and a wrong URL
would succeed against the wrong farmOS. Left for Don Santiago to decide.

**MUSHY-84 closed** (`8166994`), third symptom done. A farmer's NO now actually
closes a stranded `needs_review` draft via a new `discard_needs_review_draft`,
and the ack says "Closed that one" instead of "already pending review".

NO only: a draft reaches `needs_review` by exhausting the ask-back cap, so
honouring YES or EDIT there restarts the loop the cap exists to stop. The DAO is
a separate statement, not a loosened `_DISCARD_SQL`, because that one's
`awaiting_farmer` guard is what stops a NO unwriting a committed observation.
The guard was **mutation-checked**: dropping the status clause fails all four
status refusals plus idempotency, so those tests genuinely bite.

Scale, for anyone tempted to build more here: 3 `needs_review` rows exist
against 182 committed and 70 expired, and all 3 are from May. They predate the
24h lookup window and need clearing by hand.

**MUSHY-33 closed** (`d69ebe6`) -- whisper on-demand GPU.

The model held **2,050 MiB of a shared 6GB RTX 2060 around the clock to serve 12
voice notes since 2026-04-28**. It now runs in a worker subprocess spawned on
demand and reaped after `WHISPER_IDLE_UNLOAD_S` (default 600s).

Subprocess, not the in-process unload the ticket proposed: `del model` frees the
weights but leaves the CUDA context (~300 MiB) for the life of the container.
Killing the child returns everything.

**`/health` no longer means "model loaded".** It means the last CUDA probe
succeeded; `model_loaded` rides along as information. If it still gated the 200,
the reaper would mark the container unhealthy every time it did its job. A 200
with `model_loaded: false` is now the normal idle state, not a fault.

Verified live end to end: reap observed (VRAM 2,050 -> 0, health stayed 200),
cold respawn **4.2s** including the model load, real voice note transcribes warm
in 6.1s.

That 4.2s is the finding. The ticket assumed a 30-60s cold-start penalty; with
the HF cache volume warm it is ~4s against a 200s caller budget
(`capture/transcribe_client.py:31`). The tradeoff this ticket agonised over
barely exists, so a much shorter idle window is defensible if VRAM gets tight.

**MUSHY-93 filed, not worked.** `vad_filter=True` on audio with no speech hands
faster-whisper an empty segment list and it raises `max() arg is an empty
sequence`. The repo's own GPU smoke fixture is a pure tone, so `pytest -m gpu`
**cannot pass** and has presumably not been run in a long time. Pre-existing,
same code path as before MUSHY-33. It matters beyond the fixture: a real note
that is silence or wind fails rather than returning an empty transcript.

### Decisions taken with Don Santiago (for MUSHY-87, not yet built)

- Replay collision: **new replay-scoped draft ID, keep the superseded row**.
  Draft IDs are a deterministic hash of capture IDs and `insert_draft` has no
  upsert, so a replayed capture always collides. Hash in a replay marker;
  `source_capture_ids` still names the originals. Non-destructive.
- Replay sends: **dry-run by default, explicit flag to send**. A replay is
  usually fixing your own extraction; an unexpected DM about a session the
  farmer already logged is noise.

### Gotcha — the repo root has a broken pyenv

`python` at the repo root dies with ``pyenv: version `mushroom_farm' is not
installed`` (`.python-version`). A heredoc script can print success and change
nothing. Use `/mnt/slime-kingdom/opt/mushy/.venv/bin/python`, or run from
`src/farm-agent`.

The whisper service has its own deps and is not importable from that venv
either. Run its tests in the image:

```
docker run --rm -v "$PWD":/app -w /app mushy-whisper-transcribe \
  python3 -m pytest test -q -m "not gpu"
```

**MUSHY-94 filed 2026-08-19, not worked.** Date-only farm logs are committed at
UTC midnight and farmOS renders in `America/Montevideo`, so every one displays
on the *previous* calendar day. `inoc 2026-08-16` shows a timestamp of
2026-08-15; the Aug 18 observations show 2026-08-17. Name and timestamp
contradict each other on the same row, and the name is the one that is right.

Confirmed at the source, not inferred: prod `config` row `system.date` has
`timezone.default = "America/Montevideo"`, `user.configurable = true`.

Fix direction is local midnight (03:00Z for UYT) on the agent's commit path.
The ~180 existing rows are an open question -- rewriting them edits committed
farm history, leaving them puts a discontinuity mid-log. Don Santiago's call.

Also still unfiled: the two Aug 18 observations are both named
`observation 2026-08-18`, so the list cannot distinguish DT_1 from DT_2. The
seeding logs do this correctly (`Inoc 260816_WIN_3`); the convention was never
applied to the observation path.
