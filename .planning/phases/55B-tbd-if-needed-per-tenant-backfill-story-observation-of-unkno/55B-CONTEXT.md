# Phase 55b: Fidelity / corpus-unblock - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Land the changes that must exist BEFORE the parked full-2025-corpus run (Phase 55)
is safe to execute. Phase 55 shipped the harness + operator docs; the live run is
parked because the 2026-06-07 prod 10-page audit found ~38% infidelity on checkable
pages, including **silent strain misattribution** (POY committed as KOY, no error).

55b delivers two coupled capabilities:

1. **Commit-time fidelity cross-check** — compare extracted entries against the
   per-page CSV reading and HOLD anything not verified, instead of committing it.
2. **F1+F2 session reconcile surface** — group a backfill's per-block logs/assets
   under the inoc-session group asset (Phase 52 mechanism) with the source notebook
   page image(s) attached to the session asset, so a human can open the session in
   farmOS and reconcile it 1:1 against the physical notebook.

The original 55b placeholder named two scopes ("per-tenant backfill story",
"observation-of-unknown-asset path"); both were judged absorbed elsewhere (v1.12
Python port is tenant-aware day 1 + OSS-Foray alpha-lock; unknown-asset handled by
Phase 51 upsert + 54.1 strain-confirm + source-of-truth reconcile policy). 55b is
re-scoped to the actual blocker: fidelity + corpus-unblock (decided with Santi
2026-06-09).

### In scope
- Commit-time cross-check of extracted entries vs the per-page CSV reading.
- `needs_review` HOLD path for every entry that is not exact-verified (see D-01).
- Backfill emits session-shaped commits so per-block logs/assets group under the
  inoc-session group asset (reuse Phase 52 `commit-seeding-session.js` mechanism).
- Attach the source notebook page image(s) to the session group asset (1..N pages
  per session — a session can span multiple notebook pages).
- The session view must surface held (`needs_review`) entries, not only committed
  ones — it is the resolution UI (see D-02).
- Re-smoke + re-audit a small set before any full run (the existing GA1-isolated
  smoke discipline).

### Out of scope (deferred / not this phase)
- **The live full-corpus run itself** — still operator-triggered + GA2-gated
  (Phase 55 owns the runbook / promotion decision).
- **Extraction-prompt strain-column hardening** (root-cause fix for POY->KOY
  misreads). Detection + hold is sufficient for 55b; prompt-hardening deferred
  (Santi did not select it for discussion). See Deferred.
- **Generalizing the harness to multi-tenant** (per-tenant backfill story) — v1.12
  Python port owns this.
- **Observation-of-unknown-asset** as a standalone path — covered by Phase 51
  upsert + 54.1 strain-confirm.
- **Prod cleanup** of the 99 assets + 98 logs the 2026-06-07 audit set wrote to
  prod (some misattributed) — needs a farmOS admin DELETE; carried as a separate
  reconcile task.
- v1.13 narrowing (consumes BACK-10 output; separate milestone).
</domain>

<decisions>
## Implementation Decisions (with Santi 2026-06-09)

### Cross-check behavior
- **D-01 — Hold-everything-unverified (conservative).** Auto-commit ONLY entries
  that exactly agree with the page's CSV reading. Every CSV *disagreement* AND every
  entry with *no CSV reading at all* is held as `needs_review` (reuse the 54.1 hold
  state — not committed). Nothing unverified reaches farmOS. Rationale: the CSV is
  not authoritative ([[project_backfill_csv_is_not_ground_truth]]) so disagreement
  must never hard-reject OR silently commit; and a committed wrong strain cannot be
  upsert-fixed (Phase 51 converges names, not `fungi_type`). Santi explicitly chose
  the maximally-safe option over the strain-only variant.
- **D-02 — Resolution surface is the F2 session view, NOT a Signal batch.** At
  corpus scale ~half the entries will hold; a Signal confirm blast is unusable.
  Held (`needs_review`) entries must appear inside the session view alongside the
  attached page image so a human reconciles them against the actual notebook. The
  Signal-batched 54.1 confirm path is the wrong UI here.

### Image attachment level
- **D-03 — Attach at the session group asset, 1..N page images.** Attach every
  notebook page a session spans to the single inoc-session group asset (NOT
  per-log). Opening the session shows all its source page images side-by-side with
  its farmOS members = the F2 reconcile surface. One upload path (extend
  `commit-seeding-session.js`); no per-log attachment code in the other 4 commit
  paths. Santi confirmed session-level over per-log/both.

### Grouping unit (Santi correction, carried into all decisions)
- **D-04 — The grouping/reconcile unit is the INOC SESSION, not the notebook page.**
  A single inoc session can span more than one notebook page (and a page may hold
  more than one session / a mix of shapes). F2 is therefore a *session* view, not a
  *page* view. This corrects the "one session per page" framing in the
  2026-06-07 audit-findings todo. Aligns with
  [[project_session_is_production_shape_per_bag_is_storage]].

### Claude's Discretion
- Exact mechanism for keying the CSV cross-check (per-entry strain/quantity match
  granularity; how a page's CSV rows map onto extracted entries).
- How backfill switches from plain `log_type:'seeding'` to session-shaped commits
  (the audit-findings todo notes backfill currently emits plain `seeding` → routed
  to per-block `commit-seeding`, bypassing the session group). Researcher/planner
  picks the cleanest route into `commit-seeding-session.js`.
- Whether/how non-seeding shapes on a session (observation/harvest/activity/input)
  attach to the session group — the original "Session-per-page shape" question Santi
  deferred. Default: member logs reference member assets which carry the group
  edge; the membership log lists them. Validate during research.
- How `needs_review` entries are rendered/queryable inside the session view.
- Smoke/re-audit set size and selection.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Fidelity audit + findings (the WHY)
- `.planning/notes/2026-06-07-prod-smoke-fidelity-audit.md` — the 10-page prod
  audit; three failure modes (misread-fail / silent misattribution / under-capture);
  Santi's "CSV is a misnomer" correction; why the strain-gate (CR-01/02) does NOT
  catch mode 2.
- `.planning/todos/pending/2026-06-07-backfill-audit-findings.md` — F1 (page photo
  per log/session) + F2 (session reconcile view) + the converged design.
- `.planning/notes/2026-06-07-overnight-handoff.md` — overnight status; CR-01/02
  deferred rationale.

### Phase 55 (what shipped; 55b extends it)
- `.planning/phases/55-full-corpus-run-receipt/55-CONTEXT.md` — GA1 (operational
  isolation) + GA2 (full-run gated on Cycle-2 sign-off) decisions still bind.
- `.planning/phases/55-full-corpus-run-receipt/55-PROMOTION-DECISION.md` — dev-only
  default; prod opt-in (BACK-11).
- `.planning/phases/55-full-corpus-run-receipt/55-FULL-CORPUS-RUNBOOK.md` — GA1
  isolation pre-flight the re-smoke must reuse.

### Session-group + upsert mechanisms 55b reuses
- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` — Phase 52
  session group asset + `is_group_assignment` membership log; the extension point
  for D-03 image attach + session-shaped backfill commits.
- `.planning/notes/2026-05-24-session-as-asset-group-design.md` — Phase 52 session
  design rationale.

### Private-files prerequisite (RESOLVED — do not re-do infra)
- `.planning/notes/2026-05-25-pointer-farmos-private-files-SHIPPED.md` — bind-mount
  + `file_private_path` live + verified on dev AND prod; uploads work with no infra
  change. Only the session-level *wiring* is missing.
- [[project_farmos_private_files_and_mushy_silent_photo_drop]] — the original
  silent-drop landmine (now mitigated).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` — creates the
  inoc-session group asset via `groupAssets.upsertGroupAsset` + posts the
  `is_group_assignment` membership log. The single extension point for both the
  session-shaped backfill commit and the D-03 page-image attach.
- `src/agents/alerter/src/farmos/files.js` — `uploadAttachment`/`uploadAttachments`
  already POST to `/api/file/file`. Reuse for the session-asset image attach.
- `src/agents/alerter/src/farmos/groupAssets.js` — `upsertGroupAsset` (content-
  addressable by name; composes with Phase 51 upsert).
- `src/agents/alerter/scripts/build-backfill-receipt.js` — already computes the
  per-page CSV diff (hit/miss/extra). The SAME diff is the basis for the
  commit-time cross-check (D-01) — promote it from receipt-only to a commit gate.
- `src/agents/alerter/scripts/backfill-notebook.js` — synthetic capture already sets
  `attachment_paths:[page]` (~line 189); page provenance is already carried.

### Established Patterns
- **54.1 `needs_review` hold** — unknown-strain drafts held + resolved in a follow-up
  pass. D-01 reuses the hold STATE but changes the resolution UI to the F2 session
  view (D-02), not the Signal batch.
- **Only `commit-observation.js` uploads attachments today** — seeding/harvest/
  activity/input have ZERO attachment code. D-03 deliberately avoids touching them
  by attaching once at the session asset.
- **Flag-don't-reject** — `[[feedback_friction_policy_missing_vs_mismatch]]` and the
  CSV-not-authoritative lock both forbid hard-reject on source disagreement.

### Integration Points
- Backfill currently emits plain `log_type:'seeding'` → per-block `commit-seeding`
  (bypasses the session group). The seam to change: route backfill through the
  session-shaped commit so blocks group + the page image lands on the session.
- Cross-check sits at commit time (before the farmOS POST), reading the same CSV
  the receipt already loads.

</code_context>

<specifics>
## Specific Ideas

- "The unit is the inoc session, not the notebook page — a single inoc session can
  fill more than a single notebook page." (Santi, 2026-06-09) — the load-bearing
  reframe for F2.
- "Hold everything unverified" — Santi chose the conservative cross-check over the
  strain-only hold; he wants nothing unverified in farmOS, accepting heavier human
  reconcile load via the session view.

</specifics>

<deferred>
## Deferred Ideas

- **Extraction-prompt strain-column hardening** — root-cause fix for POY->KOY
  misreads. 55b detects+holds; prompt-hardening is a separate extraction-quality
  task. The audit calls it "secondary."
- **Strain-gate re-wire (CR-01/CR-02)** — held; conflicts with the "gate is moot"
  decision ([[project_farmos_fungi_type_24_terms_dev_prod_synced]]) and the audit
  shows it does not catch mode-2 silent misattribution anyway.
- **Prod cleanup of the 2026-06-07 audit set** (99 assets + 98 logs, some
  misattributed) — needs farmOS-admin DELETE; bot is 403.
- **Per-tenant backfill** — v1.12 Python port (tenant-aware day 1).
- **Observation-of-unknown-asset standalone path** — covered by Phase 51 upsert +
  54.1 strain-confirm.

### Reviewed Todos (not folded)
- `.planning/todos/pending/2026-06-07-backfill-audit-findings.md` — NOT folded as a
  todo but its F1/F2 design IS this phase's scope; treat as a canonical ref above.

</deferred>

---

*Phase: 55b-fidelity-corpus-unblock*
*Context gathered: 2026-06-09*
