# Phase 59: Event Gate - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 11 (7 new, 3 modified, 1 copied fixture)
**Analogs found:** 10 / 11 (1 file has no Python analog -- Node source is the reference)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `farm_agent/gate/__init__.py` | module-init | -- | `farm_agent/capture/__init__.py` (implied) | role-match |
| `farm_agent/gate/event_gate.py` | facade/orchestrator | request-response | `farm_agent/capture/pipeline.py` | role-match |
| `farm_agent/gate/rules.py` | utility (pure fn) | transform | `farm_agent/capture/pipeline.py` helpers (lines 50-113) | partial-match |
| `farm_agent/gate/classifier.py` | service client factory | request-response | `farm_agent/capture/transcribe_client.py` | exact |
| `farm_agent/gate/prompts.py` | config/constants | -- | Node `src/agents/alerter/src/event-gate/prompts.js` | no-Python-analog |
| `farm_agent/boot.py` (modify) | entrypoint | -- | `farm_agent/boot.py` lines 59-105 | self-analog |
| `farm_agent/capture/pipeline.py` (modify) | orchestrator | request-response | existing file lines 130-381 | self-analog |
| `tests/conftest.py` (modify) | test fixture | -- | `tests/conftest.py` lines 152-194 | self-analog |
| `tests/test_gate_rules.py` | test | -- | `tests/test_transcribe_client.py` | role-match |
| `tests/test_gate_classifier.py` | test | -- | `tests/test_transcribe_client.py` | exact |
| `tests/test_gate_event_gate.py` | test (corpus replay) | -- | `tests/test_capture_pipeline.py` | role-match |
| `tests/fixtures/gate/44-hand-classified-100.jsonl` | fixture data | -- | (file copy) | n/a |

---

## Pattern Assignments

### `farm_agent/gate/classifier.py` (service client factory, request-response)

**Analog:** `farm_agent/capture/transcribe_client.py` (exact match -- same never-throws closure-factory shape)

**Factory signature pattern** (lines 28-33):
```python
def create_transcribe_client(
    api_url: str,
    http: httpx.AsyncClient,
    timeout_ms: int = 200_000,
    log: logging.Logger | None = None,
) -> dict:
```
Translate to:
```python
def create_haiku_classifier(
    client: anthropic.AsyncAnthropic,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 100,
    timeout_ms: int = 2000,
    log: logging.Logger | None = None,
) -> dict:
```

**Logger + timeout setup pattern** (lines 49-50):
```python
_log = log or logger
_timeout_s = timeout_ms / 1000
```
Copy verbatim -- same pattern.

**Inner closure shape** (lines 52-91):
```python
async def transcribe(arg) -> dict:
    # ...guard on bad input...
    try:
        r = await http.post(...)
        if r.status_code >= 400:
            return {"ok": False, "reason": f"whisper {r.status_code}: ..."}
        data = r.json()
        return {"ok": True, ...}
    except httpx.TimeoutException:
        _log.warning("[transcribe] timeout ...")
        return {"ok": False, "reason": "timeout"}
    except Exception as e:  # noqa: BLE001 -- never raise from transcribe (D-01/D-04)
        _log.warning("[transcribe] error: %s", e)
        return {"ok": False, "reason": str(e)}

return {"transcribe": transcribe}
```
Translate structure to:
```python
async def classify(env_ctx: dict) -> dict:
    try:
        resp = await client.with_options(timeout=_timeout_s).messages.create(...)
        # parse tool_use block -> pydantic validation
        # return {"ok": True, ...}
    except Exception as e:  # noqa: BLE001 -- never raise from classify
        _log.warning("[haiku-classifier] degraded: %s", e)
        return {"ok": False, "reason": str(e), "fallthrough": "forced"}

return {"classify": classify}
```

**Never-throws contract comment** (line 87):
```python
except Exception as e:  # noqa: BLE001 -- never raise from transcribe (D-01/D-04)
```
Use equivalent: `# noqa: BLE001 -- never raise from classify (D-03 fail-open)`

---

### `farm_agent/gate/event_gate.py` (facade/orchestrator, request-response)

**Analog:** `farm_agent/capture/pipeline.py` for fail-open outer structure; Node `src/agents/alerter/src/event-gate/index.js` for decision logic.

**Factory + closure pattern** (pipeline.py lines 130-163):
```python
def create_capture_pipeline(
    pool: AsyncConnectionPool | None,
    signal_client: Any,
    transcribe_client: dict,
    config: TenantConfig,
    ...
    log: logging.Logger | None = None,
) -> dict:
    _log = log or _LOG
    ...
    async def handle(envelope: dict) -> dict | None:
        ...
    return {"handle": handle, ...}
```
Translate to:
```python
def create_event_gate(
    haiku_classifier: dict,
    log: logging.Logger | None = None,
) -> dict:
    _log = log or _LOG
    async def classify(env_ctx: dict, last_bot_outbound: dict | None, now_ms: int) -> dict:
        ...
    return {"classify": classify}
```

**Decision flow** (Node index.js lines 19-36 -- copy this logic verbatim):
```javascript
const pos = rules.rulePositive(envCtx);
if (pos.hit) {
  return { gate: 'fast_event', allow_extract: true, allow_convo: true };
}
const neg = rules.ruleNegative(envCtx, lastBotOutbound, nowMs);
if (neg.hit) {
  return { gate: 'skipped_rule_neg', allow_extract: false, allow_convo: false };
}
const r = await haikuClassifier.classify(envCtx);
if (!r || !r.ok) {
  return { gate: 'forced', allow_extract: true, allow_convo: true };
}
if (r.is_event === true || (typeof r.confidence === 'number' && r.confidence < 0.7)) {
  return { gate: 'haiku_event', allow_extract: true, allow_convo: true };
}
return { gate: 'haiku_chitchat', allow_extract: false, allow_convo: false };
```
Python translation notes:
- `!r || !r.ok` -> `not r or not r.get("ok")`
- `r.is_event === true` -> `r.get("is_event") is True` (strict boolean, not truthy)
- `typeof r.confidence === 'number' && r.confidence < 0.7` -> `isinstance(r.get("confidence"), (int, float)) and r.get("confidence") < 0.7`

**Fail-open dispatch pattern** (pipeline.py lines 307-311):
```python
if dispatch_result is not None:
    try:
        await dispatch_result(result)
    except Exception as exc:  # noqa: BLE001
        _log.warning("[capture] dispatch_result seam error: %s", exc)
```
The gate's classify closure does NOT need an outer try/except (the classifier already never-throws). But if one is added for safety, copy this exact pattern.

---

### `farm_agent/gate/rules.py` (utility, transform)

**Analog:** `farm_agent/capture/pipeline.py` module-level pure helpers (lines 50-113) for the pattern of compiled regexes + pure functions with no I/O.

**Module-level constant pattern** (pipeline.py lines 51-65):
```python
AUDIO_TYPES = frozenset([...])
IMAGE_TYPES = frozenset([...])
SAFE_EXT_MAP: dict[str, str] = {...}
_AUDIO_EXTS = re.compile(r"\.(aac|m4a|...)$", re.IGNORECASE)
```
Mirror for rules.py:
```python
import re
STRAIN_RE = re.compile(r"\b[A-Z]{2,4}\b")
BLOCK_RE = re.compile(r"\b\d{6}_[A-Z]{2,4}_\d+\b")
ACK_RE = re.compile(r"^(ok|yes|got it|thanks|gracias|si|sí|👍)$", re.IGNORECASE)
```

**Pure function with no I/O pattern** (pipeline.py lines 68-81):
```python
def classify(text: str | None, attachments: list[dict]) -> str:
    """Classify a message as text/audio/image/mixed. Port of capture.js:classify."""
    has_audio = any(...)
    ...
    return "text"
```
Follow the same docstring format: `Port of rules.js:rulePositive`.

**Node source for the exact rule logic** (`src/agents/alerter/src/event-gate/rules.js` -- read this file directly; the RESEARCH.md already contains the verbatim Python translation in its "Node Behavior to Reproduce Exactly" section, lines 361-403).

---

### `farm_agent/gate/prompts.py` (constants module)

**No Python analog.** Node source is the reference: `src/agents/alerter/src/event-gate/prompts.js`.

This file is three constants only: `SYSTEM_PROMPT` (verbatim string from Node), `CACHEABLE_SYSTEM_BLOCKS` (list-of-blocks with `cache_control`), `HOLDOUT_ROW_IDS` (list of 10 ULID strings). No logic, no imports beyond stdlib.

The `HOLDOUT_ROW_IDS` list is already enumerated verbatim in RESEARCH.md lines 449-462.

---

### `farm_agent/gate/__init__.py` (module init)

**Analog:** Pattern from any `farm_agent/capture/__init__.py` or similar -- a one-line re-export:
```python
from farm_agent.gate.event_gate import create_event_gate as create_event_gate
```
No logic. Honors FND-05 Foray seam: no imports from `chamber/`.

---

### `farm_agent/boot.py` (modify -- add AsyncAnthropic wiring)

**Analog:** `farm_agent/boot.py` lines 59-105 (self-analog -- mirror the existing httpx.AsyncClient pattern).

**Existing httpx.AsyncClient injection** (boot.py lines 70-73):
```python
http = httpx.AsyncClient()
signal_client = SignalClient(config=config, http=http)
transcribe_client = create_transcribe_client(config.whisper_url, http)
pipeline = create_capture_pipeline(pool, signal_client, transcribe_client, config)
```

**Add after `http = httpx.AsyncClient()` (new lines):**
```python
import anthropic  # at top of file with other imports

# One shared AsyncAnthropic for the daemon lifetime (mirrors httpx.AsyncClient singleton).
# api_key from TenantConfig.anthropic_api_key (env-only, never logged -- T-56-06-01).
anthropic_client = anthropic.AsyncAnthropic(
    api_key=config.anthropic_api_key,
    max_retries=2,
)
gate = create_event_gate(
    haiku_classifier=create_haiku_classifier(client=anthropic_client),
    log=log,
)
pipeline = create_capture_pipeline(
    pool, signal_client, transcribe_client, config, gate=gate
)
```

**Existing graceful shutdown pattern** (boot.py lines 98-105):
```python
await receive_loop.stop()
retention_task.cancel()
try:
    await retention_task
except asyncio.CancelledError:
    pass
await http.aclose()
await pool.close()
```
Add `await anthropic_client.close()` before `await http.aclose()` -- same pattern.

**Import additions at top of file:**
```python
import anthropic
from farm_agent.gate import create_event_gate
from farm_agent.gate.classifier import create_haiku_classifier
```

---

### `farm_agent/capture/pipeline.py` (modify -- add gate call)

**Analog:** `farm_agent/capture/pipeline.py` lines 236-260 -- the existing transcribe fail-open block (D-04) is the direct structural analog for the gate call.

**Existing transcription fail-open block** (pipeline.py lines 237-261):
```python
if audio_path:
    try:
        r = await transcribe_client["transcribe"](audio_path)
        if r.get("ok"):
            transcript = r.get("text")
        else:
            _log.warning(
                "[capture] transcription fail-open (D-04): sender=%s reason=%s",
                mask_number(source),
                r.get("reason"),
            )
            degraded = True
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "[capture] transcription error (D-04): sender=%s err=%s",
            mask_number(source),
            exc,
        )
        degraded = True
```

**Gate call to insert after transcription (same fail-open pattern):**
```python
extraction_gate: str | None = None
if gate is not None:
    try:
        import time as _time  # already imported at top
        gate_result = await gate["classify"](
            {"text": text, "transcript": transcript,
             "attachmentCount": len(attachment_paths)},
            None,   # last_bot_outbound -- Phase 59 wires None; Phase 60 fills this
            int(_time.time() * 1000),
        )
        extraction_gate = gate_result.get("gate")
        _log.info(
            "[capture] gate=%s allow_extract=%s sender=%s",
            extraction_gate,
            gate_result.get("allow_extract"),
            mask_number(source),
        )
    except Exception as exc:  # noqa: BLE001 -- fail-open; gate never blocks capture
        _log.warning("[capture] gate error (fail-open): sender=%s err=%s", mask_number(source), exc)
```

**Factory signature change** (pipeline.py line 130):
```python
def create_capture_pipeline(
    pool: AsyncConnectionPool | None,
    signal_client: Any,
    transcribe_client: dict,
    config: TenantConfig,
    gate: dict | None = None,          # <-- add; None = gate disabled (backward compat)
    capture_repo: Any = None,
    dispatch_result: Callable | None = None,
    log: logging.Logger | None = None,
) -> dict:
```

---

### `tests/conftest.py` (modify -- add FakeAnthropicClient)

**Analog:** `tests/conftest.py` lines 152-194 -- `FakeCaptureRepo` and `fake_transcribe_client` are the direct structural analogs.

**FakeCaptureRepo class pattern** (conftest.py lines 153-178):
```python
class FakeCaptureRepo:
    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[dict] = []

    async def insert_capture(self, pool: object, row: dict) -> dict:
        self.calls.append(row)
        if self.should_raise:
            raise RuntimeError("FakeCaptureRepo: simulated insert failure")
        return {"ok": True}

@pytest.fixture
def fake_capture_repo():
    return FakeCaptureRepo()
```

**`fake_transcribe_client` canned-result pattern** (conftest.py lines 181-194):
```python
async def _fake_transcribe(arg) -> dict:
    return {"ok": True, "text": "fake transcript", "duration_ms": 100, "language": "es"}

@pytest.fixture
def fake_transcribe_client():
    return {"transcribe": _fake_transcribe}
```

**Translate to FakeAnthropicClient:**
```python
from unittest.mock import MagicMock

class FakeAnthropicClient:
    """Fake AsyncAnthropic client for gate unit tests.

    Configures what classify_capture tool_use response to return, or what
    exception to raise. Records calls for assertion.
    """

    def __init__(
        self,
        tool_input: dict | None = None,
        raise_exc: Exception | None = None,
        return_no_tool_use: bool = False,
    ):
        self.tool_input = tool_input or {"is_event": True, "kind": "event", "confidence": 0.95}
        self.raise_exc = raise_exc
        self.return_no_tool_use = return_no_tool_use
        self.calls: list[dict] = []  # records kwargs from messages.create()

    def with_options(self, **kwargs):
        """Mirror client.with_options(timeout=...) -- returns self."""
        return self

    @property
    def messages(self):
        return self

    async def create(self, **kwargs) -> MagicMock:
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        if self.return_no_tool_use:
            mock_resp = MagicMock()
            mock_resp.content = []
            return mock_resp
        block = MagicMock()
        block.type = "tool_use"
        block.name = "classify_capture"
        block.input = self.tool_input
        mock_resp = MagicMock()
        mock_resp.content = [block]
        mock_resp.usage = MagicMock(
            input_tokens=10, output_tokens=10,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return mock_resp


@pytest.fixture
def fake_anthropic_client():
    """Return a configurable FakeAnthropicClient (default: returns is_event=True)."""
    return FakeAnthropicClient()
```

---

### `tests/test_gate_rules.py` (test, pure functions)

**Analog:** `tests/test_transcribe_client.py` lines 42-93 for the pattern of inline test data, direct function calls, and one-assertion-per-test structure.

**Import pattern** (test_transcribe_client.py lines 25-34):
```python
def _make_client():
    from farm_agent.capture.transcribe_client import create_transcribe_client
    http = httpx.AsyncClient()
    return create_transcribe_client(WHISPER_URL, http=http, timeout_ms=5_000)
```
For rules, no factory needed -- import directly:
```python
from farm_agent.gate.rules import rule_positive, rule_negative
```

**Test structure pattern** (test_transcribe_client.py lines 42-56):
```python
async def test_ok_string_path(whisper_http):
    """transcribe('/path/to/x.ogg') -> {ok:True, text, duration_ms, language}."""
    whisper_http.post(...).mock(return_value=httpx.Response(200, json={...}))
    client = _make_client()
    result = await client["transcribe"]("/data/signal-capture/x.ogg")
    assert result["ok"] is True
    assert result["text"] == "hola"
```
Translate to sync (rules are pure functions, no async needed):
```python
def test_rule_positive_attachment():
    """attachmentCount > 0 -> {hit: True, kind: 'image_or_audio'}."""
    result = rule_positive({"attachmentCount": 1, "text": "hi"})
    assert result["hit"] is True
    assert result["kind"] == "image_or_audio"
```

---

### `tests/test_gate_classifier.py` (test, mocked client)

**Analog:** `tests/test_transcribe_client.py` lines 110-154 -- the `side_effect` / error-path pattern.

**Timeout side_effect pattern** (test_transcribe_client.py lines 127-137):
```python
async def test_timeout_never_raises(whisper_http):
    whisper_http.post(f"{WHISPER_URL}/transcribe").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    client = _make_client()
    result = await client["transcribe"]("/data/signal-capture/x.ogg")
    assert result["ok"] is False
    assert result["reason"] == "timeout"
```
Translate using `FakeAnthropicClient(raise_exc=...)`:
```python
async def test_classifier_api_error_fail_open(fake_anthropic_client):
    import anthropic
    fake_anthropic_client.raise_exc = anthropic.APIConnectionError(request=None)
    from farm_agent.gate.classifier import create_haiku_classifier
    classifier = create_haiku_classifier(client=fake_anthropic_client)
    result = await classifier["classify"]({"text": "hi", "transcript": None, "attachmentCount": 0})
    assert result["ok"] is False
    assert result.get("fallthrough") == "forced"
```

**Asserting the call shape pattern** (test_transcribe_client.py line 92):
```python
assert whisper_http.calls.call_count == 0
```
Translate to:
```python
assert len(fake_anthropic_client.calls) == 1
call_kwargs = fake_anthropic_client.calls[0]
assert call_kwargs["tool_choice"] == {"type": "tool", "name": "classify_capture"}
import json
user_content = call_kwargs["messages"][0]["content"][0]["text"]
payload = json.loads(user_content)
assert "text" in payload
assert "attachmentCount" in payload
```

---

### `tests/test_gate_event_gate.py` (test, corpus replay)

**Analog:** `tests/test_capture_pipeline.py` for the factory-injection + fail-open test pattern; no direct corpus-replay analog exists (see No Analog section).

**Factory injection pattern from capture test** (inferred from conftest.py FakeCaptureRepo):
```python
async def test_fail_open_forced(fake_anthropic_client):
    import anthropic
    fake_anthropic_client.raise_exc = anthropic.APIConnectionError(request=None)
    classifier = create_haiku_classifier(client=fake_anthropic_client)
    gate = create_event_gate(haiku_classifier=classifier)
    result = await gate["classify"](
        {"text": "short", "transcript": None, "attachmentCount": 0},
        None,
        int(time.time() * 1000),
    )
    assert result["gate"] == "forced"
    assert result["allow_extract"] is True
```

**Corpus replay setup** (new pattern -- no existing analog):
```python
import json
from pathlib import Path
from farm_agent.gate.prompts import HOLDOUT_ROW_IDS

FIXTURE = Path(__file__).parent / "fixtures" / "gate" / "44-hand-classified-100.jsonl"

def load_non_holdout_rows():
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]
    return [r for r in rows if r["capture_id"] not in HOLDOUT_ROW_IDS]
```

---

### `tests/fixtures/gate/44-hand-classified-100.jsonl` (fixture data)

**No analog -- file copy.** Source:
`.planning/phases/44-event-gate-durable-signal-outbound-tenant-aware/44-hand-classified-100.jsonl`

Copy verbatim. The fixture schema fields used by tests: `capture_id`, `raw_text`, `transcript`, `attachment_count`, `expected_gate_action`, `class`.

---

## Shared Patterns

### Never-throws `{ok, ...}` result dict
**Source:** `src/farm-agent/farm_agent/capture/transcribe_client.py` lines 63-91
**Apply to:** `classifier.py` classify closure, `event_gate.py` classify closure
```python
# Success path
return {"ok": True, "is_event": ..., "kind": ..., "confidence": ..., "usage": ...}
# Any failure path -- NEVER raise
except Exception as e:  # noqa: BLE001 -- never raise (D-03 fail-open)
    _log.warning("[haiku-classifier] degraded: %s", e)
    return {"ok": False, "reason": str(e), "fallthrough": "forced"}
```

### PII masking on log lines
**Source:** `src/farm-agent/farm_agent/capture/pipeline.py` lines 223-232, 247-251
**Apply to:** `event_gate.py`, `pipeline.py` (gate call block)
```python
_log.warning(
    "[capture] attachment download failed: sender=%s ...",
    mask_number(source),   # <-- never log source e164 directly
    ...
)
```
Gate equivalent: log `gate=`, `allow_extract=`, `mask_number(sender)` -- never `env_ctx["text"]`.

### Fail-open `dispatch_result` / seam try/except
**Source:** `src/farm-agent/farm_agent/capture/pipeline.py` lines 307-311
**Apply to:** `pipeline.py` (gate call block)
```python
try:
    await gate["classify"](...)
except Exception as exc:  # noqa: BLE001
    _log.warning("[capture] gate error (fail-open): %s", exc)
    # extraction_gate stays None; pipeline continues
```

### Factory `log or _LOG` pattern
**Source:** `src/farm-agent/farm_agent/capture/transcribe_client.py` line 49
**Apply to:** `classifier.py`, `event_gate.py`
```python
_log = log or logger  # logger is module-level logging.getLogger(__name__)
```

### Fake helper class with `calls` list + `should_raise` toggle
**Source:** `src/farm-agent/tests/conftest.py` lines 153-178 (FakeCaptureRepo)
**Apply to:** `FakeAnthropicClient` in conftest.py
```python
class FakeXxx:
    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[dict] = []
    async def method(self, ...) -> dict:
        self.calls.append(...)
        if self.should_raise:
            raise RuntimeError("FakeXxx: simulated failure")
        return {"ok": True}
```

### `TEST_ENV` + `"ANTHROPIC_API_KEY": "test-key"` placeholder
**Source:** `src/farm-agent/tests/conftest.py` line 43
**Apply to:** `test_gate_classifier.py`, `test_gate_event_gate.py` if they load config
```python
"ANTHROPIC_API_KEY": "test-key",  # placeholder -- never real, never logged
```
The gate unit tests inject `FakeAnthropicClient` directly; they do NOT need `TEST_ENV`. Only if the test loads `TenantConfig` (e.g., for integration coverage) does this matter.

### `@pytest.mark.live_fire` skip gate
**Source:** Phase 58 precedent (see RESEARCH.md lines 621-622 for the gating pattern).
**Apply to:** `test_gate_event_gate.py` real-Haiku test (deferred):
```python
@pytest.mark.live_fire
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("GATE_LIVE_FIRE"),
    reason="live-fire: requires ANTHROPIC_API_KEY + GATE_LIVE_FIRE=1",
)
async def test_real_haiku_100_corpus():
    ...
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `farm_agent/gate/prompts.py` | constants | -- | No prompt-constants module exists in Python codebase; Node `prompts.js` is the source of truth. Copy SYSTEM_PROMPT verbatim, construct CACHEABLE_SYSTEM_BLOCKS as list-of-blocks per RESEARCH.md Pattern 4. |
| `tests/test_gate_event_gate.py` (corpus replay section) | test | batch | No corpus-replay test pattern exists yet in farm-agent tests. Load fixture JSONL, iterate rows, assert per-row. See RESEARCH.md lines 607-617 for the assertion logic. |

---

## Metadata

**Analog search scope:** `src/farm-agent/farm_agent/`, `src/farm-agent/tests/`, `src/agents/alerter/src/event-gate/`
**Files scanned:** 8 source files read directly
**Pattern extraction date:** 2026-06-24
