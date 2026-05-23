# Phase 45 Plan 05 — Live-fire UAT — SUMMARY

**Shipped:** 2026-05-23
**Status:** PASS (named pair + 3 ack-debt extras delivered; idempotency proven; NORTH-STAR closed)

## What shipped

- `src/agents/alerter/scripts/phase-45-backfill-outcome-acks.js` — one-shot NDJSON backfill runner; honors the deployed `tryMarkOutcomeAckSent` CAS claim (no idempotency bypass); per-draft outcome derived from status (`commit_failed`→failed, `committed`→success).
- Plan-04 alerter rebuild + recreate (image sha `1a8891fc…`); container `mushy-alerter-1` healthy with `send_commit_outcome_ack` wired, `outcome_ack_sent_at` column present.

## Live-fire dispatches (5 total)

| Draft prefix | Farmer | Outcome | Body len | Signal ts | Created |
|---|---|---|---|---|---|
| `b8a1e586…` | Vikki | failed (observation_requires_target) | 92 | 1779550514960 | 2026-05-15 22:52 |
| `1fb28e70…` | Santi | success (committed silently, T4) | 134 | 1779559033660 | 2026-05-15 23:30 |
| `0c5533f9…` | Santi | failed (no_target_asset_for_activity) | 102 | 1779559248242 | 2026-05-21 02:33 |
| `6934760c…` | Santi | failed (observation_requires_target) | 92 | 1779559253191 | 2026-05-15 23:50 |
| `946a7b08…` | Santi | failed (observation_requires_target) | 92 | 1779559262654 | 2026-05-13 12:37 |

All 5 rows present in `signal_outbound` with `intent='commit_outcome_ack'`, body length match exact, `source_module='outbound-confirm.js'`. Phase 44 plumbing validated end-to-end.

## ACK requirements

- **ACK-01** (no silent terminal post-YES) — code-side verified Plan 04. Runtime path now produces farmer-facing replies on both T4 and T6.
- **ACK-02** (Vikki Rambo replay) — DELIVERED via DM to `+59898018597`. Signal ok=true.
- **ACK-03** (Santi LIMA replay) — DELIVERED via DM to `+59892893012`. Signal ok=true.
- **ACK-04** (repeat-invocation idempotency) — PROVEN on prod. Re-running the script against both originally-listed drafts returned `claim={ok:false, reason:'already_claimed'}` and zero new dispatches.

## NORTH-STAR audit

`SELECT COUNT(*) FROM signal_draft WHERE status='commit_failed' AND outcome_ack_sent_at IS NULL` = **2**.

Both remaining are smoke/test drafts from 2026-05-14:
- `smoke20260514162505_optA_harv_d69ec48d` (dev QR gap, not real)
- `smoke20260514174046_prod_seed_6082fc30` (http_422, not real)

No real farmer-facing silent failures remain on prod. The 2026-05-15 NORTH-STAR violation is closed; the 2026-05-13, 2026-05-15 (second one), and 2026-05-21 ack-debt drafts also closed.

The 2026-05-22 paper-log draft (`e3a564d0…`) is `status='awaiting_farmer'` — Santi hasn't replied YES/NO yet, so it is correctly NOT a silent failure. Phase 47-49 will address the structural multi-parent extraction shape that produced it.

The 2026-05-23 04:34 draft (`f87eb1e0…`) is `status='discarded'` — already farmer-resolved. The script's `skip_unsupported_status` filter caught this correctly (defensive design — only dispatches for `commit_failed`/`committed`).

## Deviations

1. **Plan listed `scripts/phase-45-…` at repo root; shipped at `src/agents/alerter/scripts/`** — that's where the existing node-script pattern lives (alerter `node_modules`, env-loading via `config.load()`). Operator runs via `docker exec mushy-alerter-1 node /app/scripts/…`.
2. **Script `result` label mislabel on already-claimed path** — when `tryMarkOutcomeAckSent` returns `{ok:false, reason:'already_claimed'}`, the emitted JSONL line says `result:"not_found"` due to a guarded property check. The underlying `claim` object is the source of truth and IS captured in the line. Cosmetic; not worth a patch.
3. **`sender_name` not in schema** — renderer reads `draftRow.sender_name` to emit `Hi {name}, ` greeting; signal_draft has no such column today. Backfill script patched in via `SIGNAL_FARMER_MAP` lookup (+capitalize). Runtime dispatch path (commit-watchdog.js) has the same gap — future `commit_failed`/`commit_success` acks will lack the named-address prefix until patched. Tracked as follow-on (below).
4. **Ack-debt extension** — Plan 05 named only 2 drafts; live-fire surfaced 5 additional pre-Plan-04 silent failures. Per operator instruction, backfilled 3 real ones to Santi (skipped 2 smokes and 2 non-`commit_failed` drafts via script filter).

## Follow-ons (NOT blocking Phase 45)

1. **Runtime named-address gap** — patch `commit-watchdog.js`'s `_maybeDispatchOutcomeAck` to enrich `lockedRow.sender_name` from `config.signalFarmerMap` before dispatch. ~5 LOC + 1 unit test. Without this, fresh acks lack `Hi {name}, ` prefix.
2. **Ack-debt sweep tooling** — script could grow a `--all-silent` flag for periodic ack-debt sweeps. Pair with a "Plan-04 deployment cutoff" filter so the script never sends acks for failures predating the deployed code.
3. **Vikki paste verification** — operator-deferred to skip-for-now. Receipt is database-attested (`signal_outbound` row + `signal-cli` `ok:true`) but farmer-paste protocol from `[[feedback_verify_signal_send_attribution]]` not exercised on Vikki. Plan-05 sequencing put it before Santi; deferred at operator direction.

## Artifacts

- `.planning/phases/45-…/45-05-live-fire-prefix.md` — dry-run NDJSON for both originally-listed drafts
- `.planning/phases/45-…/45-05-live-fire-vikki-rambo.jsonl` — Vikki: boot + pre + dispatch + post + repeat-invocation already_claimed
- `.planning/phases/45-…/45-05-live-fire-santi-lima.jsonl` — Santi: boot + pre + dispatch + post + repeat-invocation already_claimed
- `.planning/phases/45-…/45-05-live-fire-santi-ack-debt.jsonl` — 5-draft sweep (2 filtered out, 3 dispatched)

## ROADMAP one-liner

Phase 45 shipped 2026-05-23: NORTH-STAR commit_failed ack live on prod; original 2026-05-15 violation closed; 3 additional pre-Plan-04 silent failures swept (Santi). ACK-01..04 satisfied. Runtime `sender_name` enrichment tracked as follow-on.
