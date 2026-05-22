# 44-01 Classification Rubric

Source: D-20 / D-21 / D-22 in `44-CONTEXT.md`, design note
`.planning/notes/2026-05-17-is-this-an-event-gate.md` §3, and the gate-decision
flow in D-02.

This rubric MUST be re-read end-to-end before hand-classifying. It locks the
6-tag vocabulary BEFORE labeling, mitigating T-44-01-02 (label bias).

---

## Output JSONL row shape (one per line, append-only)

```json
{"tenant_id":"mossrock","capture_id":"<id from raw>","sender":"<e164>","captured_at":"<iso>","raw_text":"...","transcript":"...","attachment_count":N,"class":"<one of 6 tags>","expected_gate_action":"<skip|extract>","notes":"<why>"}
```

Per `[[feedback_keep_paper_trail_of_intermediates]]`: append-only. Never edit a
line once written. If you mis-classify, append a NEW line with the same
`capture_id` and a `notes` field explaining the override, then the validator in
Task 1.3 will catch the duplicate and force a manual re-emit.

---

## D-20 target distribution (sum = 100)

| Class           | Target count | `expected_gate_action` | Gate disposition (D-02) |
| --------------- | ------------ | ---------------------- | ----------------------- |
| `hard-event`    | 36           | `extract`              | rule fast-path POSITIVE → `fast_event`, enqueue extractor |
| `confirm`       | 28           | `extract`              | NEVER REACHES GATE — Phase 39 short-circuit at `receive-loop.js:220-264` handles before `capture.js:147` |
| `phantom-ack`   | 8            | `skip`                 | rule fast-path NEGATIVE → `skipped_rule_neg`, skip extractor + convo |
| `UX-meta`       | 8            | `skip`                 | gray zone → Haiku classifier → `haiku_chitchat`, skip |
| `soft-obs`      | 12           | `extract`              | gray zone → Haiku classifier → `haiku_event`, enqueue |
| `greetings`     | 8            | `skip`                 | gray zone → Haiku classifier → `haiku_chitchat`, skip |

D-22 ship-gate metrics computed from this fixture:
- **Zero** farmer-facing preview pings on the 24 must-skip rows (8 phantom-ack + 8 greetings + 8 UX-meta).
- **≥95%** event recall on the 48 must-extract rows (36 hard-event + 12 soft-obs).
- The 28 `confirm` rows MUST bypass the gate entirely via Phase 39 short-circuit (asserted separately in smoke).

---

## Class tag definitions

### 1. `hard-event` — 36 rows — `expected_gate_action: extract`

A message that, alone or with its attachments, is unambiguously a real farm
event the extractor MUST capture. Triggers rule fast-path POSITIVE per D-02
step 1 — the gate enqueues without invoking Haiku.

A row qualifies as `hard-event` if ANY of the following is true:
- `attachment_count >= 1` AND the attachment is a substrate photo, sterilization
  photo, harvest photo, contam photo, or block-relocation photo (NOT a butt-dial
  or random image).
- `raw_text` or `transcript` contains one of the 14 active strain codes
  (`[[mossrock_active_strain_codes]]`: SHI, SH2, KOY, MAI, MALI, KOS, DT, CAS,
  CAZ, WIN, ALM, MOR, BP, LIMA) in event context (a quantity, action verb, or
  date — not just chatting about a strain).
- `raw_text` matches the block-name regex `\b\d{6}_[A-Z]{2,4}_\d+\b`.
- `raw_text` or `transcript` length > 200 chars AND describes a discrete event
  (harvest weight, sterilization batch, watering log, cold shock, contam call,
  archive, relocate).
- `message_type = 'audio'` AND the transcript narrates a session (inoc batch,
  harvest, sterilize) — typically > 200 chars transcribed.

Hard-event handlers expected downstream: Sonnet 4.6 extractor at
`extraction/extractor.js:101`.

### 2. `confirm` — 28 rows — `expected_gate_action: extract` (but BYPASS)

A short YES / NO / EDIT / ack response to an in-flight draft (within the
30m attestation window). These never reach `capture.js:147` because Phase 39's
short-circuit at `receive-loop.js:220-264` routes them into the confirm
state-machine first.

A row qualifies as `confirm` if ALL of the following are true:
- `raw_text` matches the confirm-verb shape: `ok|yes|no|got it|si|sí|gracias|thanks|👍|edit|change|cancel|nope|done`.
- The `captured_at` is within ~30 min after a `signal_outbound` row for the
  same sender with `intent = 'attestation_kickoff'` OR
  `intent = 'confirm_prompt'`.
- The text length is short (< 60 chars typically).

Because Phase 39 fires first, the smoke harness uses these rows to assert the
short-circuit still works — they must NEVER appear in the gate's decision log.

The `expected_gate_action` field stays `extract` for these rows because IF
Phase 39 missed them (regression), the gate WOULD enqueue the extractor (they
look like fast-path NEGATIVE candidates, but the gate's NEGATIVE rule only
catches `phantom-ack`, see below).

### 3. `phantom-ack` — 8 rows — `expected_gate_action: skip`

The 2026-05-15 `6934760c` case. A short conversational acknowledgement that
arrives AFTER an `attestation_kickoff` but with NO in-flight draft (the
matching draft already hit `commit_failed` hours/days ago, so
`findAwaitingForSender` returns null and Phase 39 falls through).

Without the gate, Sonnet extracts a phantom draft from "Ok" and pings the
farmer for confirmation — NORTH-STAR violation
(`[[feedback_no_silent_failure_after_farmer_confirm]]`).

A row qualifies as `phantom-ack` if ALL of the following are true:
- `raw_text` matches `^(ok|yes|got it|thanks|gracias|si|sí|👍)$` case-insensitive,
  length < 40 chars.
- There IS a `signal_outbound` row for the sender with
  `intent = 'attestation_kickoff'` within 30m before `captured_at`.
- There is NO open draft in `awaiting_farmer` state for the sender at that time
  (i.e., Phase 39 would have fallen through to `capture.js:147`).

Gate disposition: rule fast-path NEGATIVE (D-02 step 2) → `skipped_rule_neg` →
extractor AND convo BOTH suppressed (per D-05 default-silent).

### 4. `UX-meta` — 8 rows — `expected_gate_action: skip`

Messages where the farmer is talking ABOUT the bot rather than logging a farm
event. Examples: "the dashboard looks weird", "did you get my last message?",
"can you ask Vikki instead", "stop sending so many alerts", "what time zone are
you in".

A row qualifies as `UX-meta` if the message is meta-conversation directed at
the system / operator / bot itself — never a substrate, strain, or chamber
event.

Gate disposition: gray zone (not POSITIVE, not NEGATIVE) → Haiku 4.5
`classify_capture` → `is_event = false` → `haiku_chitchat` → skip extractor +
convo.

### 5. `soft-obs` — 12 rows — `expected_gate_action: extract`

Free-text observations the farmer would want logged but that don't trigger any
POSITIVE rule fast-path (no strain code, no block name, no attachment, < 200
chars). Examples: "noticed slow pinning on the back shelf", "morning temps
felt cold", "lights flickered overnight", "the smell in #3 is off".

A row qualifies as `soft-obs` if the message:
- Describes a farm-state observation (chamber condition, substrate status,
  yield impression, abnormality).
- Lacks the structural markers that would make it `hard-event` (no strain code
  in event context, no block name, no attachment, < 200 chars).
- Is NOT a confirm reply, NOT a meta-conversation, NOT a greeting.

Gate disposition: gray zone → Haiku 4.5 → `is_event = true` → `haiku_event` →
enqueue. The 95% recall floor on must-extract rows is the load-bearing metric
for these — Haiku missing soft-obs is the NORTH-STAR risk path.

### 6. `greetings` — 8 rows — `expected_gate_action: skip`

Pure social chit-chat with no farm content. Examples: "buenos días", "good
morning", "how's it going", "happy new year", "👋", "🤣🤣🤣 que loco".

A row qualifies as `greetings` if there is NO farm signal whatsoever — no
substrate, strain, chamber, sensor, schedule, observation, or system content.

Gate disposition: gray zone → Haiku 4.5 → `is_event = false` →
`haiku_chitchat` → skip extractor + convo.

---

## Edge cases & disambiguation guide

- **Strain code in chit-chat** ("haha I love SHI lol") → `greetings` or
  `UX-meta`, NOT `hard-event`. The POSITIVE rule will misfire here, which is
  EXACTLY what the smoke is designed to surface — log it as a known
  over-extraction case in `notes`.
- **Butt-dial audio** (40 KB aac, no transcript or "test test" transcript) →
  `UX-meta` or `phantom-ack`, NOT `hard-event`. The attachment-based POSITIVE
  rule will misfire; document in `notes`.
- **Photo with caption "test"** → `UX-meta`, NOT `hard-event`. Same as above.
- **"Ok" with NO recent attestation_kickoff** → `greetings`, NOT
  `phantom-ack`. Phantom-ack REQUIRES the recent kickoff window.
- **Long voice memo (>200 chars transcript) that is just gossip** →
  `greetings` or `UX-meta`. The text-length POSITIVE rule WILL misfire here;
  document in `notes` as a Haiku-only-can-catch case (but the gate doesn't
  reach Haiku because the rule already fired — known limitation).
- **YES/NO with no prior attestation** → `greetings`. Not a confirm without
  context.
- **Confirm-verb shape but explaining a new event** ("ok we sterilized
  3 bags of SHI today") → `hard-event`. The strain code + verb override the
  short-text confirm pattern.

If a row genuinely could be two classes, pick the one whose
`expected_gate_action` matches the more conservative shipping behavior
(prefer `extract` over `skip` per D-03 bias-toward-extraction).

---

## Tenant tagging

Every row gets `"tenant_id": "mossrock"` per Foray α-lock (D-08, D-11). This is
non-optional — Task 1.3 asserts it.
