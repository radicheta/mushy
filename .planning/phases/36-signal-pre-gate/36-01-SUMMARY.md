---
phase: 36-signal-pre-gate
plan: 01
status: complete
completed_utc: 2026-05-11
---

# Plan 36-01 — Pre-flight Snapshot — SUMMARY

## What shipped

Pre-registration snapshot of the signal-cli state on elder-plops, complete with a documented restore path. This artifact is the abort path for Plan 36-02.

## Concrete outputs

| Output | Path / Value |
|--------|--------------|
| Volume tarball (host) | `/mnt/slime-kingdom/mushy-backups/signal-cli-data-20260511.tar.gz` (99M, 140 entries; `./data/accounts.json` + `./data/270761.d/account.db` confirmed inside) |
| Redacted device JSON | `.planning/phases/36-signal-pre-gate/snapshots/devices-20260511.json` |
| Redacted identity JSON | `.planning/phases/36-signal-pre-gate/snapshots/identities-20260511.json` |
| Pre-flight artifact | `.planning/phases/36-signal-pre-gate/36-01-preflight-snapshot.md` |
| Backlog filed | 999.52 (Phase 35 Tier A signal-cli volume gap) — `ROADMAP.md:569` |

## Key findings (proves Phase 25 receive-400 root cause)

- `/v1/devices/+<BOT>` returns two devices: `id=1` (name empty — Signal-server-side primary, location unknown) + `id=2` (`mushy-alerter` — local elder-plops install operating as linked-secondary).
- Plan 36-01's ABORT-condition wording ("`.id == 1` already appears → Phase 36 already done") was simplified. Reality: the device list ALWAYS includes the server-side primary regardless of which device the local install is. The receive-400 symptom is the operational signal — and it's still firing — so re-registration is correctly indicated. Documented in `36-01-preflight-snapshot.md` § "Note on device list — NOT abort".

## Phase 35 Tier A coverage verdict

**GAP.** Phase 35 Tier A bundles only `.env` files + fc1 overrides + VPS heartbeat secrets — the signal-cli volume is NOT covered. Filed as 999.52. Until that lands, the local 99M tarball from this plan is the ONLY rollback path for `mushy_signal-cli-data`.

## Path deviation from plan

Plan specified `/opt/mushy-backups/signal-cli-data-YYYYMMDD.tar.gz`. Operator was unavailable for the one-time `sudo mkdir -p /opt/mushy-backups` step at capture time, so the tarball landed at `/mnt/slime-kingdom/mushy-backups/...` (RAID-backed, writable without sudo, equally durable). Documented in the preflight artifact + restore recipe. Operator may `sudo ln -s /mnt/slime-kingdom/mushy-backups /opt/mushy-backups` post-hoc if cross-script consumers assume `/opt`; nothing in this repo currently does.

## Plan 36-02 pre-flight checklist status

Mechanical gates **PASS** (tarball + JSON + verdict + restore recipe all in place). Operator gates **PENDING** before Plan 36-02 Task 2 (live re-reg):
- Farmer #1 reachability window coordinated
- 4G router powered up + reachable (in progress at session time — operator action)
- `gumbald` ssh confirmed; 4G WiFi creds available on gumbald
- 36-RUNBOOK.md drafted (Plan 36-02 Task 1)

## Decisions made during execution

- Tarball path deviated to `/mnt/slime-kingdom/mushy-backups/` — see above.
- Did NOT abort on `id=1` appearing — reasoning documented in preflight artifact.
- Filed 999.52 in ROADMAP.md (was originally going to be 999.51; that number was already taken by stale-test-debt, surfaced 2026-05-11 in the same backlog sweep).

## Verification

```
$ test -f /mnt/slime-kingdom/mushy-backups/signal-cli-data-20260511.tar.gz && echo OK
OK
$ tar -tzf /mnt/slime-kingdom/mushy-backups/signal-cli-data-20260511.tar.gz | wc -l
140
$ jq -e '.[0].id' .planning/phases/36-signal-pre-gate/snapshots/devices-20260511.json
1
$ grep -E '\+[0-9]{8,}' .planning/phases/36-signal-pre-gate/snapshots/*.json
(empty — no E.164 leaks)
$ grep -c "## " .planning/phases/36-signal-pre-gate/36-01-preflight-snapshot.md
5  # Snapshot Captured / Phase 35 verdict / Restore Recipe / Pre-Flight Checklist / References
```

All acceptance criteria from `36-01-PLAN.md` satisfied (with the documented path deviation).

## Next

Wave 2 — Plan 36-02 (RUNBOOK + live re-registration, interactive) and Plan 36-03 (post-rebuild-trust-check.sh, autonomous). Plan 36-02 cannot start until operator confirms the 4G router is reachable from gumbald and farmer #1 has a 30–60 min window.
