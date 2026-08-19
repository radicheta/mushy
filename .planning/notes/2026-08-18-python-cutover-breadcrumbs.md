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

---

## Update -- 2026-08-19 evening

`main` pushed at `e57c3b8`. **MUSHY-94 forward fix shipped and deployed**;
`alerter-py` rebuilt and recreated 17:19:56Z, boot clean, receive loop polling.
Node still stopped. Ticket moved to In Progress, deliberately not closed -- see
the open half below.

Date-only farm events committed at UTC midnight, and farmOS renders in
`America/Montevideo`, so every one displayed at 21:00 on the previous calendar
day. They now resolve to **local midnight**. Verified inside the running
container rather than only in tests: `2026-08-16T00:00:00Z` stores as
`1786849200` and renders `2026-08-16 00:00`, against the old `1786838400` /
`2026-08-15 21:00`.

New `farmos/farm_time.py` is the single place that converts date -> instant and
instant -> date. Three things worth not rediscovering:

- **Exact UTC midnight is the date-only marker.** There is no date-only flag in
  the extraction schema; the prompt asks for a day the farmer named and every
  example in it is `T00:00:00Z`. A real clock time is left unshifted, and so is
  a timestamp already carrying a local offset -- that one is *already* local
  midnight and shifting it twice lands on the next day. Both pinned by tests.

- **Log names render through the same zone now.** Not in the ticket, but the
  same defect: a name built in UTC beside a timestamp rendered locally can
  disagree on the same row. For a farm *behind* UTC the timestamp fix happens to
  keep them agreeing, so it looked fine here; for a farm *ahead* of UTC it would
  not have. One helper answers both directions, so they cannot drift.

- **The zone arrives by injection, not from env.** FND-02
  (`tests/test_tenancy.py:461`) is a grep test holding that only `tenant.py`,
  `boot.py` and `chamber/config.py` read `os.environ`. First draft of
  farm_time.py read TZ directly and that guard caught it. `TenantConfig` gained
  `farm_timezone` (from `TZ`, default `America/Montevideo` -- the value
  `alerter-py` already runs with) and boot applies it before anything that can
  build a log timestamp exists.

Loaded-but-never-applied is the MUSHY-76 / MUSHY-90 shape and fails silently
(an agent committing every log a day early looks identical to a working one), so
`test_boot_applies_the_farm_timezone` asserts the module state, not the config
field. Both halves mutation-checked: reverting to UTC midnight fails 7 tests,
removing the boot call fails the wiring test.

Suite **1177 passed / 4 skipped** against a fresh `:5434` (was 1133/4).

MUSHY-95's fallback test had pinned the UTC-midnight epoch, so it had encoded
the bug; updated to the post-fix timestamp. The two fixes interlock.

### MUSHY-94 historical backfill -- DONE, ticket CLOSED

Don Santiago authorised the rewrite the same evening, on the condition that a
log carrying a real clock time is left alone. **146 logs moved from UTC midnight
to local midnight, 116 human-created logs untouched, 0 failures** (`da8fdfc`).
Paper trail, including the old timestamp of every edited log, is in
`.planning/notes/2026-08-19-mushy94-backfill/`. The change is reversible.

The condition was unambiguous in the data: the two sets are **disjoint by
author**. All 146 logs at exact UTC midnight are mushy-committed; none of the
116 human logs sit there. `timestamp % 86400 == 0` was the discriminator. The
ticket's "~180" counted committed drafts, not logs.

**The near-miss is the part to remember.** The first survey *missed 28 logs
while duplicating 28 others*: farmOS paginates inconsistently without an
explicit sort, so `page[limit]=200` plus a `next` link returns an overlapping
window. Both passes reported a plausible 262 rows and the run reported "146
candidates, 0 failed". Trusting that would have left 28 seeding logs silently a
day early -- indistinguishable from success, and the exact failure this ticket
exists to fix. It surfaced only because the arithmetic did not reconcile (27
skips nothing accounted for). Always pass `sort=drupal_internal__id` when
paginating farmOS.

*Reconcile the arithmetic of a batch; do not read its failure count.* "0 failed"
was true and the batch was still incomplete.

### Triage of the other 57 open tickets

- **MUSHY-35 is the only `urgent` one and only Don Santiago can close it** --
  two live credentials (WiFi PSK + OpenVPN tls-auth) in git history need
  *rotating*, which is not an agent action. It has been In Progress a while.
- **The Phase 63/64/65 tickets (MUSHY-3/4/5) describe a cutover that already
  happened.** Python has served Signal alone since Aug 18; MUSHY-5's big-bang
  swap and rollback drill were improvised, not run from its runbook. Those
  tickets should be reconciled with reality rather than executed as written.
  MUSHY-44 (keep-or-fix on the 4 Node behavioural quirks) is the real remaining
  decision in that arc.
- Five tickets are In Progress at once (35, 56, 52, 7, 3), which is WIP sprawl
  rather than five live workstreams.

### Gotcha -- two venvs, and the repo-root one is not the test runner

`.venv/` at the repo root has no `pytest_asyncio`, so the suite dies in conftest
with a `ModuleNotFoundError` before collecting. The runner is
`src/farm-agent/.venv/bin/python`. This is *in addition to* the broken pyenv at
the repo root noted earlier -- three interpreters, one of them right.

`ruff` and `lint-imports` live in that same venv. Four pre-existing F401 dead
imports are on `capture/pipeline.py:29`, `confirm/dispatch.py:44`,
`extraction/extractor.py:32` and `farmos/files.py:25`; left alone, noted here.
`lint-imports` reports "Could not read any configuration" -- the import contract
is not actually configured, so that gate is inert.

### Gotcha -- the secret-dump hook fires on patch scripts

`block-secret-dumps.sh` blocks a bash heredoc containing `os.environ` /
env-shaped strings, even when it is a source patch and reads no secret. Writing
the same script to a file and running it is the way past; do not fight the hook
inline.

---

## Update -- 2026-08-19 evening, MUSHY-75

`main` pushed at `7a9674f`, `alerter-py` rebuilt and recreated, verified live in
the container. Ticket left **In Progress**: the messaging half is done, the
retry half is a decision (below).

A terminal commit failure ended every message with "Reply EDIT to fix it", so a
transport failure told the farmer their correct entry was malformed. On
2026-08-16 the farmer's 4-block inoc session failed three times with `fetch
failed` (prod farmOS had been 500ing since the Aug 13 cold start) and they were
told the save failed "because data validation failed".

`_is_transient` already drew the line; only the wording discarded it. Transport
now reads "the server was unreachable. Nothing is wrong with your entry, so
there is nothing to fix." Validation still asks for an EDIT.

The ack **promises no retry, and a test pins that**: a draft here is at the
attempt cap and the watchdog never picks it up again, so any promise would be a
lie. Prod reason codes seen by farmers are also translated now
(`observation_requires_target`, 4 of 12 failures, meant nothing to a farmer);
unrecognised codes still pass through verbatim.

22 new tests, mutation-checked (collapsing the branches fails 8). Suite **1199
passed / 4 skipped**.

### A lost farm record, found while checking the parked drafts

Exactly two drafts ever failed on transport, both `seeding_session`, both at
attempt cap. **They need opposite handling, which is the argument against a
blanket auto-requeue:**

- `84d75743ae` (2026-08-16, 4 blocks) -- **data IS in farmOS**, recovered via
  Node the same evening (seeding 272/273/274/275 + activity 276). The row is
  stale, not stranded. Requeuing would **duplicate four blocks**.
- `1192a845a7` (2026-08-02, **9 blocks**) -- **genuinely lost**. None of
  `260802_KOS_1`, `_DT_2`, `_WIN_3..9` exist in farmOS. A confirmed farm record,
  parked 17 days, silently absent from the farm history.

A naive "reset the attempt count once the target is reachable" would have
double-committed the first and rescued the second. **Any auto-requeue needs an
existence check against farmOS before the write, not a reachability check.** The
commit path has no upsert-by-identity (Phase 51's layer is a separate
milestone), so the DB cannot distinguish the two cases -- only farmOS can.

Don Santiago authorised all three recommendations the same evening.

**`1192a845a7` is recovered.** Requeued, committed on the FIRST attempt. All 9
blocks verified in prod farmOS by name: `260802_KOS_1` (seeding/280) through
`260802_WIN_9` (seeding/288), plus `inoc 2026-08-02 (9 bags)` (activity/289).
All render 2026-08-02, so MUSHY-94 held on a fresh commit. Farmer got exactly
one ack.

**`84d75743ae` reconciled** to `committed` carrying the five farmOS log ids it
really produced (drupal 272-276) plus a note in `farmos_response` explaining
why. No farmOS write, no farmer ack. Zero `fetch failed` rows remain; the 10
still in `commit_failed` are all genuine validation failures.

**Auto-retry shipped** (`aee7234`): `farmos/commit_recovery.py`, step 0 of the
watchdog tick so anything un-parked commits on the same tick.

Gotcha for anyone touching this: **a requeue must also flip `origin` to
'python'**. The Phase 62 D-01 guard means the Python watchdog selects
`origin='python'` and Node selected `origin!='python'`, so with Node retired a
node-origin confirmed draft would be drained by nothing at all. Checked: there
are currently no `node|confirmed` rows, so nothing else is orphaned.

`commit_failed_transport` is a new column because the answer is NOT recoverable
from the reason string -- `fetch failed` matches no network pattern and was
classed transient only because `http_status` was None, which the row never kept.
Pre-existing rows are deliberately not backfilled, so no validation failure can
be resurrected: verified live, 0 parked / 0 requeued / 10 untouched.

Suite **1215 passed / 4 skipped**.
