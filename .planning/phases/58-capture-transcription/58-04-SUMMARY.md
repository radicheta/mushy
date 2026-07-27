---
phase: 58-capture-transcription
plan: "04"
subsystem: capture
tags: [live-fire, assertion-harness, whisper, signal-capture, sc1, sc3]
dependency_graph:
  requires: [58-03]
  provides: [live_fire_58.py, 58-LIVE-FIRE.md]
  affects: [phase-58-close]
tech_stack:
  added: []
  patterns:
    - read-only SELECT/assert harness (mirrors live_fire_57.py shape)
    - httpx preflight GET for container health check
    - os.path.exists on-disk path assertion
key_files:
  created:
    - src/farm-agent/scripts/live_fire_58.py
    - .planning/phases/58-capture-transcription/58-LIVE-FIRE.md
  modified: []
decisions:
  - "Harness is read-only (no sends); operator sends voice note through live pipeline -- mirrors the autonomous:false intent of the plan"
  - "D-07 preflight exits non-zero immediately if Whisper /health is not 200 -- prevents false SC#1 FAIL misattributed to pipeline code"
  - "A5 check is a warning (not a hard exit) -- mount alignment requires cross-container docker inspect that the harness cannot automate; operator runbook owns that step"
  - "Transcript null for non-audio message_type prints NOTE not FAIL -- a photo-only row with null transcript is correct D-04 behavior"
metrics:
  duration_minutes: 15
  completed: "2026-06-23"
  tasks_total: 2
  tasks_completed: 1
  files_changed: 2
---

# Phase 58 Plan 04: Live-fire assertion harness + operator runbook

Read-only SC#1+SC#3 assertion harness (`live_fire_58.py`) and operator runbook (`58-LIVE-FIRE.md`) for the boot-wired Plan-03 capture pipeline. SC#1 (non-null transcript from a real voice note) requires a healthy Whisper container (D-07 ops fix) and the A5 bind-mount alignment; the live-fire is gated on operator ops work and a real Signal message.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | live_fire_58.py harness + 58-LIVE-FIRE.md runbook | 8e7bd9b | src/farm-agent/scripts/live_fire_58.py, .planning/phases/58-capture-transcription/58-LIVE-FIRE.md |

## Tasks Deferred (operator-driven)

| Task | Name | Status | Gate |
|------|------|--------|------|
| 2 | SC#1 + SC#3 live voice-note round-trip | BLOCKED -- checkpoint:human-verify | D-07 (Whisper healthy) + A5 (bind-mount aligned) + real Signal voice note from known farmer |

Task 2 is a `checkpoint:human-verify` with `gate=blocking-human`. It cannot be
completed by an automated executor: it requires ops fixes on the docker host
(D-07 cuda-compat purge, A5 mount alignment) and a real voice note sent by the
farmer through Signal. The operator runbook (`58-LIVE-FIRE.md`) provides the full
step-by-step procedure and acceptance criteria.

---

## Deviations from Plan

None. Plan executed exactly as written for Task 1. Task 2 is correctly deferred
to the operator per the plan's `autonomous: false` and `gate=blocking-human`
designations.

---

## Known Stubs

None. The harness is a complete implementation of the stated assertions.
The `transcript null for non-audio message_type` branch prints NOTE (not FAIL)
as designed -- this is D-04 correct behavior, not a stub.

---

## Threat Flags

None. The harness is read-only (SELECT only, no writes). PII exposure is
mitigated by printing only the basename of attachment paths (not the full path)
in the output, consistent with T-58-04-02 (accept disposition, low volume).

---

## Self-Check: PASSED

- `src/farm-agent/scripts/live_fire_58.py` exists: FOUND
- `.planning/phases/58-capture-transcription/58-LIVE-FIRE.md` exists: FOUND
- Commit 8e7bd9b: FOUND
- Syntax check (`ast.parse`): PASSED
- live_fire_58.py contains no send calls (read-only): CONFIRMED
- D-07 preflight exits non-zero on non-200: CONFIRMED
- SC#1 ULID length check (_ULID_LEN = 26): CONFIRMED
- SC#1 transcript null check scoped to audio/mixed message_type: CONFIRMED
- SC#3 os.path.exists per attachment_paths entry: CONFIRMED
