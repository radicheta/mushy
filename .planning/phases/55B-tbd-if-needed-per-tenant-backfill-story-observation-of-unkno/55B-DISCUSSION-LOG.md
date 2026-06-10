# Phase 55b: Fidelity / corpus-unblock - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 55b-fidelity-corpus-unblock
**Areas discussed:** 55b existence/scope, Cross-check behavior, Image attachment level

---

## 55b existence/scope (meta-decision)

| Option | Description | Selected |
|--------|-------------|----------|
| Close it — not needed | Mark N/A; per-tenant absorbed by v1.12 port + alpha-lock; unknown-asset by Phase 51/54.1 | |
| Fidelity / corpus-unblock | Repurpose to the parked-run blockers: commit-time cross-check + F1/F2 page-photo | ✓ |
| Unknown-asset observation path | Mint-with-confirm on observation/harvest of nonexistent asset | |
| Per-tenant backfill story | tenant_id-parameterize the harness for OSS-Foray | |

**User's choice:** Fidelity / corpus-unblock.
**Notes:** The two originally-named scopes were judged absorbed elsewhere; the real open
work from Phase 55 is the parked-run fidelity blockers.

---

## Cross-check behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Hold strain mismatches only | Hold strain disagreements; commit non-strain + no-CSV, reconcile in session view | |
| Hold all disagreements + no-CSV | Auto-commit only exact CSV agreement; hold everything else as needs_review | ✓ |
| Commit all, annotate only | Commit everything, tag disagreements, no holds | |

**User's choice:** Hold all disagreements + no-CSV (maximally safe).
**Notes:** Santi wants nothing unverified in farmOS, accepting heavier human reconcile
load. Implication captured in CONTEXT D-02: resolution surface must be the F2 session
view, not a Signal batch (corpus-scale holds make a Signal blast unusable).

---

## Image attachment level

| Option | Description | Selected |
|--------|-------------|----------|
| Session asset, 1..N pages | Attach every page a session spans to the one session group asset | ✓ |
| Per-log, source page each | Each block log carries its source page; N uploads + 5 commit paths touched | |
| Both | Session + per-log; overkill | |

**User's choice:** Session asset, 1..N pages.
**Notes:** Santi corrected the unit mid-discussion: "a single inoc session can fill more
than a single notebook page — the unit is the inoc session, not the notebook page." This
reframes F2 as a session view and means the session asset carries 1..N page images.

---

## Claude's Discretion

- CSV cross-check keying / per-entry match granularity.
- How backfill switches from plain `log_type:'seeding'` to session-shaped commits.
- How non-seeding shapes on a session attach to the group (deferred sub-question).
- Rendering/querying `needs_review` entries inside the session view.
- Smoke/re-audit set size + selection.

## Deferred Ideas

- Extraction-prompt strain-column hardening (root-cause; "secondary" per audit).
- Strain-gate re-wire CR-01/CR-02 (held; doesn't catch mode-2; conflicts with gate-moot).
- Prod cleanup of the 2026-06-07 audit set (needs farmOS admin DELETE).
- Per-tenant backfill (v1.12 Python port).
- Observation-of-unknown-asset standalone path (Phase 51 + 54.1).
