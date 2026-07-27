# Phase 62: farmOS Write Path - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-28
**Phase:** 62-farmos-write-path
**Areas discussed:** Origin guard, Live-fire scope, CSV fidelity gate

---

## Origin guard (SC1 — structural prod-leak prevention)

| Option | Description | Selected |
|--------|-------------|----------|
| origin column + Node patch | Add `origin` column; Python sets `origin='python'`; patch live Node watchdog SELECT with `AND origin != 'python'`. Permanent, requires live Node edit+deploy. | ✓ |
| Isolated :5434 DB only | Run all Python validation against throwaway :5434; no Node change. | |
| origin column, defer Node patch | Add column now, defer Node AND-clause to v1.13, lean on :5434 isolation today. | |

**User's choice:** origin column + Node patch.
**Notes:** Deliberately pulls the v1.13 backlog watchdog-origin-guard forward into Phase 62. Implies a HARD sequencing constraint (CONTEXT D-02): migration -> Node patch -> Node prod redeploy must all land before any Python writes `confirmed` to shared Timescale.

---

## Live-fire scope (SC2 / SC3 — upsert + image)

| Option | Description | Selected |
|--------|-------------|----------|
| In-phase dev live-fire | Commit twice against dev :18080: assert 0 dup assets + image on `image` field. Dev creds resolved. | ✓ |
| Hermetic + deferred live-fire | Mock JSON:API for automated SCs; defer real dev live-fire to operator (as 58-60 did). | |

**User's choice:** In-phase dev live-fire against farmOS :18080.
**Notes:** Departs from the 58-60 deferral pattern. Write path is a wiring seam unit tests miss.

---

## CSV fidelity gate (SC4)

| Option | Description | Selected |
|--------|-------------|----------|
| Hold + farmer ask-back | Hold as `fidelity_cross_check_unverified` AND send farmer ask-back; CSV from prod path @boot, fixture @test. | ✓ |
| Silent hold (no ask-back) | Hold only, no farmer message this phase. | |
| Fixture-only this phase | Gate logic against test fixture only; defer prod CSV wiring + ask-back. | |

**User's choice:** Hold + farmer ask-back; CSV prod path at boot, fixture in tests.
**Notes:** Consistent with no-silent-failure + farmer-as-source-of-truth. CSV stays non-authoritative (FLAG/hold, never silent hard-reject).

---

## Claude's Discretion

- commit-watchdog poll interval + boot task wiring (mirror Node 30s + Phase 57-60 pattern).
- httpx retry/backoff constants (mirror Node 10s / 3x backoff unless research diverges).
- Fixture CSV shape + ask-back message wording.

## Resolved from code (not asked of user)

- Stable identity is name-based, NOT a hex digest (merge.js is pure field-merge). ROADMAP SC2 "hex digest" wording flagged for reconciliation (CONTEXT D-05).

## Deferred Ideas

- Broader dev/prod isolation beyond the watchdog clause (Phase 64 already mandates :5434).
- CSV ask-back conversational auto-resolution flow (follow-on).
