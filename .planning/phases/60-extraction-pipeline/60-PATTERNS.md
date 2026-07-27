# Phase 60: Extraction Pipeline - Pattern Map

**Mapped:** 2026-06-26
**Files analyzed:** 11 (4 new modules, 4 new test files, 2 modified files, 1 copied fixture dir)
**Analogs found:** 11 / 11

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `farm_agent/extraction/extractor.py` | service | request-response (LLM, 2-call) | `farm_agent/gate/classifier.py` | exact |
| `farm_agent/extraction/multimodal.py` | utility | file-I/O + transform | `src/agents/alerter/src/extraction/multimodal.js` | exact (cross-lang port) |
| `farm_agent/extraction/prompts.py` | config | static | `farm_agent/gate/prompts.py` | exact |
| `farm_agent/extraction/seq_helper.py` | utility | CRUD + transform | `src/agents/alerter/src/extraction/seq-helper.js` | exact (cross-lang port) |
| `farm_agent/extraction/schemas/` | model | — | already ported (Phase 56 FND-04) | do not modify |
| `farm_agent/boot.py` | config | — | itself (add two lines) | self |
| `pyproject.toml` | config | — | itself (add one dep line) | self |
| `tests/conftest.py` | test | — | `tests/conftest.py` `FakeAnthropicClient` class | exact |
| `tests/test_extraction_extractor.py` | test | — | `tests/test_gate_classifier.py` | exact |
| `tests/test_multimodal.py` | test | — | `tests/test_gate_classifier.py` (structure) | role-match |
| `tests/test_seq_helper.py` | test | — | `tests/test_gate_classifier.py` (structure) | role-match |
| `tests/test_extraction_fixture.py` | test | — | `tests/test_schema_parity.py` (fixture loading) | role-match |
| `tests/fixtures/extraction/seeding-session-may22/` | fixture | — | `src/agents/alerter/test/fixtures/seeding-session-may22/` | copy |

---

## Pattern Assignments

### `farm_agent/extraction/extractor.py` (service, request-response)

**Analog:** `src/farm-agent/farm_agent/gate/classifier.py`

**Imports pattern** (classifier.py lines 23-33):
```python
from __future__ import annotations

import json
import logging

import anthropic
from pydantic import BaseModel, Field, ValidationError

from farm_agent.gate.prompts import CACHEABLE_SYSTEM_BLOCKS

logger = logging.getLogger(__name__)
```

For extractor.py, swap the imports to:
```python
from farm_agent.extraction.prompts import CACHEABLE_SYSTEM_BLOCKS, cacheable_few_shot
from farm_agent.extraction.multimodal import build_content_blocks
from farm_agent.extraction.schemas.submission import Submission, SUBMISSION_JSON_SCHEMA
```

**Tool constant pattern** (classifier.py lines 39-55):
```python
TOOL_NAME = "classify_capture"
TOOL_DESCRIPTION = "Classify whether this capture is an event worth extracting."

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": TOOL_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": { ... },
        "required": [...],
        "additionalProperties": False,
    },
}
```
For extractor.py: `TOOL_NAME = "submit_extraction"`. The `input_schema` is `SUBMISSION_JSON_SCHEMA` directly (pydantic v2 emits `type:object` at root; no `inlineTopLevelRef` needed unlike the Node version).

**Factory signature pattern** (classifier.py lines 107-129):
```python
def create_haiku_classifier(
    client: anthropic.AsyncAnthropic,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 100,
    timeout_ms: int = 2000,
    log: logging.Logger | None = None,
) -> dict:
    _log = log or logger
    _timeout_s = timeout_ms / 1000

    async def classify(env_ctx: dict) -> dict:
        ...
    return {"classify": classify}
```
For extractor.py: `create_extractor(client, model="claude-sonnet-4-6", max_tokens=16384, on_llm_call=None, log=None) -> {"extract": extract}`.

**Single-call + fail-open pattern** (classifier.py lines 133-176):
```python
async def classify(env_ctx: dict) -> dict:
    try:
        resp = await client.with_options(timeout=_timeout_s).messages.create(
            model=model,
            max_tokens=max_tokens,
            system=CACHEABLE_SYSTEM_BLOCKS,
            tools=[TOOL_DEF],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": build_classifier_input(env_ctx)}],
        )
    except Exception as e:  # noqa: BLE001
        _log.warning("[haiku-classifier] degraded: %s", e)
        return {"ok": False, "reason": str(e), "fallthrough": "forced"}

    block = find_tool_use_block(resp)
    if block is None:
        return {"ok": False, "reason": "no_tool_use_in_response", "fallthrough": "forced"}

    try:
        parsed = Classification.model_validate(block.input)
    except ValidationError as e:
        _log.warning("[haiku-classifier] schema_invalid: %s", e)
        return {"ok": False, "reason": "schema_invalid", "fallthrough": "forced"}

    return {"ok": True, "is_event": parsed.is_event, ...}
```

**Extended 2-call retry pattern** (Node extractor.js lines 190-244) — add this between single-call validation failure and return:
```python
# After first call's pydantic ValidationError:
assistant_turn = {"role": "assistant", "content": resp.content}
retry_user_turn = {
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": block.id,        # block.id (NOT block.name)
            "is_error": True,
            "content": str(e),              # pydantic ValidationError str
        }
    ],
}
retry_req = {**base_req, "messages": [*messages, assistant_turn, retry_user_turn]}
# retry call uses same client.with_options(timeout=...).messages.create pattern
# on second ValidationError: return {ok:False, reason:"schema_invalid", errors, raw_first, raw_retry}
# NEVER raise from extract()
```

**find_tool_use_block helper** (classifier.py lines 88-99):
```python
def find_tool_use_block(response) -> object | None:
    if not response or not hasattr(response, "content"):
        return None
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block
    return None
```
Critical: `block.type`, `block.name`, `block.id`, `block.input` are ATTRIBUTE access on SDK objects, not dict keys.

**pack_result pattern** (Node extractor.js lines 250-270):
```javascript
function packResult(submission, usage) {
  const drafts = Array.isArray(submission.drafts) ? submission.drafts : [];
  const first = drafts[0] || null;
  return {
    ok: true,
    drafts,
    continuity_decision: submission.continuity,
    continuity_reason: submission.continuity_reason,
    draft: first ? first.draft : null,
    per_field_confidence: first ? first.per_field_confidence : null,
    capture_kind: submission.capture_kind != null ? submission.capture_kind : null,
    usage: usage || null,
  };
}
```

**buildInitialUserContent pattern** (Node extractor.js lines 54-96):
```javascript
function buildInitialUserContent({ captures, inFlightDraft, corpusContext, farmerCorrection }) {
  const blocks = [];
  // MANDATORY: close the last few-shot tool_use (tu_fewshot_6)
  blocks.push({
    type: 'tool_result',
    tool_use_id: 'tu_fewshot_6',
    content: [{ type: 'text', text: 'accepted' }],
  });
  if (corpusContext) blocks.push({ type: 'text', text: `corpus_context: ${JSON.stringify(corpusContext)}` });
  blocks.push({ type: 'text', text: `In-flight draft: ${inFlightDraft ? JSON.stringify(inFlightDraft) : 'none'}` });
  if (farmerCorrection && farmerCorrection.trim()) {
    blocks.push({ type: 'text', text: `Farmer correction: ${farmerCorrection.trim()}` });
  }
  for (const cap of captures) {
    for (const b of buildContentBlocks({ text: cap.text, transcript: cap.transcript, images: cap.images })) {
      blocks.push(b);
    }
  }
  return blocks;
}
```
The `tool_result` closer for `tu_fewshot_6` MUST be the first block — Anthropic 400s without it.

---

### `farm_agent/extraction/multimodal.py` (utility, file-I/O + transform)

**Analog:** `src/agents/alerter/src/extraction/multimodal.js`

**Constants + mime detection** (multimodal.js lines 17-26):
```javascript
const MAX_BYTES = 5 * 1024 * 1024;      // 5MB
const MAX_PIXELS = 1_150_000;           // 1.15MP

function mimeFromPath(p) {
  const ext = path.extname(p).toLowerCase();
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.png') return 'image/png';
  return 'application/octet-stream';
}
```

Python equivalent:
```python
from pathlib import Path
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 1_150_000

def mime_from_path(p: str) -> str:
    ext = Path(p).suffix.lower()
    if ext in (".jpg", ".jpeg"): return "image/jpeg"
    if ext == ".png": return "image/png"
    return "application/octet-stream"
```

**Pillow downscale pattern** (from 60-RESEARCH.md Framework Quick Reference):
```python
import math, io
from PIL import Image

def downscale_if_needed(buf: bytes, media_type: str) -> tuple[bytes, str]:
    """Never raises -- caller wraps in try/except."""
    img = Image.open(io.BytesIO(buf))
    w, h = img.size
    if len(buf) <= MAX_BYTES and w * h <= MAX_PIXELS:
        return buf, media_type
    scale = math.sqrt(MAX_PIXELS / (w * h))
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # CRITICAL: JPEG save fails on RGBA/LA/P images
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue(), "image/jpeg"  # always jpeg after downscale
```

**read_image_to_base64 fail-open pattern** (multimodal.js lines 59-74):
```javascript
async function readImageToBase64(imagePath) {
  try {
    const buf = await fs.readFile(imagePath);
    const mime = mimeFromPath(imagePath);
    const scaled = await downscaleIfNeeded(buf, mime);
    if (!scaled.ok) return scaled;
    return { ok: true, data: scaled.buffer.toString('base64'), media_type: scaled.media_type };
  } catch (e) {
    logger.warn(`[multimodal] read degraded: ${e.message}`);
    return { ok: false, reason: e.message };
  }
}
```
Python: use `Path(image_path).read_bytes()` + `base64.b64encode(buf).decode("ascii")`. Always use the `media_type` returned from `downscale_if_needed`, not the original from `mime_from_path`.

**build_content_blocks pattern** (multimodal.js lines 76-94):
```javascript
function buildContentBlocks({ text, transcript, images }) {
  const blocks = [];
  if (text && text.trim()) blocks.push({ type: 'text', text: String(text) });
  if (transcript && transcript.trim()) blocks.push({ type: 'text', text: `Transcript: ${transcript}` });
  for (const img of images || []) {
    if (!img || !img.data) continue;
    blocks.push({ type: 'image', source: { type: 'base64', media_type: img.media_type || 'image/jpeg', data: img.data } });
  }
  return blocks;
}
```
`images` here is a list of already-resolved `{data, media_type}` dicts, NOT paths. Path resolution happens in the pipeline caller before passing into `build_content_blocks`.

---

### `farm_agent/extraction/prompts.py` (config, static)

**Analog:** `src/farm-agent/farm_agent/gate/prompts.py`

**File-level structure** (gate/prompts.py lines 1-13):
```python
"""gate/prompts.py -- classifier prompt constants for the event-gate gray-zone classifier.

Foray island: no imports, no logic.  All three constants are copied verbatim
from src/agents/alerter/src/event-gate/prompts.js.
"""
```

**CACHEABLE_SYSTEM_BLOCKS pattern** (gate/prompts.py lines 408-410):
```python
CACHEABLE_SYSTEM_BLOCKS: list[dict] = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
]
```
For extraction/prompts.py, copy the same shape. Add a `cacheable_few_shot()` function that returns `FEW_SHOT` (the list of few-shot turns from Node `prompts/system.js`). The few-shot turns include `tool_result` blocks that close prior few-shot `tool_use` blocks — copy verbatim.

**Source of truth for content:** `src/agents/alerter/src/extraction/prompts/system.js` (SYSTEM_PROMPT array + FEW_SHOT). Do NOT abbreviate; cache threshold requires ~1024+ tokens for Sonnet.

---

### `farm_agent/extraction/seq_helper.py` (utility, transform + CRUD)

**Analog:** `src/agents/alerter/src/extraction/seq-helper.js`

**Module-level imports:**
```python
import re
import logging
from farm_agent.extraction.schemas.seeding import BLOCK_NAME_RE

EVENT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
logger = logging.getLogger(__name__)
```

**yyyymmdd_to_yymmdd** (seq-helper.js lines 24-33):
```javascript
function yyyymmddToYymmdd(eventDate) {
  const m = eventDate.match(EVENT_DATE_RE);
  if (!m) throw new Error(`yyyymmddToYymmdd: bad eventDate '${eventDate}'`);
  return `${m[1].slice(2)}${m[2]}${m[3]}`;
}
```
Python: `m = EVENT_DATE_RE.match(event_date)` then `f"{m.group(1)[2:]}{m.group(2)}{m.group(3)}"`. Raises `ValueError` on bad input.

**mint_child_block_names** (seq-helper.js lines 43-53):
```javascript
function mintChildBlockNames({ eventDateYYMMDD, speciesCode, startSeq, qty }) {
  const out = [];
  for (let i = 0; i < qty; i++) {
    const name = `${eventDateYYMMDD}_${speciesCode}_${startSeq + i}`;
    if (!BLOCK_NAME_RE.test(name)) throw new Error(`mint_invalid_block_name: ${name}`);
    out.push(name);
  }
  return out;
}
```
Python: use `re.fullmatch(BLOCK_NAME_RE, name)` (NOT `re.match`). `260522_SHI_1_EXTRA` must be rejected; `re.match` would silently pass it.

**seqOf / seq_of** (seq-helper.js lines 57-65):
```javascript
function seqOf(blockName) {
  if (blockName === 'NEEDS_SEQ') return null;
  if (!BLOCK_NAME_RE.test(blockName)) return null;
  const idx = blockName.lastIndexOf('_');
  return Number.isFinite(Number(blockName.slice(idx + 1))) ? Number(blockName.slice(idx+1)) : null;
}
```

**extract_seqs_from_row** (seq-helper.js lines 67-92) — skip-on-error per row:
```javascript
function extractSeqsFromRow(draftJson) {
  // type === 'seeding': parse draftJson.block_name
  // type === 'seeding_session': walk groups[].child_block_names.value[]
  // never throw; return partial list on exception
}
```

**lookup_last_seq_for_date** (seq-helper.js lines 108-133):
```javascript
async function lookupLastSeqForDate(pool, eventDate) {
  const r = await pool.query(
    `SELECT draft_json FROM signal_draft
      WHERE status IN ('committed','awaiting_farmer','confirmed','pending')
        AND draft_json->>'event_date' = $1`,
    [eventDate],
  );
  // walk rows, collect MAX SEQ, return {ok:true, lastSeq, source}
}
```
Python async equivalent: `await pool.execute(...)` with psycopg3 syntax. Fail-open: return `{ok: False, reason: str(e)}` on exception.

---

### `farm_agent/boot.py` (modified — inject extractor)

**Analog:** `farm_agent/boot.py` lines 78-86 (gate injection pattern):
```python
# Phase 59: shared AsyncAnthropic singleton + event-gate (one per daemon lifetime).
# T-56-06-01: api_key flows only into the constructor and is NEVER logged.
anthropic_client = anthropic.AsyncAnthropic(
    api_key=config.anthropic_api_key,
    max_retries=2,
)
gate = create_event_gate(
    haiku_classifier=create_haiku_classifier(client=anthropic_client),
    log=log,
)
```
For Phase 60: add `from farm_agent.extraction.extractor import create_extractor` to imports, then `extractor = create_extractor(client=anthropic_client)` after the gate wiring. Pass `extractor` into `create_capture_pipeline`. The same `anthropic_client` singleton is shared — do NOT create a second `AsyncAnthropic` instance.

---

### `pyproject.toml` (modified — add Pillow)

**Analog:** pyproject.toml lines 6-13 (existing deps block):
```toml
dependencies = [
    "anthropic>=0.45",
    "pydantic>=2.13",
    "psycopg[binary]>=3.3",
    ...
]
```
Add `"Pillow>=10.0",` to the `dependencies` list. Package checkpoint required before executor adds it (ubiquitous; Pillow is a PyPA member project, 12+ years on PyPI, ~40M/wk downloads).

---

### `tests/conftest.py` (modified — FakeAnthropicClientForExtractor)

**Analog:** `tests/conftest.py` `FakeAnthropicClient` class (lines 225-296):
```python
class FakeAnthropicClient:
    def __init__(self, tool_input=None, raise_exc=None, return_no_tool_use=False):
        self.tool_input = tool_input or self._DEFAULT_TOOL_INPUT
        self.raise_exc = raise_exc
        self.return_no_tool_use = return_no_tool_use
        self.calls: list[dict] = []

    def with_options(self, **kwargs) -> "FakeAnthropicClient":
        return self

    @property
    def messages(self) -> "FakeAnthropicClient":
        return self

    async def create(self, **kwargs) -> MagicMock:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        response = MagicMock()
        block = MagicMock()
        block.type = "tool_use"
        block.name = "classify_capture"
        block.input = self.tool_input
        response.content = [block]
        return response
```

For extractor tests, extend to support a **sequence of responses** (one per call):
```python
class FakeAnthropicClientForExtractor:
    def __init__(self, responses: list[dict]):
        # responses = [{"tool_input": {...}}, {"tool_input": {...}}] or [{"raise": exc}]
        self.responses = responses
        self.call_index = 0
        self.calls: list[dict] = []

    def with_options(self, **kwargs):
        return self

    @property
    def messages(self):
        return self

    async def create(self, **kwargs) -> MagicMock:
        self.calls.append(kwargs)
        r = self.responses[self.call_index]
        self.call_index += 1
        if "raise" in r:
            raise r["raise"]
        response = MagicMock()
        block = MagicMock()
        block.type = "tool_use"
        block.name = "submit_extraction"
        block.id = f"tu_call_{self.call_index}"   # distinct per call for tool_use_id pairing
        block.input = r["tool_input"]
        response.content = [block]
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0
        response.usage = usage
        return response
```

Add a `@pytest.fixture` for it alongside the existing `fake_anthropic_client` fixture.

---

### `tests/test_extraction_extractor.py` (new test file)

**Analog:** `tests/test_gate_classifier.py`

**Test file structure** (test_gate_classifier.py lines 1-35):
```python
"""Unit tests for farm_agent.gate.classifier -- create_haiku_classifier factory.

Covers:
  - success path
  - fail-open: no_tool_use_in_response
  - fail-open: schema_invalid
  - fail-open: api_error
  - call shape: tool_choice, user-message, with_options timeout
"""
from __future__ import annotations
import logging
import anthropic
import pytest
from tests.conftest import FakeAnthropicClient

def _make_classifier(client, **kwargs) -> dict:
    from farm_agent.gate.classifier import create_haiku_classifier
    return create_haiku_classifier(client=client, **kwargs)

@pytest.mark.asyncio
async def test_classify_success(fake_anthropic_client):
    ...
```

For extractor tests: replace `FakeAnthropicClient` with `FakeAnthropicClientForExtractor`. Assertions to cover per SC from 60-RESEARCH.md:

- **SC-1 happy path:** single valid tool_use -> `result["ok"] is True`, `len(result["drafts"]) == 1`
- **SC-2 retry resolves:** first call invalid, second valid -> `result["ok"] is True`, `len(client.calls) == 2`, second call's messages include a `tool_result` block with `is_error=True` and `tool_use_id == "tu_call_1"` (matches first call's block.id)
- **SC-3 terminal failure:** both calls invalid -> `result["ok"] is False`, `result["reason"] == "schema_invalid"`, `"raw_first" in result`, `"raw_retry" in result`, no exception propagated
- **SC-4 SDK error:** `raise_exc` set -> `result["ok"] is False`, no exception propagated
- **SC-5 no_tool_use:** empty content -> `result["ok"] is False`, `result["reason"] == "no_tool_use_in_response"`
- **SC-6 fixture integration:** wrap `expected-draft.json` in valid `Submission` envelope, feed to mocked client; assert `result["drafts"][0]["draft"]["type"] == "seeding_session"`, 5 groups, 11 children, exact block names `["260522_SHI_1","260522_SHI_2","260522_SHI_3","260522_KOY_4"..."260522_KOY_11"]`
- **call shape:** `tool_choice == {"type": "tool", "name": "submit_extraction"}`, `"timeout" not in kwargs` (Pitfall 9)
- **cache_control:** `system[0]["cache_control"] == {"type": "ephemeral"}`

---

### `tests/test_multimodal.py` (new test file)

**Analog:** `tests/test_gate_classifier.py` (structure; no close Python analog for image tests)

Tests to cover:
- `mime_from_path("photo.jpg")` -> `"image/jpeg"`, `"photo.PNG"` -> `"image/png"`, `"file.tiff"` -> `"application/octet-stream"`
- `build_content_blocks(text="hello", transcript=None, images=[])` -> single text block
- `build_content_blocks(text=None, transcript="words", images=[])` -> `"Transcript: words"` block
- `build_content_blocks(text=None, transcript=None, images=[{"data":"abc","media_type":"image/jpeg"}])` -> single image block
- `read_image_to_base64` with a nonexistent path -> `{ok: False}`, no exception
- Pillow downscale: load `tests/fixtures/extraction/seeding-session-may22/paper-log.jpg` (900x1600 = 1.44MP > 1.15MP), call `downscale_if_needed`, assert returned `media_type == "image/jpeg"` and `len(buf) < original_len`
- RGBA image: create a 100x100 RGBA PNG in memory, call `downscale_if_needed`, assert no exception and result is JPEG

---

### `tests/test_seq_helper.py` (new test file)

**Analog:** `tests/test_gate_classifier.py` (structure — pure functions, no async pool needed for mint tests)

Tests to cover (all pure, no DB):
- `yyyymmdd_to_yymmdd("2026-05-22")` == `"260522"`
- `yyyymmdd_to_yymmdd("bad-input")` raises `ValueError`
- `mint_child_block_names("260522", "SHI", 1, 3)` == `["260522_SHI_1", "260522_SHI_2", "260522_SHI_3"]`
- `mint_child_block_names("260522", "KOY", 4, 4)` == `["260522_KOY_4", "260522_KOY_5", "260522_KOY_6", "260522_KOY_7"]`
- `mint_child_block_names("260522", "shi", 1, 1)` raises `ValueError("mint_invalid_block_name")` (lowercase species fails BLOCK_NAME_RE)
- `re.fullmatch(BLOCK_NAME_RE, "260522_SHI_1_EXTRA")` is `None` (rejects)
- `re.fullmatch(BLOCK_NAME_RE, "260522_SHI_1")` is not `None` (passes)
- `seq_of("260522_KOY_4")` == 4; `seq_of("NEEDS_SEQ")` is `None`
- `extract_seqs_from_row({"type":"seeding","block_name":"260522_SHI_1"})` == `[1]`
- `extract_seqs_from_row({"type":"seeding_session","groups":[{"child_block_names":{"value":["260522_KOY_4","260522_KOY_5"]}}]})` == `[4, 5]`
- `lookup_last_seq_for_date` pool tests: skip when no test DB (`@pytest.mark.skipif(not pool_available)`)

---

### `tests/test_extraction_fixture.py` (new test file)

**Analog:** `tests/test_schema_parity.py` (fixture loading pattern, lines 26-30):
```python
from pathlib import Path
import json
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "submission_json_schema.json"

def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())
```

For extraction fixture test:
```python
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "extraction" / "seeding-session-may22"

def _load_expected_draft() -> dict:
    return json.loads((FIXTURE_DIR / "expected-draft.json").read_text())
```

Test: load `expected-draft.json`, validate it against `Submission.model_validate()` (proves parity with the real extractor schema). Assert: `submission.drafts[0].draft.type == "seeding_session"`, `len(submission.drafts[0].draft.groups) == 5`, child names sum == 11.

---

### `tests/fixtures/extraction/seeding-session-may22/` (copied fixture)

**Source:** `src/agents/alerter/test/fixtures/seeding-session-may22/`

Files to copy:
- `transcript.txt`
- `paper-log.jpg` (900x1600 = 1.44MP; confirms Pillow downscale fires in tests)
- `text-followup.txt`
- `expected-draft.json` (locked regression anchor — the child block names list is the parity gate)

Note: `README.md` from the source dir is optional.

---

## Shared Patterns

### Never-throws factory
**Source:** `src/farm-agent/farm_agent/gate/classifier.py` lines 107-177
**Apply to:** `extractor.py`

Every public `async def` returned from a factory must be wrapped in a top-level `try/except Exception` that catches all errors and returns `{"ok": False, "reason": str(e)}`. This includes the outermost body of `extract()`, separate from the inner retry try/catch blocks.

### with_options timeout (not body kwarg)
**Source:** `src/farm-agent/farm_agent/gate/classifier.py` line 146
**Apply to:** `extractor.py` (both initial call and retry call)
```python
resp = await client.with_options(timeout=_timeout_s).messages.create(...)
```
NEVER: `messages.create(..., timeout=60)` — SDK 400 "Extra inputs are not permitted".

### cache_control ephemeral on system blocks
**Source:** `src/farm-agent/farm_agent/gate/prompts.py` lines 408-410
**Apply to:** `extraction/prompts.py`
```python
CACHEABLE_SYSTEM_BLOCKS: list[dict] = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
]
```

### Attribute access on Anthropic response objects
**Source:** `src/farm-agent/farm_agent/gate/classifier.py` lines 88-99
**Apply to:** `extractor.py` (`find_tool_use_block` + retry turn assembly)

`resp.content` is a list of pydantic-model objects. Use `block.type`, `block.name`, `block.id`, `block.input` — NOT `block["type"]` etc. Only `block.input` is a plain dict (passed to `model_validate`).

### Pydantic ValidationError raises, not returns
**Source:** `src/farm-agent/farm_agent/gate/classifier.py` lines 163-167
**Apply to:** `extractor.py` (both initial validation and retry validation)
```python
try:
    parsed = Classification.model_validate(block.input)
except ValidationError as e:
    ...
```
`model_validate` RAISES on failure. Must be caught explicitly. Second failure must NOT propagate — return `{ok: False, ...}`.

### FakeAnthropicClient structure (with_options + messages property)
**Source:** `src/farm-agent/tests/conftest.py` lines 225-296
**Apply to:** `FakeAnthropicClientForExtractor` in `tests/conftest.py`

The fake must implement:
1. `with_options(**kwargs) -> self` (timeout passthrough)
2. `messages` property returning `self` (so `client.messages.create()` chains)
3. `async create(**kwargs)` that records `kwargs` in `self.calls` and returns a `MagicMock` with attribute-based content blocks

### PII-safe WARNING logging
**Source:** `src/farm-agent/farm_agent/gate/classifier.py` lines 154-156, 165-167
**Apply to:** `extractor.py`, `multimodal.py`
```python
_log.warning("[haiku-classifier] degraded: %s", e)
```
Log only the exception/reason string — never farmer text, transcript content, or image data.

---

## No Analog Found

All files have analogs. No entries in this section.

---

## Metadata

**Analog search scope:** `src/farm-agent/farm_agent/`, `src/farm-agent/tests/`, `src/agents/alerter/src/extraction/`
**Files scanned:** 14 source files read in full
**Pattern extraction date:** 2026-06-26
