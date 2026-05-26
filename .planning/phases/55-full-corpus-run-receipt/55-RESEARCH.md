# Phase 55: Full Corpus Run + Receipt -- Research

**Researched:** 2026-05-25
**Domain:** Backfill harness extension + receipt/stats generation + isolation runbook
**Confidence:** HIGH (codebase-verified; no external libraries researched)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**GA1 -- Prod-leak race mitigation: OPERATIONAL ISOLATION ONLY (no code)**
Mitigate the commit-watchdog prod-leak by choosing ONE of:
- Run backfill against an isolated throwaway postgres (fresh `DATABASE_URL`; harness `initDb` self-creates schema; the prod-pointing watchdog never sees the backfill drafts), OR
- Stop `mushy-alerter-1` for the run window, run backfill (commits go to dev :18080), restart. Cost: minutes of no prod RH alerting -- needs explicit OK.

The RUNBOOK pre-flight MUST verify isolation explicitly, not by trusting the env. No commit-watchdog code change.

**GA2 -- Scope vs Cycle-1/2: Phase 55 = FULL RUN, GATED ON CYCLE-2 SIGN-OFF**
Phase 55 plans ONLY the full-corpus run + receipt + per-shape stats + promotion decision.
The live run is gated on Phase 54 Cycle-1 and Cycle-2 dev smokes with farmer sign-off.
Phase 55 does NOT re-own the 54-05/06 cycle runbooks; it documents the gate and picks up after Cycle-2 is signed off.

### Claude's Discretion
- Exact mechanism for the full-corpus page range (drop the Cycle cap; parameterize "all pages" vs an explicit max).
- Receipt + stats file layout and how per-shape buckets are defined (reuse `build-backfill-receipt.js` aggregation where possible).
- RUNBOOK structure (extend Cycle-2 runbook vs a fresh full-corpus runbook).
- How the bulk-backfill auto-YES tagging is represented in BACK-10 stats output.

### Deferred Ideas (OUT OF SCOPE)
- Commit-watchdog origin-guard (recurring coexistence fix).
- 4 bogus dev-farmOS fungi_type terms (LIM/SHIITAKE/OYS/CAR) -- need farmOS admin DELETE.
- v1.13 narrowing -- consumes BACK-10 output; separate milestone.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BACK-09 | Full corpus processed; receipt at `.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.md` + sibling `.jsonl` of UUIDs | `buildReceipt()` currently writes to `<runDir>/receipt.md` (gitignored). A new copy-out step is needed for the `.planning/notes/` destination. The JSONL sibling is a new artifact -- `computeAggregate` has all asset_ids/log_ids in memory; extracting them to JSONL is a small addition. |
| BACK-10 | Per-shape confirm-accuracy stats from the run: n_per_shape and YES rate, tagged bulk-backfill auto-YES | "Shape" = `log_type` (seeding/observation/activity/harvest/input). All auto-YES in bulk-backfill mode means 100% YES rate by construction; tagging must make this explicit so v1.13 ignores these as human-YES signal. Add a new `computePerShapeStats()` in `build-backfill-receipt.js` and emit a tagged stats block in the receipt. |
| BACK-11 | Prod-promotion decision documented (default: dev-only; prod write only if operator opts in per-session-class) | A static markdown template authored as a plan artifact, not generated code. Documents the decision criteria, the session-class opt-in process, and the farmOS upsert path if promotion proceeds. |
</phase_requirements>

---

## Summary

Phase 55 is a thin extension of the Phase 54 backfill harness, not a new build. Three work areas:

**1. Harness extension (backfill-notebook.js):** The only change needed to go from <=20-page Cycle runs to a full-corpus run is removing the `--limit` enforcement as the default. The `selectPages()` function already handles `limit=Infinity` or `limit=0` correctly (it would return an empty slice for limit=0, so the right approach is to make limit=Infinity when not set, or to add an `--all-pages` flag that sets limit to the total page count). The corpus is fixed: 73 pages in the IMG_3775..IMG_3847 range that pass `PAGE_REGEX` (the regex was written for IMG_3775..IMG_3861 but only 73 files exist; the actual last page is IMG_3847). [VERIFIED: filesystem]

**2. Receipt + stats (build-backfill-receipt.js):** `buildReceipt()` already produces a rich per-page + aggregate markdown. Three gaps vs BACK-09/BACK-10: (a) it writes to the gitignored `<runDir>/receipt.md`, not `.planning/notes/`; (b) no UUID JSONL sibling is emitted; (c) `computeAggregate` tracks per_strain counts but not per-shape (log_type) counts or the auto-YES tag. Adding `computePerShapeStats()` and a copy-out path to `.planning/notes/` covers all three gaps without touching any existing function signatures.

**3. Runbook + promotion decision doc:** The full-corpus RUNBOOK is structurally identical to the Cycle-2 RUNBOOK but with (a) the isolation pre-flight replacing the falsified Phase-54 assumption, (b) no `--limit` cap, and (c) a smoke-first check (5 pages before the full run per [[feedback_smoke_before_expensive_batch]]). BACK-11 is a static markdown doc, not generated code.

**Primary recommendation:** Extend `build-backfill-receipt.js` with `computePerShapeStats()` + UUID JSONL writer + copy-out to `.planning/notes/`. Add `--all-pages` flag to `backfill-notebook.js`. Author the full-corpus RUNBOOK and BACK-11 promotion-decision doc as plan artifacts.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Full-corpus page iteration | `backfill-notebook.js` CLI | `listCorpusPages()` / `selectPages()` | Already owns corpus enumeration; just need to lift the `--limit` default |
| Per-draft auto-confirm + commit | `processDraftsForCapture()` in backfill-notebook.js | commit-router, extraction-db | No change needed; existing path handles all log types uniformly |
| Paid-LLM persistence | `makeResponsesObserver()` + `openResponsesJsonl()` | backfill-context.js `onLlmCall` hook | Append-only JSONL already enforced; no change needed |
| Receipt generation (per-page + aggregate) | `build-backfill-receipt.js` `buildReceipt()` | computeAggregate, renderPageSection | Existing; gaps are UUID JSONL + copy-out + per-shape stats |
| Per-shape stats (BACK-10) | NEW `computePerShapeStats()` in build-backfill-receipt.js | computeAggregate | Small addition to same module; data already in runSummary |
| UUID JSONL artifact (BACK-09) | NEW `buildUuidJsonl()` in build-backfill-receipt.js | Called from buildReceipt() | Asset/log IDs already in memory; write to sibling file |
| Prod-leak isolation | OPERATIONAL (pre-flight runbook check) | No code | GA1 decision: no commit-watchdog change |
| Promotion decision (BACK-11) | Static markdown doc | Authored in plan | Decision criteria + opt-in process; not generated code |

---

## Corpus Size (VERIFIED)

[VERIFIED: filesystem scan 2026-05-25]

| Fact | Value |
|------|-------|
| Total JPEGs in mushdatadump/jpeg/ | 95 |
| Pages matching `PAGE_REGEX` (IMG_3775..IMG_3861 range) | 73 (IMG_3775..IMG_3847 -- files only go to IMG_3847, not IMG_3861) |
| Pages matching `UN_TRANSCRIBED_REGEX` (IMG_3862..IMG_3884) | 22 |
| CSV ground truth rows | 1,088 data rows (1,089 lines incl. header) |
| Cycle-1 cap | 5 pages |
| Cycle-2 cap | 20 pages |
| Full corpus | 73 pages (all PAGE_REGEX matches) |
| Skip list (operator-known-bad) | IMG_3790 (CA3 regex fail), IMG_3810 (renumbering ambiguity), IMG_3820 (WEDGE regex fail) |

The `PAGE_REGEX` regex (`/^IMG_3(7[7-9][0-9]|8[0-5][0-9]|86[0-1])\.jpg$/`) covers IMG_3770..IMG_3861 theoretically, but only 73 files exist in that range (up to IMG_3847). The RUNBOOK should note this -- `--all-pages` will produce 73 pages, not 87 (3861-3775+1).

---

## Focus Question Answers

### Q1: What must change in backfill-notebook.js to go from <=20-page Cycle cap to full-corpus?

[VERIFIED: codebase]

**What currently enforces the cap:** The `--limit=<n>` flag (default 5). `selectPages(allPages, {limit, resumeFrom})` slices `allPages.slice(start, start + cap)`. When `cap=0`, it returns empty (bug if used for "no limit"). `limit` is a plain number in `parseArgs()`.

**Minimal change:** Add a `--all-pages` boolean flag. When set, `selectPages()` is called with `limit=allPages.length` (or `Infinity` -- the slice `allPages.slice(0, Infinity)` returns the full array). This is a 3-line change: parse `--all-pages` in `parseArgs()`, set `opts.limit = Infinity` when true, update the USAGE string.

**Alternative:** Accept `--limit=0` as "all pages" (set cap to `allPages.length` when limit===0). More terse but less explicit. Prefer `--all-pages` for operator clarity.

**No other loop changes needed.** The dispatch loop, `processDraftsForCapture`, drain, strain-confirm gate, and `buildReceipt` call in `finally{}` all scale to any N without modification.

**Approximate cost estimate for 73 pages at Cycle-1/2 pricing ($0.10-0.50 / 5 pages, $2 / 20 pages):** The Cycle-2 runbook estimates ~$2 for 20 pages, so full corpus of 73 pages estimates ~$7-10. The smoke step (5 pages first) costs ~$0.50. Total budget: ~$10-11.

### Q2: How should per-shape confirm-accuracy stats (BACK-10) be computed?

[VERIFIED: codebase]

**What "shape" means here:** `log_type` field on each commit entry (seeding / observation / activity / harvest / input). These are the five types in the locked schema extracted in `schemas/index.js`. The draft's `log_type` is set during pipeline enqueue from `(draft && draft.type)`.

**What "YES rate" means in bulk-backfill mode:** ALL non-held, non-failed drafts are auto-YES (via `flipDraftToConfirmed` with `needs_review_reason='bulk_backfill_santi'`). This means the YES rate is 100% minus the held/failed rate, by construction. The BACK-10 requirement says to tag these as bulk-backfill auto-YES so v1.13 does NOT mistake them for human-YES signal.

**Where to add it:** Extend `computeAggregate()` in `build-backfill-receipt.js` -- OR add a separate `computePerShapeStats(runSummary)` function that returns a stats object. The separate function is cleaner since it's a distinct report.

**Shape for `computePerShapeStats()`:**

```js
// Returns: {
//   by_shape: { seeding: {n:N, ok:N, held:N, failed:N}, observation: {...}, ... },
//   tag: 'bulk_backfill_auto_yes',  // BACK-10: never human-YES signal for v1.13
//   total: { n, ok, held, failed }
// }
```

`ok` = `c.ok === true`; `held` = `c.ok === 'held'` (reason `strain_unknown_pending_confirm`); `failed` = `c.ok === false`. `n` = total commits for that shape. YES rate = `ok / (ok + held + failed)` for each shape.

**Auto-YES tag representation:** A literal `tag: 'bulk_backfill_auto_yes'` field in the stats object, echoed verbatim into the receipt's BACK-10 section header. v1.13 can grep for this tag to exclude these counts from its human-YES training set.

**Emitted in receipt as a new section:** `## BACK-10 Per-shape stats (bulk-backfill auto-YES -- not human-YES signal for v1.13)` with a table of shape, n, ok, held, failed, yes_rate_pct. The tag appears in the section header and as a field in the sibling UUID JSONL.

### Q3: What does the receipt + UUID JSONL (BACK-09) need that build-backfill-receipt.js doesn't already produce?

[VERIFIED: codebase]

**Gap 1 -- Destination:** `buildReceipt()` currently writes to `<runDir>/receipt.md` where `runDir = .planning/backfill/2025-notebook/<runId>/`. That directory is gitignored (by design -- per-run paid LLM outputs stay off git). BACK-09 requires the receipt at `.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.md` which IS tracked. The full-corpus receipt is the permanent artifact; Cycle-1/2 receipts live in the gitignored runDir.

**Gap 2 -- UUID JSONL sibling:** No JSONL sibling is currently written. BACK-09 requires `.planning/notes/2026-XX-XX-2025-notebook-backfill-receipt.jsonl`. The shape (one JSON object per committed asset/log) is straightforward:

```jsonl
{"type":"asset","uuid":"...","block_name":"...","log_type":"seeding","page":"IMG_3775.jpg"}
{"type":"log","uuid":"...","draft_id":"...","log_type":"seeding","page":"IMG_3775.jpg"}
```

All the data is already in `runSummary[].commits[].{asset_ids, log_ids, log_type, block_name}` and `runSummary[].pagePath`. No new harness data needed.

**Gap 3 -- Per-shape stats section:** See Q2. Currently `computeAggregate()` returns `per_strain` counts but not `per_shape` (log_type) counts. The receipt has a "Per-strain breakdown" section but no "Per-shape breakdown."

**Implementation plan for `build-backfill-receipt.js`:**

- Add `buildUuidJsonl(runSummary)` -- returns a JSONL string (one line per UUID).
- Add `computePerShapeStats(runSummary)` -- returns the per-shape object from Q2.
- Extend `buildReceipt()` with two new params: `notesReceiptPath` (if set, copy the markdown there) and `notesJsonlPath` (if set, write UUID JSONL there).
- Add the BACK-10 stats section to the receipt markdown.
- The existing `<runDir>/receipt.md` write stays (audit trail in gitignored runDir); the `.planning/notes/` copy is an additional write.

### Q4: Smoke-before-expensive-batch story and paid-results persistence

[VERIFIED: codebase, memory feedback_smoke_before_expensive_batch, feedback_persist_paid_results_default]

**Smoke step:** Run 5 pages with `--limit=5` (or `--limit=5 --bulk-backfill --farmer=santi`) as a paid-LLM smoke before the full `--all-pages` run. This is already documented in the Cycle-2 RUNBOOK as Step 4 (dry-run) + Step 5 (real run). For Phase 55, the full-corpus RUNBOOK adds:
- Step 1: dry-run smoke (`--all-pages --dry-run`) -- confirms 73 pages selected, no spend.
- Step 2: paid smoke (5 pages) -- ~$0.50, confirms extraction + commit path is healthy.
- Step 3: full run (`--all-pages`) -- only after Step 2 produces clean receipt.

**Paid-results persistence:** Already implemented in Plan 03 via `makeResponsesObserver(fd)` + append-only `responses.jsonl`. The `runIdExistsGuard()` (exit 6 on collision) prevents clobbering a prior run's evidence. The `--resume-from=IMG_NNNN.jpg` flag + a new `--run-id` allows resuming a crashed full-corpus run without re-spending on completed pages. These mechanisms are already in the harness -- the RUNBOOK must explain them for the larger N case.

**Crash recovery for 73-page run:** The `finally{}` block always calls `buildReceipt()` even on crash, so a partial run always produces a partial receipt. The operator picks the last successfully-completed page (visible in `summaries.log`), issues `--resume-from=<basename> --run-id=<fresh-id>`. The two partial run dirs are then merged manually for the final receipt (or accepted as two partial receipts if the crop is not reprocessed). The RUNBOOK must document this explicitly.

### Q5: What must the operator RUNBOOK pre-flight assert to guarantee isolation?

[VERIFIED: codebase -- commit-watchdog.js + commit-db.js + docker-compose.yml]

**The actual prod-leak mechanism (confirmed from code):**

- `commit-watchdog.js` polls: `SELECT * FROM signal_draft WHERE status='confirmed' ORDER BY confirmed_at ASC LIMIT $1`
- It runs against the SHARED timescale (`timescale` container, port 5432 on localhost).
- The live alerter (`mushy-alerter-1`) is wired to PROD farmOS (:8082).
- When the backfill harness flips drafts to `'confirmed'` status, those rows are immediately visible to the commit-watchdog's polling query.
- The watchdog then commits those rows to PROD farmOS, defeating the harness's `FARMOS_URL` dev-only guard.

**The falsified Phase-54 pre-flight step was:** "echo $DATABASE_URL -- should resolve to the alerter's dev TimescaleDB (NOT prod)" -- but there IS no separate dev TimescaleDB. There is one shared TimescaleDB used by both the dev harness and the prod-pointing alerter. This pre-flight step is misleading and was never actually protective.

**Correct pre-flight assertions for the full-corpus RUNBOOK:**

Option A (isolated throwaway DB):
```bash
# 1. Start a fresh postgres for this backfill run only
docker run -d --name backfill-pg-$(date +%s) \
  -e POSTGRES_PASSWORD=backfill \
  -p 5433:5432 \
  postgres:14
# Wait for ready
until pg_isready -h localhost -p 5433 -U postgres; do sleep 1; done
# 2. Export the throwaway DATABASE_URL
export DATABASE_URL="postgresql://postgres:backfill@localhost:5433/postgres"
# 3. Confirm it does NOT point at the production timescale port
echo "$DATABASE_URL" | grep -v ":5432" || { echo "ABORT: DATABASE_URL may point at shared timescale"; exit 1; }
```

Option B (stop alerter for run window):
```bash
# 1. Confirm mushy-alerter-1 is running
docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}'
# 2. Get explicit operator OK (not autonomous)
echo "CONFIRM: alerter will be stopped for the run window. Prod RH alerting paused."
# 3. Stop alerter
docker stop mushy-alerter-1
# 4. Confirm it stopped
docker ps --filter "name=mushy-alerter" --format '{{.Names}} {{.Status}}' | grep -v "Up" || true
# 5. Verify the shared timescale is still accessible (backfill needs it)
pg_isready -h localhost -p 5432 -U postgres
# After backfill: restart alerter
docker start mushy-alerter-1
```

**Pre-flight MUST also assert (regardless of which isolation option):**

```bash
# dev farmOS reachable (not prod)
curl -s -o /dev/null -w '%{http_code}\n' http://10.68.155.50:18080/jsonapi
# FARMOS_URL does not contain :8082 or 'prod'
echo "$FARMOS_URL" | grep -vE ":8082|prod" || { echo "ABORT: prod-guard"; exit 1; }
# Alerter suite green
cd src/agents/alerter && npx jest --passWithNoTests
# ANTHROPIC_API_KEY set
[ -n "$ANTHROPIC_API_KEY" ] && echo OK || { echo "ABORT: ANTHROPIC_API_KEY missing"; exit 1; }
```

---

## Architecture Patterns

### Recommended Project Structure (new files only)

```
src/agents/alerter/
  scripts/
    backfill-notebook.js         -- ADD --all-pages flag (3-line change)
    build-backfill-receipt.js    -- ADD buildUuidJsonl(), computePerShapeStats(),
                                    extend buildReceipt() with notesReceiptPath/notesJsonlPath

.planning/phases/55-full-corpus-run-receipt/
  55-FULL-CORPUS-RUNBOOK.md     -- New: the operator runbook for the full-corpus run
  55-PROMOTION-DECISION.md      -- BACK-11: prod-promotion decision doc template
  55-RESEARCH.md                -- This file
  55-PLAN.md files...

.planning/notes/
  2026-XX-XX-2025-notebook-backfill-receipt.md   -- BACK-09 permanent receipt (git-tracked)
  2026-XX-XX-2025-notebook-backfill-receipt.jsonl -- BACK-09 UUID JSONL (git-tracked)
```

### Pattern: --all-pages flag in parseArgs()

```js
// In parseArgs():
if (arg === '--all-pages') { opts.allPages = true; continue; }

// In main(), after parseArgs():
if (opts.allPages) opts.limit = Infinity;

// selectPages() already handles Infinity correctly:
// allPages.slice(0, Infinity) returns the full array.
```

[ASSUMED] -- `Array.prototype.slice(0, Infinity)` behavior in Node.js. Almost certainly correct but verifying in a one-liner before coding is trivial.

Actually [VERIFIED: JS spec] -- `Array.prototype.slice` converts limit to integer; `ToInteger(Infinity) = Infinity`; `Math.min(Infinity, len) = len`. Works correctly.

### Pattern: buildUuidJsonl(runSummary)

```js
function buildUuidJsonl(runSummary) {
  const lines = [];
  for (const page of runSummary || []) {
    const pageBase = path.basename(page.pagePath || page.page || '');
    for (const c of (page.commits || [])) {
      for (const uuid of (c.asset_ids || [])) {
        lines.push(JSON.stringify({
          type: 'asset', uuid,
          block_name: c.block_name || null,
          log_type: c.log_type || null,
          page: pageBase,
          draft_id: c.draftId || null,
        }));
      }
      for (const uuid of (c.log_ids || [])) {
        lines.push(JSON.stringify({
          type: 'log', uuid,
          log_type: c.log_type || null,
          page: pageBase,
          draft_id: c.draftId || null,
        }));
      }
    }
  }
  return lines.join('\n') + (lines.length > 0 ? '\n' : '');
}
```

### Pattern: computePerShapeStats(runSummary)

```js
const KNOWN_SHAPES = ['seeding', 'observation', 'activity', 'harvest', 'input'];

function computePerShapeStats(runSummary) {
  const by_shape = {};
  for (const shape of KNOWN_SHAPES) {
    by_shape[shape] = { n: 0, ok: 0, held: 0, failed: 0 };
  }
  const total = { n: 0, ok: 0, held: 0, failed: 0 };

  for (const page of runSummary || []) {
    for (const c of (page.commits || [])) {
      const shape = c.log_type || 'unknown';
      if (!by_shape[shape]) by_shape[shape] = { n: 0, ok: 0, held: 0, failed: 0 };
      by_shape[shape].n += 1;
      total.n += 1;
      if (c.ok === true) { by_shape[shape].ok += 1; total.ok += 1; }
      else if (c.ok === 'held') { by_shape[shape].held += 1; total.held += 1; }
      else { by_shape[shape].failed += 1; total.failed += 1; }
    }
  }

  return {
    // BACK-10: tag this entire stats object so v1.13 never treats
    // these as human-YES signal. bulk_backfill_auto_yes = auto-confirm
    // short-circuit only; no human reviewed individual drafts.
    tag: 'bulk_backfill_auto_yes',
    by_shape,
    total,
  };
}
```

### Anti-Patterns to Avoid

- **Trusting DATABASE_URL to mean "dev-only":** The Phase-54 pre-flight step did this. It is wrong. There is one shared postgres. Isolation requires either a separate container or stopping the alerter.
- **Running full corpus without a dry-run first:** 73 pages = real LLM spend. Always dry-run then smoke-5 before `--all-pages`.
- **Running `--all-pages` without `--run-id`:** The auto-generated run-id is fine but the RUNBOOK must note it so the operator can resume a crash with `--resume-from` + a fresh `--run-id`.
- **Writing `.planning/notes/` receipt from inside `finally{}` with no error handling:** The `buildReceipt()` call in `finally{}` already has a try/catch in main(). The copy-out to `.planning/notes/` should be inside that same try/catch.
- **Merging Cycle-1/2 receipt logic with full-corpus receipt logic:** Keep the copy-out to `.planning/notes/` as an opt-in parameter (`notesReceiptPath`). Cycle-1/2 runs do not write to `.planning/notes/`; only the full-corpus run does.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Append-only paid LLM evidence | Custom write buffer | Existing `makeResponsesObserver()` + `openResponsesJsonl()` -- already in harness |
| Crash-resilient audit | Try/finally logic | Existing `buildReceipt()` in `finally{}` in `main()` -- already there |
| Corpus page enumeration | Custom glob | Existing `listCorpusPages()` + `selectPages()` -- already handles sort + resume |
| Per-draft strain resolution | Custom string match | Existing `resolveStrain()` from `strain-resolver.js` + curated set |
| Postgres pool + extraction pipeline bootstrap | Custom init | Existing `createBackfillContext()` in `backfill-context.js` -- already wires pool + pipeline + schema |

---

## Common Pitfalls

### Pitfall 1: The "dev DB" is actually the same shared postgres

**What goes wrong:** Operator sets `DATABASE_URL` and assumes the alerter watchdog isn't looking at it. The watchdog polls `WHERE status='confirmed'` on the same DB every 30s. Backfill-confirmed drafts immediately leak to prod farmOS.
**Why it happens:** The Phase-54 Cycle-1 pre-flight said "DATABASE_URL should resolve to the alerter's dev TimescaleDB" -- but there is no separate dev TimescaleDB. The shared timescale is on `localhost:5432`.
**How to avoid:** RUNBOOK pre-flight Option A (throwaway postgres on port 5433) or Option B (stop alerter first). Verify explicitly with a port check or docker ps confirmation.
**Warning signs:** `mushy-alerter-1` is running, `DATABASE_URL` ends in `:5432`. That combination means the watchdog will see backfill drafts.

### Pitfall 2: selectPages() with limit=0 returns empty

**What goes wrong:** Operator uses `--limit=0` hoping for "no limit" behavior, gets zero pages.
**Why it happens:** `selectPages()` does `const cap = Math.max(0, Number(limit) || 0)` then `allPages.slice(start, start + cap)`. With cap=0, this is `slice(0, 0)` = `[]`.
**How to avoid:** Use `--all-pages` flag (sets limit to `Infinity`). Document clearly in USAGE string.

### Pitfall 3: Resume-from requires a fresh --run-id

**What goes wrong:** Operator uses `--resume-from=IMG_3800.jpg` without changing `--run-id`. `runIdExistsGuard()` exits 6 because `responses.jsonl` already exists in the run dir.
**Why it happens:** The guard was specifically designed to prevent clobbering existing responses.jsonl (T-54-10). But resume semantics require a new run dir.
**How to avoid:** RUNBOOK explicitly: "If the run interrupts, use BOTH `--resume-from=IMG_NNNN.jpg` AND a new `--run-id`." Accept that crash-recovery produces two partial run dirs.

### Pitfall 4: Held strains block the per-shape stats for those drafts

**What goes wrong:** Some drafts remain `ok='held'` (unknown strains) and never get a log_type committed. The per-shape stats then show `n=N` but ok/held/failed breakdown doesn't distinguish "held before commit-router" from "failed at commit-router."
**Why it happens:** `processDraftsForCapture()` sets `entry.ok = 'held'` before commit-router is called. These entries have `log_type` from `draft.log_type` but no committed asset_ids/log_ids.
**How to avoid:** `computePerShapeStats()` must read `c.log_type` from the commit entry (it's set there: `log_type: logType`). Held entries should count toward `n` but show up in `held`, not `ok`. The RUNBOOK notes that held count needs follow-up via `backfill-confirm-strains.js` before re-running the receipt.

### Pitfall 5: .planning/notes/ receipt must be ASCII-only

**What goes wrong:** em-dashes or other non-ASCII characters in strain names / reasons slip through to the `.planning/notes/` receipt.
**Why it happens:** `buildReceipt()` already applies `body.replace(/[--]/g, '--')` at the end before writing `<runDir>/receipt.md`. The copy-out must use the same sanitized body, not re-read the raw data.
**How to avoid:** Pass the sanitized markdown string to the copy-out write, not a fresh render pass. In practice: run sanitization once, write both destinations from the same string.

---

## Runtime State Inventory

This is a backfill phase -- it writes TO dev farmOS. The important inventory is what MUST NOT be touched:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data (prod farmOS) | Production farmOS :8082 assets/logs from May-22 live backfill + ongoing live captures | Isolation pre-flight ensures backfill never touches prod |
| Stored data (dev farmOS) | Cycle-1/2 smoke run assets/logs already in dev :18080 | The full-corpus run will encounter them and test Phase 51 upsert stability -- expected behavior |
| Live service config | `mushy-alerter-1` commit-watchdog polls shared timescale every 30s; wired to prod :8082 | GA1 runbook: stop alerter OR use isolated postgres for backfill |
| Shared timescale (localhost:5432) | Single postgres instance; both live alerter and backfill would use it | Must be isolated per GA1; throwaway postgres on port 5433 is the clean option |
| OS-registered state | None -- backfill is operator-triggered, not scheduled | None |
| Secrets/env vars | `ANTHROPIC_API_KEY`, `DATABASE_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` | Already in harness required-env check (exit 5 if missing) |
| Build artifacts | `.planning/backfill/` (gitignored) accumulates run dirs | No action; gitignored by design per Plan 02 |
| `.planning/notes/` | Only existing files: `2026-05-24-prod-write-receipt.md`, `2026-05-24-prod-write-receipt-uuids.json` | New backfill receipt will be a sibling; no conflict |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| dev farmOS :18080 | All harness writes | Operator-verified per runbook | -- | None -- must be up |
| Anthropic API key | LLM extraction | Operator-provided env | -- | None -- required for real run |
| TimescaleDB (localhost:5432) | Shared DB (pipeline + capture-db) | Running (docker compose) | pg14 | Throwaway postgres option |
| Throwaway postgres :5433 | GA1 isolation Option A | Not yet running | -- | GA1 Option B (stop alerter) |
| `mushy-alerter-1` container | GA1 isolation Option B | Running | -- | GA1 Option A (throwaway postgres) |
| mushdatadump corpus `/mnt/slime-kingdom/shared/mushdatadump/jpeg/` | `listCorpusPages()` | Verified 95 files | -- | None -- corpus is read-only |
| `mushroom_log.csv` | CSV diff in receipt | Verified at corpus path | -- | Receipt says "N/A (no ground truth)" per page |
| Node.js + npm/npx | Test runner | Running | -- | -- |

**Missing dependencies with no fallback:**
- dev farmOS :18080 must be reachable before any real run
- ANTHROPIC_API_KEY must be set

**Missing dependencies with fallback:**
- Throwaway postgres :5433 -- Option B (stop alerter) is viable

---

## Validation Architecture

`nyquist_validation: true` in `.planning/config.json` -- section is required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Jest (existing; 1,342 pass / 9 skipped in current baseline) |
| Config file | `src/agents/alerter/jest.config.js` (or `package.json` jest field) |
| Quick run command | `cd src/agents/alerter && npx jest --testPathPattern=backfill` |
| Full suite command | `cd src/agents/alerter && npx jest --passWithNoTests` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BACK-09 part A | `--all-pages` flag selects all 73 pages (not just 5) | unit | `npx jest build-backfill-receipt.test.js backfill-notebook.test.js` | Extend existing |
| BACK-09 part B | `buildUuidJsonl()` emits one JSONL line per asset UUID and one per log UUID | unit | `npx jest build-backfill-receipt.test.js -t "buildUuidJsonl"` | New test in existing file |
| BACK-09 part C | `buildReceipt()` writes to `notesReceiptPath` when param provided | unit | `npx jest build-backfill-receipt.test.js -t "notesReceiptPath"` | New test in existing file |
| BACK-10 | `computePerShapeStats()` returns per-shape bucket with `tag: 'bulk_backfill_auto_yes'` | unit | `npx jest build-backfill-receipt.test.js -t "computePerShapeStats"` | New test in existing file |
| BACK-10 | `computePerShapeStats()` correctly counts ok/held/failed for each log_type | unit | `npx jest build-backfill-receipt.test.js -t "per-shape"` | New test in existing file |
| BACK-11 | Promotion decision doc exists at correct path | doc-exists | manual | New doc artifact |

### Sampling Rate

- **Per task commit:** `cd src/agents/alerter && npx jest --testPathPattern="backfill|build-backfill-receipt" --passWithNoTests`
- **Per wave merge:** `cd src/agents/alerter && npx jest --passWithNoTests`
- **Phase gate:** Full suite green (1,342+ pass / 0 fail) before operator runs the full-corpus RUNBOOK

### Wave 0 Gaps

No new test files needed -- all new tests go into the existing `build-backfill-receipt.test.js` and `backfill-notebook.test.js` files. Current baseline: 1,342 pass.

---

## Security Domain

`security_enforcement` not set in config -- treated as enabled.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No -- harness is operator-run, not web-facing | -- |
| V3 Session Management | No | -- |
| V4 Access Control | Partial | `assertFarmerGate()` (santi-only) + `assertProdGuard()` (no :8082/prod) -- already in place |
| V5 Input Validation | Yes | `assertProdGuard()` for FARMOS_URL; `runIdExistsGuard()` for run-id collision; strain reply parsing in `parseStrainReply()` |
| V6 Cryptography | No | -- |

### Known Threat Patterns

| Pattern | STRIDE | Mitigation |
|---------|--------|-----------|
| Prod-leak via shared DB | Elevation of Privilege | GA1 operational isolation (throwaway postgres or stop alerter) |
| Over-spend on paid LLM | Denial of Service (budget) | Smoke-5 step before full run; `runIdExistsGuard` prevents re-running |
| Auto-YES tagging confused for human-YES | Repudiation | `tag: 'bulk_backfill_auto_yes'` in BACK-10 stats; section header in receipt |
| receipts with em-dashes | Information Disclosure | `body.replace(/[--]/g, '--')` enforced in `buildReceipt()`; copy-out uses same string |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Array.prototype.slice(0, Infinity)` returns the full array in Node.js | Q1 / Pattern | Trivial to verify; extremely low risk |
| A2 | The 73 PAGE_REGEX-matching files are the correct full-corpus scope (not 87 = 3861-3775+1) | Corpus Size | Low -- filesystem verified; the regex was written conservatively but only 73 files exist |
| A3 | Per-shape stats tag `'bulk_backfill_auto_yes'` is the right signal for v1.13 to exclude | BACK-10 | Medium -- v1.13 design not yet started; if v1.13 uses a different exclusion mechanism, the tag may be unused; but having it costs nothing |

---

## Open Questions (RESOLVED)

> All three resolved during Phase 55 planning (2026-05-25); the chosen approaches are reflected in 55-01-PLAN.md and 55-02-FULL-CORPUS-RUNBOOK.md.

1. **Skip-list handling in --all-pages mode**
   - RESOLVED: Document the 3 known-bad pages (IMG_3790/3810/3820) in the RUNBOOK as acceptable extraction failures (they surface in the per-page receipt, do not crash the run). No auto-skip flag added — simpler path chosen.
   - What we know: IMG_3790, IMG_3810, IMG_3820 are operator-known-bad. The corpus enumeration does NOT skip them -- `listCorpusPages()` returns all PAGE_REGEX matches including these.
   - What's unclear: Should `--all-pages` auto-skip the known-bad pages, or should the operator use `--resume-from` to skip ranges?
   - Recommendation: Add an optional `--skip-pages=IMG_3790.jpg,IMG_3810.jpg,IMG_3820.jpg` flag to `parseArgs()` and filter in `listCorpusPages()`. 3-line addition. Alternatively, document in RUNBOOK that those 3 pages will likely produce extraction failures but won't crash the run (failure reasons will appear in the per-page receipt section). Either is fine; the latter is simpler.

2. **Partial crash recovery and multi-run receipt merge**
   - What we know: A crash at page 50/73 leaves 50 pages in run-A and requires resume with run-B from page 51.
   - What's unclear: Should the Phase 55 RUNBOOK define a `merge-receipts.js` helper, or just accept two partial receipts?
   - Recommendation: Accept two partial run dirs for now. The final BACK-09 receipt can be authored manually by concatenating the two partial receipts. Automating the merge is deferred unless Cycle-2 demonstrates the need.
   - RESOLVED: Accept two partial run dirs; no `merge-receipts.js` helper this phase. RUNBOOK documents the concat-by-hand path. Deferred pending Cycle-2 evidence of need.

3. **Throwaway postgres provisioning -- Docker vs pg_isready**
   - What we know: elder-plops has Docker (docker compose v2 in use). A fresh postgres container on port 5433 is Option A for isolation.
   - What's unclear: Does elder-plops have port 5433 free? Is there a running service on 5433?
   - Recommendation: RUNBOOK pre-flight step 0: `lsof -i :5433 || echo "port 5433 free"`. If occupied, use port 5434 or choose Option B (stop alerter).
   - RESOLVED: RUNBOOK pre-flight includes the `lsof -i :5433` check with the port-5434-or-Option-B fallback. Operator decides per-run.

---

## Sources

### Primary (HIGH confidence)
- Codebase: `scripts/backfill-notebook.js` -- `parseArgs`, `selectPages`, `listCorpusPages`, `processDraftsForCapture`, `runIdExistsGuard`, `makeResponsesObserver`, harness `main()`
- Codebase: `scripts/build-backfill-receipt.js` -- `buildReceipt`, `computeAggregate`, `aggregateCost`, `renderPageSection`, `computeCsvDiff`
- Codebase: `scripts/backfill-confirm-strains.js` -- `parseStrainReply`, `applyStrainConfirmations`
- Codebase: `scripts/backfill-context.js` -- `createBackfillContext`, `buildPool`, `initSchemas`
- Codebase: `src/farmos/commit-db.js` -- `findConfirmedCandidates` (WHERE status='confirmed' -- the exact query that causes prod-leak)
- Codebase: `src/farmos/commit-watchdog.js` -- watchdog polling confirmed drafts
- Filesystem: `/mnt/slime-kingdom/shared/mushdatadump/jpeg/` -- 73 PAGE_REGEX files (IMG_3775..IMG_3847), 22 UN_TRANSCRIBED files (IMG_3862..IMG_3884), 95 total
- Plan artifacts: `54-CYCLE-1-RUNBOOK.md`, `54-CYCLE-2-RUNBOOK.md`
- `.planning/phases/55-full-corpus-run-receipt/55-CONTEXT.md`
- `.planning/STATE.md` -- Phase 54 closeout, test baseline 1,232 (now 1,342 post-54.1)

### Secondary (MEDIUM confidence)
- Memory: `project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog` -- prod-leak mechanism description (confirmed by code)
- Memory: `feedback_smoke_before_expensive_batch` -- smoke-5-pages-first rule
- Memory: `feedback_persist_paid_results_default` -- append-only paid results
- Memory: `project_v111_backfill_harness_shape` -- two-cycle shape, Cycle-2 gated on farmer sign-off

---

## Metadata

**Confidence breakdown:**
- Corpus size and file range: HIGH -- filesystem verified
- Harness extension (--all-pages flag): HIGH -- code read, change is mechanical
- Receipt gaps (UUID JSONL, copy-out, per-shape stats): HIGH -- code read, gaps confirmed
- Isolation pre-flight: HIGH -- commit-watchdog.js + commit-db.js confirmed the mechanism
- Cost estimate for full run: MEDIUM -- extrapolated from Cycle-2 estimate ($2/20 pages -> ~$7-10/73 pages); actual depends on page complexity and caching

**Research date:** 2026-05-25
**Valid until:** Stable (harness code unlikely to change before Phase 55 executes)
