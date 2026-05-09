---
status: complete
phase: 25-bidirectional-signal-farmer-robot-capture-channel
source:
  - 25-01-SUMMARY.md
  - 25-02-SUMMARY.md
  - 25-03-SUMMARY.md
  - 25-04-SUMMARY.md
  - 25-05-SUMMARY.md
started: 2026-04-28T17:30:00Z
updated: 2026-04-28T17:30:00Z
---

## Current Test

[none — session complete]

## Tests

### 1. Snooze (R4) — `mute` ack
expected: From farmer's phone, sending `mute` to the bot returns `alerts muted for 24h` within 30s.
result: pass
evidence: Live UAT 2026-04-28 ~17:00Z. User reported reply received in ~30s. Alerter log: `[receive] snooze all for 86400000ms`.

### 2. Snooze degraded (R6, whisper down) — fast-path holds
expected: With whisper-transcribe stopped, `mute` still acks within 30s (snooze never depends on whisper).
result: pass
evidence: Live UAT 2026-04-28. User reported 17s end-to-end with whisper offline. Well inside R6 budget.

### 3. Text capture + LLM reply (R5) — sender, raw_text, llm_reply persist
expected: Farmer sends `logged 5 jars in tent A, inoculation today`. Within ~60s, LLM reply arrives. DB row in `signal_capture` with sender, raw_text, message_type=text, llm_reply all populated.
result: pass
evidence: After fix `9d752cc` (envelope double-wrap bug surfaced and patched mid-UAT). Reply: "Got it — inoc-2026-04-28, 5 jars logged in Tent A. What substrate/species are you working with today?" DB row 01KQAGKJW77MZP4F0DJ3ZVXFJY confirmed sender=+59892893012, raw_text='logged 5 jars in tent A, inoculation today'.
note: llm_session_tag column stays NULL — tag is in reply prose only. Logged as deferred.

### 4. Audio (9s) + 2 photos (R3+R5) — transcribe, persist, compose
expected: Farmer sends 9s voice note + 2 jpgs. Within 3 min, LLM reply arrives. /data/signal-capture/2026-04-28/ contains audio + 2 image files. DB rows show transcript captured for the audio envelope.
result: pass
evidence: 3 files persisted (40 KB .aac + 122 KB + 128 KB .jpgs). Transcript captured: "Attaching two images of inoculation logs for April 25 and 26." LLM reply dated-aware. Whisper POST /transcribe → 200 OK.

### 5. LLM degraded (R6) — fallback fires, never silent
expected: With invalid ANTHROPIC_API_KEY, alerter still replies to farmer with `received N attachment(s) + M chars text at TS — will follow up`. After key restore, LLM resumes and retains conversation context.
result: pass
evidence: 401 from Anthropic logged: `[llm] degraded: 401 invalid x-api-key`. Fallback reply landed within budget. After restore: LLM reply "Confirmed restored — session tagged inoc-2026-04-28, Tent A, 5 Shiitake jars logged" — context retained from captureHistory across restart.
note: degraded=false in DB row despite LLM failure (UPDATE only fires when llmOk=true). Logged as deferred.

### 6. Whitelist enforcement (R7) — non-whitelisted sender silently dropped
expected: Message from a number NOT in the whitelist produces no reply, no DB row, alerter log shows `rejected sender (not in whitelist)`.
result: pass
evidence: +59898018597 sent text. Alerter log: `[receive] rejected sender (not in whitelist)`. DB query: 0 rows from that sender. Bot silent.

### 7. Capture-error visibility (D-03) — audio with whisper down
expected: With whisper offline, audio message still produces a DB row. Row shows message_type=audio, transcript=null, degraded=true. LLM still composes a reply using no-transcript context.
result: pass
evidence: Row 01KQAHB0NVEV3P0B9Z11Y09DEM: message_type=audio, transcript=NULL, degraded=true. Alerter log: `[capture] transcribe degraded: fetch failed`. LLM still replied: "What does the attached image or audio from this message show — is it another inoculation log, or something else from today's session?"

### 8. Cold Start Smoke Test
expected: Stop alerter + whisper. Bring both back via `docker compose up -d`. Boot logs clean (initDb, retention cron schedule), no `signal-cli receive 400` spam, whisper /health ok. A fresh farmer text still round-trips.
result: skipped
reason: User explicitly chose to trust warm-state attestation 2026-04-28 — "we'll fix cold-start problems if any some other day"

## Summary

total: 8
passed: 7
issues: 0
pending: 0
skipped: 1

## Gaps

[none — all 7 functional UATs PASS; cold-start consciously deferred]
