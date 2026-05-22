# Phase 44: Event-gate + Durable `signal_outbound` (tenant-aware) — Research

**Researched:** 2026-05-21
**Domain:** Node.js alerter agent — Anthropic SDK classifier + Postgres durable outbound + layered config + ship-gate smoke
**Confidence:** HIGH (almost everything verifiable from code; one externally-verified Anthropic gotcha)

## Summary

Phase 44 is unusually well-scoped going in — CONTEXT.md locks D-01..D-23. This research validates code anchors against current repo state, confirms reusable patterns, and surfaces **one externally-verified gotcha that contradicts the CONTEXT.md hint**: Anthropic prompt-caching minimum for Haiku 4.5 is **4,096 tokens**, not 1,024 as the context suggested. The classifier system prompt must be sized accordingly or caching silently no-ops.

The 14-site `signalClient.send` audit (2026-05-17) holds against current code (one minor line drift: capture.js:192 → :197). The `signal.js` wrapper is the correct and existing single choke-point — adding an `opts.intent` field and a post-send `outbound-db.insertOutbound` call is the minimal change for OUTBOUND-01. The extraction subsystem already imports `@anthropic-ai/sdk` (^0.91.1) with the exact `cache_control: { type: 'ephemeral' }` pattern Phase 44 needs to mirror for the Haiku classifier. The repo's `EVAL_RUN_LIVE=1` env-gated `describe.skip` pattern is the proven live-API test idiom for Plan-04.

**Primary recommendation:** Treat all of D-01..D-23 as load-bearing inputs to planning. The two planner-discretion areas with material risk are (a) **the wrapper API ergonomics** (recommendation: keep current `signalClient.send(body, opts)` shape; add `intent` and optional `relatedCaptureId`/`relatedDraftId` to opts — no positional-arg break) and (b) **the layered config loader** (recommendation: add `yaml@^2.x` as a new dep — no YAML parser is currently in the alerter package; `js-yaml` is heavier and unmaintained-ish; the modern `yaml` package is the right choice).

## User Constraints (from CONTEXT.md)

### Locked Decisions
Copy of CONTEXT.md `<decisions>` block — D-01..D-23 are all binding. Highlights the planner MUST honor:

- **D-01:** Ship hybrid stack (rules + Haiku) in Phase 44 — not staged "rules first, audit, then Haiku."
- **D-02:** Gate flow is rules-POS → rules-NEG → Haiku gray-zone, in that order. NEGATIVE rule predicate is: `lastBotOutbound.intent === 'attestation_kickoff'` within 30m AND reply text < 40 chars AND matches `/^(ok|yes|got it|thanks|gracias|si|sí|👍)$/i`.
- **D-03:** Haiku failure → fall through to extractor (fail-OPEN). Missed events are worse than over-extracts per NORTH-STAR posture.
- **D-04:** Audit column `signal_capture.extraction_gate VARCHAR(32)` with five enum values. Populate at gate before dispatch.
- **D-05/D-06/D-07:** Convo path is gated TOO; behavior is config-knobbed via `EVENT_GATE_CONVO_MODE` with default `silent`. Confirmed this does NOT violate `[[feedback_no_silent_failure_after_farmer_confirm]]` — the gate fires before any confirm flow, on cold inbound only.
- **D-08/D-09:** Only `signal_outbound` gets `tenant_id NOT NULL` in Phase 44. Existing tables deferred to v2.0.
- **D-10:** Phase 45 ships AFTER Phase 44; Phase 44 must NOT touch state-machine terminal states.
- **D-11:** `tenants/mossrock/` contents: `config.yaml` (committed), `strains.yaml` (committed), `secrets.env` (gitignored).
- **D-12/D-13:** Exact DDL for `signal_outbound`. Intent enum is an extensible string (no DB CHECK). 12 intent values enumerated; `commit_ack` reserved for Phase 45.
- **D-14:** Single persistence hook lives in `signal.js` wrapper. No fanning out to 14 callsites.
- **D-15:** Each call site passes `intent` as second arg or via opts. Planner picks ergonomics.
- **D-16:** Confirm + extraction outbound modules also route through the wrapped `signal.js`; per-draft event logs remain for audit.
- **D-17/D-18/D-19:** `fmtHistory` reads merged `signal_capture` + `signal_outbound`; truncate 400/200 chars; `lastBotOutbound` exposed as distinct prompt field.
- **D-20/D-21/D-22/D-23:** Ship-gate is 100-capture hand-classified smoke from live Timescale; operator hand-labels; metrics are 0 chit-chat pings + ≥95% event recall + confirm rows bypass via Phase 39 short-circuit (audit-verified below).

### Claude's Discretion
- File layout under `src/agents/alerter/src/event-gate/`.
- `outbound-db.js` DAO location.
- Boot-chain config loader implementation (YAML lib + layering library).
- Haiku timeout/retry policy. Default suggestion: 2s timeout, no retry.
- `EVENT_GATE_CONVO_MODE` default location in `tenants/mossrock/config.yaml`.

### Deferred Ideas (OUT OF SCOPE)
- Tenant-id retrofit on `signal_capture` / `signal_draft` / `signal_draft_event` (v2.0).
- Phase 45 NORTH-STAR ack + replay drafts.
- Drop `signal_capture.llm_reply` column (v2.0).
- CI grep-gate against raw `signalClient.send(` outside `signal.js` (v1.9 candidate).
- Multi-tenant skeleton beyond `tenants/mossrock/` + `tenants/example/`.
- Telemetry/cost dashboard on Haiku calls (v1.9 candidate).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GATE-01 | Zero farmer-facing preview pings on 24 must-skip rows of 100-capture smoke | Gate insertion site verified at `capture.js:147`; convo gate site verified at `capture.js:171` (compose call). Verified Phase 39 confirm short-circuit at `receive-loop.js:220-264` runs BEFORE `capturePipeline.handle` at :269 — confirm verbs cannot reach the gate, per D-22 third bullet. |
| GATE-02 | ≥95% event recall on 48 must-extract rows | Anthropic SDK already in dep tree (`@anthropic-ai/sdk@^0.91.1`); Haiku 4.5 model id `claude-haiku-4-5-20251001` confirmed in SDK type defs; cached system prompt pattern verified in `extraction/prompts/system.js`. Caching threshold gotcha noted in §"Common Pitfalls." |
| OUTBOUND-01 | Every send writes one `signal_outbound` row with intent tag | Single wrapper at `signal.js` confirmed; 14 call sites verified against current code (1 line-drift correction below). Wrap point is the `try { res = fetch(...) }` block at `signal.js:92-112` — insert outbound-db.insertOutbound after `sendHistory.push(now)`. |
| OUTBOUND-02 | `fmtHistory` reads `signal_outbound` + surfaces `lastBotOutbound` | `fmtHistory` confirmed at `llm-client.js:33-40`; `buildUserBlock` at `:49-62` is the prompt-assembly site. `MAX_HISTORY_ROWS=20` cap exists; 200-char per-line cap exists — both need updating per D-18. |
| TENANT-01 | `signal_outbound.tenant_id` indexed + `tenants/mossrock/` exists | DDL with index verified in CONTEXT D-12. `tenants/` dir does NOT exist today (greenfield). `.gitignore` does NOT currently reference `tenants/` or `secrets` — update required. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Rule-based fast-path classification | alerter Node process | — | Pure CPU, no I/O; sits inline in capture pipeline |
| Haiku 4.5 gray-zone classification | alerter Node process | Anthropic API | API call with 2s timeout + fail-open posture |
| Outbound durability persistence | alerter Node process | Timescale Postgres | `signal_outbound` row inserted post-send in the wrapper |
| Tenant-scoped config resolution | alerter boot chain | filesystem (`tenants/<id>/*.yaml`) + env | Layered loader: file → env → default |
| Secrets injection | CI / GitHub Secrets → gitignored `tenants/mossrock/secrets.env` | alerter process env | Existing secret deploy path; no new secrets pipeline |
| Smoke fixture hand-labeling | operator (Don Santiago) | live Timescale + filesystem | Per `[[feedback_real_data_before_ship_gate_pass]]` — cannot be automated |
| Phase 37 prompt enrichment with bot history | alerter LLM client | `signal_outbound` table read via `capture-history.js` | Read happens in `compose()` before SDK call |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@anthropic-ai/sdk` | ^0.91.1 (already in `package.json`) | Haiku 4.5 classifier call | `[VERIFIED: codebase grep]` Already imported by extractor and llm-client; reuse the same client posture. Do NOT bump version unless needed — the extractor depends on it. |
| `pg` | ^8.20.0 (already present) | `signal_outbound` DAO + Plan-01 Timescale SELECT | `[VERIFIED: codebase grep]` Already pooled and configured in `index.js`. |
| `yaml` | ^2.6.x | Parse `tenants/<id>/config.yaml` + `strains.yaml` | `[CITED: npmjs.com/package/yaml]` Modern, maintained, ~85KB. Recommended over `js-yaml` (legacy, ~200KB) for new deps. `[ASSUMED]` version — verify with `npm view yaml version` before pinning. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ulid` | ^3.0.2 (already present) | If outbound IDs need to mirror capture IDs | D-12 specifies `uuid PRIMARY KEY DEFAULT gen_random_uuid()` — Postgres-side generation; ulid only needed if planner wants client-side IDs (recommend NOT — match D-12 verbatim). |
| `zod` | ^3.23.0 (already present) | Validate Haiku tool_use output `{is_event, kind, confidence}` | Strongly recommended — mirror `extraction/schemas/index.js` validator pattern for the classifier output. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `yaml@^2.x` | `js-yaml@^4.x` | js-yaml is older, larger, less actively maintained. `yaml` package supports YAML 1.2 cleanly and is the modern default. Either works — `yaml` is the safer new-dep pick. |
| `yaml@^2.x` | JSON config files | Operator preference per CONTEXT.md is YAML. Sticking with JSON would obviate the new dep but violate the locked decision. |
| `gen_random_uuid()` (Postgres) | `ulid()` (client) | D-12 locks `uuid PRIMARY KEY DEFAULT gen_random_uuid()` — no choice to make. |

**Installation:**
```bash
cd src/agents/alerter
npm install yaml
```

**Version verification:**
```bash
cd src/agents/alerter
npm view yaml version          # confirm current 2.x release
npm view @anthropic-ai/sdk version  # confirm 0.91.1 is current enough for Haiku 4.5
```

## Package Legitimacy Audit

`slopcheck` not run in this research session (tool unavailable in this sandbox). Per the package legitimacy gate, the new package below is marked `[ASSUMED]` even though `npm view` would confirm registry existence — and `@anthropic-ai/sdk` carries an `[OK]` here only because it is **already installed and battle-tested in this repo across Phases 25, 38, 39**.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `yaml` | npm | ~12 yrs (eemeli/yaml) | very high (millions/wk) | github.com/eemeli/yaml | not run | `[ASSUMED]` — planner should add a `checkpoint:human-verify` task before `npm install yaml`. Verify on npmjs.com that the package is `eemeli/yaml`, not a typosquat. |
| `@anthropic-ai/sdk` | npm | n/a (already-installed) | n/a | github.com/anthropics/anthropic-sdk-typescript | `[OK]` (in production) | Approved — no install action; already declared in `package.json`. |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none (slopcheck not run; `yaml` is widely-known but planner must human-verify per protocol)

## Architecture Patterns

### System Architecture Diagram

```
Signal envelope
   │
   ▼
receive-loop.js tick()
   │
   ├─→ whitelist gate (drop if not allowed sender)
   ├─→ command branches (experiment / snooze) ──→ signalClient.send (×8)
   ├─→ Phase 39 confirm short-circuit ──→ confirmOutbound.dispatch ──→ signalClient.send (×1)
   │      (D-22 third bullet: confirm verbs NEVER reach the gate below)
   │
   ▼
capturePipeline.handle(env, ctx)   [capture.js:65]
   │
   ├─ persist signal_capture row [capture.js:122]
   │
   ├─ fire-and-forget extraction enqueue [capture.js:147]  ◄── EXTRACTOR DISPATCH SITE (D-02)
   │       │
   │       ▼   pre-gate inserted here
   │  ┌─────────────────────────────────┐
   │  │ event-gate/index.js             │
   │  │  ├─ rules.js                    │
   │  │  │   • POS: image/audio/strain/blockname/len>200
   │  │  │   • NEG: lastBotOutbound check + len<40 + ack regex
   │  │  └─ haiku-classifier.js         │
   │  │      • claude-haiku-4-5-20251001
   │  │      • 2s timeout, no retry
   │  │      • fail-OPEN (D-03)
   │  └─────────────────────────────────┘
   │       │
   │       ├─ skipped_rule_neg / haiku_chitchat ──► UPDATE extraction_gate; no extract
   │       └─ fast_event / haiku_event / forced  ──► UPDATE extraction_gate; extraction.enqueue
   │
   ├─ llm compose (Phase 37 convo) [capture.js:171]  ◄── CONVO DISPATCH SITE (D-05)
   │       │  if gateDecision.allow_convo per EVENT_GATE_CONVO_MODE
   │       ▼
   │  llm-client.js compose()
   │       │
   │       ├─ captureHistory.selectRecentBySender (existing)
   │       └─ captureHistory.selectRecentOutboundByRecipient (NEW — D-18)
   │              │
   │              └─ merge in fmtHistory; lastBotOutbound exposed in buildUserBlock (D-19)
   │
   └─ signalClient.send [capture.js:197] ──┐
                                            ▼
                                  signal.js send(body, opts)
                                            │
                                            ├─ existing: rate-cap, group resolution, fetch
                                            ├─ NEW: opts.intent required (per D-15)
                                            └─ NEW: outbound-db.insertOutbound(...)  ◄── SINGLE PERSISTENCE HOOK (D-14)
                                                       │
                                                       ▼
                                              signal_outbound table
                                              (tenant_id NOT NULL, intent, ...)
```

### Recommended Project Structure (planner-discretion areas marked)

```
src/agents/alerter/src/
├── event-gate/              # NEW (planner discretion: flat layout if preferred)
│   ├── index.js             # createEventGate({...}) → { classify(envCtx) }
│   ├── rules.js             # rule fast-paths (pure functions, unit-testable)
│   └── haiku-classifier.js  # Anthropic Haiku 4.5 wrapper, 2s timeout, fail-open
├── outbound-db.js           # NEW — initDb (DDL+indexes) + insertOutbound + selectRecentByRecipient
├── signal.js                # MODIFIED — wrap send, fan to outbound-db
├── capture.js               # MODIFIED — gate insertion at :147, convo gate at :171
├── capture-history.js       # MODIFIED — add selectRecentOutboundByRecipient
├── capture-db.js            # MODIFIED — ALTER ADD COLUMN extraction_gate
├── llm-client.js            # MODIFIED — fmtHistory merges streams; buildUserBlock exposes lastBotOutbound
├── config.js                # MODIFIED — layered tenants/<id>/ → env → default loader
└── index.js                 # MODIFIED — 3 call sites pass intent

tenants/                     # NEW
├── mossrock/
│   ├── config.yaml          # committed
│   ├── strains.yaml         # committed
│   └── secrets.env          # gitignored
└── example/
    └── config.yaml          # committed (Foray v0.1 placeholder)
```

### Pattern 1: Anthropic SDK with prompt caching (REUSE EXISTING)
**What:** Build a `client = new Anthropic({ apiKey, maxRetries: 2 })`; pass `system` as an array of blocks with `cache_control: { type: 'ephemeral' }`; pass `tools` + `tool_choice` to force structured output.
**When to use:** Haiku classifier in Plan-04.
**Example (mirror this from `src/extraction/prompts/system.js:217-219`):**
```javascript
// Source: src/agents/alerter/src/extraction/prompts/system.js:217
const CACHEABLE_SYSTEM_BLOCKS = [
  { type: 'text', text: SYSTEM_PROMPT, cache_control: { type: 'ephemeral' } },
];
```
And in the classifier (mirror `src/extraction/extractor.js:112-134`):
```javascript
const client = injectedClient || new Anthropic({ apiKey, maxRetries: 2 });
// ...
const resp = await client.messages.create({
  model: 'claude-haiku-4-5-20251001',
  max_tokens: 100,  // tool_use returns ~30 tokens; 100 is generous
  system: CACHEABLE_SYSTEM_BLOCKS,
  tools: [{
    name: 'classify_capture',
    description: 'Classify whether this capture is an event worth extracting.',
    input_schema: { /* zod-to-json-schema for {is_event, kind, confidence} */ },
  }],
  tool_choice: { type: 'tool', name: 'classify_capture' },
  messages: [{ role: 'user', content: buildClassifierInput(envCtx) }],
});
```

### Pattern 2: ALTER TABLE ADD COLUMN IF NOT EXISTS (existing idempotent migration)
**What:** Add the `extraction_gate` audit column in `capture-db.js` initDb.
**When to use:** D-04.
**Example (template from `capture-db.js:32-34`):**
```javascript
// Source: src/agents/alerter/src/capture-db.js:32
await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS extraction_gate text`);
```
Note: D-04 says `VARCHAR(32)` but project convention here is plain `text` (Postgres treats both identically for storage; `text` is the project style). Planner: align with project style (use `text`), document the discrepancy with CONTEXT D-04 in PLAN.md.

### Pattern 3: Wrapper opts ergonomics (proposed)
**Current `signal.js:58` signature:** `async function send(body, { bypassCap = false, to } = {})`
**Proposed:** `async function send(body, { bypassCap = false, to, intent, relatedCaptureId, relatedDraftId } = {})`
**Rationale:** Additive; all 14 callsites continue to work without `intent` (interim — until lint enforces it); planner enables a runtime warn-if-missing for one release, then errors on missing intent. Avoids positional-arg break (`signal.js:5` already uses this options-bag style — match it).

### Pattern 4: EVAL_RUN_LIVE-gated live-API test (REUSE EXISTING)
**What:** `describe.skip` unless env var set.
**When to use:** Plan-04 Haiku live-fire smoke test.
**Example (template from `test/eval/ingestion/paperlog.test.js:14-15`):**
```javascript
// Source: src/agents/alerter/test/eval/ingestion/paperlog.test.js:14
const liveMode = process.env.EVAL_RUN_LIVE === '1' && !!process.env.ANTHROPIC_API_KEY;
const describeMaybe = liveMode ? describe : describe.skip;
```

### Anti-Patterns to Avoid
- **Hand-rolling YAML parsing:** Don't. `yaml@^2.x` is small and right.
- **Fanning the outbound write to 14 callsites:** Per D-14 audit-§5, this is exactly the regression risk. Single hook in `signal.js`.
- **Bumping `@anthropic-ai/sdk` version for the Haiku classifier:** Existing extractor depends on 0.91.1. Reuse the same client; don't add a parallel install.
- **Putting the gate INSIDE `extractionPipeline.enqueue`:** The gate must run BEFORE the enqueue (D-02 / `capture.js:147`) so the audit column gets set even when extraction is skipped. Putting it inside the pipeline breaks the audit trail.
- **Tightening Haiku timeout below 2s:** Anthropic API tail latency is bursty. 2s is the floor; <1s will cause spurious fail-opens.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML parsing | regex-based parser | `yaml@^2.x` | YAML's edge cases (anchors, multiline, types) are a swamp |
| Anthropic HTTP retries | bare fetch + setTimeout | `new Anthropic({ maxRetries: 2 })` SDK handles 429/5xx | SDK already retries with proper jitter |
| UUIDs | client-side libs | Postgres `gen_random_uuid()` | D-12 locks it; works in pgcrypto (already enabled per existing DDL elsewhere) |
| Layered config | nconf, convict | Plain functional layer: `(key) => fileVal ?? env[k] ?? default` | The whole loader is <50 LOC; no framework needed |
| Tool-use response validation | manual JSON.parse + checks | `zod` (already in deps) | Reuse extraction/validator.js pattern |
| Live-API test gating | conditional `it.only` | `EVAL_RUN_LIVE=1` env + `describe.skip` (existing repo idiom) | 5 existing tests use this; consistency matters |

**Key insight:** Almost every primitive Phase 44 needs already exists somewhere in `src/agents/alerter/`. The work is composition, not invention.

## Runtime State Inventory

> Phase 44 is mostly greenfield additions, but a few migration considerations apply.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `signal_capture` table exists with `llm_reply` column (legacy band-aid path); will gain `extraction_gate` column via ALTER IF NOT EXISTS. NO data migration needed — `extraction_gate` starts NULL for existing rows. | Code edit only (ALTER) |
| Live service config | `EVENT_GATE_CONVO_MODE` is new; default `silent` set in `tenants/mossrock/config.yaml`. Existing env vars (`SIGNAL_*`, `ANTHROPIC_API_KEY`, `FARMOS_*`) move from raw env to layered loader — see Walking-Skeleton Risk below. | Code edit + new files |
| OS-registered state | None. Alerter is a Docker container with no systemd/cron coupling beyond the existing `node-cron` retention job. | None |
| Secrets / env vars | `ANTHROPIC_API_KEY`, `FARMOS_PASSWORD`, `SIGNAL_SENDER` migrate from `.env` to `tenants/mossrock/secrets.env`. The `secrets.env` file is gitignored; CI must be updated to write secrets to that path instead of (or in addition to) the existing `.env`. **The existing `.env` mechanism MUST keep working as a fallback** — many existing tests pass `env: {ANTHROPIC_API_KEY: 'test-key'}` to `config.load(env)` directly. | Update CI deploy + preserve fallback chain |
| Build artifacts | None — alerter is a Node service, no compiled outputs to invalidate. | None |

## Common Pitfalls

### Pitfall 1: Haiku 4.5 prompt caching requires 4,096 tokens, not 1,024
**What goes wrong:** CONTEXT.md `<specifics>` says "Cached system prompt for the classifier: ≥1024 tokens (Haiku has lower threshold than Sonnet)." **This is WRONG for Haiku 4.5.**
**Why it happens:** Haiku 3.5 and Haiku 3 had a 2,048-token minimum. Haiku 4.5 uses a longer attention window and Anthropic raised the threshold to **4,096 tokens** — same as Sonnet.
**How to avoid:** Either (a) size the classifier system prompt + few-shot examples to ≥4,096 tokens, or (b) accept that caching will silently no-op for this phase and pay full input price per call. **There is no error when caching fails to hit** — `cache_creation_input_tokens` just returns 0.
**Warning signs:** `usage.cache_creation_input_tokens === 0` consistently across calls means the prompt is under threshold.
**Recommended action for planner:** Size the classifier prompt to 4,096+ tokens by including a substantial few-shot examples block. The 100-capture smoke set will provide perfect few-shot material.
**Source:** `[CITED: docs.anthropic.com/en/docs/build-with-claude/prompt-caching]` cross-verified with multiple secondary sources — see Sources section.

### Pitfall 2: capture.js line drift since CONTEXT.md was written
**What goes wrong:** CONTEXT.md cites `capture.js:147` (gate), `:168` (convo), `:192` (send), `:200` (UPDATE). Current code: `:147` ✓ (gate site still correct — `extractionPipeline.enqueue` is at :148), `:171` (compose, was :168), `:197` (send, was :192), `:206` (UPDATE, was :200).
**Why it happens:** Backlog 999.53 (token-usage tracking) added ~5 lines between gate and send.
**How to avoid:** Planner should re-grep before writing line-specific tasks; do not copy-paste line numbers from CONTEXT.md into PLAN.md without re-verification.
**Warning signs:** A task that says "edit `capture.js:192`" without freshly grepping `signalClient.send` will land in the wrong place.

### Pitfall 3: signal.js wrapper does NOT currently receive intent — back-compat shim needed
**What goes wrong:** Adding `intent` as a required field will break the 8 receive-loop sites + 3 index.js sites if they're not all updated atomically.
**How to avoid:** Use a two-step rollout: (1) accept optional `intent`, default `'unknown'`, log warn when missing; (2) update all 14 sites in the same PR to pass an explicit intent; (3) in a follow-up (v1.9), tighten to required + add lint/CI grep to enforce.
**Warning signs:** Any new test that mocks `signalClient.send` without an intent kwarg will silently get `intent='unknown'` rows in `signal_outbound` — pollutes the audit.

### Pitfall 4: extraction_gate column name collision
**What goes wrong:** `signal_capture` has 18 columns today (verified by reading `capture-db.js`); none named `extraction_gate`. Safe to add.
**How to avoid:** ALTER IF NOT EXISTS handles re-runs idempotently. Verified.

### Pitfall 5: Phase 39 confirm short-circuit ordering
**What goes wrong:** D-22 third bullet asserts confirm rows never reach the gate. **VERIFIED:** at `receive-loop.js:220-264` (confirm short-circuit with `continue` on YES/NO/EDIT) runs strictly before `capturePipeline.handle` at `:269`. ✓ assertion holds.
**Edge case:** `parsed.kind === 'NOOP'` (line 262 comment) falls through to capture pipeline. This is current behavior and matches D-22 intent (NOOP = no confirm match = back to gray-zone capture flow).
**How to avoid:** Phase 44 must NOT add a redundant confirm-bypass inside the gate. The smoke test should assert that the 28 confirm rows never increment `extraction_gate` counters (they bypass entirely).

### Pitfall 6: `signal_capture.llm_reply` UPDATE vs new `signal_outbound` write race
**What goes wrong:** Per D-17 / `[[2026-05-17-llm-outbound-amnesia]]` and the audit table, the convo reply at `capture.js:197` is also persisted via the UPDATE at `capture.js:206-226`. Under Phase 44, the SAME send will write to BOTH `signal_capture.llm_reply` (existing UPDATE path) AND `signal_outbound` (new wrapper hook). Documented as intentional in D-17 ("kept for audit trail").
**How to avoid:** Confirm with planner that this dual-write is intentional. If the wrapper insert fails but the UPDATE succeeds, `fmtHistory` will not see this turn in `signal_outbound` but will see it in `signal_capture.llm_reply` — and D-17 says `fmtHistory` no longer reads `llm_reply`. So a failed outbound insert causes invisibility in next-turn LLM context. Acceptable per D-03 fail-open posture, but logger.warn must fire and an alert-on-repeated-failure observation should be filed (v1.9 candidate).

### Pitfall 7: `tenants/` directory is greenfield + `.gitignore` does not currently exclude `secrets.env`
**What goes wrong:** First commit could leak `tenants/mossrock/secrets.env` into git history.
**How to avoid:** Plan-01 (or pre-flight) MUST update `.gitignore` BEFORE creating any `tenants/mossrock/secrets.env`. Suggested entry:
```
tenants/*/secrets.env
tenants/*/.env
```
**Warning signs:** `git status` showing `tenants/mossrock/secrets.env` as untracked rather than ignored.

## Code Examples

### Layered config loader (proposed shape — planner discretion)
```javascript
// Source: NEW src/agents/alerter/src/config.js (refactor)
const fs = require('fs');
const path = require('path');
const YAML = require('yaml');

function loadTenantFile(tenantId, filename) {
  const p = path.join(__dirname, '..', '..', '..', '..', 'tenants', tenantId, filename);
  if (!fs.existsSync(p)) return {};
  try { return YAML.parse(fs.readFileSync(p, 'utf8')) || {}; }
  catch (e) { console.warn(`[config] ${p} parse failed: ${e.message}`); return {}; }
}

function layeredGet(tenantConfig, env, key, def) {
  if (tenantConfig[key] !== undefined && tenantConfig[key] !== null) return tenantConfig[key];
  if (env[key] !== undefined) return env[key];
  return def;
}

function load(env = process.env) {
  const tenantId = env.TENANT_ID || 'mossrock';
  const tenantConfig = {
    ...loadTenantFile(tenantId, 'config.yaml'),
    ...loadTenantFile(tenantId, 'strains.yaml'),
  };
  // existing parseFarmerMap, parseIntEnv etc. — but pull from layeredGet instead of env directly
  return Object.freeze({
    tenantId,
    // ...existing fields, each using layeredGet(tenantConfig, env, 'KEY', default)
  });
}
```

### Wrapper signature ergonomics (proposed)
```javascript
// Source: NEW src/agents/alerter/src/signal.js (modification)
async function send(body, { bypassCap = false, to, intent, relatedCaptureId = null, relatedDraftId = null } = {}) {
  if (!intent) {
    logger.warn('[signal] send() called without intent — defaulting to "unknown" (v1.9 will require)');
  }
  // ...existing rate-cap + group resolution + fetch as today...
  // After successful send (after sendHistory.push(now)):
  try {
    await outboundDb.insertOutbound(pool, {
      tenant_id: config.tenantId,
      sent_at: new Date(),
      recipient_e164: isStringTarget ? target : null,
      // group sends: recipient_e164 stays null; planner: add recipient_group_id column? (NOT in D-12 — flag for review)
      intent: intent || 'unknown',
      body,
      source_module: /* requires caller to pass or stack-walk; planner pick */ null,
      source_line: null,
      related_capture_id: relatedCaptureId,
      related_draft_id: relatedDraftId,
    });
  } catch (e) {
    logger.warn(`[signal] outbound persistence failed: ${e.message} — send succeeded, audit row missed`);
  }
}
```
**⚠ Planner: D-12 schema does not have a `recipient_group_id` column.** Group sends will write `recipient_e164=null`. Either (a) accept this (D-13 mapping table can document), or (b) add a `recipient_group_id text` column. Recommend (a) — keep D-12 verbatim, document the semantics in the intent-mapping table per D-13.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `signal_capture.llm_reply` as the only durable outbound | Dedicated `signal_outbound` table | Phase 44 (this phase) | Closes amnesia finding 1b; replaces the v1.7.x band-aid |
| Single `.env` for all config | Layered `tenants/<id>/` → env → default | Phase 44 (this phase) | First step toward OSS-Foray multi-tenant; v2.0 will extract |
| Rules-only extractor dispatch (no gate) | Hybrid rules + Haiku 4.5 classifier | Phase 44 (this phase) | Stops paying Sonnet on chit-chat |
| Haiku 3.5 (2,048-token cache min) | Haiku 4.5 (**4,096-token cache min**) | Anthropic Oct 2025 release | Re-verify cache prompt sizing per Pitfall 1 |

**Deprecated/outdated:**
- The 2026-05-17 amnesia note's recommended "Option a*" (read `llm_reply` in `fmtHistory`) is **SUPERSEDED** by D-17 — `fmtHistory` will read `signal_outbound`, not `llm_reply`. The `llm_reply` UPDATE stays for audit.
- The 2026-05-17 event-gate note's recommended "rules-only first, audit a week, then add Haiku" sequencing is **SUPERSEDED** by D-01 — ship the full hybrid in Phase 44.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `yaml@^2.x` is the right new YAML dep | Standard Stack | Low — `js-yaml` is the only other realistic choice; both work. Planner can verify with `npm view`. |
| A2 | `gen_random_uuid()` is available in this Timescale install (requires pgcrypto extension) | Architecture / D-12 | Medium — if pgcrypto is not enabled, the DDL will error on first run. Verify with `SELECT extname FROM pg_extension WHERE extname='pgcrypto';` on elder-plops Timescale before Plan-02. If missing, `CREATE EXTENSION IF NOT EXISTS pgcrypto;` in the same migration. |
| A3 | Haiku 4.5 prompt cache min is 4,096 tokens (verified externally but not against Anthropic's official docs in this session — secondary sources agree) | Common Pitfalls / Pitfall 1 | Medium — if actually 2,048, the classifier prompt could be smaller. Planner: fetch `docs.anthropic.com/en/docs/build-with-claude/prompt-caching` once and pin the exact threshold in PLAN.md. |
| A4 | The 14-site inventory is exhaustive | OUTBOUND-01 | Low — verified via `grep -rn "signalClient.send" src/agents/alerter/src/` in this research; 14 lines confirmed. CI grep-gate (deferred to v1.9) would lock this permanently. |
| A5 | `EVAL_RUN_LIVE=1` env-gated `describe.skip` is the right live-API test idiom for Plan-04 | Architecture | Low — 5 existing test files use exactly this pattern. |
| A6 | The boot-chain refactor of `config.js` can preserve back-compat with tests that pass `env={...}` to `config.load(env)` | Walking-Skeleton Risk | Medium-High — see Walking-Skeleton Risk below. |
| A7 | Phase 39 confirm short-circuit at `receive-loop.js:220-264` runs before `capturePipeline.handle` at `:269` | Pitfall 5 | Verified — `[VERIFIED: codebase grep]` reading current `receive-loop.js`. |

## Open Questions

1. **`recipient_group_id` column on `signal_outbound`?**
   - What we know: D-12 schema only has `recipient_e164 text NOT NULL`. Group sends in current code use `{to: {groupId}}`.
   - What's unclear: With `recipient_e164 NOT NULL`, group sends would error on insert.
   - Recommendation: Either (a) relax `recipient_e164` to NULL-allowed + add a CHECK constraint that at least one of recipient_e164/group_id is set, or (b) for group sends, write the group id into `recipient_e164` with a `group:` prefix and accept the field-name awkwardness. **Suggest the planner consult the operator** — this is a D-12 ambiguity, not a planner discretion area.

2. **Source module/line capture mechanism**
   - What we know: D-12 schema has `source_module text NOT NULL, source_line integer`. The audit §2 table shows each call site by file+line.
   - What's unclear: How is the wrapper supposed to know which file/line called it? Options: (a) caller passes them explicitly, (b) parse `new Error().stack`, (c) hardcode at the call site as an opts field.
   - Recommendation: Option (a) — `signalClient.send(body, { intent, sourceModule: 'capture.js', ... })`. Stack-walking is slow + brittle.

3. **Plan ordering: when does the wrapper start writing rows?**
   - What we know: D-14 says single hook in `signal.js`; Plan-01 is the 100-capture hand-classify; Plan-04 is the Haiku live-fire.
   - What's unclear: If wrapper writes start in Plan-02 (DDL), but call sites only pass `intent` in Plan-03+, the early rows have `intent='unknown'`. Acceptable noise during phase build.
   - Recommendation: Document explicitly in PLAN-02 that early wrapper rows will be `intent='unknown'`; truncate the table once before Plan-03 finishes.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | All alerter code | ✓ (already running in Docker) | container default | — |
| `@anthropic-ai/sdk` | Haiku classifier | ✓ | ^0.91.1 (in package.json) | none — Phase 44 hard-depends |
| Timescale Postgres (elder-plops) | `signal_outbound` table + Plan-01 SELECT | ✓ (running) | per `[[project_openmct_dashboard]]` | — |
| `pgcrypto` extension (for `gen_random_uuid()`) | D-12 DDL | UNVERIFIED — see A2 | — | `CREATE EXTENSION IF NOT EXISTS pgcrypto;` in migration |
| `yaml` npm package | Config loader | ✗ (not installed) | — | None acceptable per D-11 (YAML files are committed); must install |
| `ANTHROPIC_API_KEY` env | Haiku classifier + Plan-04 live test | ✓ (used by extractor today) | — | none |
| Live `signal_capture` rows on elder-plops `>= 2026-05-10` | Plan-01 corpus pull | ✓ (per `[[project_2026_05_20_fc_buffer_real_outage_validation]]` — system has been running) | — | none |
| Operator availability for hand-labeling | Plan-01 ship-gate | ✗ (gating step) | — | Cannot be automated per `[[feedback_real_data_before_ship_gate_pass]]` |

**Missing dependencies with no fallback:**
- `yaml` package install (cheap to fix; planner adds to Plan-00 or pre-flight)
- Operator hand-labeling time for 100 captures (no fallback; estimated 1-2 hours of focused work)

**Missing dependencies with fallback:**
- `pgcrypto` — likely already enabled but unverified; `CREATE EXTENSION IF NOT EXISTS` is idempotent and safe

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Jest ^29.7.0 (`devDependencies` in `src/agents/alerter/package.json`) |
| Config file | none (uses jest defaults); eval suites have their own `test/eval/*/jest.config.js` |
| Quick run command | `cd src/agents/alerter && npx jest <test-file>` |
| Full suite command | `cd src/agents/alerter && npm test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GATE-01 | 0 farmer pings on 24 must-skip rows (smoke) | integration (mocked Haiku) | `npx jest test/event-gate/integration.test.js` | ❌ Wave 0 — new file |
| GATE-01 | Rule POS fast-paths match expected captures | unit | `npx jest test/event-gate/rules.test.js` | ❌ Wave 0 |
| GATE-01 | Rule NEG fast-path matches ack-after-attestation only | unit | `npx jest test/event-gate/rules.test.js -t "negative"` | ❌ Wave 0 |
| GATE-02 | ≥95% recall on 48 must-extract (smoke harness) | integration | `npx jest test/event-gate/smoke.test.js` (reads 44-hand-classified-100.jsonl) | ❌ Wave 0 |
| GATE-02 | Haiku classifier returns expected tool-use shape on canned inputs | unit (mocked Anthropic) | `npx jest test/event-gate/haiku-classifier.test.js` | ❌ Wave 0 — mirror `test/farmos/mock-client.js` pattern |
| GATE-02 | Haiku live-fire on 10 gray-zone fixtures | live | `EVAL_RUN_LIVE=1 ANTHROPIC_API_KEY=... npx jest test/event-gate/haiku-live.test.js` | ❌ Wave 0 |
| OUTBOUND-01 | Wrapper writes one row per send with intent | unit | `npx jest test/signal.test.js -t "outbound persistence"` | partial — extend existing `test/signal.test.js` |
| OUTBOUND-01 | All 14 callsites pass an intent (no `'unknown'` rows after phase complete) | integration | `npx jest test/integration.test.js -t "outbound intents"` | partial — extend existing |
| OUTBOUND-02 | `fmtHistory` includes outbound stream | unit | `npx jest test/llm-client.outbound-merge.test.js` | ❌ Wave 0 |
| OUTBOUND-02 | `buildUserBlock` exposes `lastBotOutbound` | unit | `npx jest test/llm-client.test.js -t "lastBotOutbound"` | partial — extend existing |
| TENANT-01 | `signal_outbound.tenant_id` is NOT NULL + indexed | unit | `npx jest test/outbound-db.test.js` | ❌ Wave 0 |
| TENANT-01 | Config loader reads `tenants/mossrock/config.yaml` with fallback to env | unit | `npx jest test/config.test.js -t "tenant"` | partial — extend existing |

### Sampling Rate
- **Per task commit:** `cd src/agents/alerter && npx jest <touched-test-file>`
- **Per wave merge:** `cd src/agents/alerter && npm test` (full suite, ~700 tests per project memory `[[project_2026_05_16_phase43_shipped]]`)
- **Phase gate:** Full suite green + smoke harness green + `EVAL_RUN_LIVE=1 npm test` green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `test/event-gate/rules.test.js` — covers GATE-01 fast paths
- [ ] `test/event-gate/haiku-classifier.test.js` — covers GATE-02 mocked shape
- [ ] `test/event-gate/haiku-live.test.js` — covers GATE-02 live; gated on `EVAL_RUN_LIVE=1`
- [ ] `test/event-gate/integration.test.js` — full capture-pipeline-with-gate (covers GATE-01 + GATE-02 integration)
- [ ] `test/event-gate/smoke.test.js` — reads `44-hand-classified-100.jsonl`, asserts D-22 metrics
- [ ] `test/outbound-db.test.js` — covers TENANT-01 DDL + insert + select
- [ ] `test/llm-client.outbound-merge.test.js` — covers OUTBOUND-02 merge ordering
- [ ] Extend `test/signal.test.js` — outbound persistence hook (OUTBOUND-01)
- [ ] Extend `test/config.test.js` — tenant layered loader (TENANT-01)
- [ ] No framework install needed — Jest already in deps

## Security Domain

`security_enforcement` not explicitly set in `.planning/config.json` — treat as enabled.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | Anthropic API key flows through layered config; `mustEnv` guard already present in `config.js` |
| V3 Session Management | no | No sessions — single-process agent |
| V4 Access Control | yes | Sender whitelist at `receive-loop.js:131` — already in place; Phase 44 must not bypass |
| V5 Input Validation | yes | `zod` schema on Haiku tool_use output (mirror extraction validator) |
| V6 Cryptography | yes | `gen_random_uuid()` uses pgcrypto — never hand-roll. `tenants/mossrock/secrets.env` MUST be gitignored. |
| V7 Error Handling | yes | Fail-open posture per D-03 must be intentional (it is) and logged on every fail |
| V14 Configuration | yes | Layered config loader must not log secrets — `maskNumber` exists for phones; reuse |

### Known Threat Patterns for {stack}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leak via committed `secrets.env` | Information Disclosure | `.gitignore` MUST be updated before any tenant file is created (Pitfall 7) |
| Anthropic API key in logs | Information Disclosure | Existing pattern: never log `apiKey`; only pass to `new Anthropic({apiKey})`. Mirror this in classifier. |
| Prompt injection from farmer message into classifier system prompt | Tampering | System prompt is static + cached; user content is the farmer message — keep them separate (don't string-concat). Already the pattern in extractor. |
| SQL injection on `signal_outbound` insert | Tampering | `pg` parameterized queries (existing project pattern); never string-concat into SQL |
| Slopsquat on new `yaml` dep | Tampering | Per Package Legitimacy Audit — verify package source URL before install |
| Haiku fail-open as DoS amplifier | Denial of Service | Per D-03 acceptable — over-extraction is recoverable; rate-cap on `signal.js` (existing) still protects the farmer-facing surface |

## Sources

### Primary (HIGH confidence)
- Codebase grep — `src/agents/alerter/src/capture.js`, `signal.js`, `receive-loop.js`, `llm-client.js`, `capture-history.js`, `capture-db.js`, `config.js`, `extraction/extractor.js`, `extraction/prompts/system.js`, `confirm/outbound-confirm.js`, `extraction/outbound.js`, `index.js` (lines :180,:183,:185), `package.json`
- CONTEXT.md (`.planning/phases/44-event-gate-durable-signal-outbound-tenant-aware/44-CONTEXT.md`) — D-01..D-23
- `.planning/notes/2026-05-17-signal-outbound-schema-audit.md` — §2 14-site inventory (verified against current code)
- `.planning/ROADMAP.md` — Phase 44 section, GATE-01/02/OUTBOUND-01/02/TENANT-01 definitions
- Anthropic SDK source (`node_modules/@anthropic-ai/sdk/.../messages/messages.d.ts:707`) — confirmed `claude-haiku-4-5-20251001` model id exists

### Secondary (MEDIUM confidence)
- WebSearch verified across multiple sources: Haiku 4.5 prompt-caching threshold = 4,096 tokens (raised from Haiku 3.5's 2,048). Cross-source agreement is high but I did not fetch the Anthropic doc directly in this session.

### Tertiary (LOW confidence)
- Assumption that `pgcrypto` is enabled on elder-plops Timescale — UNVERIFIED. Flagged as A2.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — `@anthropic-ai/sdk`, `pg`, `zod` already in repo; `yaml` is a single small dep to add
- Architecture: HIGH — all integration points verified against current code
- Pitfalls: HIGH for code-side pitfalls (verified); MEDIUM for Pitfall 1 (Haiku cache threshold — secondary sources only)
- 14-site inventory: HIGH — re-verified against current code, one line-drift correction documented

**Research date:** 2026-05-21
**Valid until:** 2026-06-04 (14 days — Haiku 4.5 + Anthropic SDK posture is stable; code references valid until next refactor of `capture.js` or `signal.js`)

Sources:
- [Prompt caching - Anthropic](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [Claude prompt caching minimum token thresholds](https://help.apiyi.com/en/claude-prompt-caching-not-hit-minimum-token-troubleshooting-en.html)
- [How to Add Prompt Caching to an Anthropic SDK App](https://startdebugging.net/2026/04/how-to-add-prompt-caching-to-an-anthropic-sdk-app-and-measure-the-hit-rate/)
- [yaml npm package](https://www.npmjs.com/package/yaml)
