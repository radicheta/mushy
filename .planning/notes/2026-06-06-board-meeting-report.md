# Mushy / FC-1 Board Report

**Prepared:** 2026-06-05 (for the board meeting this weekend, ~2026-06-06/07)
**Covers:** since the last board meeting, the "fire conversation" of 2026-05-09 (~4 weeks ago)
**Expected at the table:** Santi (F1), Vikki (F2), Selina (F3), Zoy (farmOS dev side), radicheta (mushy side), the Boss

---

## Mushy's opening statement (read aloud)

The chamber controls itself. The bot logged farm events in the lab and then spammed the Signal group, so it's muted.

Pick a direction: run this farm, grow more chambers, or build a product. Everything else follows from that.

---

## TL;DR (read this if you read nothing else)

Four weeks ago the board commissioned one thing: free-form farm-event logging through Signal (voice, photo, text), so nobody has to do manual bookkeeping. **We built it, and a lot more around it.** Six milestones shipped in four weeks; a seventh is in progress.

It works. But this week it crossed a line: the bot got too chatty and started replying with low-value chatter, so on 2026-06-04 we hit the emergency stop and paused all of its conversation. Chamber safety alerts still go out. The farm is fine; the chatty assistant is parked.

So this meeting is not a status update. It is a **fork in the road**. The thing the last board asked for now works well enough to ask a bigger question: what is this project actually for from here? There are three honest answers, and they point in different directions. The board should pick one.

---

## 1. What we committed to last time, and what landed

The headline decision at the 2026-05-09 fire meeting (DECISION-1, unanimous):

> "Next major milestone is free-form data entry of farm events through Signal stream."

Two days later (2026-05-11) we locked the FarmOS data schema with Zoy's team, which unblocked the whole build. Since then:

| Shipped | Date | In plain words |
|---|---|---|
| v1.5 Humidity control + forcing | 2026-05-09 | The chamber holds humidity tightly and can force condensation/evaporation on demand. |
| v1.6 VPS hub + outage recovery | 2026-05-11 | If the home network or power drops, telemetry is buffered and back-filled automatically, and someone gets paged. |
| **v1.7 Multimodal Signal to FarmOS** | **2026-05-16** | **DECISION-1, delivered.** Send the bot a voice note or photo of the paper log; it extracts the farm events and writes them into FarmOS. |
| v1.8 Event-gate + durable records | 2026-05-23 | The bot learned to tell "real farm event" from "chitchat", and every message it sends is now stored for audit. Built multi-farm-ready from day one. |
| v1.9 Inoc-session correctness | 2026-05-23 | Inoculation sessions (many bags from many parents in one go) are logged correctly, the way the notebook records them. |
| v1.10 Order-independent writes | 2026-05-24 | History can arrive in any order (live messages vs. old paper logs) without creating duplicates. |
| v1.11 2025-notebook backfill | in progress (~33%) | Feeding last year's paper notebook through the same pipeline. **Paused at a safety checkpoint** (see note below). |

That is a real delivery record against a real commission. The control core (sense, hold, recover, alert) is mature and trustworthy. The 2025-backfill work is deliberately paused at a checkpoint that requires a human action on the dev system before it is allowed to proceed; that is by design, not a stall.

Quality signal for the board: the system now carries over 1,300 automated tests that run on every change.

---

## 2. The one incident that needs board attention: the bot got too chatty (999.55)

**What happened.** The conversational assistant (the v1.7 feature) began replying to farmers with low-value, sometimes nonsensical messages, turning the farm Signal group into noise. Santi flagged it directly: "we're spamming the farmers with meaningless conversations."

**What we did, same day (2026-06-04).** Added a single kill switch. The bot is now in "write-only" mode: it still captures and logs everything, and it still sends real chamber alerts (humidity, CO2, sensor offline) and the daily health heartbeat, but it no longer holds conversations. Everything it *would* have said is recorded to a debug log so we can study the noise before turning speech back on. This is a stop-gap, not a cure. The real fix is tracked as item 999.55.

**Current state.** Safe and stable. Farmers get alerts, no spam. The logging pipeline behind the scenes is untouched. The cost is that the assistant cannot currently ask "what strain is this?" or confirm "logged 11 bags, ok?", so its day-to-day helpfulness is reduced until we re-enable speech carefully.

**The honest lesson.** This is the third time a farmer-facing message has misfired and been instantly visible to everyone (wrong-recipient replies, a broken confirm flow, and now chatter). The pattern is not bad luck. The bot was built to be conversational by default, and conversational-by-default is structurally noisy. There was no quality gate on what it says, and the farmer, not the system, was the one who caught it. That is fixable, but it is a design decision, not a one-line patch, and which way we fix it depends on the fork below.

---

## 3. The fork in the road (the actual decision for this meeting)

There are three different futures wearing the same project. They are all legitimate. They want opposite things, which is why the board should pick.

### Fork A. Run *this* farm well

Treat the chamber-control mission as essentially won. Keep the bot as a quiet, reliable capture tool (send it a log, it files it, it does not chat). Spend our energy growing mushrooms, not building software.

- **For the farmers:** less software in your face, not more. The bot becomes a silent filing clerk.
- **For the dev effort:** most of the planned roadmap (Python rewrite, auto-commit automation) pauses. We shift to maintenance and small quality-of-life fixes.
- **Risk:** we leave capability on the table that we already paid to build.

### Fork B. Grow the operation (more chambers)

Replicate the working chamber: more growing chambers, each with cheap remote sensors and actuators, all reporting to one dashboard.

- **For the farmers:** more production capacity under the same control system that already works.
- **For the dev effort:** the priority becomes hardware and a genuinely multi-chamber control system. The chatty AI assistant is a side feature.
- **Risk:** hardware cost and physical install time; the control system needs work to handle many chambers cleanly.

### Fork C. Turn it into a product (the open-source "Foray" idea)

Other mushroom farms run this. We have already been building every piece "multi-farm-ready" with this in mind.

- **For the farmers:** Mossrock becomes the flagship/reference farm; possibly a revenue or reputation angle.
- **For the dev effort:** the conversational assistant has to become genuinely excellent, with real quality gates, because other farms will not tolerate a chatty bot. Documentation and per-farm isolation become as important as features. In this future, item 999.55 is not a nuisance, it is existential.
- **Risk:** this is the most ambitious path and the furthest from "just run the farm." It is a real product commitment, not a weekend.

**How the chatty-bot incident reads in each:** a footnote in Fork A, a distraction in Fork B, a five-alarm fire in Fork C. We cannot sensibly sequence the next few months until the board says which one we are in. Right now energy is being spread thin across all three at once.

---

## 4. A standing risk to name out loud (true in every fork)

The project's "bus factor" is one. Development and production run on the same single machine (elder-plops), with no separate staging. The encrypted-backup recovery key lives only on that one machine, held by one person. One human (Santi) wears all the hats: operator, grower, and builder.

None of this has bitten us yet, and the outage-recovery work (v1.6) genuinely helps. But this is the kind of risk that is boring to fix and therefore keeps not getting fixed, and it is the single thing most likely to actually hurt the farm. Worth a board decision on whether to invest a small amount in reducing it (an offsite backup copy, a second pair of hands trained on the system), regardless of which fork we pick.

---

## 5. Board decisions (2026-06-06)

1. **Direction: Fork A + incubation chamber.** Run this farm well via Signal. No lateral expansion to more fruiting chambers. Next hardware is an incubation chamber — extending the system to cover the full cultivation lifecycle, not replicating what already exists.
2. **The bot's voice:** Signal interaction is the goal, not a silent filing clerk. Bot re-enable is gated on a proper intent router — six canonical playbooks (inoculation session, random observation, create todo, mark todo done, substrate prep, harvest event) as the shared layer between the Signal bot and the farmOS Flask app. See `.planning/notes/2026-06-06-board-meeting-playbooks.md`.
3. **The bus-factor risk:** Three actions decided: (a) mirror the Tier A backup to a separate local disk in addition to the VPS; (b) Zoy holds a copy of the age decryption key (`id_ed25519`) for safekeeping; (c) farmOS DB dumps pushed to VPS nightly alongside the Tier A bundle — implemented same day, script updated.
4. **Next board cadence:** Event-driven, not fixed. Nudge scheduled for ~2026-06-27 to check if a meeting is warranted.

---

## Appendix: technical detail (opt-in)

- **Incident 999.55 detail and the fix mechanism:** see `.planning/ROADMAP.md` backlog entry "Phase 999.55" (top of the parking-lot list). Kill switch is `SIGNAL_FARMER_MUTE` in `docker-compose.override.yml`; only `rh_alert` and `attestation_kickoff` intents reach Signal; everything else is shadow-logged to the `signal_outbound` table tagged `muted:*`. Branch `fix/mute-signal-convo-spam`, commit `634d03e`, pushed.
- **Schema lock:** FarmOS schema locked 2026-05-11 (farmos repo commit `d4e5a30`).
- **Milestone records with dates, commit counts, and audits:** `.planning/MILESTONES.md` and `.planning/milestones/*-ROADMAP.md`.
- **Last board meeting source notes:** `.planning/notes/2026-05-09-fire-conversation.md` (DECISION-1 through DECISION-N) and `2026-05-09-farmer-1-quotes.md`.
- **Current paused work (v1.11 / Phase 54.2):** `.planning/STATE.md` documents the blocking human-action checkpoint on the dev FarmOS system before the 2025-notebook backfill may proceed.
- **The product/OSS framing ("Foray"):** `.planning/notes/2026-05-17-oss-foray-decision.md` and `2026-05-13-ten-ambitious-moves.md`.
