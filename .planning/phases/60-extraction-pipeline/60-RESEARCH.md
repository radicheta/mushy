# Phase 60: Extraction Pipeline - Research

**Researched:** 2026-06-26
**Domain:** Anthropic Python SDK multi-turn tool-use, Pillow image downscale, pydantic v2 schema validation, SeedingSession block-name minting
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Area 1 — Extractor structure, model & LLM reuse**
- New `farm_agent/extraction/extractor.py` with factory `create_extractor(client, model="claude-sonnet-4-6", max_tokens=16384, on_llm_call=None) -> {"extract": async_fn}`. Mirror the Phase-59 `create_haiku_classifier` shape (never-throws, discriminated `{ok, ...}` result). Reuse the shared `AsyncAnthropic` singleton injected at `boot.py`.
- Model: `claude-sonnet-4-6` verbatim (NOT haiku).
- `max_tokens`: 16384.
- Forced tool `submit_extraction`; `tool_choice={"type": "tool", "name": "submit_extraction"}`.
- Validated via `pydantic Submission.model_validate(tool_use.input)`.
- Gate and extractor remain SEPARATE factories (different model, timeout, system prompt). Do NOT unify.

**Area 2 -- Multimodal image handling**
- New `farm_agent/extraction/multimodal.py`. Input = image FILE PATHS; reads + base64-encodes inline as `{type:"image", source:{type:"base64", media_type, data}}` blocks.
- ADD **Pillow** as runtime dependency; port Node's downscale (~5MB or ~1.15MP triggers).
- Missing/unreadable image = FAIL-OPEN: skip that block, log WARNING, continue.
- `media_type`: detect from extension (`.jpg`/`.jpeg` → `image/jpeg`, `.png` → `image/png`); default `image/jpeg`.

**Area 3 -- Retry, provenance, SEQ & testing**
- MAX 2 LLM calls: initial `messages.create`, validate via pydantic; on failure send follow-up turn with `tool_result` block (`is_error: True` + matching `tool_use_id` + error list); on second failure return `{ok: False, reason: "schema_invalid", errors, raw_first, raw_retry}` -- never throws.
- Provenance taxonomy in system prompt verbatim (audio / paper_log_photo / bag_label_photo / text / model_inference).
- New `farm_agent/extraction/seq_helper.py` for pure helpers: `mint_child_block_names` + `lookup_last_seq_for_date`. Emit `needs_input='starting_seq'` sentinel; interactive ask-back DEFERRED to Phase 61.
- Prompts: inline verbatim in `farm_agent/extraction/prompts.py`; `cache_control: {type: "ephemeral"}`.
- Testing: copy 2026-05-22 fixture; hermetic mocked-tool_use unit test (FakeAnthropicClient extended); re-run FND-04 parity. Real-Sonnet accuracy run DEFERRED.

### Claude's Discretion
- Internal helper names, file splits within `extraction/`, exact downscale thresholds within Node's documented bounds, test parametrization -- provided locked behavior + schema + module boundaries hold.

### Deferred Ideas (OUT OF SCOPE)
- Real-Sonnet accuracy run on the live 2026-05-22 fixture (marker/env-gated) -- operator-run.
- Interactive `handle_starting_seq_reply` farmer ask-back + confirm-prompt wiring -- Phase 61.
- Unifying gate + extractor LLM plumbing into a shared helper.
- Any extraction-behavior changes beyond reproducing Node.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| XTR-01 | Multimodal extractor fuses text + audio transcript + image into a single draft via Claude tool-use against the pydantic schema, with cacheable system prompt + few-shot turns ported (prompt-cache breakpoints preserved). | Covered by extractor.py factory, multimodal.py base64 assembly, prompts.py cache_control. |
| XTR-02 | Schema-invalid model output triggers the same retry behavior; the multi-parent SeedingSession shape (N children from M>1 parents) and per-field provenance are reproduced. | Covered by 2-call retry pattern, tool_result is_error block, pydantic Submission validation, existing SeedingSession schema. |
| XTR-03 | B5 block-name minting (`{YYMMDD}_{SPECIES3}_{SEQ}`, per-session SEQ) is reproduced; `BLOCK_NAME_RE` uses anchored full-match; drafts persist to `signal_draft` (hex-SHA id). | Covered by seq_helper.py port, re.fullmatch enforcement, fixture regression test. |
</phase_requirements>

---

## Summary

Phase 60 ports the Node multimodal extraction pipeline to Python. The main deliverable is four new modules under `farm_agent/extraction/`: `extractor.py` (factory + 2-call LLM retry), `multimodal.py` (Pillow downscale + base64 image assembly), `prompts.py` (verbatim Node system prompt with cache_control), and `seq_helper.py` (pure SEQ mint/lookup). The pydantic schemas are already ported (Phase 56 FND-04) and must not be re-ported; the extractor imports and validates against `Submission` from `farm_agent.extraction.schemas.submission`.

The critical new SDK knowledge needed is the exact shape for a multi-turn Anthropic tool-use retry: after the model returns a `tool_use` block whose `.input` fails pydantic validation, the retry user turn carries a `tool_result` content block with `type="tool_result"`, `tool_use_id=<block.id>`, `is_error=True`, and a `content` string describing the errors. The assistant turn between the first call and the retry turn carries `{"role": "assistant", "content": resp.content}` (the raw content list from the first response, attribute-accessed). This exact pattern is verified from the Node source and confirmed against the anthropic SDK 0.112.0 type stubs.

For Pillow: the paper-log fixture image (`paper-log.jpg`) is 900x1600 = 1.44MP, which exceeds the 1.15MP ceiling, so downscaling is confirmed as a live code path for this fixture. The Pillow API is verified: `Image.open(BytesIO(buf))`, compute `w*h` from `.size`, scale via `thumbnail()` or explicit resize, `convert("RGB")` before JPEG save (RGBA images fail without conversion), save to `BytesIO` with `format="JPEG", quality=85`, then `base64.b64encode(out.getvalue()).decode("ascii")`.

**Primary recommendation:** Follow the Node extractor.js + validator.js structure precisely; the Python port is a faithful translation, not a redesign.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Anthropic LLM call + retry | API / Backend (extractor.py) | -- | All LLM communication is server-side; never client |
| Image base64 encoding / downscale | API / Backend (multimodal.py) | -- | File I/O happens before the API call |
| Pydantic schema validation | API / Backend (extractor.py) | schemas/ (already ported) | Validation is in-process at call time |
| B5 block-name minting | API / Backend (seq_helper.py) | -- | Pure function, no external deps |
| SEQ lookup | Database / Storage (seq_helper.py + pool) | -- | Requires signal_draft query |
| Draft persistence | Database / Storage (called from pipeline) | -- | extractor.py emits result; pipeline persists |
| Prompt caching | CDN / Static (Anthropic's prompt cache) | prompts.py (breakpoints) | Cache breakpoints set via cache_control in prompts.py |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | >=0.45 (0.112.0 confirmed) [VERIFIED: PyPI] | AsyncAnthropic client, multi-turn messages | Already in pyproject.toml; singleton in boot.py |
| pydantic | >=2.13 [VERIFIED: PyPI] | model_validate on tool_use.input | Already in pyproject.toml; schemas already ported |
| Pillow | 12.2.0 (latest) [VERIFIED: PyPI] | Image.open, resize, JPEG re-encode | Replaces Node's jimp; ubiquitous, well-maintained |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| base64 (stdlib) | Python 3.12 [ASSUMED] | base64.b64encode after Pillow re-encode | Always in multimodal.py |
| io (stdlib) | Python 3.12 [ASSUMED] | BytesIO for in-memory image buffer | Always in multimodal.py |
| re (stdlib) | Python 3.12 [ASSUMED] | re.fullmatch(BLOCK_NAME_RE, name) | In seq_helper.py mint validation |
| pathlib (stdlib) | Python 3.12 [ASSUMED] | Path extension detection | In multimodal.py mime_from_path |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pillow | opencv-python | OpenCV is 40+ MB heavier; Pillow is sufficient for resize+JPEG |
| Pillow | wand (ImageMagick) | Requires libmagick system dep; Pillow is pure Python |

**Installation (pyproject.toml addition):**
```toml
"Pillow>=10.0",
```

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| Pillow | PyPI | 12+ yrs (fork of PIL c.2010) | ~40M/wk [ASSUMED] | github.com/python-pillow/Pillow | not run (slopcheck unavailable) | [ASSUMED] Approved -- extremely well-known, official Python imaging library |

**Packages removed due to slopcheck [SLOP] verdict:** none

**Packages flagged as suspicious [SUS]:** none

*slopcheck was not available at research time (permission denied for --break-system-packages install). Pillow is tagged `[ASSUMED]` by policy. However, Pillow is a 12+ year old, universally-recognized Python library (PyPA member project, listed at python-pillow.github.io) confirmed at version 12.2.0 on PyPI via `pip index versions`. The planner should include a human-verify checkpoint before the `pip install Pillow` step per protocol, but confidence in legitimacy is extremely high.*

---

## Framework Quick Reference

### Anthropic Python SDK: Multi-Turn Tool-Use Retry

**Verified against:** anthropic 0.112.0 [VERIFIED: PyPI pip show]

The exact retry shape mirrors the Node validator.js `buildToolResultRetry`. After the first `messages.create` call:

1. **Find the tool_use block** in `resp.content` by iterating and checking `block.type == "tool_use" and block.name == TOOL_NAME`. Use attribute access (`.type`, `.name`, `.id`, `.input`), NOT dict keys -- `resp.content` is a list of pydantic-like objects.

2. **Validate** `Submission.model_validate(block.input)` (pydantic v2). On `ValidationError`, collect errors.

3. **Build the retry turn** (verified from ToolResultBlockParam type hints):
```python
retry_user_turn = {
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": block.id,       # block.id, not block.name
            "is_error": True,
            "content": error_text,         # string or list[TextBlockParam]
        }
    ],
}
```

4. **Build the assistant turn** (carries the raw first response content):
```python
assistant_turn = {"role": "assistant", "content": resp.content}
```
The SDK accepts `resp.content` (list of response objects) directly as the assistant turn's content -- this is the same shape Node uses (`resp.content` in JS).

5. **Retry call** appends both turns to the original message history:
```python
retry_req = {**base_req, "messages": [*messages, assistant_turn, retry_user_turn]}
resp2 = await client.with_options(timeout=_timeout_s).messages.create(**retry_req)
```

6. **Second failure**: return `{ok: False, reason: "schema_invalid", errors: ..., raw_first: block.input, raw_retry: block2.input}` -- never raise.

**Key trap:** `timeout` goes through `client.with_options(timeout=_timeout_s)`, NOT as a `messages.create()` body kwarg. The SDK strict-validates the body and returns 400 `"Extra inputs are not permitted"` otherwise. This is the same trap documented in Phase 59 Pitfall 1 / D-03.

### Anthropic Python SDK: Image Base64 Blocks

```python
image_block = {
    "type": "image",
    "source": {
        "type": "base64",
        "media_type": "image/jpeg",   # or "image/png"
        "data": base64_string,         # ascii str, not bytes
    },
}
```
The SDK accepts plain dicts for all block types. [VERIFIED: anthropic 0.112.0 type stubs]

### Anthropic Python SDK: System Blocks with cache_control

```python
CACHEABLE_SYSTEM_BLOCKS = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
]
```
Passed as `system=CACHEABLE_SYSTEM_BLOCKS` in `messages.create()`. [VERIFIED: gate/prompts.py precedent]

The cache threshold for Sonnet models is >= 1024 tokens (Haiku is >= 2048 tokens). [ASSUMED -- verify against current Anthropic docs before finalizing prompts.py; the extraction system prompt is large (>100 lines) and should exceed the threshold comfortably.]

### Pillow Downscale API

Verified against Pillow 12.2.0 [VERIFIED: PyPI]:

```python
from PIL import Image
import io, base64, math

MAX_BYTES = 5 * 1024 * 1024       # 5 MB
MAX_PIXELS = 1_150_000             # 1.15 MP

def downscale_if_needed(buf: bytes, media_type: str) -> tuple[bytes, str]:
    """Returns (possibly-rescaled buf, media_type). Never raises -- caller wraps in try/except."""
    img = Image.open(io.BytesIO(buf))
    w, h = img.size
    pixels = w * h
    if len(buf) <= MAX_BYTES and pixels <= MAX_PIXELS:
        return buf, media_type
    scale = math.sqrt(MAX_PIXELS / pixels)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # CRITICAL: JPEG save fails on RGBA images -- convert to RGB first
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue(), "image/jpeg"
```

**Fixture verification:** `paper-log.jpg` is 900x1600 = 1.44MP, which exceeds the 1.15MP cap. Downscale fires in the test fixture. [VERIFIED: confirmed via Pillow 12.2.0 `Image.open` against the fixture file]

Note: Node uses `img.resize(newW, newH)` (Jimp). Python equivalent is `img.resize((w, h), Image.LANCZOS)` -- NOT `thumbnail()`. `thumbnail()` is in-place and only ever shrinks, but the explicit resize + JPEG save gives identical control over output size.

---

## Node Source Behavior to Reproduce

### extractor.js: Exact Call Flow

```
create_extractor(client, model, max_tokens, on_llm_call) -> {"extract": async_fn}

extract({captures, in_flight_draft, corpus_context, farmer_correction}):
  1. system = CACHEABLE_SYSTEM_BLOCKS (from prompts.py)
  2. few_shot = cacheable_few_shot()   (from prompts.py)
  3. user_content = build_initial_user_content(...)
     - Prepends: tool_result closing tu_fewshot_6 ("accepted")
     - Appends:  corpus_context block (if non-null)
     - Appends:  in-flight draft block
     - Appends:  farmer_correction block (if non-empty)
     - Appends:  per-capture content blocks (text, transcript, image blocks)
  4. messages = [...few_shot, {"role": "user", "content": user_content}]
  5. base_req = {model, max_tokens, system, tools=[tool_spec], tool_choice, messages}
  6. resp = await callWithObserver(base_req, capture_id)   -- on SDK error -> {ok:false}
  7. tool_use = find_tool_use_block(resp)                  -- if None -> {ok:false, reason:'no_tool_use'}
  8. parsed = Submission.model_validate(tool_use.input)    -- if ValidationError:
       assistant_turn = {role:'assistant', content:resp.content}
       retry_user_turn = {role:'user', content:[tool_result(is_error=True, tool_use_id, errors)]}
       retry_req = {...base_req, messages:[...messages, assistant_turn, retry_user_turn]}
       resp2 = await callWithObserver(retry_req, capture_id)  -- on SDK error -> {ok:false}
       tool_use2 = find_tool_use_block(resp2)
       if not tool_use2: return {ok:false, reason:'no_tool_use'}
       parsed2 = Submission.model_validate(tool_use2.input)
       if ValidationError: return {ok:false, reason:'schema_invalid', errors, raw_first, raw_retry}
  9. return pack_result(parsed, usage_sum)
     -> {ok:True, drafts, continuity_decision, continuity_reason, draft, per_field_confidence, capture_kind, usage}
```

The `on_llm_call` observer fires for BOTH the initial and retry call (via `call_with_observer` wrapper). Observer errors are caught + warn-logged, never propagated.

### multimodal.js: Image Block Assembly

```
read_image_to_base64(image_path) -> {ok, data, media_type} | {ok:False, reason}
  - Read file bytes
  - mime_from_path(path) -> image/jpeg | image/png | application/octet-stream
  - downscale_if_needed(buf, mime_type) -> {ok, buffer, media_type}
  - Return {ok:True, data:base64_str, media_type}
  - Fail-open on any exception: return {ok:False, reason} (caller skips this image)

build_content_blocks({text, transcript, images}) -> list[block]
  - text block (if non-empty text)
  - transcript block (if non-empty transcript): "Transcript: {transcript}"
  - per image in images: {type:"image", source:{type:"base64", media_type, data}}
  - (images here are already-resolved {data, media_type} objects, NOT paths)
```

**pipeline.js pattern for path->block resolution (the BUG FIX from 2026-05-12):**
The extractor receives already-resolved `{data, media_type}` image dicts. Path-to-base64 resolution happens in `pipeline.py` (the orchestrator), NOT inside the extractor or multimodal. The pipeline calls `read_image_to_base64(path)` for each path, collects the resulting blocks, and passes them into `captures[{images: [blocks]}]`.

### seq-helper.js: SEQ Helpers

```
mint_child_block_names({event_date_yymmdd, species_code, start_seq, qty}) -> list[str]
  - yields qty consecutive names: f"{yymmdd}_{species_code}_{start_seq + i}"
  - each validated via re.fullmatch(BLOCK_NAME_RE, name) -- raises on mismatch

yyyymmdd_to_yymmdd(event_date: str "YYYY-MM-DD") -> str "YYMMDD"
  - e.g. "2026-05-22" -> "260522"

lookup_last_seq_for_date(pool, event_date) -> {ok, last_seq, source}
  - Queries signal_draft WHERE status IN ('committed','awaiting_farmer','confirmed','pending')
    AND draft_json->>'event_date' = $1
  - Walks both legacy seeding.block_name AND seeding_session.groups[].child_block_names.value[]
  - Returns MAX SEQ across all rows, or None if no rows
  - skip-on-error per row (single malformed draft must not crash lookup)
  - 'NEEDS_SEQ' sentinel explicitly excluded from parsing
```

**Per-session SEQ counter rule (memory: `b5-seq-is-per-session-not-per-strain`):** KOY starts at 4 in the May-22 fixture, NOT 1. The counter spans species within a single session. `mint_child_block_names` receives `start_seq` from the running counter; the caller advances `counter += qty` after each group.

### pipeline.js: Continuity Emission and Draft Persistence

Phase 60 ports the extractor's EMISSION of the continuity decision; the full pipeline persistence state-machine integration is out of scope for the extractor module but must be understood for the tests. Key behaviors:
- `continuity` = one of `"append"`, `"replace"`, `"start_new"` (from `Submission.continuity`)
- Hard 30-min idle-gap guard: if `inFlight.last_updated_at_ms` is > 30 min ago, force `start_new`
- `seeding_session` with `draft.needs_input == "starting_seq"` -> AWAITING_FARMER path; pipeline dispatches `send_starting_seq_askback` (Phase 61)
- `batch mode` (drafts.length > 1 or seeding_session in multi-draft): force start_new, persist N rows, no per-draft ask-back

---

## Public Names and Paths: Already-Ported Pydantic Schemas

**Module:** `farm_agent/extraction/schemas/`

The extractor MUST import from these existing modules. Do NOT re-port or modify.

```python
from farm_agent.extraction.schemas.submission import (
    Submission,            # top-level model_validate target
    SUBMISSION_JSON_SCHEMA,# passed as input_schema in the tool spec
    DraftSubmission,       # each element of Submission.drafts
)
from farm_agent.extraction.schemas.seeding import (
    BLOCK_NAME_RE,         # r"^[0-9]{6}_[A-Z]{2,4}_[0-9]+$"
)
from farm_agent.extraction.schemas.provenance import (
    Provenanced,           # generic wrapper {value, confidence, sources[]}
    SourceEnum,            # Literal["audio","paper_log_photo","bag_label_photo","text","model_inference"]
)
from farm_agent.extraction.schemas.seeding_session import (
    SeedingSession,        # type Literal["seeding_session"] + event_date + groups + needs_input
    SeedingSessionGroup,   # parent + species + qty + child_block_names (all Provenanced[T])
)
```

**Key schema facts:**
- `Submission.model_json_schema()` is exported as `SUBMISSION_JSON_SCHEMA` -- pass directly as `input_schema` in the tool spec (pydantic v2 emits `type: object` at the root, unlike the Node zod-to-json-schema which needed `inlineTopLevelRef`).
- `BLOCK_NAME_RE = r"^[0-9]{6}_[A-Z]{2,4}_[0-9]+$"` -- use `re.fullmatch()` NOT `re.match()` or `re.search()`.
- `Submission.drafts` is `list[DraftSubmission]` with `min_length=1`.
- `DraftSubmission.draft` is `DraftUnion` (discriminated by `type` field).
- `SeedingSession.needs_input` is `OptStartingSeq` (optional `Literal["starting_seq"]`).
- All models have `extra="forbid"` -- any extra key in `tool_use.input` fails validation.

---

## Architecture Patterns

### System Architecture Diagram

```
Signal message
     |
     v
[Capture Pipeline] -- attachment paths --> [pipeline.py (Phase 60 scope)]
                                                |
                                    1. lookup in-flight draft
                                    2. idle-gap guard (30 min)
                                    3. load image blocks
                                       [multimodal.py]
                                       path -> read_image_to_base64
                                               -> Pillow downscale (if >1.15MP or >5MB)
                                               -> base64 encode
                                               -> {data, media_type}
                                    4. call extractor
                                       [extractor.py]
                                       build_initial_user_content
                                          (tool_result tu_fewshot_6 closer,
                                           corpus_context, in-flight, captures)
                                       messages.create (Sonnet, forced submit_extraction)
                                            |
                                       pydantic Submission.model_validate
                                            |
                                      valid? --(yes)-->  pack_result
                                            |
                                           (no)
                                            |
                                       retry turn (tool_result is_error=True)
                                       messages.create (retry)
                                            |
                                      valid? --(yes)--> pack_result
                                            |
                                           (no)
                                            v
                                       {ok:False, reason:'schema_invalid'}
                                    5. resolve continuity decision
                                    6. SEQ lookup/mint (seq_helper.py)
                                    7. persist draft -> signal_draft
                                    8. dispatch side effects
```

### Recommended Project Structure

```
src/farm-agent/farm_agent/extraction/
├── __init__.py               # (empty or re-export)
├── extractor.py              # NEW: create_extractor factory, 2-call retry
├── multimodal.py             # NEW: read_image_to_base64, build_content_blocks
├── prompts.py                # NEW: CACHEABLE_SYSTEM_BLOCKS, cacheable_few_shot()
├── seq_helper.py             # NEW: mint_child_block_names, lookup_last_seq_for_date
└── schemas/                  # ALREADY PORTED -- do not modify
    ├── __init__.py
    ├── _types.py
    ├── activity.py
    ├── harvest.py
    ├── input.py
    ├── observation.py
    ├── provenance.py
    ├── seeding.py
    ├── seeding_session.py
    └── submission.py

src/farm-agent/tests/
├── conftest.py               # EXTEND: FakeAnthropicClient for Messages API tool_use + retry
├── fixtures/
│   └── extraction/
│       └── seeding-session-may22/   # NEW: copy from Node fixture dir
│           ├── transcript.txt
│           ├── paper-log.jpg
│           ├── text-followup.txt
│           └── expected-draft.json
└── extraction/
    ├── test_extractor.py         # NEW: hermetic mocked tool_use unit test
    ├── test_multimodal.py        # NEW: Pillow downscale + base64 assembly
    └── test_seq_helper.py        # NEW: pure mint + lookup tests
```

### Pattern 1: Never-Throws Factory (mirroring Phase 59)

```python
# Source: farm_agent/gate/classifier.py (Phase 59)
def create_extractor(
    client: anthropic.AsyncAnthropic,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 16384,
    on_llm_call=None,
    log: logging.Logger | None = None,
) -> dict:
    _log = log or logger

    async def extract(captures, in_flight_draft=None, corpus_context=None) -> dict:
        try:
            # ... build messages, call SDK ...
        except Exception as e:
            _log.warning("[extractor] degraded: %s", e)
            return {"ok": False, "reason": str(e)}

    return {"extract": extract}
```

### Pattern 2: tool_result Retry Turn

```python
# After first LLM call fails pydantic validation:
assistant_turn = {"role": "assistant", "content": resp.content}
retry_user_turn = {
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": block.id,
            "is_error": True,
            "content": format_validation_errors(errors),
        }
    ],
}
retry_messages = [*messages, assistant_turn, retry_user_turn]
```

### Pattern 3: Attribute Access on Response Objects

```python
# resp.content is a list of SDK response objects -- use ATTRIBUTE access, NOT dict keys
for block in resp.content:
    if block.type == "tool_use" and block.name == TOOL_NAME:
        return block   # block.id, block.input, block.type, block.name are attributes
```

This was documented as Phase 59 Pitfall 5 and is equally applicable here.

### Pattern 4: Pillow Downscale (fail-open)

```python
async def read_image_to_base64(image_path: str, log=None) -> dict:
    try:
        buf = Path(image_path).read_bytes()
        media_type = mime_from_path(image_path)
        if media_type in ("image/jpeg", "image/png"):
            buf, media_type = downscale_if_needed(buf, media_type)
        return {"ok": True, "data": base64.b64encode(buf).decode("ascii"), "media_type": media_type}
    except Exception as e:
        (log or logger).warning("[multimodal] read degraded: %s", e)
        return {"ok": False, "reason": str(e)}
```

### Anti-Patterns to Avoid

- **Passing `timeout` as a body kwarg:** `messages.create(..., timeout=30)` -- SDK 400. Use `client.with_options(timeout=30.0).messages.create(...)`.
- **Dict access on response blocks:** `resp.content[0]["type"]` -- AttributeError. Use `resp.content[0].type`.
- **`re.match()` for BLOCK_NAME_RE:** matches prefix, not full string. `260522_SHI_1_EXTRA` would pass. Use `re.fullmatch()`.
- **Not closing the tu_fewshot_6 tool_use:** The first user turn MUST prepend a `tool_result` block with `tool_use_id: "tu_fewshot_6"` to close the last few-shot assistant turn. Anthropic 400s when any tool_use in an assistant turn lacks a following tool_result.
- **Saving RGBA image as JPEG:** Pillow raises `OSError: cannot write mode RGBA as JPEG`. Convert with `img.convert("RGB")` before saving if mode is not RGB.
- **Re-porting the schemas:** Phase 56 FND-04 already ported and tested. The parity test `test_schema_parity.py` must stay green.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Image resize / re-encode | Custom JPEG byte manipulation | `Pillow Image.resize + save` | Edge cases: EXIF, color modes, progressive JPEG |
| JSON Schema generation | Manually write the tool input_schema | `Submission.model_json_schema()` | Already ported; parity-tested via FND-04 |
| Schema validation | Custom dict-walk validator | `Submission.model_validate(block.input)` raises `ValidationError` with structured errors | Pydantic catches nested errors, type coercion, `extra='forbid'` |
| Tool result retry text | Custom error formatter | `str(e)` from `ValidationError` or list of `e.errors()` | Pydantic error format is already structured |

**Key insight:** The schema validation, JSON Schema emission, and error formatting are all handled by the already-ported pydantic models. The extractor's job is purely wiring, not schema logic.

---

## File-by-File Implementation Map

### `farm_agent/extraction/extractor.py` (NEW)

- Factory: `create_extractor(client, model, max_tokens, on_llm_call)` -> `{"extract": extract}`
- Constants: `TOOL_NAME = "submit_extraction"`, `TOOL_DESCRIPTION`
- Functions:
  - `build_tool_spec()` -- uses `SUBMISSION_JSON_SCHEMA` directly (no `inlineTopLevelRef` needed; pydantic v2 emits `type:object` at root)
  - `build_initial_user_content(captures, in_flight_draft, corpus_context, farmer_correction)` -- builds the user turn with the tu_fewshot_6 closer, context blocks, and per-capture content blocks
  - `find_tool_use_block(resp)` -- attribute access on `resp.content`
  - `call_with_observer(req, capture_id)` -- wraps `messages.create`, fires `on_llm_call` (both initial + retry)
  - `pack_result(submission, usage)` -- expands `Submission` into `{ok, drafts, continuity_decision, continuity_reason, draft, per_field_confidence, capture_kind, usage}`
  - `sum_usage(list)` -- sums `{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}`
  - inner `extract(...)` -- the never-throws async function
- Import: `Submission, SUBMISSION_JSON_SCHEMA` from `farm_agent.extraction.schemas.submission`
- Import: `CACHEABLE_SYSTEM_BLOCKS, cacheable_few_shot` from `farm_agent.extraction.prompts`
- Import: `build_content_blocks` from `farm_agent.extraction.multimodal`

### `farm_agent/extraction/multimodal.py` (NEW)

- Constants: `MAX_BYTES = 5 * 1024 * 1024`, `MAX_PIXELS = 1_150_000`
- Functions:
  - `mime_from_path(p: str) -> str` -- extension-based: `.jpg`/`.jpeg` -> `image/jpeg`, `.png` -> `image/png`, else `application/octet-stream`
  - `downscale_if_needed(buf, media_type) -> tuple[bytes, str]` -- Pillow resize + JPEG re-encode; `convert("RGB")` before JPEG save; never throws (caller wraps)
  - `read_image_to_base64(image_path, log) -> dict` -- fail-open: `{ok, data, media_type}` or `{ok:False, reason}`
  - `build_content_blocks({text, transcript, images}) -> list[dict]` -- text block, transcript block (`"Transcript: ..."`), image blocks from `{data, media_type}` objects

### `farm_agent/extraction/prompts.py` (NEW)

- `SYSTEM_PROMPT: str` -- verbatim copy of the SYSTEM_PROMPT array from `src/agents/alerter/src/extraction/prompts/system.js` (joined with `\n`)
- `CACHEABLE_SYSTEM_BLOCKS: list[dict]` -- `[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]`
- `FEW_SHOT: list[dict]` -- verbatim copy of the few-shot turns from `system.js`; the last few-shot assistant turn uses tool_use_id `tu_fewshot_6`
- `cacheable_few_shot() -> list[dict]` -- returns a copy of FEW_SHOT (or FEW_SHOT directly)
- **Critical:** the few-shot turns include `tool_result` blocks that close prior few-shot `tool_use` blocks. Copy the structure verbatim -- do not simplify or omit.

### `farm_agent/extraction/seq_helper.py` (NEW)

- `BLOCK_NAME_RE` imported from `farm_agent.extraction.schemas.seeding`
- `EVENT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")`
- Functions:
  - `yyyymmdd_to_yymmdd(event_date: str) -> str` -- raises on bad input (mirrors Node)
  - `mint_child_block_names(event_date_yymmdd, species_code, start_seq, qty) -> list[str]` -- raises `ValueError("mint_invalid_block_name: ...")` on `re.fullmatch` failure
  - `seq_of(block_name: str) -> int | None` -- parses trailing SEQ; returns None for `"NEEDS_SEQ"` or non-matching
  - `extract_seqs_from_row(draft_json: dict) -> list[int]` -- walks both `seeding.block_name` and `seeding_session.groups[].child_block_names.value[]`; skip-on-error
  - `async lookup_last_seq_for_date(pool, event_date, log) -> dict` -- `{ok, last_seq, source}` or `{ok:False, reason}`

### `tests/conftest.py` (EXTEND)

Add `FakeAnthropicClientForExtractor` (or extend `FakeAnthropicClient`) to support:
- Multi-call behavior: first call returns a `tool_use` block with invalid input; second call returns a valid `tool_use` block (for retry path test)
- Configurable sequence of responses (list of `tool_input` dicts, one per call)
- `block.name = "submit_extraction"` (not `"classify_capture"`)
- `block.id` must be a distinct string for each call (to pair `tool_use_id` in retry turn)

Example shape:
```python
class FakeAnthropicClientForExtractor:
    def __init__(self, responses: list[dict]):
        # responses = [{"tool_input": {...}}, {"tool_input": {...}}] or {"raise": exc}
        self.call_index = 0
        self.responses = responses
        self.calls = []

    def with_options(self, **kwargs):
        return self

    @property
    def messages(self):
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.responses[self.call_index]
        self.call_index += 1
        # return MagicMock with block.type="tool_use", block.name="submit_extraction",
        # block.id="tu_call_N", block.input=r["tool_input"]
```

### `tests/fixtures/extraction/seeding-session-may22/` (NEW)

Copy from: `src/agents/alerter/test/fixtures/seeding-session-may22/`
- `transcript.txt`
- `paper-log.jpg`
- `text-followup.txt`
- `expected-draft.json`

### `tests/extraction/test_extractor.py` (NEW)

Hermetic unit tests (no real API calls):

1. **SC-1: Happy path** -- single mocked `tool_use` response with valid Submission JSON; assert `result.ok == True`, `len(result.drafts) == 1`, `result.continuity_decision` present.

2. **SC-2: Retry resolves** -- first call returns invalid tool_use (missing required field); second call returns valid Submission; assert `result.ok == True`, confirm two calls were made (`len(client.calls) == 2`), confirm retry turn had `tool_result` block with `is_error=True` and correct `tool_use_id`.

3. **SC-3: Terminal failure** -- both calls return invalid; assert `result.ok == False`, `result.reason == "schema_invalid"`, no exception raised, `result.raw_first` and `result.raw_retry` present.

4. **SC-4: SDK error** -- `with_options(...).messages.create()` raises `Exception("network error")`; assert `result.ok == False`, `result.reason` contains the error, no exception propagated.

5. **Fixture integration** -- load `expected-draft.json`, wrap in valid `Submission` envelope, feed to mocked client; assert `result.drafts[0].draft.type == "seeding_session"`, `len(result.drafts[0].draft.groups) == 5`, total children == 11, exact block names match `["260522_SHI_1","260522_SHI_2","260522_SHI_3","260522_KOY_4","260522_KOY_5","260522_KOY_6","260522_KOY_7","260522_KOY_8","260522_KOY_9","260522_KOY_10","260522_KOY_11"]`, per-field provenance present on each group field.

**Assert child names, not parent attribution.** The KOY parent in the fixture (`260118_KOY_12` vs `260425_KOY_4`) is intentionally ambiguous in the source audio -- the child block names are the locked regression guard.

### `tests/extraction/test_seq_helper.py` (NEW)

Pure unit tests (no async pool needed for `mint_child_block_names`):
- `mint_child_block_names("260522", "SHI", 1, 3)` -> `["260522_SHI_1", "260522_SHI_2", "260522_SHI_3"]`
- `mint_child_block_names("260522", "KOY", 4, 4)` -> `["260522_KOY_4", "260522_KOY_5", "260522_KOY_6", "260522_KOY_7"]`
- `mint_child_block_names("260522", "SHI", 1, 1)` with lowercase `"shi"` raises `ValueError`
- `re.fullmatch(BLOCK_NAME_RE, "260522_SHI_1_EXTRA")` is None (rejects)
- `re.fullmatch(BLOCK_NAME_RE, "260522_SHI_1")` is not None (passes)
- `yyyymmdd_to_yymmdd("2026-05-22")` == `"260522"`
- `lookup_last_seq_for_date` tests require pool fixture (skip when no test DB)

### `pyproject.toml` (MODIFY)

Add to `dependencies`:
```toml
"Pillow>=10.0",
```

---

## Validation Architecture

> `workflow.nyquist_validation` is not explicitly set to false in `.planning/config.json`; section is included.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1 + pytest-asyncio |
| Config file | `src/farm-agent/pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/extraction/ -x` |
| Full suite command | `uv run pytest tests/` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| XTR-01 | Multimodal content blocks assembled (text + transcript + image) | unit | `pytest tests/extraction/test_multimodal.py -x` | No -- Wave 0 |
| XTR-01 | Cacheable system prompt blocks have `cache_control: ephemeral` | unit | `pytest tests/extraction/test_extractor.py::test_system_prompt_cache_control -x` | No -- Wave 0 |
| XTR-01 | Happy-path extractor call returns `{ok, drafts, continuity_decision}` | unit | `pytest tests/extraction/test_extractor.py::test_happy_path -x` | No -- Wave 0 |
| XTR-02 | Retry turn carries `tool_result is_error=True` with correct `tool_use_id` | unit | `pytest tests/extraction/test_extractor.py::test_retry_resolves -x` | No -- Wave 0 |
| XTR-02 | Second failure -> `{ok:False, reason:'schema_invalid'}`, no exception | unit | `pytest tests/extraction/test_extractor.py::test_terminal_failure -x` | No -- Wave 0 |
| XTR-02 | May-22 fixture: 5 groups, 11 children, correct block names | unit (mocked) | `pytest tests/extraction/test_extractor.py::test_may22_fixture -x` | No -- Wave 0 |
| XTR-02 | Per-field provenance present on each SeedingSessionGroup field | unit (mocked) | `pytest tests/extraction/test_extractor.py::test_may22_fixture -x` | No -- Wave 0 |
| XTR-03 | `mint_child_block_names` produces correct consecutive names | unit | `pytest tests/extraction/test_seq_helper.py -x` | No -- Wave 0 |
| XTR-03 | `re.fullmatch` rejects `260522_SHI_1_EXTRA` | unit | `pytest tests/extraction/test_seq_helper.py::test_block_name_re -x` | No -- Wave 0 |
| FND-04 | Submission JSON schema structural diff still passes | unit | `pytest tests/test_schema_parity.py -x` | Yes -- re-run |

### Sampling Rate
- **Per task commit:** `pytest tests/extraction/ -x`
- **Per wave merge:** `uv run pytest tests/`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/extraction/__init__.py` -- package init
- [ ] `tests/extraction/test_extractor.py` -- XTR-01, XTR-02
- [ ] `tests/extraction/test_multimodal.py` -- XTR-01 (image assembly)
- [ ] `tests/extraction/test_seq_helper.py` -- XTR-03
- [ ] `tests/fixtures/extraction/seeding-session-may22/` -- fixture files (copy from Node)
- [ ] FakeAnthropicClientForExtractor in `tests/conftest.py` -- multi-call sequence
- [ ] `Pillow>=10.0` in `pyproject.toml` -- runtime dep

**Real-Sonnet live-fire test** (`@pytest.mark.live_fire`): marker already defined in `[tool.pytest.ini_options]`. Skipped unless `ANTHROPIC_API_KEY + EXTRACTION_LIVE_FIRE=1`. DEFERRED -- operator-run, like Phase 58/59.

---

## Common Pitfalls

### Pitfall 1: tool_result tool_use_id Pairing

**What goes wrong:** The retry user turn's `tool_use_id` references the wrong id, or `block.id` is used instead of `block.name` (or vice versa).

**Root cause:** The `tool_use` block has BOTH an `id` attribute (e.g., `"toolu_01ABC..."`) and a `name` attribute (e.g., `"submit_extraction"`). The `tool_result` block's `tool_use_id` must match the `id` of the paired `tool_use` block -- not the tool name.

**How to avoid:** `retry_block["tool_use_id"] = block.id` (the `id` attribute, not `block.name`).

**Warning signs:** Anthropic 400 `"tool_use_id ... does not match any tool_use in conversation"`.

### Pitfall 2: Image base64 media_type Mismatch

**What goes wrong:** An image is loaded as PNG but sent with `media_type: "image/jpeg"` (or vice versa), causing Anthropic to fail to decode it.

**Root cause:** Downscaling always re-encodes to JPEG. After downscale, the `media_type` returned from `downscale_if_needed` is `"image/jpeg"` regardless of the original format. If the caller uses the original mime_type from the path, the content block carries mismatched `media_type`.

**How to avoid:** Always use the `media_type` returned from `downscale_if_needed`, not the one from `mime_from_path`. The downscale function normalizes both `buffer` and `media_type` together.

**Warning signs:** Anthropic API error `"image data is not valid for the specified media_type"`.

### Pitfall 3: RGBA -> JPEG Conversion

**What goes wrong:** `img.save(out, format="JPEG")` raises `OSError: cannot write mode RGBA as JPEG`.

**Root cause:** PNG images with transparency (mode `RGBA`) cannot be saved as JPEG. Pillow does not auto-convert.

**How to avoid:** Before `save(format="JPEG")`, check `if img.mode in ("RGBA", "LA", "P"): img = img.convert("RGB")`.

**Warning signs:** `OSError: cannot write mode RGBA as JPEG` raised inside `downscale_if_needed`.

### Pitfall 4: cache_control Token Threshold

**What goes wrong:** The system prompt is too short and falls below the prompt-cache threshold, silently disabling caching. No error is raised -- the prompt is just sent and billed as uncached.

**Root cause:** Anthropic requires >= 1024 tokens for Sonnet caching (Haiku is >= 2048). The Phase 59 system prompt was explicitly padded to exceed the Haiku threshold (gate/prompts.py: "Do NOT shorten this string").

**How to avoid:** Port the Node system prompt verbatim. The extraction system prompt is significantly longer than the gate prompt and should exceed the threshold. Verify via `usage.cache_creation_input_tokens > 0` on the first call.

**Warning signs:** `usage.cache_creation_input_tokens == 0` and `usage.cache_read_input_tokens == 0` on every call.

### Pitfall 5: Never-Throws on Second Failure

**What goes wrong:** `Submission.model_validate(block2.input)` raises `ValidationError`, which propagates out of `extract()` as an unhandled exception.

**Root cause:** pydantic v2 `model_validate` raises `ValidationError` (not returns `None`). Must be caught explicitly.

**How to avoid:** Wrap the second `model_validate` in `try: ... except ValidationError as e: return {ok: False, reason: "schema_invalid", errors: e.errors(), ...}`.

**Warning signs:** Tests that inject invalid data for both calls see an uncaught exception rather than `{ok: False}`.

### Pitfall 6: SEQ is Per-Session, Not Per-Strain

**What goes wrong:** KOY block-names start at 1 in the test (expected `260522_KOY_4`), test fails.

**Root cause:** The SEQ counter is a per-session running counter that spans all species within a session. KOY starts at 4 because SHI used 1-3 first. There is no per-strain counter reset.

**How to avoid:** `mint_child_block_names` takes `start_seq` (the current running counter). The caller must advance `counter += qty` after EACH group, not reset per species. The fixture's expected draft is the locked regression guard -- assert child names, not parent attribution.

**Warning signs:** Child block names like `260522_KOY_1` instead of `260522_KOY_4`.

### Pitfall 7: Attribute Access vs Dict Access on Anthropic Response

**What goes wrong:** `block["type"]` raises `KeyError` or `block["input"]` raises.

**Root cause:** `resp.content` is a list of pydantic-model objects in the Anthropic SDK, not plain dicts. Access via attributes: `block.type`, `block.name`, `block.id`, `block.input`.

**How to avoid:** `find_tool_use_block(resp)` uses `block.type == "tool_use"` and `block.name == TOOL_NAME`. This is already the established pattern from Phase 59 `classifier.py`.

### Pitfall 8: tu_fewshot_6 Tool Result Closer

**What goes wrong:** Anthropic returns 400 `"tool_use_id tu_fewshot_6 does not have a corresponding tool_result"`.

**Root cause:** The last few-shot turn in FEW_SHOT is an assistant turn with a `tool_use` block whose `tool_use_id` is `"tu_fewshot_6"`. Anthropic requires every `tool_use` block to be followed by a `tool_result` in the next user turn.

**How to avoid:** The first element of `build_initial_user_content()`'s output MUST be `{"type": "tool_result", "tool_use_id": "tu_fewshot_6", "content": [{"type": "text", "text": "accepted"}]}`. This is the Node pattern from `extractor.js:65-70`. Copy verbatim.

**Warning signs:** Anthropic 400 `"tool_use_id 'tu_fewshot_6' does not have a corresponding tool_result"`.

### Pitfall 9: SDK Timeout in Body vs. with_options

(Already documented as Phase 59 Pitfall 1 / D-03; re-stated here because extractor has a longer timeout than the gate and the trap is more likely to be forgotten.)

**What goes wrong:** `messages.create(..., timeout=60)` -> 400 `"timeout: Extra inputs are not permitted"`.

**How to avoid:** `client.with_options(timeout=60.0).messages.create(...)`.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Node.js extractor (Jimp for images) | Python extractor (Pillow for images) | Phase 60 | Pillow is the Python-ecosystem standard; API is similar to Jimp |
| Single-draft schema (`draft: Draft`) | Multi-draft schema (`drafts: list[DraftSubmission]`) | Node Phase 38 Plan 08 | Python must use `Submission.drafts[]` not `Submission.draft` |
| zod `safeParse` for validation | pydantic `model_validate` | Phase 56 FND-04 | `model_validate` raises `ValidationError`; must be caught |
| `zodToJsonSchema` wraps in `{$ref, definitions}` requiring `inlineTopLevelRef` | pydantic `model_json_schema()` emits `type: object` directly | Phase 56 FND-04 | Python skips the `inlineTopLevelRef` workaround |
| Node's `inlineTopLevelRef` in buildToolSpec | Pass `SUBMISSION_JSON_SCHEMA` directly | Phase 60 | Simpler Python tool spec assembly |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pillow is tag `[ASSUMED]` per package policy (slopcheck unavailable); extremely high confidence in legitimacy | Standard Stack / Package Audit | Near-zero risk; Pillow is a PyPA-recognized library with 12+ years history |
| A2 | cache_control threshold for Sonnet is >= 1024 tokens | Framework Quick Reference (cache_control) | If threshold is higher, caching silently disabled; verify via `usage.cache_creation_input_tokens > 0` |
| A3 | stdlib base64, io, re, pathlib are available in Python 3.12-slim Docker image | Standard Stack | These are always-available stdlib modules; risk is negligible |

---

## Open Questions (RESOLVED)

> Both resolved at plan time (2026-06-26). Q1 is verified at runtime by the live-fire cache-liveness assertion; Q2 is implemented per the 60-03 plan action.

1. **cache_control threshold for claude-sonnet-4-6 specifically** — RESOLVED: verify via `usage.cache_creation_input_tokens > 0` in the deferred live-fire (60-04); the verbatim long system prompt + `cache_control: ephemeral` is the mitigation regardless of the exact tier threshold.
   - What we know: Anthropic docs state >= 1024 tokens for "Claude 3" family; Haiku 4.5 required >= 2048 (per gate/prompts.py comment: "conservative proxy for the >= 4,096-token cache threshold"). The extraction system prompt is long (>200 lines) and almost certainly exceeds any threshold.
   - What's unclear: Whether the threshold differs by model tier (Sonnet vs Haiku) for the claude-sonnet-4-6 model ID.
   - Recommendation: Verify via `usage.cache_creation_input_tokens > 0` on the first real API call. If 0, system prompt needs expansion.

2. **`on_llm_call` observer: async or sync?** — RESOLVED: accept `Callable | None`; if `inspect.iscoroutinefunction(on_llm_call)` (or the result is a coroutine), `await` it, else call directly; errors in the observer are caught + logged WARNING. Implemented per the 60-03 plan action.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | farm-agent runtime | confirmed (pyproject.toml) | 3.12 | -- |
| anthropic SDK | extractor.py | confirmed in pyproject.toml | 0.112.0 | -- |
| pydantic v2 | schemas + validation | confirmed in pyproject.toml | >=2.13 | -- |
| Pillow | multimodal.py | not yet in pyproject.toml | 12.2.0 (latest) [VERIFIED: PyPI] | -- |
| pytest-asyncio | tests | confirmed in pyproject.toml dev deps | >=1.4 | -- |
| Node fixture files | test fixture | present at `src/agents/alerter/test/fixtures/seeding-session-may22/` | -- | copy required |

**Missing dependencies with no fallback:**
- `Pillow>=10.0` must be added to `pyproject.toml` before `multimodal.py` is runnable.

**Missing dependencies with fallback:**
- None.

---

## Security Domain

> `security_enforcement` key absent from `.planning/config.json`; treating as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | yes | pydantic `Submission.model_validate` with `extra='forbid'`; tool_use.input is untrusted LLM output |
| V6 Cryptography | no | -- |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via farmer text / transcript | Tampering | Farmer content goes in `messages[]` (separate user turn), never concatenated into `CACHEABLE_SYSTEM_BLOCKS` (T-44-04-01; same mitigation as classifier) |
| LLM output schema bypass | Tampering | pydantic `model_validate` with `extra='forbid'` on every nested model; `ValidationError` triggers retry or `{ok:False}` |
| API key disclosure in logs | Information Disclosure | Injected `AsyncAnthropic` client owns the key; extractor never logs it (T-56-06-01 pattern) |
| Image path traversal | Tampering | Image paths come from the capture pipeline (already validated at CAP-01); no path construction in multimodal.py |
| PII in logs | Information Disclosure | Log WARNING on image load failure logs only the path and reason, NOT the image content. Transcript/text WARNING logs log only the reason (same T-59-02-01 pattern) |

---

## Sources

### Primary (HIGH confidence)
- Node source: `src/agents/alerter/src/extraction/extractor.js` -- exact 2-call retry flow, callWithObserver, pack_result
- Node source: `src/agents/alerter/src/extraction/multimodal.js` -- MAX_BYTES, MAX_PIXELS, Jimp API, mime detection
- Node source: `src/agents/alerter/src/extraction/seq-helper.js` -- mint_child_block_names, lookup_last_seq_for_date, NEEDS_SEQ exclusion
- Node source: `src/agents/alerter/src/extraction/validator.js` -- buildToolResultRetry shape (is_error, tool_use_id, content as string)
- Node source: `src/agents/alerter/src/extraction/prompts/system.js` -- SYSTEM_PROMPT, FEW_SHOT structure, tu_fewshot_6
- Python source: `src/farm-agent/farm_agent/gate/classifier.py` -- factory blueprint, with_options, attribute access pattern
- Python source: `src/farm-agent/farm_agent/extraction/schemas/` -- all existing ported schemas (submission.py, seeding.py, seeding_session.py, provenance.py)
- Python source: `src/farm-agent/tests/conftest.py` -- FakeAnthropicClient extension point
- Fixture: `src/agents/alerter/test/fixtures/seeding-session-may22/expected-draft.json` -- locked regression anchor
- SDK type stubs: anthropic 0.112.0 `ToolResultBlockParam` (is_error: bool, tool_use_id: str, content: str|list) [VERIFIED: pip install + type_hints inspection]
- Pillow 12.2.0: Image.open, size, resize, convert, save API [VERIFIED: pip install + live test against fixture image]

### Secondary (MEDIUM confidence)
- Implicit from Phase 59 codebase: `cache_control: ephemeral` shape on system blocks; per-request timeout via `with_options`

### Tertiary (LOW confidence)
- cache_control minimum token threshold for claude-sonnet-4-6: stated as >= 1024 tokens for "Claude 3 family" in Anthropic docs, but not verified specifically for `claude-sonnet-4-6`. Marked as `[ASSUMED]` in Assumptions Log.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries confirmed installed and APIs tested live
- Architecture: HIGH -- Node source is the authoritative reference; fully read
- Pitfalls: HIGH -- most pitfalls are documented live bugs from the Node codebase history (extractor.js comments reference specific plan numbers where bugs were found and fixed)

**Research date:** 2026-06-26
**Valid until:** 2026-07-26 (stable; anthropic SDK breaking changes unlikely in 30 days)
