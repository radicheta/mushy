---
phase: 37
slug: multi-farmer-routing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-11
---

# Phase 37 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

See `37-RESEARCH.md` §Validation Architecture for the testable-surface inventory.
This file will be filled in by the planner / Wave 0 task with concrete per-task rows.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest (alerter — `src/agents/alerter/`) |
| **Config file** | `src/agents/alerter/jest.config.*` (TBC by planner) |
| **Quick run command** | `cd src/agents/alerter && npx jest --testPathPattern={changed_file}` |
| **Full suite command** | `cd src/agents/alerter && npx jest` |
| **Estimated runtime** | ~TBD seconds |

---

## Sampling Rate

- **After every task commit:** Run quick jest matching changed file
- **After every plan wave:** Run full alerter jest
- **Before `/gsd-verify-work`:** Full suite must be green + live 999.20 replay UAT (f2 DMs → reply to f2 only)
- **Max feedback latency:** ~30s target

---

## Per-Task Verification Map

*Planner fills this in once PLAN.md files are drafted. Each D-XX decision must have ≥1 row.*

| Task ID | Plan | Wave | Requirement | Decision | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|----------|-----------|-------------------|-------------|--------|
| TBD     |      |      |             |          |           |                   |             | ⬜ pending |

---

## Wave 0 Requirements

- [ ] **Live signal-cli smoke probe** — confirm group-send via `/v2/send` with `recipients: ["group.<base64>"]` works on current signal-cli deviceId; capture fixture envelopes for the six new shapes (DM, group-mention, group-command, group-reply-to-bot, group-silent, group-UPDATE/QUIT)
- [ ] **Mention shape fixture** — verify `dataMessage.mentions[].number` is present in REST mode (issue #805 reports gap in JSON-RPC mode)
- [ ] **Quote shape fixture** — confirm `dataMessage.quote.author` field (defensive matching planned for `authorNumber` variant)
- [ ] Fixture set committed under `src/agents/alerter/test/fixtures/envelopes/` (or repo-existing fixture location — planner verifies)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 999.20 proof-of-fix replay | ROUTE-01 | Real Signal account, real device | f2 (zoy) DMs bot → reply lands on f2's phone, NOT f1 |
| Group alert visibility | ROUTE-02 | Visual confirmation in group | Trigger a heartbeat / alert; verify it lands in "Mushroom Farm" group, not f1 DM |
| Unknown-number capture | ROUTE-03 | Real envelope from non-mapped sender | Whitelist a number absent from `SIGNAL_FARMER_MAP`; send message; verify `farmos_person='(unassigned)'` row in `signal_capture` and reply still fires |
| Group `mute` from any farmer | D-10 | Multi-device coordination | f2 sends `mute` in group; verify global mute + in-group ack |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (deviceId group-send, mentions[], quote.author)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
