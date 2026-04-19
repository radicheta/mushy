# Phase 999.15: Bidirectional Signal — farmer↔robot capture channel — Specification

**Created:** 2026-04-19
**Ambiguity score:** 0.19 (gate: ≤ 0.20)
**Requirements:** 7 locked
**Scope note:** Originally scoped as "unblock signal-cli receive for snooze." Rescoped 2026-04-19 at farmer request into a capture channel for field notes (text + audio + photos). **Recommended promotion to v1.4 as Phase 25** — see Scope Decision below.

## Goal

When the farmer sends a Signal message (text, audio, or image) to the robot's number, the robot receives it, stores the raw content durably with sender+timestamp metadata, transcribes audio locally, runs the transcript+image metadata through an LLM to infer a session tag, and replies with either a receipt summary or a clarifying question — within 3 minutes for audio, 60 seconds for text-only. Snooze commands continue to work (collapsed to a single "mute everything for 24h" UX). FarmOS writes are explicitly deferred.

## Background

**What exists today (scouted 2026-04-19):**

- `src/agents/alerter/src/signal.js` — send path (`/v2/send`) proven live; receive path (`/v1/receive/{sender}`) hits HTTP 400 on `bbernhard/signal-cli-rest-api:0.200-dev` in json-rpc mode when the account is linked as a secondary device.
- `src/agents/alerter/src/snooze.js` — strict regex grammar `snooze {rh|sensor|pi|humidifier|all} {30m|1h|2h|4h|8h|24h}`; 10 unit tests pass against a fake server.
- `src/agents/alerter/src/receive-loop.js` — polls `/v1/receive`, whitelists source against `{SIGNAL_SENDER, SIGNAL_RECIPIENT}`, dispatches valid commands, replies with help text for invalid. Blocked by the 400 above.
- `src/agents/alerter/src/config.js` — single `SIGNAL_RECIPIENT` env var; single-farmer model.
- No capture pipeline. No transcription. No LLM integration. No media storage path.

**What triggers this work:** Farmer opened Pandora's box when Phase 17 alerts started arriving on his phone — he replied, messages went nowhere, he'd like them to land somewhere useful. Short term: "a bot that listens and I can refer back to later." Long term: free-form field notes at inoculation/harvest flow into farmOS events. Today's inoculation session produced photos + audio the farmer would dump into the robot if the robot existed.

**LLM choice:** Anthropic API (per farmer lock 2026-04-19).
**Transcription choice:** Local, dedicated container (per farmer lock — "prefer local, can deploy dedicated docker").

## Requirements

1. **Receive channel unblocked**: The robot's Signal account can pull incoming envelopes reliably.
   - Current: `/v1/receive` returns HTTP 400 for linked-secondary accounts; receive-loop.js never gets envelopes in prod.
   - Target: Receive-loop.js calls a working receive endpoint (upgraded image, primary re-provision, or alternate daemon) and successfully pulls text + attachment envelopes from the linked number at configured poll cadence.
   - Acceptance: Send a test message from the farmer's phone; receive-loop logs the envelope (source + text + attachment refs) within `ALERT_RECEIVE_POLL_SEC` seconds without raising an HTTP error.

2. **Raw capture persistence**: Every inbound message is stored durably before any processing.
   - Current: No capture path. Envelopes are parsed for snooze and discarded.
   - Target: Each inbound envelope writes a row with `(id, timestamp, sender, message_type, raw_text, attachment_paths[])` to a persistent store (Timescale or SQLite); attachments (audio/images) are saved to disk under a `/data/signal-capture/YYYY-MM-DD/` tree with stable filenames.
   - Acceptance: After farmer sends 1 audio + 3 photos + 1 text, the store has 5 rows (or 1 grouped row with 4 attachments — design choice for discuss-phase); all 4 attachment files exist on disk; rows are queryable by `(sender, timestamp range)`.

3. **Audio transcription (local)**: Inbound audio is transcribed locally and stored alongside the raw blob.
   - Current: No transcription. Whisper not deployed.
   - Target: A dedicated transcription container (faster-whisper / whisper.cpp / similar — decision deferred to discuss-phase) runs on elder-plops, invoked by the capture pipeline when an envelope has an audio attachment. Transcript text is written to the same row/record as the raw audio file.
   - Acceptance: A 30-second farmer voice note completes transcription within 3 minutes on elder-plops; transcript text appears in the capture store; the transcript is accurate enough for the farmer to recognize his own words (human judgment, single farmer test).

4. **Snooze still works**: Farmer can silence alerts with a simple Signal message.
   - Current: Snooze grammar exists in code but receive path is broken, so it has never worked in prod.
   - Target: The words `snooze`, `mute`, or `quiet` (case-insensitive, optionally followed by arguments) trigger a 24-hour silence of *all* alert types. Existing per-type grammar (`snooze rh 4h`) remains accepted but is not the advertised UX.
   - Acceptance: Farmer sends `snooze` → within 30 seconds, robot replies "alerts muted for 24h"; a PROBLEM condition that would normally fire an alert within the next 24h produces no Signal send; heartbeat resumes after 24h.

5. **Capture-pipeline reply**: Every non-snooze inbound message produces a farmer-facing reply that confirms receipt and includes an LLM-generated session inference.
   - Current: No reply pipeline exists for non-snooze messages.
   - Target: After storing raw + transcribing any audio, the capture pipeline calls the Anthropic API with the transcript + image metadata (filenames, count, timestamps) and generates either: (a) a receipt summary (≤2 lines) naming the inferred session tag (e.g. "logged as `inoc-2026-04-19`, 3 photos + 1 audio"), or (b) a clarifying question when inference is ambiguous. Reply is sent via the existing `signalClient.send()` path.
   - Acceptance: For a clearly inoc-tagged batch (audio transcript mentions "inoculation", photos show substrate jars), reply names the session tag. For an ambiguous single photo with no context, reply asks a specific clarifying question.

6. **Degraded-mode reply**: If transcription or LLM fails, the robot still acknowledges receipt.
   - Current: N/A (no pipeline exists).
   - Target: If Whisper is down, reply within 60 seconds with "received N attachments + M chars text at `<ts>` — transcription queued, will follow up". If LLM is down, reply with raw file count + timestamps, no session inference. Silence is never acceptable.
   - Acceptance: With transcription container stopped, farmer-sent audio still produces a reply within 60 seconds naming the file was received.

7. **Sender whitelist preserved**: Only the configured farmer number produces captures or replies.
   - Current: `receive-loop.js` already whitelists `{SIGNAL_SENDER, SIGNAL_RECIPIENT}`.
   - Target: Non-whitelisted senders are silently dropped (logged at warn, no reply, no capture). Multi-recipient / farmOS-people-directory routing is explicitly out of scope.
   - Acceptance: A message from any number other than `SIGNAL_RECIPIENT` produces no capture row, no disk write, no reply; a warn log line confirms the drop.

## Boundaries

**In scope:**

- Receive-loop infrastructure unblock (upgrade image, or alternate path chosen during discuss-phase)
- Capture persistence layer (schema + storage)
- Local transcription service (containerized, deployed on elder-plops)
- Anthropic LLM call for session inference + reply composition
- Simplified snooze UX (single 24h global mute; legacy grammar accepted)
- Degraded-mode replies when transcription or LLM unavailable
- Single-farmer model (existing `SIGNAL_RECIPIENT` whitelist)

**Out of scope:**

- **FarmOS event creation from captured content** — the LLM-drafted farmOS write is the next phase; capturing here is sufficient proof of value.
- **Multi-recipient routing / farmOS people directory** — single farmer today; directory is seeded (`project_farmos_people_directory_seed.md`) but not built.
- **QR-tag linking** (scan substrate bag → next message attaches) — valid future capability, not this phase.
- **Robot-initiated conversations** ("good morning, RH is 91% — log tray check?") — proactive messaging is a separate concern.
- **Operator vs grower role distinction** — single farmer plays both today.
- **Per-alert-type snooze UX** — grammar still parses, but farmer-facing surface is "mute everything 24h."
- **Retention beyond 30 days / cold storage / S3 archival** — hot disk only; retention policy TBD during discuss-phase.
- **Voice synthesis / TTS replies** — text-only replies.
- **Image understanding (visual inference by LLM)** — LLM sees metadata (filename, count, timestamp) and transcript context only; image content inference belongs to v1.4 Phase 24 CV work.

## Constraints

- **Anthropic API key required** — farmer-confirmed LLM choice; key added to alerter/capture service environment.
- **Transcription must be local** — no audio leaves elder-plops for transcription (privacy + cost). Dedicated container acceptable.
- **Reply latency budgets:** 30s for snooze confirmation, 60s for text-only, 3min for audio with transcription, 60s degraded-mode reply if transcription is down.
- **Single-farmer model** — `SIGNAL_RECIPIENT` whitelist enforced; scope change requires a separate phase.
- **Must coexist with existing alerter** — receive-loop dispatches to both alerter rules (snooze) and the capture pipeline; cannot regress Phase 17 send-side behavior.
- **Pi is not involved** — all capture + transcription + LLM work runs on elder-plops.
- **Storage path lives on the RAID** — attachments under `/data/signal-capture/` (per `project_data_path_on_raid.md`).

## Acceptance Criteria

- [ ] Receive-loop successfully pulls envelopes from the linked Signal account in prod (no HTTP 400)
- [ ] Inbound text message stored in capture store within 60s with correct sender+timestamp
- [ ] Inbound audio stored AND transcribed within 3min; transcript retrievable from the store
- [ ] Inbound images (1–5 in a batch) all saved to `/data/signal-capture/YYYY-MM-DD/` with stable names
- [ ] `snooze` / `mute` / `quiet` keyword triggers 24h global alert silence; robot confirms within 30s
- [ ] Non-snooze messages produce an LLM-generated receipt reply naming a session tag or asking a clarifying question
- [ ] With transcription container stopped, farmer-sent audio still receives a within-60s acknowledgement
- [ ] Messages from non-whitelisted senders produce no capture, no reply, and a warn log line
- [ ] Capture store is queryable by `(sender, time range)` and returns rows for the last 30 days

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                                            |
|--------------------|-------|------|--------|------------------------------------------------------------------|
| Goal Clarity       | 0.85  | 0.75 | ✓      | Capture + transcribe + LLM-reply, explicit latency budgets       |
| Boundary Clarity   | 0.82  | 0.70 | ✓      | 8-item out-of-scope list with reasoning                          |
| Constraint Clarity | 0.78  | 0.65 | ✓      | Anthropic API + local transcription locked; /data on RAID        |
| Acceptance Criteria| 0.78  | 0.70 | ✓      | 9 pass/fail checkboxes                                           |
| **Ambiguity**      | 0.19  | ≤0.20| ✓      |                                                                  |

## Interview Log

| Round | Perspective                   | Question summary                                          | Decision locked                                                                                     |
|-------|-------------------------------|-----------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| 1     | Researcher                    | Who's asking + what would they send first?                | Trigger: farmer replied to Phase 17 alerts. MVP first messages: field notes from inoc sessions.     |
| 2     | Researcher + Simplifier       | Minimum viable capture + session-context model            | Option (b) dumb receipt + transcription; session inferred from content; LLM-driven clarifier        |
| 3     | Boundary Keeper               | Snooze coexistence + explicit OUTs + LLM-clarifier depth  | Snooze simplified to global 24h mute; "take it little by little"; LLM-driven clarifier              |
| 4     | Failure Analyst + Seed Closer | Infra path + command routing + acceptance + LLM/STT       | Anthropic API for LLM; local dedicated container for transcription; infra path deferred to discuss |

## Scope Decision

**Recommendation: Promote to v1.4 as Phase 25.**

- Original 999.15 framing was "unblock snooze receive" — a narrow infrastructure fix.
- Rescoped 999.15 is a full capture channel (receive + storage + Whisper + Anthropic + LLM reply) — that is a phase, not a backlog item.
- v1.4 is demo-pressure-driven (funding). "Farmer sends voice note to the robot during inoculation, robot replies with session-tagged receipt" is a *very* strong demo artifact and complements Phase 24 CV work (both are "robot listens").
- v1.4 current state: Phases 21–22 complete; 23 (ffmpeg time-lapse) and 24 (ComfyUI CV) remain. Inserting Phase 25 after 24 does not block anything; Phase 25 is independent of 21–24.
- The narrow "receive infrastructure unblock" concern is *absorbed* into Requirement 1 above — 999.15 can be retired from the backlog when this phase ships.

**Action for user:** update `.planning/ROADMAP.md` to add Phase 25 under v1.4 and retire 999.15 from the backlog when ready. Not doing that in this spec.

---

*Phase: 999.15 → recommend promotion to 25 (v1.4)*
*Spec created: 2026-04-19*
*Next step: `/gsd:discuss-phase 999.15` — implementation decisions (receive-infra path choice, capture schema, transcription container selection, LLM prompt design, snooze/capture routing, reply composition).*
