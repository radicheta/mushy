# Phase 44: Event-gate + Durable `signal_outbound` (tenant-aware) - Discussion Log

**Date:** 2026-05-21
**Mode:** discuss (default), Auto Mode harness active
**Operator:** Don Santiago

This log is for human reference only (audits, retrospectives). Not consumed by downstream agents — they read 44-CONTEXT.md.

---

## Pre-loaded context

- Roadmap entry for Phase 44 (ROADMAP.md §"Phase 44") — goal + 5 proposed requirements (GATE-01/02, OUTBOUND-01/02, TENANT-01) + 4 open design questions.
- 5 reference notes (all dated 2026-05-17): event-gate design, llm-outbound amnesia, OSS-Foray α decision, signal_outbound schema audit, prod corpus survey, tenant-id retrofit map.
- Prior CONTEXT.md style template from Phase 43.
- 40+ memory entries — strongest hits: `[[2026-05-17-findings-discussion-decisions]]`, `[[2026-05-17-oss-foray-alpha-lock]]`, `[[mossrock_active_strain_codes]]`, `[[feedback_smoke_before_expensive_batch]]`, `[[feedback_real_data_before_ship_gate_pass]]`, `[[feedback_no_silent_failure_after_farmer_confirm]]`, `[[feedback_no_farmer_bookkeeping_tax]]`.

Operator override expected: the 2026-05-17 event-gate note §10 recommended rules-only-first with conditional Haiku follow-up; the roadmap left this open.

---

## Q1 — Gate model

**Options presented:**
1. Rules-only first, audit a week, add Haiku only if needed (Recommended per note §10)
2. Hybrid (rules + Haiku) from day one
3. Rules-only, file Haiku as v1.9 candidate (don't even scaffold)

**Operator selection:** Hybrid (rules + Haiku) from day one — **overrode the recommendation**.

**Resulting decisions:** D-01, D-02, D-03, D-04.

**Implication:** Plan-04 (Haiku classifier) is in-scope for Phase 44 — not conditional, not deferred. Operator chose committed scope over staged rollout.

---

## Q2 — Convo gating at capture.js:168

**Options presented (first round):**
1. Yes — bundle (gate both extractor and convo paths)
2. No — gate extractor only
3. NEGATIVE fast-path only — silence convo on attestation-ack, keep open in gray zone

**Operator response:** "explain this please"

**Explanation provided:** Walked through the two paid LLM calls per inbound message (`:147` extractor / `:168` convo compose), showed concrete examples ("Ok" after attestation, "hola" greeting, "650g shiitake from logs") under each option, and the UX tradeoffs (responsive bot vs. token savings vs. NORTH-STAR collision risk).

**Re-ask options:**
1. NEGATIVE-only (Recommended after Q1=hybrid)
2. Gate both fully
3. Don't gate convo

**Operator selection (verbatim):** "build what you have to build, keep it flexible, but focus on cheap for now. we don't mind erring on the side of silent"

**Interpretation:** Map to "gate both fully" (cheapest, errs silent) BUT make the convo-gate behavior configurable so we can dial back if the silence overshoots. Default = `silent`; escape hatches = `negative_only` and `off`.

**Resulting decisions:** D-05 (gate both), D-06 (config knob `EVENT_GATE_CONVO_MODE`), D-07 (no NORTH-STAR collision since gate fires pre-confirm).

**Memory check:** Re-read `[[feedback_no_silent_failure_after_farmer_confirm]]` — the NORTH-STAR carve-out is "post-YES paths must ack." Gate fires on cold inbound (no prior YES), so silence here is allowed. Confirmed.

---

## Q3 — Tenant-id retrofit for existing tables

**Options presented:**
1. Defer to v2.0 carve-out (Recommended per OSS-Foray decision)
2. Add nullable tenant_id columns now (no backfill)
3. Full retrofit now (add + backfill + reindex)

**Operator selection:** Defer to v2.0 carve-out (Recommended).

**Resulting decisions:** D-08, D-09.

**Rationale:** Locked by 2026-05-17 OSS-Foray decision §"v1.8 implications." No re-litigation needed.

---

## Q4 (bundle) — Phase 45 bundling

**Options presented:**
1. Keep separate — ship 44 first, then 45 (Recommended)
2. Bundle: do ACK + replay inside Phase 44

**Operator selection:** Keep separate (Recommended).

**Resulting decisions:** D-10.

**Rationale:** Phase 44 is already ~5d bundled work. Phase 45 touches state-machine terminal-state enumeration + replay logistics for 2 specific drafts — different blast radius. `signal_outbound` will be live for Phase 45 to consume.

---

## Q4 (tenants/) — tenants/mossrock/ contents

**Options presented (multiselect):**
1. SIGNAL_FARMER_MAP (Recommended)
2. Strain vocab — 14 active codes (Recommended)
3. Secrets: ANTHROPIC_API_KEY + Signal sender/recipient/group (Recommended)
4. FarmOS endpoint config (Recommended)

**Operator selection:** ALL FOUR.

**Resulting decisions:** D-11 (full migration set), file layout (`config.yaml` + `strains.yaml` + `secrets.env` gitignored), boot chain (`tenants/<id>/` → env → default).

---

## Scope creep / deferred ideas surfaced

- **CI grep-gate against raw `.send(` outside `signal.js`** — surfaced from amnesia note §8 as a regression-prevention nice-to-have. Filed deferred; planner may include if cheap.
- **Drop `signal_capture.llm_reply` column** — kept for audit/rollback safety in Phase 44; v2.0 cleanup. Filed deferred.
- **Telemetry counter / cost dashboard for Haiku classifier** — `extraction_gate` audit column suffices for ship-gate. v1.9 candidate. Filed deferred.

No new-scope creep raised by operator during the session.

---

## Claude's discretion (handed to planner)

- File layout under `event-gate/`: `index.js` + `rules.js` + `haiku-classifier.js` or flatter — planner picks.
- DAO location: `outbound-db.js` parallel to `capture-db.js`/`extraction-db.js`/`confirm-db.js`.
- Boot-chain config loader: planner picks YAML lib (lightweight only); no heavy framework.
- Haiku timeout/retry policy: planner picks; default suggestion 2s no-retry → fall through to Sonnet.
- Wrapper signature ergonomics for the 14 send sites: planner picks; suggestion `send(recipient, body, { intent, attachments?, relatedCaptureId?, relatedDraftId? })`.

---

## Next step

`/clear` then:

`/gsd-plan-phase 44`

---

*Discussion gathered: 2026-05-21*
