# Phase 42 PILOT-LOG -- SHI-on-Sawdust Pilot

> **DEPRECATED 2026-08-21. Do not fill this in.** The pilot never started and
> will not. Production use of the agent replaced it; see `42-VERIFICATION.md`
> for what that does and does not still prove. Kept as a record that this was
> scaffolded and deliberately abandoned, not lost.

**Append-only journal.** Do not edit prior entries. New events are added at
the bottom of this file, one commit per event with message format:

```
pilot(42): PILOT-NN <gist>
```

Reference: `42-RUNBOOK.md` for the playbook; `42-CONTEXT.md` for decisions.

**Pilot started:** `[pending operator]`
**Pilot block uuid:** `[pending operator]` (filled in after PILOT-02)
**Pilot expected duration:** 4-8 weeks from PILOT-01 to PILOT-06.

Style locks: no em-dashes; numerics use `fmtNum()`; address operator as Don
Santiago in any narration.

---

## Event template (copy for each new entry)

```
### PILOT-NN -- <short label>

- timestamp_utc: <iso>
- signal_msg_id: <id from signal-cli>
- bot_reply_msg_id: <id>
- confirm_reply: YES | CANCEL
- farmos_asset_id: <uuid> (if applicable)
- farmos_log_id: <uuid> (if applicable)
- photo_attachments: [<path1>, <path2>, ...]
- verification_command: <one of the tool invocations from RUNBOOK>
- verification_output: <inline JSON / pasted output>
- success_criterion_met: yes | no | partial
- commentary: <free-form notes, surprises, deviations>
```

---

## Entries

### PILOT-01 -- Sterilization batch  [pending operator]

- timestamp_utc: [pending operator]
- signal_msg_id: [pending operator]
- bot_reply_msg_id: [pending operator]
- confirm_reply: [pending operator]
- farmos_asset_id: [pending operator]
- farmos_log_id: [pending operator]
- photo_attachments: [pending operator]
- verification_command: [pending operator]
- verification_output: [pending operator]
- success_criterion_met: [pending operator]
- commentary: [pending operator]

---

*(Append PILOT-02 through PILOT-06 entries below as the pilot progresses,
copying the template above each time. Commit each entry atomically.)*
