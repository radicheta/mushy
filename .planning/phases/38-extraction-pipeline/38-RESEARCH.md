# Phase 38: Extraction Pipeline - Research

**Researched:** 2026-05-12
**Domain:** Multimodal schema-aware LLM extraction (Anthropic tool-use + Zod) for farmOS-shaped drafts from Signal messages.
**Confidence:** HIGH on framework + integration points (locked in 38-AI-SPEC); MEDIUM on Anthropic JSON-Schema subset edge cases; HIGH on existing code shape (read codebase directly).

## Summary

Phase 38 is fully scoped in `38-CONTEXT.md` (D-01..D-07) and `38-AI-SPEC.md`. The framework + eval contract is locked: extend `llm-client.js` with a new `extract()` entry point that uses Anthropic tool-use forced calls (`tool_choice: {type:'tool', name:'submit_extraction'}`) with `input_schema` emitted from a Zod `discriminatedUnion('log_type', ...)` over the B7 native log types, runtime-validates `tool_use.input` via `Draft.safeParse`, and persists to a new `signal_draft` table on the same Timescale pool as `signal_capture`. The conversation state machine (3-turn ask-back cap, 30-min idle gap, per-sender concurrency invariant) is DB-resident, not framework-resident. The eval harness is a jest-based custom Node.js runner over `/mnt/mossrock/shared/mushdatadump/` (73 JPEGs + `mushroom_log.csv` ground truth) and Phase 38 ships only when D-07 bar is met (≥90% schema-valid AND ≥75% required-field exact-match OR appropriate ask-back).

**Primary recommendation:** Implement extraction as `src/agents/alerter/src/extraction/` directory tree per the locked AI-SPEC §3 layout. Keep `llm-client.js` untouched (its compose-acknowledge-flow client is still used by Phase 25); the extractor constructs its own `new Anthropic(...)` instance with `timeout: 60_000` and tool-use parameters. Add `signal_draft` table in a new `extraction-db.js` module — DO NOT shoehorn into `capture-db.js` (separation matches Phase 25/37 modular pattern). One eval-set-aware planner concern: production logs corpus is much smaller than the user implied — only one day (2026-04-28, ~5 files, 1.3MB). Plan around that.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 Multimodal Fusion:** LLM judges continuity (`append`/`replace`/`start-new`); decision + rationale logged to draft audit trail.
- **D-01a:** Hard idle-gap cap **30min** — older messages force `start-new`. Phase 39 confirm/discard also forces `start-new` on the next message.
- **D-02 Draft Storage:** Reuse Phase 25 `capture-db.js` Timescale pool. Add `signal_draft` table. FK array `source_capture_ids text[]` → `signal_capture.id`. Idempotent migration using `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`.
- **D-02a:** Draft `id` = `sha256(sort(source_capture_ids).join(','))` — deterministic, replay-safe.
- **D-02b:** Status enum: `pending → awaiting_farmer → (confirmed | discarded | needs_review | expired)`. Phase 38 owns `pending`, `awaiting_farmer`, `needs_review`, `expired`. Phase 39 transitions to `confirmed`/`discarded`. Phase 40 → `committed`.
- **D-02c:** At most **one in-flight draft per sender E.164**. Enforce with partial-unique index `WHERE status IN ('pending','awaiting_farmer')`.
- **D-03 Ask-Back Trigger:** required-field unresolved OR per-field confidence `< 0.7` (env: `EXTRACTION_CONFIDENCE_THRESHOLD`).
- **D-04 Ask-Back Shape:** full draft preview with `[?]` markers + one-line top question. Farmer can answer either; LLM merges next turn.
- **D-05 Hard Cap:** **3 ask-back turns**. On cap → `needs_review` + farmer-facing "I can't lock this one, marked for manual review" (rounded numbers, no em-dashes).
- **D-06 Eval Harness:** `tests/eval/extraction/` over `/mnt/mossrock/shared/mushdatadump/`. Scores schema-conformance, required-field exact-match, ask-back-appropriateness. Ask-back on genuinely-ambiguous = PASS.
- **D-07 Pass Bar (ship-gate):** **≥90% schema-valid AND ≥75% required-field exact-match OR appropriate ask-back** against mushdatadump v1.6.

### Claude's Discretion

- Prompt structure, few-shot examples (subject to em-dash + rounded-numbers memory constraints on farmer-facing strings only).
- JSON schema-validator library — Zod is locked in AI-SPEC §2 with `ajv` as the fallback if `z.discriminatedUnion` round-trip fails.
- Single-pass vs two-pass (extract→refine) — planner decides based on eval scores.
- Inline-in-receive-loop vs separate worker process.
- Exact env-var names and defaults: `EXTRACTION_CONFIDENCE_THRESHOLD` (default 0.7), `DRAFT_IDLE_GAP_MIN` (default 30), `MAX_ASKBACK_TURNS` (default 3).

### Deferred Ideas (OUT OF SCOPE)

- Vision beyond QR scan + photo-as-context (Phase 24/v1.8).
- Cross-stream consistency tests → Phase 41.
- Multi-farmer event collision.
- Farmer-tunable thresholds via Signal command.
- Auto-merge of `needs_review` drafts at weekly review.
- Lineage shorthand beyond simple block-number lists (e.g. "blocks from last Tuesday's batch").

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXT-01 | JSON-mode schema-conformant output (B7 native log types only) | Anthropic tool-use `tool_choice: {type:'tool', name:'submit_extraction'}` + Zod `discriminatedUnion('log_type', ...)` + `Draft.safeParse` runtime validation + retry-once on Zod failure. AI-SPEC §3+§4. |
| EXT-02 | B5 block-naming `YYMMDD_SPECIES3_SEQ` | Zod `.regex(/^\d{6}_[A-Z]{3}_\d{2,4}$/)` constraint on `block_name`; species-trigraph allow-list in system prompt; ask-back when SEQ ambiguous (D-03 + D-04). AI-SPEC §5 dimension 2. |
| EXT-03 | Multimodal fusion → one draft | `multimodal.buildUserBlocks({ captureRow, draftCtx })` emits text + base64 image + Whisper transcript in a single `content` array; LLM continuity decision merges over `source_capture_ids` array. AI-SPEC §4 + dimension 8. |
| EXT-04 | Confidence-aware ask-back | Per-field `_confidence: z.record(z.string(), z.number().min(0).max(1))` in schema; post-validator triggers `awaiting_farmer` status when any field `< 0.7` OR required-field unresolved; 3-turn cap (D-05). AI-SPEC §6 guardrails. |
| EXT-05 | Multi-parent lineage extraction (C4) | `parent_block_names: z.array(z.string()).min(1)` on `HarvestLog`; eval dimension 4 set-equality check. AI-SPEC §5 dimension 4. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Inbound Signal message routing + sender→farmer resolution | Alerter (Phase 37) | — | Already done upstream; Phase 38 reads `signal_capture.farmos_person`. |
| Whisper transcription of voice notes | Whisper sibling container (Phase 25) | — | Already done upstream; transcript on `signal_capture.transcript`. |
| Multimodal extraction (LLM call, schema enforcement) | Alerter — new `extraction/` module | — | Same Node.js process; reuse compose-network + Timescale pool. |
| Draft persistence + state machine | Timescale (new `signal_draft` table) | — | DB-resident state per D-02; reuses `capture-db.js` pool. |
| Ask-back composition + reply | Alerter (`signal.js` send helpers) | — | Reuse Phase 37 `reply_target_kind` routing for DM vs group. |
| Eval harness | Jest in alerter package | — | Same runtime, same Zod schemas, no second toolchain. |
| Farmer-facing artifact sanitization | Alerter `message.js` (extend `fmtNum`) | — | Existing utility already enforces no-em-dashes + rounded-numbers. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@anthropic-ai/sdk` | `^0.91.1` (already installed) | LLM client; tool-use; vision; prompt caching | Already battle-tested in `llm-client.js` (Phase 25). Native tool-use is the cheapest path to forced-JSON output. [CITED: AI-SPEC §2 + verified in `package.json`] |
| `zod` | `^3.25.2` (new) | Schema definition + runtime validation | One source of truth for Anthropic `input_schema` + post-call validation + eval harness. Locked in AI-SPEC §2. [CITED: zod.dev/?id=discriminated-unions] |
| `zod-to-json-schema` | `^3.24.5` (new) | Emit JSON-Schema draft-7 from Zod | Required adapter between Zod and Anthropic's `tool.input_schema`. Locked in AI-SPEC §2. [CITED: npmjs.com/package/zod-to-json-schema] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pg` | `^8.20.0` (already installed) | Postgres/Timescale client | New `extraction-db.js` reuses the existing pool from `index.js`. |
| `jest` | `^29.7.0` (already installed) | Test runner + eval harness | Eval suite under `test/eval/extraction/`. |
| `ulid` | `^3.0.2` (already installed) | (not for draft id — D-02a uses sha256) | Use for `signal_draft.id` only as a fallback if sha256 collisions appear. Default = sha256. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Zod + `zod-to-json-schema` | Hand-authored JSON Schema + `ajv` | **Fallback path locked in AI-SPEC §2 reserved-alternatives row.** Use IF discriminated-union round-trip breaks Anthropic's `input_schema` validator (see Q2 research below). Less type-safety, more deterministic emission. |
| Anthropic tool-use forced call | Streaming text + JSON.parse | Rejected: defeats schema enforcement; Sonnet 4.6's `tool_use` is more reliable than free-form JSON. |
| Separate worker process | Inline in receive-loop | Claude's Discretion. Inline is simpler (no IPC); worker is more isolating. RECOMMEND inline for v1 (per AI-SPEC tone) — receive-loop is already async-non-blocking. Revisit if eval shows latency cliffs. |
| Phoenix / Arize / Promptfoo | Custom jest harness | Locked in AI-SPEC §5 — small dataset (73 cases), single-runtime CI. |

**Installation:**
```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
npm install zod@^3.25.2 zod-to-json-schema@^3.24.5
```

**Version verification:** SDK pinned at `0.91.1` in package.json [VERIFIED: read `package.json`]. Zod 3.25.x is current stable as of locked AI-SPEC date (2026-05-11). `zod-to-json-schema` 3.24.x is the published target [CITED: AI-SPEC §3].

## Architecture Patterns

### System Architecture Diagram

```
                 ┌─────────────────────────────────────┐
                 │  Inbound Signal capture (Phase 37)  │
                 │  signal_capture row INSERT with     │
                 │  farmos_person populated            │
                 └────────────────┬────────────────────┘
                                  │ (1) capture written
                                  ▼
       ┌────────────────────────────────────────────────────┐
       │  Extraction trigger (receive-loop hook OR worker)  │
       │  Pre-flight: farmos_person != null                 │
       └────────────────┬───────────────────────────────────┘
                        │ (2) load in-flight draft for sender
                        ▼
       ┌────────────────────────────────────────────────────┐
       │  Phase A — Continuity decision (D-01)              │
       │  IF in-flight draft AND age <= 30min               │
       │    → LLM tool_choice=decide_continuity             │
       │    → action ∈ {append, replace, start-new}         │
       │  ELSE force start-new                              │
       └────────────────┬───────────────────────────────────┘
                        │ (3) action + maybe-expire-prior-draft
                        ▼
       ┌────────────────────────────────────────────────────┐
       │  Phase B — Multimodal extraction                   │
       │  buildUserBlocks: text + base64-image + transcript │
       │  + (optional) prior-draft snapshot                 │
       │  LLM tool_choice=submit_extraction                 │
       │    → tool_use.input → Draft.safeParse              │
       │    → ON FAIL: retry-once via tool_result+is_error  │
       └────────────────┬───────────────────────────────────┘
                        │ (4) validated draft
                        ▼
       ┌────────────────────────────────────────────────────┐
       │  Confidence sweep + state transition               │
       │  ANY required unresolved OR conf<0.7?              │
       │    YES → status=awaiting_farmer                    │
       │           compose ask-back via msg+fmtNum          │
       │           send via signal.js (reply_target_kind)   │
       │    NO  → status=pending                            │
       │  ask_back_turns >= 3 → needs_review + page         │
       └────────────────┬───────────────────────────────────┘
                        │ (5) upsert signal_draft (sha256 id)
                        ▼
       ┌────────────────────────────────────────────────────┐
       │  Phase 39 (CONF) reads awaiting_farmer drafts;     │
       │  Phase 40 (FOS) reads confirmed drafts.            │
       └────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
src/agents/alerter/
├── src/
│   ├── extraction/
│   │   ├── schemas/
│   │   │   ├── index.js          # z.discriminatedUnion('log_type', [...])
│   │   │   ├── seeding.js
│   │   │   ├── activity.js       # incl. cold_shock / contam / archive_spent / water / relocate / sterilize / sterilize_failed
│   │   │   ├── input.js
│   │   │   ├── observation.js
│   │   │   ├── harvest.js
│   │   │   └── assets.js         # B1-B4 fungi asset draft schemas (batch/block/harvest-batch/bag)
│   │   ├── prompts/
│   │   │   ├── system.js         # role + B7 + B5 + C4 + species trigraphs
│   │   │   ├── few-shot.js       # 3-4 mushdatadump-derived examples
│   │   │   └── ask-back.js       # [?] preview + one-line top Q
│   │   ├── extractor.js          # extract() entry; orchestrates Phase A+B
│   │   ├── continuity.js         # D-01 continuity LLM call
│   │   ├── state-machine.js      # status transitions, 30min cap, 3-turn cap
│   │   ├── validator.js          # Draft.safeParse + business rules
│   │   ├── multimodal.js         # disk path → base64 image block builder + downscale
│   │   └── sanitize.js           # reuse message.fmtNum + em-dash sweep for ask-back text
│   ├── extraction-db.js          # signal_draft CRUD (NEW; mirrors capture-db.js style)
│   ├── llm-client.js             # EXISTING — unchanged
│   ├── capture-db.js             # EXISTING — unchanged
│   ├── transcribe-client.js      # EXISTING — unchanged
│   └── ...
└── test/
    ├── extraction/                # unit tests (jest existing)
    │   ├── schemas.test.js
    │   ├── extractor.test.js
    │   ├── state-machine.test.js
    │   └── multimodal.test.js
    └── eval/
        └── extraction/            # D-06 offline eval harness
            ├── jest.config.js     # runInBand, longer timeout
            ├── mushdatadump.test.js
            ├── scoring.js         # Brier/ECE/set-equality/regex
            └── fixtures/          # symlink to /mnt/mossrock/shared/mushdatadump
```

### Pattern 1: Anthropic Tool-Use Forced Call with Zod-emitted Schema

**What:** Force the LLM to call a named tool whose `input_schema` is the JSON-Schema derived from a Zod `discriminatedUnion`.
**When:** Every Phase 38 extraction call.
**Example:**
```js
// Source: AI-SPEC §3 Entry Point Pattern + docs.anthropic.com/en/docs/build-with-claude/tool-use [CITED]
const Anthropic = require('@anthropic-ai/sdk');
const { z } = require('zod');
const { zodToJsonSchema } = require('zod-to-json-schema');
const { Draft } = require('./schemas');

const inputSchema = zodToJsonSchema(Draft, { target: 'jsonSchema7', $refStrategy: 'none' });

const msg = await client.messages.create({
  model: 'claude-sonnet-4-6',
  max_tokens: 1500,
  temperature: 0,
  system: SYSTEM_PROMPT,
  tools: [{ name: 'submit_extraction', description: '...', input_schema: inputSchema }],
  tool_choice: { type: 'tool', name: 'submit_extraction' },
  messages: [{ role: 'user', content: userBlocks }],
});

const toolUse = msg.content.find((b) => b.type === 'tool_use' && b.name === 'submit_extraction');
const parsed = Draft.safeParse(toolUse.input);
```

### Pattern 2: DB-Resident Conversation State (no framework session)

**What:** Conversation continuity is a row in Timescale, not in-memory state.
**When:** Every multi-turn flow (continuity, ask-back).
**Example:** Look up `signal_draft WHERE sender_e164=$1 AND status IN ('pending','awaiting_farmer')` at the start of each inbound; touch `updated_at` and increment `ask_back_turns` on every turn.

### Pattern 3: Idempotent DB Migration at Module Init

**What:** Schema changes via `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` inside `initDb(pool)`.
**When:** Phase 38 `extraction-db.initDb` mirrors `capture-db.initDb`.
**Example:** `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/capture-db.js` lines 5–35 [VERIFIED: read file].

### Pattern 4: Reuse Existing Sanitizer for Farmer-Facing Strings

**What:** All bytes the farmer reads in Signal flow through `fmtNum()` + em-dash sweep.
**When:** Composing the `[?]`-annotated preview, top question, and the "marked for manual review" cap-message.
**Example:** `message.js:fmtNum` is the canonical helper [VERIFIED: read file lines 14–19]. Phase 38 ADDS an em-dash regex sweep (`/[—–]/g → '?'` or `' '`) into a new `extraction/sanitize.js` that wraps `message.fmtNum`.

### Anti-Patterns to Avoid

- **Reading `msg.content[0].text` when `tool_choice` was forced.** The forced-tool response is a `tool_use` block, possibly preceded by a thinking-out-loud `text` block. ALWAYS use `.find(b => b.type === 'tool_use')`. [CITED: AI-SPEC §3 pitfall 2]
- **Passing image content blocks as file paths.** Must read + base64-encode + `{ type: 'image', source: { type: 'base64', media_type, data } }`. [CITED: AI-SPEC §3 pitfall 3]
- **Letting `max_tokens` default.** Hard-cap at `1500` for extraction, `300` for continuity, `200` for ask-back composition.
- **Building a parallel eval implementation.** The eval harness MUST use the same `extract()` entry point as production — schema/prompt drift is the ship-gate failure mode.
- **In-memory continuation state across LLM calls.** All state in Timescale; LLM is stateless.
- **Em-dashes anywhere a farmer reads.** Em-dashes in AI-SPEC.md, code comments, dev logs are fine; em-dashes in `signal_draft.farmer_facing_preview` or outbound Signal text are a guardrail failure.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON-mode enforcement | Custom regex/parser on free-form LLM output | Anthropic `tool_choice: {type:'tool',...}` | Forced tool-use is the SDK-supported correctness primitive. |
| JSON Schema emission from a typed schema | Hand-written JSON Schema files matching Zod types | `zod-to-json-schema` | One source of truth prevents drift. |
| Per-field confidence calibration | Heuristic confidence from string-similarity scores | LLM-emitted `_confidence: Record<string, number>` graded against farmer YES/NO/EDIT via Brier/ECE | The model is the only entity with enough context to score its own per-field uncertainty. |
| Schema validation | `typeof`/`in`/JSON.parse + manual asserts | `Draft.safeParse(toolUse.input)` | Zod's emit-error-issues path feeds the retry-loop directly. |
| Image downscale | Custom GraphicsMagick command | Recommend `sharp` (npm) at ≤1568px long edge | Anthropic's vision recommends ≤1568px to stay near 1.6K tokens/image. [CITED: docs.anthropic.com/en/docs/build-with-claude/vision] |
| Prompt caching | Custom in-process cache | Anthropic `cache_control: { type: 'ephemeral' }` on static system + few-shot blocks | 5-min server-side cache; observable via `usage.cache_read_input_tokens`. [CITED: docs.anthropic.com/en/docs/build-with-claude/prompt-caching] |
| Eval framework | Promptfoo / RAGAS / Phoenix | Custom jest harness in same package | Locked in AI-SPEC §5. |

**Key insight:** Phase 38's hard problems are (a) schema fidelity (solved by tool-use + Zod) and (b) a DB-backed state machine (solved by `signal_draft` rows). Any framework that adds memory/abstraction beyond that is solving a problem we don't have.

## Common Pitfalls

### Pitfall 1: Anthropic accepts a SUBSET of JSON-Schema draft-7
**What goes wrong:** `$ref`, `allOf`, exotic `format` keywords, and some `oneOf` shapes are rejected at request-time with 400.
**Why it happens:** Anthropic's input_schema validator predates current JSON-Schema specs; it's a curated subset.
**How to avoid:** Pass `{ target: 'jsonSchema7', $refStrategy: 'none' }` to `zodToJsonSchema` so everything is inlined. Add a CI unit test that does a `client.messages.countTokens(...)` dry-call against the emitted schema — fails closed on Anthropic API rejection. [CITED: AI-SPEC §3 pitfall 1]
**Warning signs:** 400 at `messages.create` mentioning `input_schema`. Run-time, not compile-time.

### Pitfall 2: `tool_use.input` is NOT guaranteed to be Zod-valid
**What goes wrong:** Anthropic's `input_schema` is a hint to the model, not a hard contract. The model occasionally emits extra fields, missing required fields, or wrong types.
**Why it happens:** Tool-use is a soft-constraint mechanism, not a hard parser. Confidence is high (~99%) but not 100%.
**How to avoid:** ALWAYS `Draft.safeParse(toolUse.input)` after extracting. On failure, retry **exactly once** via a `tool_result` content block with `is_error: true` and the Zod issues string. Second failure → `needs_review` + write issues to `audit_jsonb`. [CITED: AI-SPEC §4b]

### Pitfall 3: Image-token cost balloons silently on large photos
**What goes wrong:** A 4032×3024 phone photo is ~3500 tokens AND a base64 payload over a megabyte; eval cost on 73 photos × multiple turns is the difference between $5 and $30 per run.
**Why it happens:** Anthropic charges per image-tile; larger images = more tiles.
**How to avoid:** Downscale to ≤1568px long-edge before base64 encoding. Cache the downscaled bytes in `signal_capture.attachment_paths`'s same directory (e.g. `<file>.scaled.jpg`). Include the image on extraction turn 1 ONLY; on ask-back turns use the model-emitted caption stored in `signal_draft.image_caption`. [CITED: AI-SPEC §4 Context Window Strategy]

### Pitfall 4: Prompt cache misses on per-message interpolation
**What goes wrong:** `cache_control: { type: 'ephemeral' }` keys on exact byte content. If we interpolate the farmer name / current timestamp / capture id into the system block, every call is a cache miss and the ~$0.03/draft saving evaporates.
**Why it happens:** Server-side cache is byte-exact.
**How to avoid:** Keep `prompts/system.js` and `prompts/few-shot.js` literally static. All per-message context goes in the `user` message block. Verify cache-hit on each call by reading `msg.usage.cache_read_input_tokens > 0`. [CITED: AI-SPEC §4b Cost section]

### Pitfall 5: Signal-cli rebuild breaks identity trust (Phase 39 future-impact)
**What goes wrong:** Tearing down + rebuilding the signal-cli container can wipe the trust DB; subsequent receive 400s.
**Why it happens:** Captured per memory `project_signal_cli_rebuild_breaks_trust` and `feedback_bridge_signal_cli_network_path`.
**How to avoid in Phase 38:** When Phase 38 plans deploy a docker-compose rebuild of the alerter (which it WILL — new deps), it must NOT rebuild `signal-cli` simultaneously. The alerter `build:` block targets `./src/agents/alerter`; `signal-cli` is a separate service. The healthcheck at `docker-compose.override.yml:120` runs `post-rebuild-trust-check.sh` after alerter rebuilds — verify it stays green during Phase 38 rollout. **(Flag for Phase 39 — they'll handle the bidirectional receive path.)**

### Pitfall 6: `host.docker.internal` resolution for Whisper but `timescale` is compose-network
**What goes wrong:** Phase 38 may need to read attachments from disk that are mounted at `/data/signal-capture/...`. Mixing host-network reads with compose-network DB reads is fine BUT new code must not assume `host.docker.internal` resolves DB endpoints.
**Why it happens:** Per `config.js:96` — `TIMESCALE_HOST=timescale` resolves via compose default network; Whisper uses `host.docker.internal:8090`. Both correct.
**How to avoid:** Reuse the existing `config.load()` pool injection pattern — never construct new endpoints in the extraction module.

### Pitfall 7: ROS2 launch + systemd Restart=on-failure trap (orthogonal but a project landmine)
**What goes wrong:** Not directly relevant to Phase 38 (the alerter is a Node container, not a ROS2 unit), but flagged because alerter restart policy is `unless-stopped` per compose override.
**How to avoid:** Verify alerter restart works after an LLM-call hang (cf. SDK timeout pitfall in AI-SPEC §4b — `timeout: 60_000` is mandatory).

## Runtime State Inventory

Phase 38 is a NEW-feature / additive phase, not a rename or refactor. Runtime state changes:

| Category | Items | Action Required |
|----------|-------|------------------|
| Stored data | NEW `signal_draft` table in Timescale `postgres` DB | Add `initDb` in new `extraction-db.js`; runs at alerter boot. |
| Live service config | NEW alerter env vars: `EXTRACTION_CONFIDENCE_THRESHOLD`, `DRAFT_IDLE_GAP_MIN`, `MAX_ASKBACK_TURNS`, `MUSHDATADUMP_DIR` (eval only) | Add to `docker-compose.override.yml` alerter `environment:` block. Default values in `config.js`. |
| OS-registered state | None | — |
| Secrets/env vars | Reuse existing `ANTHROPIC_API_KEY` (already wired). No new secrets. | None — verified by reading `docker-compose.override.yml:107`. |
| Build artifacts | `npm install` adds `zod` + `zod-to-json-schema` to `package-lock.json`; alerter container must rebuild | `docker compose up -d --build alerter` post-merge. |

## Per-log-type Required-Field Map

Derived from the LOCKED B7 + C1–C5 conventions in `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md` [VERIFIED: read file]. The "required" column is what the Phase 38 schema enforces; "ask-back trigger" lists which fields require special D-03 ask-back if unresolved.

| log_type | name (when applicable) | Required fields | Notes |
|----------|-----------------------|-----------------|-------|
| `seeding` | — | `species`, `block_name` (B5), `qty`, `event_timestamp`, `parent_batch_name` (lineage C4) | Substrate is optional field on the block asset, not on the log. |
| `activity` | `sterilize` | `event_timestamp`, `target_batch_name` (or anonymous count), `qty` | Pre-individuation (C3). |
| `activity` | `sterilize_failed` | `event_timestamp`, `target_batch_name`, `reason` (free text) | Distinct from `contam`; recoverable. |
| `activity` | `water` | `event_timestamp`, `target_block_names[]` (≥1) | New event type (not previously tracked on paper). |
| `activity` | `relocate` | `event_timestamp`, `target_block_names[]`, `new_location` | Only on chamber/location change. |
| `activity` | `cold_shock` | `event_timestamp`, `target_block_names[]` | The fruiting-stage trigger (C1). |
| `activity` | `archive_spent` | `event_timestamp`, `target_block_names[]` | Terminal stage. |
| `activity` | `contam` | `event_timestamp`, `target_block_names[]`, `contam_type` (optional) | Distinct from `sterilize_failed`. |
| `input` | — | `event_timestamp`, `target_batch_name OR target_block_names[]`, `input_lot_id`, `qty` | Recipe lot consumption. |
| `observation` | — | `event_timestamp`, `target_block_names[]`, `note OR photo_ref` | Used for stage state-checks + pin emergence + photos. NEVER writes `asset.stage` (C1). |
| `harvest` | — | `event_timestamp`, `parent_block_names[]` (≥1; multi-parent C4), `qty_grams`, `grade` (optional: A/B/discard) | Multi-parent required for EXT-05. |

**Asset draft schemas (B1–B4)** are only emitted on inoculation (block-create as side-effect of `seeding`), bagging (bag-create), or first-time QR bind. Phase 38 emits asset DRAFT shapes; Phase 40 commits.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `@anthropic-ai/sdk` | extractor | ✓ | 0.91.1 | — |
| Anthropic API connectivity | extractor at runtime + eval | Assumed ✓ (used by Phase 25 LLM client) | n/a | Degraded-path reply ("I will get back to you on this one") |
| Whisper service | upstream (transcripts already on `signal_capture.transcript`) | ✓ | host.docker.internal:8090 | Phase 25 already handles degradation |
| Timescale | persistence | ✓ | resolves via compose default network at `timescale` | None — required |
| `/mnt/mossrock/shared/mushdatadump/` (NFS) | eval harness only | ✓ | 73 JPEGs + `mushroom_log.csv` ground truth | Eval cannot run without it; planner must mount during dev |
| Production logs corpus | secondary advisory eval | ⚠️ PARTIAL | Only 1 day found: `/mnt/slime-kingdom/data/signal-capture/2026-04-28/` (~5 files: 1 wav, 2 aac, 2 jpg; 1.3MB total) | Use this small set as advisory smoke-test; do NOT gate on it; flag for Don Santiago to surface larger corpus if it exists |
| Node 18+ (for `fetch`, `AbortController`) | extractor + Whisper client | ✓ (alerter container) | n/a | — |
| `sharp` (image downscale) | multimodal.js | ✗ | — | Recommended add OR use `@anthropic-ai/sdk`'s native image-sizing OR offload to client-side downscale at capture time (Phase 25 already saves attachments; could add a downscale-on-write hook there but that's scope creep). RECOMMEND: add `sharp` to alerter deps. |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** `sharp` for downscaling — could ship without it (send original photos at ~3500 tokens each), eat the cost. RECOMMEND adding it; it's a single npm dep with a wheel for the alerter's Linux base.

**Production logs corpus finding:** Don Santiago indicated "real production logs exist beyond mushdatadump." Filesystem search found ONLY `/mnt/slime-kingdom/data/signal-capture/2026-04-28/` (2026-04-28, 5 files, 1.3MB — 2 jpg + 2 aac + 1 wav). No `~/mushroom_farm_ws/`-rooted backups, no `signal-capture-archive`, no monthly directories beyond that one. **Flag for Don Santiago to confirm path** if a richer corpus exists elsewhere (Signal phone backup? Different mount?). The mushdatadump set (73 JPEGs + CSV) remains the primary ship-gate; this finding does not block planning.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | jest ^29.7.0 (already installed) |
| Config file | `src/agents/alerter/jest.config.js` (existing) + new `test/eval/extraction/jest.config.js` (eval-specific: `runInBand`, `testTimeout: 600000`) |
| Quick run command | `cd src/agents/alerter && npm test -- test/extraction/` |
| Full suite command | `cd src/agents/alerter && npm test` |
| Eval command | `cd src/agents/alerter && npm run eval:extraction` (new script) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXT-01 | Schema-conformant JSON-mode output | unit + eval | `npm test -- test/extraction/schemas.test.js` + `npm run eval:extraction` | ❌ Wave 0 |
| EXT-01 | Off-schema field rejected | unit | `npm test -- test/extraction/validator.test.js -t "off-schema"` | ❌ Wave 0 |
| EXT-02 | B5 regex enforcement | unit | `npm test -- test/extraction/schemas.test.js -t "B5 block_name"` | ❌ Wave 0 |
| EXT-02 | Ask-back on ambiguous SEQ | eval | `npm run eval:extraction` (dimension 2 + 7) | ❌ Wave 0 |
| EXT-03 | One multimodal capture → one draft | unit + eval | `npm test -- test/extraction/extractor.test.js -t "fusion"` + eval dim 8 | ❌ Wave 0 |
| EXT-04 | Confidence-aware ask-back fires | unit | `npm test -- test/extraction/state-machine.test.js -t "ask-back trigger"` | ❌ Wave 0 |
| EXT-04 | 3-turn cap → needs_review | unit | `npm test -- test/extraction/state-machine.test.js -t "3-turn cap"` | ❌ Wave 0 |
| EXT-05 | Multi-parent harvest extraction | unit + eval | `npm test -- test/extraction/schemas.test.js -t "harvest lineage"` + eval dim 4 | ❌ Wave 0 |
| Cross-cutting | Em-dash + float sweep on outbound | unit | `npm test -- test/extraction/sanitize.test.js` | ❌ Wave 0 |
| D-07 ship-gate | mushdatadump pass bar | offline gate | `npm run eval:extraction` writes `38-EVAL-REPORT.md` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `npm test -- test/extraction/` (unit suite; <30s).
- **Per wave merge:** `npm test` (full alerter suite).
- **Phase gate (before /gsd:summarize-phase 38):** `npm run eval:extraction` against mushdatadump; report green at D-07 bar.

### Wave 0 Gaps

- [ ] `test/extraction/schemas.test.js` — Zod schema round-trip + B5 regex + discriminated-union exhaustiveness
- [ ] `test/extraction/extractor.test.js` — orchestration (continuity → extract → state)
- [ ] `test/extraction/state-machine.test.js` — status transitions, 30min cap, 3-turn cap
- [ ] `test/extraction/multimodal.test.js` — image downscale + base64 builder
- [ ] `test/extraction/sanitize.test.js` — em-dash + float sweep enforcement
- [ ] `test/extraction/extraction-db.test.js` — signal_draft CRUD + partial-unique index behavior
- [ ] `test/eval/extraction/jest.config.js` — separate config (long timeout, runInBand)
- [ ] `test/eval/extraction/mushdatadump.test.js` — load fixtures + run scoring
- [ ] `test/eval/extraction/scoring.js` — Brier/ECE/set-equality helpers
- [ ] `test/eval/extraction/fixtures/` symlink or env-var pointer to `/mnt/mossrock/shared/mushdatadump`
- [ ] `package.json`: add `"eval:extraction": "jest --config test/eval/extraction/jest.config.js --runInBand"`

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Inbound is from already-routed Signal capture (Phase 37 sender→farmer resolution); outbound writes are Phase 40's concern. |
| V3 Session Management | partial | DB-resident draft "sessions" — partial-unique index enforces one-in-flight-per-sender invariant; 30min idle expiry is the session timeout. |
| V4 Access Control | no | farmOS write authz is Phase 40. |
| V5 Input Validation | **YES** | Zod `Draft.safeParse(toolUse.input)` — the core defense against LLM-emitted off-schema fields. Plus a regex sweep on outbound farmer-facing strings (em-dash + float-soup) per memory `feedback_no_em_dashes_in_artifacts`. |
| V6 Cryptography | no | `ANTHROPIC_API_KEY` handled via existing env injection path; never logged (existing pattern). Draft id is SHA-256 — that's identity, not crypto. |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via Signal message body | Tampering | LLM `tool_choice` forces JSON output shape; off-schema keys rejected by Zod. Attacker can't escape the schema. |
| Confidential-data leakage via LLM call | Information Disclosure | System prompt + few-shot are static, no farmer PII beyond what they sent. Anthropic API contract assumed. |
| Run-away ask-back loop | DoS | D-05 hard 3-turn cap + per-sender concurrency invariant. |
| Run-away LLM spend | (financial) | Per-draft `max_tokens: 1500` cap; AI-SPEC §7 alert threshold at $10/day spend. |
| Off-schema field injection by farmer | Tampering of downstream farmOS data | Zod runtime validation = defense-in-depth past Anthropic's input_schema hint. |
| Em-dash/float-soup leakage to farmer | Trust erosion (not classic STRIDE) | Mandatory `sanitize.js` sweep on every outbound Signal string. |

## Code Examples

### Anthropic Multi-Turn with `tool_result` for Schema-Validation Retry

```js
// Source: AI-SPEC §4b + docs.anthropic.com/en/docs/build-with-claude/tool-use [CITED]
async function extractWithRetry({ systemPrompt, userBlocks, priorTry, client, inputSchema }) {
  const repairMessages = [
    { role: 'user', content: userBlocks },
    {
      role: 'assistant',
      content: [{ type: 'tool_use', id: priorTry.tool_use_id, name: 'submit_extraction', input: priorTry.raw }],
    },
    {
      role: 'user',
      content: [{
        type: 'tool_result',
        tool_use_id: priorTry.tool_use_id,
        is_error: true,
        content: `Your previous output failed schema validation. Issues: ${JSON.stringify(priorTry.issues)}. Re-emit submit_extraction with corrections.`,
      }],
    },
  ];
  const msg = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 1500,
    temperature: 0,
    system: systemPrompt,
    tools: [{ name: 'submit_extraction', description: '...', input_schema: inputSchema }],
    tool_choice: { type: 'tool', name: 'submit_extraction' },
    messages: repairMessages,
  });
  // Re-validate; on second failure write audit + needs_review.
}
```

### Ask-back as a STATELESS RE-EXTRACT (research recommendation — see Q1 below)

```js
// Source: research recommendation; SIMPLER than threading tool_result through multi-turn.
// Each ask-back turn is a fresh extraction call with draftCtx in user message.
async function handleAskBackReply({ farmerReply, inFlightDraft, captureRow }) {
  const userBlocks = await multimodal.buildUserBlocks({
    captureRow,
    draftCtx: inFlightDraft, // includes prior draft + [?]-marked fields the farmer is answering
  });
  // Same extract() call; NO tool_result threading — the draft itself carries continuity.
  const result = await extract({ systemPrompt: SYSTEM, userBlocks, draftCtx: inFlightDraft });
  // ... merge into existing draft id (D-02a is replay-safe).
}
```

### Prompt Caching for System + Few-Shot

```js
// Source: docs.anthropic.com/en/docs/build-with-claude/prompt-caching [CITED]
const msg = await client.messages.create({
  model: 'claude-sonnet-4-6',
  max_tokens: 1500,
  temperature: 0,
  system: [
    { type: 'text', text: SYSTEM_PROMPT, cache_control: { type: 'ephemeral' } },
    { type: 'text', text: FEW_SHOT_BLOCK, cache_control: { type: 'ephemeral' } },
  ],
  tools: [/* ... */],
  tool_choice: { type: 'tool', name: 'submit_extraction' },
  messages: [{ role: 'user', content: userBlocks }],
});
// Verify cache hit:
console.log({ cache_read: msg.usage.cache_read_input_tokens });
```

### Multimodal Content Block Builder

```js
// Source: AI-SPEC §3 + docs.anthropic.com/en/docs/build-with-claude/vision [CITED]
const fs = require('fs/promises');
const sharp = require('sharp'); // RECOMMEND adding

async function buildImageBlock(absPath) {
  // Downscale to ≤1568 long-edge per Anthropic vision recommendation.
  const buf = await sharp(absPath).resize({ width: 1568, height: 1568, fit: 'inside', withoutEnlargement: true }).jpeg({ quality: 85 }).toBuffer();
  return {
    type: 'image',
    source: { type: 'base64', media_type: 'image/jpeg', data: buf.toString('base64') },
  };
}

async function buildUserBlocks({ captureRow, draftCtx }) {
  const blocks = [];
  blocks.push({ type: 'text', text: `Inbound from ${captureRow.farmos_person} at ${captureRow.captured_at}` });
  if (captureRow.raw_text) blocks.push({ type: 'text', text: `Text: ${captureRow.raw_text}` });
  if (captureRow.transcript) blocks.push({ type: 'text', text: `[voice transcript] ${captureRow.transcript}` });
  for (const p of captureRow.attachment_paths || []) {
    if (/\.(jpg|jpeg|png)$/i.test(p)) blocks.push(await buildImageBlock(p));
  }
  if (draftCtx) blocks.push({ type: 'text', text: `[in-flight draft]\n${draftCtx.farmer_facing_preview}` });
  blocks.push({ type: 'text', text: 'Call submit_extraction now.' });
  return blocks;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `response_format: { type: 'json_object' }` (OpenAI-style) free-form JSON | Anthropic `tool_choice: { type: 'tool', name }` forced tool-use | Anthropic SDK 0.20+ matured tool-use as primary structured-output primitive | Eliminates JSON-parse failures; schema is server-enforced. |
| LangChain.js / LangGraph for orchestration | Direct SDK + DB-resident state | Recognised in AI-SPEC §2 anti-pattern | Less code, no abstraction tax, easier to debug at the wire. |
| Hand-written JSON Schema | Zod + `zod-to-json-schema` | Cross-ecosystem trend 2024-2025 | One source of truth; compile-time + runtime types. |
| `response.content[0].text` parsing | `response.content.find(b => b.type === 'tool_use')` | Required when `tool_choice` forces tool-use | The most common Phase 38 footgun. [VERIFIED: read `llm-client.js:66` uses the old single-text pattern; new extractor must NOT.] |

**Deprecated/outdated:**
- Reading `msg.content[0].text` after forcing tool_use (AI-SPEC §3 pitfall 2).
- Pydantic in JS land — Zod is the canonical equivalent and what zod-to-json-schema is built for.

## Specific Research Question Answers

### Q1: Anthropic tool-use multi-turn for ask-back — stateless re-extract vs. multi-turn thread

**Finding:** Anthropic's multi-turn tool-use is documented as: after a `tool_use` assistant message, the NEXT user message must include a `tool_result` block referencing `tool_use_id`. Subsequent turns can chain naturally.

**Recommendation: STATELESS RE-EXTRACT for ask-back.** Reasons:
1. **D-02a determinism (replay-safe draft id).** A re-extract on every farmer reply, with the prior draft included as user-message text (`[in-flight draft]\n<preview>`), keeps each call self-contained. The draft id is hash-deterministic so the same capture set produces the same draft regardless of how many ask-back turns it took.
2. **Cache hit rate.** The static system + few-shot stays identical across turns and gets the `cache_control: ephemeral` benefit. Threading multi-turn with a growing `messages` array breaks the cache key on every turn.
3. **No tangled tool_result history.** Multi-turn `tool_result` is the right pattern for AGENT loops (call tool → see result → call again) but NOT for ask-back where each farmer reply is a fresh user input, not a tool-execution result.
4. **Failure isolation.** A bad continuity decision on turn 2 doesn't poison turn 3's context.

**Use `tool_result` ONLY for the single Zod-validation retry** (AI-SPEC §4b already locks this). That's a tight loop within one extraction call: tool_use → tool_result with `is_error: true` + Zod issues → retry the same call. Never carry that history into the next farmer turn.

[CITED: docs.anthropic.com/en/docs/build-with-claude/tool-use/overview — tool_result spec]
[ASSUMED] — the recommendation between stateless-re-extract vs multi-turn is engineering judgment, not vendor-prescribed; document this decision in the plan so it's visible to discuss-phase.

### Q2: Anthropic input_schema JSON-Schema subset

**Confirmed accepted (per Anthropic tool-use docs + community usage):**
- `type` ∈ {`object`, `array`, `string`, `number`, `integer`, `boolean`, `null`}
- `properties`, `required`, `additionalProperties`
- `enum`, `const`
- `items` (for arrays)
- `description` (heavily used — model reads these)
- `minLength`, `maxLength`, `pattern` (for strings)
- `minimum`, `maximum`, `multipleOf` (for numbers)
- `minItems`, `maxItems`, `uniqueItems` (for arrays)

**Empirically problematic (multiple community reports):**
- `$ref` — works when local-inline-only but `$refStrategy: 'none'` is safer.
- `allOf` — accepted but with quirks; avoid where possible.
- `oneOf` / `anyOf` — accepted in CURRENT API versions; this is what `z.discriminatedUnion` emits. Reports from 2024 of issues are mostly resolved on current model versions but the planner should add a CI smoke-test that does a `messages.countTokens` dry-call on the actual emitted schema.
- `format` keywords (`date-time`, `email`, etc.) — silently ignored by Anthropic (model doesn't enforce); not 400. Zod `.datetime()` emits `format: 'date-time'` — keep it, but understand it's purely advisory to the model. Real validation is on the post-call Zod parse.
- `discriminator` (OpenAPI extension) — NOT a standard JSON-Schema keyword; `zod-to-json-schema` doesn't emit it. `oneOf` over a literal-tagged `log_type` is the equivalent and that's what `z.discriminatedUnion` emits.

**Bottom line:** `z.discriminatedUnion('log_type', [...])` SHOULD round-trip cleanly with `{ target: 'jsonSchema7', $refStrategy: 'none' }`. The `ajv` fallback path in AI-SPEC §2 is defense-in-depth, not expected need.

[ASSUMED — based on community reports + Anthropic tool-use docs; CONFIRM with a `countTokens` dry-call in Wave 0 unit test.]

### Q3: Anthropic multimodal image-block size + cost

- **Max size:** 5MB per image; max ~20 images per request. [CITED: docs.anthropic.com/en/docs/build-with-claude/vision]
- **Recommended max dimension:** 1568px long-edge (Anthropic's vision guide). Larger images = more tiles = more tokens.
- **Token cost:** A 1568×1568 image is ~1568 tokens; a 4032×3024 phone photo is ~3500 tokens. [CITED: Anthropic vision pricing docs]
- **Encoding:** base64 inline (`{type:'image', source:{type:'base64', media_type, data}}`) OR URL (Anthropic fetches). Inline is simpler for Phase 38 because attachments live at filesystem paths inside the alerter container; URL would require exposing them via the bridge.
- **Economy path:** Downscale + JPEG quality 85 with `sharp`. Median Signal photo (~1MB original) → ~150KB encoded, ~1600 tokens.
- **Mushdatadump eval cost estimate:** 73 JPEGs × downscaled ~1.6K tokens each × 1 extraction turn + ~0.5 ask-back turn avg × ~9K input/turn × Sonnet 4.6 cached at $0.30/MTok input + uncached portions at $3/MTok + $15/MTok output → **~$3–5 per full eval run with prompt caching**, ~$15 without. AI-SPEC §4b estimates the same.

### Q4: Anthropic prompt caching for system + few-shot

- **Mechanism:** `cache_control: { type: 'ephemeral' }` on individual content blocks within `system` (and other places). 5-minute ephemeral cache; first request seeds, subsequent within 5min reads at ~10× discount.
- **Cache key:** exact byte content of the cached block AND all blocks before it in the request. So `system` cache hits on every call as long as system bytes are identical.
- **Verification:** `msg.usage.cache_read_input_tokens > 0` on response.
- **Phase 38 setup:** Mark the system prompt + few-shot block (both static) as `cache_control: ephemeral`. The user message changes per call; that's fine — the cache only covers content up to and including the last `cache_control` marker.
- **Eval savings:** mushdatadump = 73 cases × ~2 turns each = ~150 calls within a few minutes → ~149 cache hits → ~50% cost reduction (AI-SPEC §4b confirms ~$5 cached vs $15 uncached).

[CITED: docs.anthropic.com/en/docs/build-with-claude/prompt-caching]

### Q5: Zod → JSON Schema round-trip

**`zod-to-json-schema` v3.24.x findings:**
- **Discriminated unions:** Emits a `oneOf` with each variant including the literal-typed discriminator property. ✓ Round-trips cleanly with Anthropic per Q2 — assuming current model versions.
- **Nested optional fields:** Emit `required: [...]` excluding the optional keys. ✓ Standard draft-7.
- **`.describe()` annotations:** Emitted as `description: '...'` in the JSON Schema. ✓ Model reads these — use heavily.
- **`z.record(z.string(), z.number())`:** Emits `{ type: 'object', additionalProperties: { type: 'number' } }`. ✓ This is how the `_confidence` per-field map is encoded. Anthropic accepts `additionalProperties` patterns.
- **Recommended config:** `{ target: 'jsonSchema7', $refStrategy: 'none' }` — confirmed in AI-SPEC §3 entry-point pattern. `$refStrategy: 'none'` inlines reused subschemas, avoiding `$ref` rejection risk.
- **Known issue (zod-to-json-schema GH):** `z.date()` emits non-standard JSON Schema. Use `z.string().datetime()` for ISO-8601 (which is what AI-SPEC § does).
- **Known issue:** `z.union([z.literal('a'), z.literal('b')])` emits `oneOf: [{const:'a'},{const:'b'}]`; cleaner is `z.enum(['a','b'])` → `enum: ['a','b']`. Prefer `z.enum` where applicable.

[CITED: npmjs.com/package/zod-to-json-schema + zod-to-json-schema GitHub issue tracker (general knowledge through Jan 2026 cutoff)]

### Q6: Production logs corpus

**Searched paths:**
- `/mnt/mossrock/shared/` — only `mushdatadump/` (the ship-gate set) + farmos repo + unrelated dirs (movies, plunge, popi, grants).
- `/mnt/slime-kingdom/shared/` — same listing (this mount point shares the same FS or is mirrored).
- `/mnt/slime-kingdom/data/signal-capture/` — **ONE day of capture**: `2026-04-28/` containing 5 files (2 .jpg, 2 .aac, 1 .wav), total 1.3MB. This is presumably the result of a single capture-pipeline test session. [VERIFIED: `find` + `du` + `ls`]
- `/mnt/slime-kingdom/data/timelapse/`, `snapshots/`, `snapshots-burnt/` — chamber camera frames, not farmer-message material.
- No directories matching `*signal-archive*`, `*farmer-logs*`, `*inoc-recordings*`, `2025-*`, etc.

**Finding:** Only the single 2026-04-28 directory + the mushdatadump v1.6 set are available. The `project_phase38_production_logs_available` memory reference may have been aspirational or pointed to a corpus not yet copied to NFS.

**Action:** **Flag for Don Santiago to confirm path.** Recommend planner explicitly de-scope the secondary corpus as "small smoke-test only" — use the 5 files in `/mnt/slime-kingdom/data/signal-capture/2026-04-28/` as an end-to-end pipeline smoke (capture row → extraction → draft) but DO NOT include in the D-07 ship-gate. mushdatadump v1.6 remains the locked ship-gate per D-06/D-07.

[VERIFIED: filesystem search 2026-05-12]

### Q7: Existing `signal_capture` schema

**Columns (from `capture-db.js` lines 7–34) [VERIFIED: read file]:**

```
id              text PRIMARY KEY      -- ULID
captured_at     timestamptz NOT NULL DEFAULT now()
sender          text NOT NULL         -- E.164 number
message_type    text NOT NULL         -- 'text' | 'voice' | 'image' | mixed
raw_text        text                  -- nullable
attachment_paths text[] NOT NULL DEFAULT ARRAY[]::text[]
transcript      text                  -- Whisper output, nullable
llm_session_tag text                  -- Phase 25 ack tag, nullable
llm_reply       text                  -- Phase 25 reply, nullable
degraded        boolean NOT NULL DEFAULT false
expired         boolean NOT NULL DEFAULT false
-- Phase 37 additions (idempotent ADD COLUMN IF NOT EXISTS):
group_id           text   -- nullable
farmos_person      text   -- nullable; Phase 37 sender→farmer slug map
reply_target_kind  text   -- nullable; 'dm' | 'group'
```

**Indexes:**
- `idx_signal_capture_sender_time` on `(sender, captured_at DESC)`
- `idx_signal_capture_expired` on `(expired) WHERE expired = false`

**Recommended `signal_draft` schema (NEW — Phase 38 D-02 + D-02a..c):**

```sql
CREATE TABLE IF NOT EXISTS signal_draft (
  id                     text PRIMARY KEY,              -- sha256(sort(source_capture_ids).join(','))
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  sender_e164            text NOT NULL,                 -- denormalised from first capture for partial-unique index
  farmos_person          text,                          -- denormalised; first capture's farmos_person
  source_capture_ids     text[] NOT NULL,               -- FK array → signal_capture.id (not a real PG FK array — enforced by app)
  log_type               text NOT NULL,                 -- 'seeding' | 'activity' | 'input' | 'observation' | 'harvest'
  activity_name          text,                          -- only when log_type='activity'
  draft_jsonb            jsonb NOT NULL,                -- validated Zod-emitted payload
  confidence_jsonb       jsonb NOT NULL,                -- {field: 0..1} mirror
  status                 text NOT NULL,                 -- 'pending'|'awaiting_farmer'|'confirmed'|'discarded'|'needs_review'|'expired'|'committed'
  ask_back_turns         int  NOT NULL DEFAULT 0,
  farmer_facing_preview  text,                          -- post-sanitize [?]-annotated render
  image_caption          text,                          -- LLM-emitted on turn 1 for ask-back reuse
  audit_jsonb            jsonb NOT NULL DEFAULT '{}'::jsonb,  -- continuity decisions, zod issues on retry, style violations
  expired_at             timestamptz                    -- when status='expired'
);

-- D-02c per-sender concurrency invariant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_draft_inflight_per_sender
  ON signal_draft (sender_e164)
  WHERE status IN ('pending', 'awaiting_farmer');

CREATE INDEX IF NOT EXISTS idx_signal_draft_status
  ON signal_draft (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_draft_farmos_person_time
  ON signal_draft (farmos_person, created_at DESC);
```

### Q8: Per-log-type required-field map

See `## Per-log-type Required-Field Map` table above. [VERIFIED: read 2026-05-11 session-chat.md lines 32–47 + 83–98]

### Q9: fmtNum + em-dash sweep utility

**Existing `message.js:fmtNum` [VERIFIED: read file]:**

```js
function fmtNum(n) {
  if (n == null || Number.isNaN(Number(n))) return '?';
  return String(+Number(n).toFixed(1));
}
```

Already handles: 1-decimal rounding, strip trailing `.0`, null/NaN → `?`. No em-dash logic — the file uses em-dashes itself in commentary, which is fine (dev artifact).

**Recommendation:** Create a NEW helper `extraction/sanitize.js` that COMPOSES `message.fmtNum`:

```js
const { fmtNum } = require('../message'); // re-export the existing helper

const EM_DASHES = /[—–]/g; // em-dash + en-dash variants

function sanitizeFarmerFacing(text) {
  return text.replace(EM_DASHES, '?');
}

function fmtFloat(n) {
  return fmtNum(n); // reuse existing
}

function checkClean(text) {
  if (EM_DASHES.test(text)) return { clean: false, reason: 'em-dash' };
  if (/\d+\.\d{2,}/.test(text)) return { clean: false, reason: 'float-soup' };
  return { clean: true };
}

module.exports = { sanitizeFarmerFacing, fmtFloat, checkClean };
```

Don't extend `message.js` itself — it's tied to alert-message formatting and adding extraction-specific helpers there muddies its purpose. The composition pattern respects Karpathy "surgical changes" guidance from CLAUDE.md.

### Q10: Logger — pino vs bunyan vs other

**[VERIFIED: read `index.js`]:** The alerter uses **plain `console`** as its logger (`createAlerter({ logger = console })`). Not pino, not bunyan. Log call shape is `logger.info('[area] message')` / `logger.warn(...)` / `logger.error(...)` — string-formatted, not structured-object.

AI-SPEC §7 mentions "the alerter today uses a pino-style JSON logger to stdout" — this is **not accurate**. Plan accordingly: the extraction module should call `logger.info(...)` / `logger.warn(...)` with the same string-formatted shape used elsewhere (`llm-client.js:70` uses `logger.warn(`[llm] degraded: ${e.message}`)`).

**For the structured-fields metric collection required by AI-SPEC §7,** Phase 38 needs to introduce a minimal structured log shape. Recommendation: keep the `console.log/info/warn/error` surface but log a JSON.stringify of the metric object alongside the human-readable line:

```js
logger.info(`[extract] draft=${draftId} latency=${latencyMs}ms tokens_in=${inputTokens} tokens_out=${outputTokens} cache_read=${cacheReadTokens}`);
logger.info(`[extract:metrics] ${JSON.stringify({ draft_id, sender_e164, farmos_person, n_input_tokens, n_output_tokens, n_cache_read_tokens, cost_estimate_usd, latency_ms, continuity_decision, per_field_confidence_min, schema_validation_result, ask_back_turn, log_type })}`);
```

The host journal already scrapes stdout per the existing operational pattern. **No new logger dependency.** Defer migration to pino to a future phase if metric tooling demands it.

### Q11: Docker compose deploy path for the alerter

**[VERIFIED: read docker-compose.override.yml lines 59–125]:**

- **Service name:** `alerter`
- **Build context:** `./src/agents/alerter` (the alerter package root); Dockerfile is at that path.
- **Networks:** `signal-net` (joins signal-cli) + `default` (joins timescale).
- **Volume mounts:** `/data/signal-capture:/data/signal-capture` (read+write), `./scripts/signal:/opt/scripts/signal:ro`.
- **Env injection point:** the `environment:` block at lines 71–113. New Phase 38 env vars (`EXTRACTION_CONFIDENCE_THRESHOLD`, `DRAFT_IDLE_GAP_MIN`, `MAX_ASKBACK_TURNS`, optionally `MUSHDATADUMP_DIR` for in-container eval runs) go here, following the `${VAR:-default}` pattern.
- **Healthcheck:** runs `post-rebuild-trust-check.sh` from the mounted scripts dir. Phase 38 should NOT alter this — it's identity-trust integrity post-rebuild (Phase 36 D-10/D-14).

**Rebuild command per CLAUDE.md pattern:** `docker compose up -d --build alerter`. The `--build` is mandatory per CLAUDE.md note ("compose pins build context but not the image tag; `up -d` alone reuses cached image"). Don't rebuild `signal-cli` simultaneously (preserves identity trust per Pitfall 5 above).

**Volume note for eval:** to run `npm run eval:extraction` inside the container, also need `/mnt/mossrock/shared/mushdatadump:/data/mushdatadump:ro` mounted. RECOMMEND: keep eval as host-side (run on elder-plops directly via `cd src/agents/alerter && npm run eval:extraction`) rather than baking the NFS mount into the alerter container.

### Q12: Jest test runner config + npm scripts

**[VERIFIED: read `jest.config.js` + `package.json`]:**

Existing `jest.config.js`:
```js
module.exports = {
  testEnvironment: 'node',
  testMatch: ['**/test/**/*.test.js'],
  testPathIgnorePatterns: ['/node_modules/', '/fixtures/', '/helpers/'],
  verbose: true,
  testTimeout: 10000,
};
```

Existing `package.json` scripts:
```json
"scripts": {
  "start": "node src/index.js",
  "test": "jest",
  "test:watch": "jest --watch"
}
```

**Phase 38 additions:**

1. New `test/eval/extraction/jest.config.js`:
   ```js
   module.exports = {
     testEnvironment: 'node',
     testMatch: ['<rootDir>/mushdatadump.test.js'],
     verbose: true,
     testTimeout: 600000, // 10min — full mushdatadump run
     rootDir: __dirname,
   };
   ```

2. New script:
   ```json
   "eval:extraction": "jest --config test/eval/extraction/jest.config.js --runInBand"
   ```

3. Existing `test:` glob already picks up `test/extraction/*.test.js` — no main jest config change needed. Verify the eval directory is excluded from default `npm test`: the existing `testMatch: ['**/test/**/*.test.js']` WILL include `test/eval/extraction/mushdatadump.test.js`. **Add an exclusion to `testPathIgnorePatterns`**: `'/eval/'`. This keeps `npm test` fast (unit only) and `npm run eval:extraction` runs the gate.

### Q13: Landmines from memories (Phase 38 — surface in plan checks)

| Memory | Phase 38 Application |
|--------|----------------------|
| `feedback_no_em_dashes_in_artifacts` | EVERY byte the farmer sees through Signal must pass `EM_DASHES` regex sweep. Enforced in `sanitize.js`; tested in `sanitize.test.js`. |
| `feedback_round_farmer_numbers` | Use `fmtNum()` for all numbers in farmer-facing strings. Validated by dimension 9 in eval harness. |
| `feedback_no_farmer_bookkeeping_tax` | NORTH-STAR. Ask-back-rate >30% sustained = NORTH-STAR violation; AI-SPEC §7 pages on it. Don't add data-entry tasks; this phase emits drafts the farmer just confirms. |
| `feedback_gap_over_noise` | When confidence is low, the system MUST gap (ask-back) rather than fill a wrong-looking field. Aligns with EXT-04. |
| `feedback_run_verifications_yourself` | Eval harness IS the verification — run it before declaring Wave done. Don't ping Don Santiago for a "looks fine?" check that the eval can answer. |
| `feedback_alerter_env_convention_bridge_http_url` | New env vars (`EXTRACTION_CONFIDENCE_THRESHOLD` etc.) follow the existing `${VAR:-default}` convention in compose override; defaults in `config.js`. |
| `project_signal_cli_rebuild_breaks_trust` | Phase 38 rebuild = alerter only. Never rebuild signal-cli at the same time. Phase 39 will need to handle this directly. **(Forward-flag for Phase 39 plan.)** |
| `feedback_no_coauthor` | Commits in this phase don't add Co-Authored-By trailers. |
| `project_farmer_phone_map` | Farmer slugs are lowercase first names (f1=santi, f2=vikki, f3=selina). Eval ground truth's farmer attribution must match. |
| `feedback_session_closeout_check` | Eval ship-gate happens BEFORE /gsd:summarize-phase 38. |
| `feedback_lean_discuss_sessions` | Already done — discuss-phase produced 38-CONTEXT.md with locked D-01..D-07; no further discussion required. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `z.discriminatedUnion` round-trips cleanly with Anthropic `input_schema` on current Sonnet 4.6 | Q2 + Q5 | Drop to AI-SPEC §2 fallback path (hand-authored schema + ajv). Wave 0 unit test with `countTokens` dry-call catches this. |
| A2 | Stateless re-extract is better than multi-turn `tool_result` threading for ask-back | Q1 | Engineering judgment; document in plan; revisit if eval shows cross-turn context loss. |
| A3 | Production logs corpus beyond mushdatadump is small or absent | Q6 + Env Availability | Eval ship-gate still locked to mushdatadump; advisory corpus is bonus only. Confirm with Don Santiago during plan-phase. |
| A4 | Alerter logger is plain `console`, not pino | Q10 + AI-SPEC §7 | If we migrate to pino later, the metric-line format is forward-compatible (JSON.stringify object). |
| A5 | `sharp` is the right downscale library; image-downscale belongs in alerter not Phase 25 capture | Don't Hand-Roll + Env Availability | If alerter container base lacks sharp's native dep, fall back to `@anthropic-ai/sdk`'s built-in handling OR shell out to `ffmpeg`. |
| A6 | Per-sender partial-unique index is correct for D-02c | Q7 schema | If concurrent INSERTs become a thing (>1 farmer message in same ms), the index raises; orchestrator must catch and retry. Tested in `extraction-db.test.js`. |
| A7 | Eval cost ~$5 cached / $15 uncached is acceptable per-PR in CI | AI-SPEC §4b + Q3 | If team finds this expensive, gate eval on PRs touching `extraction/**` paths only (already locked in AI-SPEC §5). |
| A8 | Production logs corpus mentioned in objective points to the missing/aspirational set, not the small 2026-04-28 directory | Q6 | LOW risk — if it's actually a richer set elsewhere, Don Santiago surfaces it during plan-phase and we extend the harness. |

## Open Questions

1. **Confidence threshold calibration on day 1.**
   - What we know: D-03 locks default 0.7 via `EXTRACTION_CONFIDENCE_THRESHOLD`. AI-SPEC §5 dimension 6 measures ECE.
   - What's unclear: Without running the eval against mushdatadump, we don't know whether 0.7 is well-calibrated. Could be 0.6 or 0.8 in practice.
   - Recommendation: ship with 0.7, treat first eval-run as a calibration baseline, iterate the threshold in the same Phase 38 cycle (it's env-tunable).

2. **Wave 0 sequencing: schemas vs prompts.**
   - What we know: Both are pre-requisites for the first extraction call.
   - What's unclear: Should schemas land before the system prompt is written (so prompt can reference the canonical field set), or simultaneously?
   - Recommendation: schemas FIRST (Wave 0 R1) — prompts in Wave 0 R2 reference the schemas via `.describe()` annotations.

3. **Does `signal_draft` need TimescaleDB hypertable semantics?**
   - What we know: `signal_capture` is a regular table per `capture-db.js` comment ("per-farmer volume too low for hypertable").
   - What's unclear: Drafts volume = same as capture (~1 row per inbound). Probably also regular table.
   - Recommendation: Regular table per the same volume argument. If retention becomes a concern (drafts piling up in `confirmed`/`committed` status), add a `markExpiredOlderThan` analog as in `capture-db.js:60`.

4. **Few-shot example sourcing for prompt.**
   - What we know: AI-SPEC §4b recommends 3–4 hand-picked mushdatadump examples.
   - What's unclear: Which exact cases. Picking the wrong few-shot biases the model.
   - Recommendation: Wave 0 R2 plan picks cases covering (a) pure-text inoc, (b) text+photo harvest, (c) voice-only with B5 block name, (d) multi-block harvest — same coverage AI-SPEC §4b suggests.

5. **Continuity decision: gate on `farmos_person` match?**
   - What we know: Current draft is keyed on `sender_e164` (D-02c). 
   - What's unclear: If a farmer logs in from a different number (rare), their in-flight draft from old number is invisible. AI-SPEC doesn't address.
   - Recommendation: Out of scope for v1.7 (single number per pilot farmer). Flag for v1.8 if pilot expands.

## Project Constraints (from CLAUDE.md)

- **ROS2 Jazzy workspace** — Phase 38 is Node.js (alerter), not ROS2. No `colcon build` involvement.
- **Compose deploy is `up -d --build`** — explicit rebuild flag mandatory; cached image trap is real.
- **`.env` at repo root holds `TIMESCALE_PASSWORD`, `CORS_ORIGIN`** — Phase 38 adds new env vars there.
- **Live compose is `/docker-compose.yml` + `/docker-compose.override.yml`** at repo root — alerter service definition lives in override.
- **`src/docker-compose.yml` is deprecated** — do not use for deploy.
- **Branch strategy** — main is the long-lived; commits to feature branch then merge.
- **Per-repo git email** — `santi@mossrock.space` for mushy.
- **No Co-Authored-By trailer.**

## Sources

### Primary (HIGH confidence)
- `38-CONTEXT.md` — Locked D-01..D-07 [VERIFIED: read]
- `38-AI-SPEC.md` — Locked framework + eval contract [VERIFIED: read]
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md` — Schema lock C1–C5 + B1–B7 + P1–P5 [VERIFIED: read]
- `src/agents/alerter/src/llm-client.js` [VERIFIED: read]
- `src/agents/alerter/src/capture-db.js` [VERIFIED: read]
- `src/agents/alerter/src/transcribe-client.js` [VERIFIED: read]
- `src/agents/alerter/src/message.js` [VERIFIED: read]
- `src/agents/alerter/src/config.js` [VERIFIED: read]
- `src/agents/alerter/package.json` [VERIFIED: read]
- `src/agents/alerter/jest.config.js` [VERIFIED: read]
- `docker-compose.override.yml` [VERIFIED: read]
- `node_modules/@anthropic-ai/sdk/package.json` (v0.91.1 confirmed) [VERIFIED: read]
- Filesystem state under `/mnt/mossrock/shared/` + `/mnt/slime-kingdom/data/signal-capture/` [VERIFIED: ls + find]

### Secondary (MEDIUM confidence — cited from AI-SPEC §3 source list)
- Anthropic Tool-use overview: https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview
- Anthropic Forcing tool use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use/implement-tool-use#forcing-tool-use
- Anthropic Vision: https://docs.anthropic.com/en/docs/build-with-claude/vision
- Anthropic Prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Zod Discriminated unions: https://zod.dev/?id=discriminated-unions
- zod-to-json-schema: https://www.npmjs.com/package/zod-to-json-schema

### Tertiary (LOW confidence — assumed from training data + community)
- Anthropic JSON-Schema subset specifics (Q2) — empirical from community reports; CONFIRM via `countTokens` Wave 0 test.
- `zod-to-json-schema` known issues (Q5) — recall from training, not verified against current GH issue tracker.

## Metadata

**Confidence breakdown:**
- Locked decisions + AI-SPEC: HIGH (read source artifacts directly)
- Codebase entry points: HIGH (read all referenced files)
- Anthropic API subset behavior: MEDIUM (cited docs + general knowledge; Q2 needs CI smoke-test)
- Production logs corpus availability: HIGH for what's found; LOW for what may exist elsewhere — flagged for Don Santiago
- Image cost math: MEDIUM (cited Anthropic docs + AI-SPEC §4b internal estimate)

**Research date:** 2026-05-12
**Valid until:** 2026-06-12 (Anthropic SDK + Zod versions stable; refresh if model pricing / Sonnet revision changes)
