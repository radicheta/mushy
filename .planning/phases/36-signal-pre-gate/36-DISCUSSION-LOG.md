# Phase 36: Signal Pre-gate — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 36-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-11
**Phase:** 36-signal-pre-gate
**Areas discussed:** Backup posture, Trust re-issuance, Artifact form, Verification recipients

---

## Backup + Rollback Posture

| Option | Description | Selected |
|--------|-------------|----------|
| Full volume tarball + identity DB | Snapshot signal-cli-data volume + JSON dump of /v1/devices + /v1/identities to elder-plops disk before re-reg | ✓ |
| Identity files only | Skip the volume tarball, just save the identity JSON | |
| Rely on Phase 35 nightly backup | No new snapshot; Tier A age-encrypted nightly tarball is sufficient | |

**User's choice:** "whatever" — discretion accepted. Defaulting to the full-volume-tarball-plus-identity-JSON shape (safest, ~MB-scale on disk, cheap to keep for 7 days). Phase 35 backup verified as fallback only — D-03 turns it into a check (does Phase 35 actually cover signal-cli state).

**Notes:** Restoration path from local tarball documented in D-04 as the abort plan. Keep old linked-secondary device entry alive until PRE-02 passes (D-05) so coexistence is the rollback story, not "kill old before knowing new works."

---

## Trust Re-issuance to Farmers

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-trust via curl loop | Run `trust_all_known_keys=true` against every known farmer identity immediately after re-reg | |
| Ask farmers to re-accept manually | Bot sends a "I've been re-registered, please tap the safety-number warning to re-accept me" message; farmers do it on their phones | ✓ |
| Hybrid (auto-trust + ping-back) | Auto-trust to bypass the warning, then ping each farmer to confirm | |

**User's choice:** "ask farmers to re-accept"

**Notes:** Safer trust posture; farmers see the bot is back and have a moment to notice. Auto-trust curl path is preserved as a recovery tool for the *post-rebuild trust-DB corruption* scenario (D-08) — distinct from initial re-reg.

---

## Artifact Form (Script vs Runbook)

| Option | Description | Selected |
|--------|-------------|----------|
| Single idempotent shell script | scripts/signal/re-register.sh runs the full re-reg flow | |
| Step-by-step runbook | 36-RUNBOOK.md documents the manual flow with checkpoints | (primary) ✓ |
| Hybrid (runbook + small enforcement script) | Runbook for the re-reg event; one small script for the post-rebuild trust check | (selected) ✓ |

**User's choice:** "whatever you think"

**Notes:** Took the hybrid (D-09 + D-10). Re-registration is a one-time event with a manual SMS captcha step — runbook is the right form. The *post-rebuild trust check* IS scriptable and load-bearing for SC#3, so it lands as `scripts/signal/post-rebuild-trust-check.sh`.

---

## Verification Recipients + Cadence

| Option | Description | Selected |
|--------|-------------|----------|
| Farmer #1 only | Operator + farmer #1 round-trip | |
| Farmer #1 + farmer #2 (zoy) | f1 = on-site farm operator; f2 = zoy (dev partner) | ✓ |
| All three farmers (#1, #2, #3 iOS) | Maximum coverage | |
| Operator + gumbald + f1 + f2 | Internal-only verification | |

**User's choice:** "f1 and f2"

**Notes:** Farmer #3 (iOS) and gumbald deferred to opportunistic add-on. Cadence (D-13) added without explicit ask but flagged in CONTEXT: same-session verification + 24h re-run + load-bearing container rebuild during verification window. This makes Success Criterion #3 actually attestable instead of vibe-checkable.

---

## Claude's Discretion

- Concrete backup paths/commands (D-01..D-04 specifics) — planner decides shapes.
- Where `post-rebuild-trust-check.sh` runs (healthcheck vs systemd timer vs manual) — planner picks based on alerter compose patterns.
- Exact text of the farmer-facing kickoff message — planner drafts in Phase 25 reply tone.

## Deferred Ideas

- Auto-trust everywhere as default (vs initial-manual-accept).
- Multi-account signal-cli setup (per-farmer accounts).
- Signal-CLI version pinning + upgrade story.
- gumbald wg-hub peer (999.47) — operator-side convenience.
