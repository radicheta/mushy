# TODO: unmerged work stranded on `fix/inoc-starting-seq-dispatch`

Status: open / deferred (logged 2026-06-27)
Priority: medium (working features live in prod but not on main)

## Issue

The branch `fix/inoc-starting-seq-dispatch` is misnamed and carries a grab-bag of
unmerged work. As of 2026-06-27 it is **34 commits ahead / 56 behind `main`**. The
deployed Mission Control stack (openmct + bridge) was built from its commit
`fbccb5c` — i.e. prod was running off this stale side-branch, not main.

On 2026-06-27 the **VPD + "Water in air" derived-telemetry** feature (`fbccb5c`)
was cherry-picked out onto `main` (`fecbed2`) and MC was redeployed from main, so
that part is resolved. But the branch still has other work that exists ONLY there:

- **Pinning cycler** — `c3baeb8` feat(fc): pinning cycler (condensation/evaporation
  cycles), `ba83df8` vent-aware wet phase, `8f695b2` systemd unit (reboot-persistent).
- **Phase 54.2 strain-detection** — `09521d9`, `40b6dbc`, `4488fcb`, `985ad14`,
  `e33232a` and related (send_strain_ask_back dispatcher, multi-group correction
  guard, strain-detection tests).
- Assorted docs/board commits.

## Why it matters

These are real, possibly-deployed behaviors that aren't on the mainline. If main
(or `feat/phase-56-foundation`) is ever the build source for fc-core / the
alerter, this work silently disappears. The pinning cycler in particular is
referenced in operating memory (pinning runs) — confirm whether what's running on
fc1 corresponds to committed code on main before assuming parity.

## Suggested resolution (when picked up)

1. Triage each cluster (pinning cycler, 54.2 strain-detection) independently —
   cherry-pick or merge onto `main` the pieces that are still wanted.
2. Reconcile against `feat/phase-56-foundation` (the Python-port milestone, 198
   ahead of main) so the 54.2 alerter work isn't duplicated or lost.
3. Delete `fix/inoc-starting-seq-dispatch` once its contents are merged or
   explicitly abandoned.

## Root cause (process)

Single working tree on elder-plops doubles as both the edit surface AND the docker
build context. Building MC requires the MC branch checked out; editing the alerter
requires the milestone branch. Switching between them is how prod ended up built
off a stale branch nobody was tracking. Consider a dedicated checkout/worktree for
the deploy build context, or pinning the MC deploy to `main`.
