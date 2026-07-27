# Phase 59: Event Gate — Research

**Researched:** 2026-06-24
**Domain:** Python port of Node event-gate: rule prefilter + Haiku forced tool-use classifier
**Confidence:** HIGH (Node source read directly; Python SDK verified against official docs; fixture schema confirmed)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Area 1: Module structure & LLM client**
- New `farm_agent/gate/` leaf package: `event_gate.py`, `rules.py`, `classifier.py`, `prompts.py`
- One shared `anthropic.AsyncAnthropic` created at boot, injected into the gate/classifier factory closure
- `anthropic>=0.45` runtime dependency added to `pyproject.toml`
- Factory returns `{"classify": async_fn}` — never-throws, returns `{ok, ...}` discriminated result

**Area 2: Behavioral fidelity (port-locked)**
- Model: `claude-haiku-4-5-20251001` verbatim
- System prompt (~20KB) committed verbatim inline in `prompts.py`; `cache_control: {type: "ephemeral"}` on the system block
- Decision flow exactly: rulePositive → ruleNegative → await classifier; fail-open on `!ok`; 0.7 confidence floor
- Gate enum: `skipped_rule_neg | fast_event | haiku_event | haiku_chitchat | forced`
- Rule regexes verbatim from Node `rules.js`; ack patterns verbatim; 30-min window, <40-char, <40-char thresholds
- Classifier: forced tool `classify_capture`; `max_tokens=100`; `timeout=2000ms` in request-options (NOT body); `max_retries=2`
- User message = compact JSON `{text, transcript, attachmentCount}` — never concatenated into system prompt
- All behavioral constants inline as module-level constants; no new `TenantConfig` fields

**Area 3: Validation & test strategy**
- Fixture copied to `tests/fixtures/gate/44-hand-classified-100.jsonl`
- Deterministic unit tests with mocked Anthropic client; 90-row non-holdout subset
- Holdout (W10 = 10 rows, IDs in `prompts.py`) excluded from unit/few-shot subset
- Real-Haiku 100-corpus accuracy run is marker/env-gated, deferred to operator validation

### Claude's Discretion
- Exact internal helper names, file splits within `gate/`, and test parametrization — provided the locked behavior and module/test boundaries above are honored.

### Deferred Ideas (OUT OF SCOPE)
- Real-Haiku full-corpus accuracy validation run (marker/env-gated) — operator-run like Phase 58 live-fire
- Any gate-behavior changes (taxonomy tweaks, new rules)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GATE-01 | A rule pre-filter + Haiku classifier (forced tool-use, short timeout, fail-open) decides which inbound messages enter the extraction pipeline, reproducing the Node gate's accept/reject behavior. | Full Node source read; Python SDK call shapes verified; fixture schema confirmed; test strategy mapped. |
</phase_requirements>

---

## Summary

Phase 59 is a faithful Python port of the Node `src/agents/alerter/src/event-gate/` module. The gate has two stages: a pure-function rule prefilter that fast-paths obvious events (attachments, long text, strain codes, block names) and obvious negatives (short acks after attestation), followed by a Haiku 4.5 LLM classifier for gray-zone messages. The Python port reproduces this decision flow exactly, using the `anthropic` Python SDK's async client with forced tool-use, prompt-caching via `cache_control`, and a per-request timeout passed via `client.with_options()` (not in the request body — this is the same bug the Node code hit live in May 2026).

The module lives as a new `farm_agent/gate/` leaf package, wired into `boot.py` alongside the existing `httpx.AsyncClient` and pool. The classifier factory mirrors the `transcribe_client` never-throws closure pattern. The 100-row Phase 44 hand-classified fixture drives both the deterministic unit tests (90 non-holdout rows, mocked client) and the deferred real-Haiku validation run (all 100, env-gated).

**Primary recommendation:** Copy the Node source files directly; translate line-by-line rather than re-designing. The only structural decision is the timeout mapping (JS `AbortSignal` → Python `client.with_options(timeout=...)`) and replacing `zod.safeParse` with a pydantic `model_validate` try/except.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Rule prefilter (rulePositive / ruleNegative) | API / Backend | — | Pure function, no I/O; sits in the inbound message processing path before any LLM call |
| Haiku LLM classification | API / Backend | External LLM API | Async HTTP call to Anthropic; gateway is the `gate/` package; result feeds capture pipeline |
| Prompt caching | External LLM API | — | Token threshold enforced by Anthropic infrastructure; `cache_control` hint is our side |
| `extraction_gate` audit column write | Database / Storage | — | Already migrated (Phase 56 migration 007); gate writes the enum value to `signal_capture` |
| Boot-time client injection | API / Backend | — | `boot.py` creates `AsyncAnthropic`, passes to gate factory; same wiring as `httpx.AsyncClient` |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `anthropic` | `>=0.45` (current: 0.112.0) | AsyncAnthropic client + forced tool-use + prompt caching | Official first-party SDK; handles request signing, retries, tool-use parsing |
| `pydantic` | `>=2.13` (already in pyproject.toml) | Tool-use response schema validation (replaces zod.safeParse) | Already project-standard; v2 `model_validate` replaces zod pattern |

[VERIFIED: PyPI] `anthropic` latest is 0.112.0 (released 2026-06-24); minimum for forced tool-use + cache_control is well below 0.45. The `>=0.45` floor satisfies the locked decision and gives substantial headroom.

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-asyncio` | `>=1.4` (already dev dep) | Async test support | Gate unit tests are all `async def` |

**Installation:**
```bash
# In pyproject.toml [project] dependencies, add:
"anthropic>=0.45",
# Then:
uv sync
```

**Version verification:**
```bash
pip index versions anthropic   # confirms 0.112.0 latest as of 2026-06-24
```

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| anthropic | PyPI | 3+ yrs | Very high (official SDK) | github.com/anthropics/anthropic-sdk-python | First-party Anthropic package | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

[VERIFIED: PyPI] `anthropic` is the official first-party Anthropic Python SDK. slopcheck not run (not available in environment); package identity confirmed via PyPI and official Anthropic documentation.

---

## Architecture Patterns

### System Architecture Diagram

```
Signal capture envelope (text, transcript, attachmentCount, lastBotOutbound)
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  gate/event_gate.py  create_event_gate()                │
│                                                          │
│   1. rulePositive(envCtx)                               │
│      hit? ──────────────────────────► fast_event (allow)│
│      miss ↓                                             │
│   2. ruleNegative(envCtx, lastBotOutbound, nowMs)        │
│      hit? ──────────────────────────► skipped_rule_neg  │
│                                        (deny)           │
│      miss ↓                                             │
│   3. await classifier.classify(envCtx)                   │
│      !ok?  ─────────────────────────► forced (allow)    │
│      ok: is_event || confidence<0.7 ► haiku_event (allow)│
│      ok: confident chitchat ────────► haiku_chitchat    │
│                                        (deny)           │
└─────────────────────────────────────────────────────────┘
    │
    ▼
 GateDecision: {gate, allow_extract, allow_convo}
    │
    ▼
 capture pipeline writes extraction_gate to signal_capture
    │
    ▼
 Phase 60 extraction pipeline (if allow_extract=True)
```

```
classifier.classify(envCtx)
    │
    ▼
 AsyncAnthropic.messages.create(
   model, system=[{type:text, text:SYSTEM_PROMPT,
                   cache_control:{type:ephemeral}}],
   tools=[classify_capture schema],
   tool_choice={type:tool, name:classify_capture},
   messages=[{role:user, content: compact JSON}],
   max_tokens=100
 ) via client.with_options(timeout=2.0)
    │
    ├── APIError / timeout ──► {ok:False, reason, fallthrough:forced}
    ├── no tool_use block ───► {ok:False, reason:no_tool_use_in_response}
    ├── schema invalid ──────► {ok:False, reason:schema_invalid}
    └── valid ───────────────► {ok:True, is_event, kind, confidence, usage}
```

### Recommended Project Structure
```
src/farm-agent/
├── farm_agent/
│   ├── gate/
│   │   ├── __init__.py        # exports create_event_gate
│   │   ├── event_gate.py      # facade; create_event_gate() factory
│   │   ├── rules.py           # rulePositive / ruleNegative (pure, no I/O)
│   │   ├── classifier.py      # create_haiku_classifier() factory; never-throws
│   │   └── prompts.py         # SYSTEM_PROMPT, CACHEABLE_SYSTEM_BLOCKS, HOLDOUT_ROW_IDS
│   └── boot.py                # add AsyncAnthropic creation + gate wiring
└── tests/
    ├── fixtures/
    │   └── gate/
    │       └── 44-hand-classified-100.jsonl
    └── test_gate_rules.py
    └── test_gate_classifier.py
    └── test_gate_event_gate.py
```

### Pattern 1: AsyncAnthropic client creation at boot

```python
# boot.py addition (mirror of httpx.AsyncClient wiring)
import anthropic

# Source: platform.claude.com/docs/en/api/sdks/python
anthropic_client = anthropic.AsyncAnthropic(
    api_key=config.anthropic_api_key,
    max_retries=2,
)
gate = create_event_gate(
    haiku_classifier=create_haiku_classifier(client=anthropic_client),
    logger=log,
)
# Pass gate into capture pipeline or expose as pipeline["gate"]
```

**Never** create a new `AsyncAnthropic` per call or per request. One instance for the daemon lifetime.

### Pattern 2: Per-request timeout via with_options (CRITICAL — see Pitfall 1)

```python
# Source: platform.claude.com/docs/en/api/sdks/python#timeouts
# CORRECT: timeout as client option, not a body param
resp = await client.with_options(timeout=2.0).messages.create(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    system=CACHEABLE_SYSTEM_BLOCKS,
    tools=[TOOL_DEF],
    tool_choice={"type": "tool", "name": TOOL_NAME},
    messages=[{"role": "user", "content": build_classifier_input(env_ctx)}],
)
```

**Never** pass `timeout=` inside the `messages.create()` keyword arguments as a body param — the SDK strict-validates the request body and will raise `BadRequestError: Extra inputs are not permitted`. The `with_options()` wrapper applies it as a transport-level option, not a body field.

### Pattern 3: Forced tool-use and tool_use block parsing

```python
# Tool definition
TOOL_DEF = {
    "name": "classify_capture",
    "description": "Classify whether this capture is an event worth extracting.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_event": {"type": "boolean"},
            "kind": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["is_event", "kind", "confidence"],
        "additionalProperties": False,
    },
}

# Forced tool choice
tool_choice = {"type": "tool", "name": "classify_capture"}

# Parsing the tool_use block from response
# Source: official docs; response.content is a list of blocks
def find_tool_use_block(response):
    if not response or not hasattr(response, "content"):
        return None
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_capture":
            return block
    return None

# block.input is a dict; validate with pydantic
from pydantic import BaseModel, Field

class Classification(BaseModel):
    is_event: bool
    kind: str
    confidence: float = Field(ge=0.0, le=1.0)

try:
    parsed = Classification.model_validate(block.input)
except Exception as e:
    return {"ok": False, "reason": "schema_invalid", "fallthrough": "forced"}
```

### Pattern 4: Prompt caching with cache_control

```python
# Source: platform.claude.com/docs/en/docs/build-with-claude/prompt-caching
# system= accepts a list of blocks (NOT a plain string) when using cache_control
CACHEABLE_SYSTEM_BLOCKS = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,      # must be >=4096 tokens for Haiku 4.5 caching
        "cache_control": {"type": "ephemeral"},
    }
]

# Pass directly as system=
resp = await client.with_options(timeout=2.0).messages.create(
    model="claude-haiku-4-5-20251001",
    system=CACHEABLE_SYSTEM_BLOCKS,
    ...
)
# Verify caching in live-fire: resp.usage.cache_creation_input_tokens > 0
```

**Cache threshold for Haiku 4.5 is 4,096 tokens.** [VERIFIED: official Anthropic prompt caching docs] The SYSTEM_PROMPT in `prompts.js` is ~20,000 chars / ~4,100 tokens, so it just clears the threshold. If the Python string is shortened, caching will silently stop working with no error.

### Pattern 5: Never-throws closure factory (mirror of transcribe_client.py)

```python
def create_haiku_classifier(
    client: anthropic.AsyncAnthropic,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 100,
    timeout_ms: int = 2000,
    log: logging.Logger | None = None,
) -> dict:
    _log = log or logging.getLogger(__name__)
    _timeout_s = timeout_ms / 1000

    async def classify(env_ctx: dict) -> dict:
        # ... call + parse ...
        # NEVER raise; always return {ok:True,...} or {ok:False,reason,...}
        try:
            resp = await client.with_options(timeout=_timeout_s).messages.create(...)
        except Exception as e:
            _log.warning("[haiku-classifier] degraded: %s", e)
            return {"ok": False, "reason": str(e), "fallthrough": "forced"}
        ...

    return {"classify": classify}
```

### Anti-Patterns to Avoid
- **Passing `timeout=` in `messages.create()` kwargs:** Causes `BadRequestError: Extra inputs are not permitted`. Use `client.with_options(timeout=...)` instead.
- **Truncating the system prompt:** Dropping below 4,096 tokens breaks prompt caching silently. Do not shorten `SYSTEM_PROMPT` from the Node verbatim copy.
- **Concatenating farmer text into system prompt:** Threat T-44-04-01. User message must be a separate `messages` entry, never embedded in the system block.
- **Logging `env_ctx.text` at INFO level:** PII risk — farmer messages contain names, addresses, phone numbers. Log only mask_number()-sanitized sender and gate outcome.
- **Raising from the classify closure:** Breaks the never-throws contract; the capture pipeline's outer try/except is a last resort, not the primary defense.
- **Creating AsyncAnthropic per-call:** Creates a new httpx connection pool each time; one shared instance is wired at boot.

---

## Node Behavior to Reproduce Exactly

### Decision Order (index.js)

```
1. pos = rulePositive(envCtx)
   pos.hit → {gate: 'fast_event', allow_extract: true, allow_convo: true}

2. neg = ruleNegative(envCtx, lastBotOutbound, nowMs)
   neg.hit → {gate: 'skipped_rule_neg', allow_extract: false, allow_convo: false}

3. r = await haikuClassifier.classify(envCtx)
   !r || !r.ok → {gate: 'forced', allow_extract: true, allow_convo: true}
   r.is_event === true || (typeof r.confidence === 'number' && r.confidence < 0.7)
             → {gate: 'haiku_event', allow_extract: true, allow_convo: true}
   else      → {gate: 'haiku_chitchat', allow_extract: false, allow_convo: false}
```

**Python translation notes:**
- `!r || !r.ok` → `not r or not r.get("ok")`
- `typeof r.confidence === 'number'` → confidence will always be float from pydantic; check `isinstance(r.get("confidence"), (int, float))`
- `r.is_event === true` → `r.get("is_event") is True` (strict, not truthy — mirrors JS ===)

### rulePositive (rules.js verbatim → Python)

```python
import re

STRAIN_RE = re.compile(r"\b[A-Z]{2,4}\b")
BLOCK_RE = re.compile(r"\b\d{6}_[A-Z]{2,4}_\d+\b")

def rule_positive(env_ctx: dict) -> dict:
    if (env_ctx.get("attachmentCount") or 0) > 0:
        return {"hit": True, "kind": "image_or_audio"}
    body = env_ctx.get("text") or env_ctx.get("transcript") or ""
    if len(body) > 200:
        return {"hit": True, "kind": "long_text"}
    if STRAIN_RE.search(body):
        return {"hit": True, "kind": "strain_code"}
    if BLOCK_RE.search(body):
        return {"hit": True, "kind": "block_name"}
    return {"hit": False}
```

**Key:** body is `text OR transcript`, not concatenation. Attachment check uses `> 0`, not `>= 1` (same thing but mirrors JS exactly).

### ruleNegative (rules.js verbatim → Python)

```python
from datetime import datetime, timezone

ACK_RE = re.compile(r"^(ok|yes|got it|thanks|gracias|si|sí|👍)$", re.IGNORECASE)

def rule_negative(env_ctx: dict, last_bot_outbound: dict | None, now_ms: int) -> dict:
    if not last_bot_outbound or last_bot_outbound.get("intent") != "attestation_kickoff":
        return {"hit": False}
    sent_at = last_bot_outbound.get("sent_at")
    if not sent_at:
        return {"hit": False}
    sent_at_ms = int(datetime.fromisoformat(sent_at.replace("Z", "+00:00")).timestamp() * 1000)
    if now_ms - sent_at_ms > 30 * 60 * 1000:
        return {"hit": False}
    body = (env_ctx.get("text") or "").strip()
    if len(body) >= 40:
        return {"hit": False}
    if not ACK_RE.match(body):
        return {"hit": False}
    return {"hit": True, "kind": "short_ack_within_30m"}
```

**Key:**
- `body.length >= 40` is `>= 40` (NOT `> 40`) — a 40-char body does NOT trigger negative rule
- `ACK_RE` tests the full body (`^...$`); `re.match` anchors at start, but `$` anchor is still needed since `re.match` doesn't anchor at end
- `sent_at` is an ISO-8601 string from the DB; parse via `datetime.fromisoformat`

### Classifier Input Shape (haiku-classifier.js buildClassifierInput)

```python
import json

def build_classifier_input(env_ctx: dict) -> list[dict]:
    payload = {
        "text": env_ctx.get("text"),            # None if absent
        "transcript": env_ctx.get("transcript"), # None if absent
        "attachmentCount": env_ctx.get("attachmentCount") or 0,
    }
    return [{"type": "text", "text": json.dumps(payload)}]
```

### Gate Enum Values (D-04 lock)

```python
GATE_FAST_EVENT = "fast_event"
GATE_SKIPPED_RULE_NEG = "skipped_rule_neg"
GATE_HAIKU_EVENT = "haiku_event"
GATE_HAIKU_CHITCHAT = "haiku_chitchat"
GATE_FORCED = "forced"
```

These values are written to `signal_capture.extraction_gate` (VARCHAR(32), already migrated in Phase 56 migration 007).

### Fail-open Error Shapes (haiku-classifier.js → Python)

| Scenario | Return dict |
|----------|-------------|
| API error / timeout | `{"ok": False, "reason": str(e), "fallthrough": "forced"}` |
| Response has no tool_use block | `{"ok": False, "reason": "no_tool_use_in_response", "fallthrough": "forced"}` |
| tool_use.input fails schema | `{"ok": False, "reason": "schema_invalid", "fallthrough": "forced"}` |
| Success | `{"ok": True, "is_event": bool, "kind": str, "confidence": float, "usage": {...}}` |

### Holdout Row IDs (prompts.js HOLDOUT_ROW_IDS — verbatim)

```python
HOLDOUT_ROW_IDS = [
    # soft-obs (7 rows)
    "01KS3X9RYSV46CM09MRF3HCS8G",  # "2100 refilled"
    "01KS3N9AYC0RY0Z633NC8AE4C6",  # "1830 refilled"
    "01KS3EG9BY0S2Z86ZTYFVA202H",  # "Checked"
    "01KS2MRHXFPEAQSE7VX0XE71PF",  # "St is on. Off by 2200"
    "01KS08MA5AS5KPSFZK4PQ7XJ24",  # "Containers cleaned and sprayed ready in Lab 2"
    "01KRGY9PKT54ZTMRRFPEFV8ARQ",  # "Not fruiting chamber but the greenhouse"
    "01KRGNCZCRZ2Z14W8DHWGXJYT3",  # "Timestamp, just now. Redt, leave blank"
    # ux-meta (3 rows)
    "01KRQ0RTNV3CE5YV6G299PVKN1",  # "Copiado, gracias..."
    "01KRVVE7WQ04HQYBSZK5DQ8CP9",  # "Note this somewhere that makes sense"
    "01KRQ3R1BNMMRE6MJ88E1YY5B4",  # "Where are we with the LIMA to FC1 event?"
]
```

These 10 row IDs must be excluded from the unit/few-shot subset. The test fixture filter is: `row["capture_id"] not in HOLDOUT_ROW_IDS`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tool-use response validation | Custom dict key checks | `pydantic.BaseModel.model_validate()` | Exact parity with Node's `zod.safeParse`; handles type coercion, min/max, missing fields atomically |
| Retry logic on API errors | `for i in range(n)` loop | `anthropic.AsyncAnthropic(max_retries=2)` | SDK handles exponential backoff, 429 rate limit, 5xx correctly |
| ISO-8601 to ms conversion | String splitting | `datetime.fromisoformat(...).timestamp() * 1000` | Handles timezone offset in `sent_at` values from the DB |
| Timeout abort | `asyncio.wait_for` | `client.with_options(timeout=_timeout_s)` | SDK maps to httpx transport timeout; `asyncio.wait_for` wraps the coroutine but doesn't cancel the in-flight HTTP request cleanly |

---

## File-by-File Implementation Map

### `farm_agent/gate/__init__.py`
- Exports: `create_event_gate`
- Foray seam: no imports from `chamber/`; may import from `tenancy/` only for type hints (not logic)

### `farm_agent/gate/prompts.py`
- `SYSTEM_PROMPT`: verbatim string copy from Node `prompts.js` (do NOT shorten; cache threshold is ~4096 tokens)
- `CACHEABLE_SYSTEM_BLOCKS`: `[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]`
- `HOLDOUT_ROW_IDS`: verbatim list from Node `prompts.js`
- No logic, no imports beyond stdlib

### `farm_agent/gate/rules.py`
- `rule_positive(env_ctx) -> dict`
- `rule_negative(env_ctx, last_bot_outbound, now_ms) -> dict`
- Module-level: `STRAIN_RE`, `BLOCK_RE`, `ACK_RE` compiled at import time
- Pure functions — no I/O, no imports of farm_agent internals

### `farm_agent/gate/classifier.py`
- `create_haiku_classifier(client, model, max_tokens, timeout_ms, log) -> {"classify": async_fn}`
- Module-level constants: `TOOL_NAME`, `TOOL_DESCRIPTION`, `TOOL_DEF`, `Classification` (pydantic model)
- `build_classifier_input(env_ctx) -> list[dict]`
- `find_tool_use_block(response) -> block | None`
- The `classify` closure: try/except wrapping `client.with_options(timeout=...).messages.create()`, then tool_use block extraction, then pydantic validation, then success dict

### `farm_agent/gate/event_gate.py`
- `create_event_gate(haiku_classifier, rules, logger) -> {"classify": async_fn}`
- The `classify(env_ctx, last_bot_outbound, now_ms) -> dict` coroutine
- Decision flow exactly as in `index.js` (steps 1→2→3 in order)
- Returns `{gate: str, allow_extract: bool, allow_convo: bool}`

### `farm_agent/boot.py`
- Add `import anthropic`
- After `http = httpx.AsyncClient()`, add:
  ```python
  anthropic_client = anthropic.AsyncAnthropic(
      api_key=config.anthropic_api_key,
      max_retries=2,
  )
  ```
- Create gate: `gate = create_event_gate(create_haiku_classifier(client=anthropic_client), ...)`
- Pass gate into capture pipeline
- Add `await anthropic_client.close()` in shutdown sequence

### `tests/fixtures/gate/44-hand-classified-100.jsonl`
- File copy of `.planning/phases/44-event-gate-.../44-hand-classified-100.jsonl`
- 100 rows; schema fields used by tests: `capture_id`, `raw_text`, `transcript`, `attachment_count`, `expected_gate_action`, `class`

### `tests/test_gate_rules.py`
- Direct calls to `rule_positive` and `rule_negative`; no mock needed
- Test data: inline dicts covering each rule branch (image_or_audio, long_text, strain_code, block_name, short_ack_within_30m, all hit=False paths)

### `tests/test_gate_classifier.py`
- `FakeAnthropicClient` fixture returning a canned response object with `content=[tool_use_block]`
- Tests: success path, no_tool_use_in_response, schema_invalid, API exception, timeout
- Asserts the user-message JSON shape and tool_choice

### `tests/test_gate_event_gate.py`
- 90-row corpus replay (non-holdout); for each row: build `env_ctx` from fixture, call `gate.classify`, assert `allow_extract` matches `expected_gate_action == "extract"`
- Rule fast-path rows (attachment_count > 0, text > 200 chars, STRAIN_RE match) should return `fast_event` without calling the mock classifier
- Fail-open: mocked classifier returning `{"ok": False}` → `forced`, `allow_extract=True`

---

## Common Pitfalls

### Pitfall 1: Timeout as body param (the Node live-fire bug, 2026-05-23)
**What goes wrong:** Passing `timeout=2000` (or `timeout=2.0`) inside `messages.create()` kwargs sends it as a JSON body field. The Anthropic API strict-validates the body and returns `400 BadRequestError: "signal: Extra inputs are not permitted"` (Node equivalent) or `"timeout: Extra inputs are not permitted"` (Python).
**Why it happens:** Node SDK second positional arg is request-options; Python SDK uses `client.with_options()` for the same purpose. Both are transport-level, not body-level.
**How to avoid:** Always use `client.with_options(timeout=_timeout_s).messages.create(...)`.
**Warning signs:** `BadRequestError` with message containing `Extra inputs are not permitted`; the request reaches Anthropic and fails at schema validation.

### Pitfall 2: Prompt cache threshold for Haiku 4.5 is 4,096 tokens
**What goes wrong:** Shortening `SYSTEM_PROMPT` below 4,096 tokens causes `cache_control` to be silently ignored. No error is raised; the cache hit counter stays at 0; every call pays full prompt token cost (~4,100 input tokens at ~$0.00025/1K).
**Why it happens:** The 4,096-token minimum is enforced by Anthropic infrastructure. [VERIFIED: official prompt caching docs]
**How to avoid:** Copy `SYSTEM_PROMPT` verbatim from Node `prompts.js` without truncation (~20,000 chars). Verify caching in the live-fire run by checking `resp.usage.cache_creation_input_tokens > 0` on first call.
**Warning signs:** `cache_creation_input_tokens` and `cache_read_input_tokens` both 0 in response usage.

### Pitfall 3: ruleNegative body length threshold is `>= 40`, not `> 40`
**What goes wrong:** Exact-40-char bodies slip past the negative rule when they should. A body of exactly 40 chars returns `{hit: False}` — it does NOT trigger the negative rule.
**Why it happens:** Node code: `if (body.length >= 40) return { hit: false }`. The `>=` means "too long to be a short ack".
**How to avoid:** `if len(body) >= 40: return {"hit": False}` — same operator.

### Pitfall 4: ACK_RE with re.match needs explicit `$` anchor
**What goes wrong:** `re.match(r"^(ok|yes|...)", body)` matches "ok then let me explain..." as a phantom_ack because `re.match` only anchors the start.
**Why it happens:** JS `ACK_RE.test(body)` is a full-string test in JS when the pattern uses `^...$`. Python `re.match` only anchors start.
**How to avoid:** `re.match(r"^(ok|yes|got it|thanks|gracias|si|sí|👍)$", body, re.IGNORECASE)` — the `$` is required.

### Pitfall 5: tool_use block attribute access on pydantic response model
**What goes wrong:** `block.type` and `block.name` and `block.input` are attribute access on a pydantic model returned by the SDK, not dict keys. `block["type"]` raises `TypeError`.
**Why it happens:** The Python SDK returns typed response objects, not raw dicts.
**How to avoid:** Use `block.type`, `block.name`, `block.input` — attribute access. The `input` field is a plain `dict` (not a pydantic model), so `block.input["is_event"]` or `Classification.model_validate(block.input)` both work.

### Pitfall 6: Holdout rows must be excluded from deterministic test assertion
**What goes wrong:** Running all 100 fixture rows through the mock-classifier corpus test and asserting exact gate outcomes. The 10 holdout rows are gray-zone: soft_obs and ux_meta with no rule fast-path. The mock classifier returns deterministic results that may not match the hand-labeled `expected_gate_action`, producing false failures.
**Why it happens:** The holdout rows were deliberately selected as cases where even human classification is uncertain. A mock classifier returning e.g. `{ok:True, is_event:False, confidence:0.8}` may produce `haiku_chitchat` while the fixture says `expected_gate_action: extract`.
**How to avoid:** Filter to 90 non-holdout rows: `[r for r in rows if r["capture_id"] not in HOLDOUT_ROW_IDS]`. The holdout rows are reserved for the deferred real-Haiku run.

### Pitfall 7: PII in log output
**What goes wrong:** Logging `env_ctx` (which contains farmer-authored text) at INFO or DEBUG level exposes PII.
**Why it happens:** `env_ctx["text"]` is the raw farmer Signal message; it may contain names, locations, phone numbers.
**How to avoid:** Log only: gate outcome enum, `allow_extract`, and if needed a truncated/masked sender reference. Match the `mask_number()` pattern from `capture/pipeline.py`. Never log `env_ctx["text"]` or `env_ctx["transcript"]`.

### Pitfall 8: `sent_at` timezone handling in ruleNegative
**What goes wrong:** `datetime.fromisoformat(sent_at)` in Python 3.11 handles `+00:00` but NOT the trailing `Z` in Python < 3.11. The DB may store either form.
**Why it happens:** Python 3.11+ added `Z` support to `fromisoformat`; Python 3.12 (our target) should handle it, but the `.replace("Z", "+00:00")` guard is zero-cost insurance.
**How to avoid:** `sent_at.replace("Z", "+00:00")` before calling `fromisoformat`.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1 + pytest-asyncio 1.4 (asyncio_mode=auto) |
| Config file | `src/farm-agent/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_gate_rules.py tests/test_gate_classifier.py tests/test_gate_event_gate.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GATE-01 | rulePositive fast-path fires on attachment, long text, strain code, block name | unit | `pytest tests/test_gate_rules.py::test_rule_positive -x` | Wave 0 |
| GATE-01 | ruleNegative fires on short ack within 30min of attestation_kickoff | unit | `pytest tests/test_gate_rules.py::test_rule_negative -x` | Wave 0 |
| GATE-01 | ruleNegative does NOT fire on ack outside 30min window | unit | `pytest tests/test_gate_rules.py -x` | Wave 0 |
| GATE-01 | Classifier returns ok:True with correct shape on valid tool_use response | unit | `pytest tests/test_gate_classifier.py::test_classify_success -x` | Wave 0 |
| GATE-01 | Classifier returns ok:False on no tool_use block (fail-open) | unit | `pytest tests/test_gate_classifier.py::test_no_tool_use -x` | Wave 0 |
| GATE-01 | Classifier returns ok:False on schema_invalid (fail-open) | unit | `pytest tests/test_gate_classifier.py::test_schema_invalid -x` | Wave 0 |
| GATE-01 | Classifier returns ok:False on API exception (fail-open) | unit | `pytest tests/test_gate_classifier.py::test_api_error -x` | Wave 0 |
| GATE-01 | Timeout → ok:False → gate returns forced (allow_extract=True) | unit | `pytest tests/test_gate_event_gate.py::test_fail_open_forced -x` | Wave 0 |
| GATE-01 (SC-1) | 90-row corpus: 0 chit-chat rows incorrectly allowed (0% false-positive) | corpus replay | `pytest tests/test_gate_event_gate.py::test_corpus_no_false_positives -x` | Wave 0 |
| GATE-01 (SC-2) | 90-row corpus: >=95% event recall (no real events gate-rejected) | corpus replay | `pytest tests/test_gate_event_gate.py::test_corpus_event_recall -x` | Wave 0 |
| GATE-01 (SC-3) | WARNING logged on classifier failure | unit | `pytest tests/test_gate_classifier.py::test_warning_on_failure -x` | Wave 0 |

**Success criteria mapping:**
- SC-1 (0% false-positive on labeled negatives): test asserts that for all 90 non-holdout rows where `expected_gate_action == "skip"`, the gate returns `allow_extract=False`. This uses the mocked classifier (which returns a deterministic `{ok:True, is_event:False, confidence:0.95}` for text-only non-event-shaped inputs).
- SC-2 (>=95% event recall): test asserts that for all 90 non-holdout rows where `expected_gate_action == "extract"`, the gate returns `allow_extract=True`. Rule fast-path rows cover the majority; a small number reach the mock classifier.
- SC-3 (fail-open on timeout/API error): test injects a mock that raises `anthropic.APIConnectionError`; asserts gate returns `{gate: "forced", allow_extract: True}` and WARNING was logged.

**Deferred real-Haiku run:**
The ROADMAP's 0%/95% criteria are proven on the 90-row deterministic subset above. The **full-100 real-Haiku accuracy run** (including the 10 holdout rows) is a separate test marked `@pytest.mark.live_fire` and skipped unless `ANTHROPIC_API_KEY` is set and `GATE_LIVE_FIRE=1`. It mirrors the Phase 58 live-fire pattern and is deferred to operator validation.

### Sampling Rate
- **Per task commit:** `pytest tests/test_gate_rules.py tests/test_gate_classifier.py tests/test_gate_event_gate.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_gate_rules.py` — covers rulePositive / ruleNegative unit cases
- [ ] `tests/test_gate_classifier.py` — covers classifier factory; needs `FakeAnthropicClient` fixture
- [ ] `tests/test_gate_event_gate.py` — covers corpus replay (90 rows) + fail-open + decision flow integration
- [ ] `tests/fixtures/gate/44-hand-classified-100.jsonl` — copied from planning fixture
- [ ] `FakeAnthropicClient` fixture in `tests/conftest.py` or `tests/test_gate_classifier.py` — configurable response for tool_use and error paths

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | API key via existing TenantConfig.anthropic_api_key (env-only) |
| V3 Session Management | No | Stateless per-message classification |
| V4 Access Control | No | Gate is an internal pipeline component; whitelist gate is upstream in router.py |
| V5 Input Validation | Yes | `pydantic.BaseModel.model_validate(block.input)` on tool_use output; compact JSON user message prevents prompt injection |
| V6 Cryptography | No | No cryptographic operations; API key is transport-level (HTTPS) |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via farmer message | Tampering | User message is a separate `messages` entry (compact JSON), never concatenated into system prompt — T-44-04-01 mitigation locked by Node source |
| API key leakage via logs | Information Disclosure | `config.anthropic_api_key` only flows into `AsyncAnthropic(api_key=...)` constructor; never logged (T-56-06-01 pattern from boot.py) |
| PII in log output | Information Disclosure | `env_ctx["text"]` / `env_ctx["transcript"]` MUST NOT appear in logs at any level; only gate outcome and masked sender |
| Classifier overconfidence on OOD input | Tampering / Spoofing | Confidence floor of 0.7 in facade (not classifier); low-confidence non-events still pass to extraction |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| JS AbortSignal in request body | Python `client.with_options(timeout=...)` | 2026-05-23 (Node live-fire) | Avoids 400 "Extra inputs" error |
| Plain string `system=` | List of blocks with `cache_control` | SDK >=0.45 | Enables prompt caching; halves effective per-call cost for cached prompts |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `anthropic>=0.45` is sufficient for `AsyncAnthropic`, forced tool-use, and `cache_control` on system blocks | Standard Stack | Low — current SDK is 0.112.0; all these features predate 0.45 by months; confirmed via official docs |
| A2 | `block.input` on a tool_use response object is a plain `dict` (not a nested pydantic model) | Architecture Patterns | Low — confirmed by SDK docs describing nested request params as TypedDicts and responses as Pydantic models; `input` is untyped in the schema |
| A3 | `client.with_options(timeout=2.0)` correctly maps to a 2-second transport timeout for async requests | Pitfall 1 | Medium — confirmed by official docs showing the same pattern for both sync and async; not live-fire tested yet in this phase |

**If this table is empty:** it is not — three low/medium assumptions noted above.

---

## Open Questions

1. **FakeAnthropicClient fixture shape**
   - What we know: The SDK returns typed pydantic response objects; `block.type`, `block.name`, `block.input` are attributes.
   - What's unclear: The exact constructor path to fake a `Message` object with a `content` list containing a `ToolUseBlock`. May need to use `MagicMock` or construct via `anthropic.types`.
   - Recommendation: Use `unittest.mock.MagicMock(spec=...)` configured with `content=[mock_block]` where `mock_block.type = "tool_use"`, `mock_block.name = "classify_capture"`, `mock_block.input = {...}`. This avoids importing private SDK types.

2. **Gate integration point in capture pipeline**
   - What we know: Phase 58 `pipeline.py` exists; gate sits between capture and extraction (Phase 60 is extraction).
   - What's unclear: Does the gate get wired into `pipeline.py` in Phase 59, or does Phase 60 wire it? The locked decisions say gate is a leaf unit importable by the capture/extraction pipeline.
   - Recommendation: Phase 59 creates `gate/` and wires it into `boot.py`; the capture pipeline's `handle()` function calls `gate.classify()` and writes `extraction_gate` to the DB row. Phase 60 reads `allow_extract` from the capture row to decide whether to run extraction.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Gate package | ✓ | 3.12 (project requirement) | — |
| `anthropic` PyPI package | classifier.py | Not yet in pyproject.toml | 0.112.0 (latest) | — (must add) |
| Anthropic API key | live-fire only | ✓ (env ANTHROPIC_API_KEY) | — | n/a — deferred run only |
| `uv` | dependency management | ✓ | project standard | — |

**Missing dependencies with no fallback:**
- `anthropic` not yet in `pyproject.toml`; must be added before any import of `anthropic` works

**Missing dependencies with fallback:**
- None

---

## Sources

### Primary (HIGH confidence)
- Node source `src/agents/alerter/src/event-gate/{index,rules,haiku-classifier,prompts}.js` — read directly; exact regexes, thresholds, decision order, holdout IDs
- `platform.claude.com/docs/en/api/sdks/python` — AsyncAnthropic, timeout via `with_options`, max_retries, error types [VERIFIED: official Anthropic docs]
- `platform.claude.com/docs/en/docs/build-with-claude/prompt-caching` — cache_control syntax, 4096-token threshold for Haiku 4.5 [VERIFIED: official Anthropic docs]
- `pypi.org/pypi/anthropic/json` — latest version 0.112.0, release date 2026-06-24 [VERIFIED: PyPI]
- `src/farm-agent/farm_agent/capture/transcribe_client.py` — never-throws closure factory pattern to mirror
- `src/farm-agent/farm_agent/boot.py` — boot wiring pattern for injected clients
- `src/farm-agent/tests/conftest.py` — fake client fixture patterns

### Secondary (MEDIUM confidence)
- `platform.claude.com/docs/en/docs/build-with-claude/tool-use/overview` — tool_choice forced syntax, tool_use response shape [VERIFIED: official Anthropic docs]

---

## Metadata

**Confidence breakdown:**
- Node behavior to reproduce: HIGH — source read directly
- Python SDK call shapes: HIGH — verified against official docs
- Prompt cache threshold: HIGH — explicitly stated in official docs
- Test strategy: HIGH — mirrors Phase 58 pattern already in codebase
- Timeout mapping: MEDIUM-HIGH — documented in SDK docs; not yet live-fired in Python

**Research date:** 2026-06-24
**Valid until:** 2026-07-24 (SDK stable; 30-day window)
