# 44-02 Task 2.3a — Group-send recipient encoding decision (RESEARCH Open Q1 / B2)

**Status:** AWAITING OPERATOR DECISION
**Blocks:** Task 2.3 (signal.js persistence-hook wiring) and downstream Plan-04 `lastBot`
lookup + Plan-05 `fmtHistory` recipient-filter.
**Raised by:** executor for 44-02 on 2026-05-21.

## Why this is up to you, not the planner

`signal_outbound.recipient_e164 text NOT NULL` (D-12, verbatim) was written for
1:1 sends. Three of the 14 send sites in the audit (RH alerts at `index.js:180,
183, 185`; group convo replies) target a **group**, not an e164 number.

The planner's original sketch (RESEARCH Pattern 3) suggested encoding group
sends as `recipient_e164 = 'group:<id>'` (option b). Per B2 — operator owns this
schema-semantics call, not the planner — the executor halts here.

## The three options

### (a) Add a nullable `recipient_group_id text` column

- DDL change: drop `NOT NULL` on `recipient_e164`, `ALTER TABLE signal_outbound
  ADD COLUMN IF NOT EXISTS recipient_group_id text`, plus
  `CREATE INDEX IF NOT EXISTS idx_signal_outbound_group_sent
  ON signal_outbound(recipient_group_id, sent_at DESC) WHERE recipient_group_id IS NOT NULL`.
- For 1:1 sends: `recipient_e164` populated, `recipient_group_id` null.
- For group sends: `recipient_e164` null, `recipient_group_id` populated.
- Pros: schema is self-documenting; no string-prefix parsing downstream;
  recipient filter at fmtHistory / lastBot can `WHERE recipient_e164 = $1 OR
  recipient_group_id = $2`.
- Cons: extra ALTER on a brand-new table (cheap; nothing has shipped); breaks
  the verbatim D-12 NOT NULL invariant for `recipient_e164`; one more index.

### (b) Encode as `group:<id>` prefix in `recipient_e164`  (planner's sketch)

- DDL unchanged from D-12 verbatim — `recipient_e164` stays `NOT NULL`.
- For 1:1 sends: `recipient_e164 = '+15551234567'`.
- For group sends: `recipient_e164 = 'group:<id-b64>'` where `<id-b64>` is the
  resolved id-b64 form (matches what signal-cli emits, matches what existing
  `signal.js` logs already say `group:<id-prefix>…`).
- Pros: zero schema change; preserves D-12; recipient-filter at fmtHistory is
  a single `WHERE recipient_e164 = $1` with caller passing `'group:<id>'` for
  group lookups.
- Cons: column name lies about its content; prefix-parsing required if any
  downstream consumer wants to know "is this a group send?"; one more place to
  remember the convention.

### (c) Other — operator's call

- Describe the desired encoding; the executor implements it exactly.

## Recommendation (executor non-binding)

**(b) prefix.** Rationale: the table is brand-new and the receive-loop already
labels groups in logs as `group:<prefix>…` — adopting the same string at the
column level keeps the mental model symmetric (logs ↔ DB rows) and avoids a
schema deviation from D-12 on the very first ship of the table. The downside
(prefix-parsing) is local to one consumer in Plan-05 fmtHistory.

But this is genuinely your call — option (a) is cleaner if you want to keep
`recipient_e164` semantically pure for downstream multi-tenant carve-out (v2.0
Foray will scan this column for PII; mixed e164/group:id values may complicate
that).

## Resume-signal

Reply with one of:

- `encoding: column (a)` — executor implements path (a)
- `encoding: prefix (b)` — executor implements path (b)
- `encoding: <other>` with description — executor implements path (c)

The executor will then resume at Task 2.3.
