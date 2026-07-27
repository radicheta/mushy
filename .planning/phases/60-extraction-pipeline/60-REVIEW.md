---
phase: 60-extraction-pipeline
reviewed: 2026-06-26T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - src/farm-agent/farm_agent/extraction/extractor.py
  - src/farm-agent/farm_agent/extraction/multimodal.py
  - src/farm-agent/farm_agent/extraction/seq_helper.py
  - src/farm-agent/farm_agent/extraction/prompts.py
  - src/farm-agent/farm_agent/boot.py
findings:
  critical: 2
  warning: 4
  info: 2
  total: 8
status: fixed
fixed_at: 2026-06-26T00:00:00Z
fix_notes: >
  CR-02: sum_usage now returns None when all usages are null (mirrors Node sumUsage any flag).
  CR-01: lookup_last_seq_for_date docstring documents snake_case deviation from Node lastSeq;
         AST-based test asserts return key is "last_seq".
  WR-01: downscale_if_needed wrapped in try/except to honor never-raises contract.
  WR-02: _call_with_observer fires observer in finally block with (req, resp, exc) mirroring Node.
  WR-03: corpus_context guard changed to isinstance(dict) mirroring Node typeof === 'object'.
  WR-04: iscoroutinefunction(on_llm_call) used instead of iscoroutine(result).
  IN-02: SUBMISSION_JSON_SCHEMA wrapped in copy.deepcopy() at module level.
  IN-01: Comment added to bare-list branch documenting intentional Node-parity deviation.
---

# Phase 60: Code Review Report

**Reviewed:** 2026-06-26
**Depth:** standard (with Node-source fidelity cross-check)
**Files Reviewed:** 5
**Status:** issues_found

## Summary

The port is structurally sound. All the hard invariants (forced tool call, block.id
pairing on retry, fail-open return shape, tu_fewshot_6 closer, timeout via
with_options, ValidationError caught on retry) are correctly implemented. The
critical findings are two genuine behavioral divergences from the Node source that
affect call-site contracts. Four warnings cover a broken internal contract
(downscale_if_needed claims never-raises but can raise), a fidelity gap in the
observer timing, a corpus_context type-guard divergence, and a camelCase/snake_case
key rename on the lookup_last_seq_for_date return dict that will silently break
callers expecting the Node field name.

---

## Critical Issues

### CR-01: `lookup_last_seq_for_date` return key renamed -- breaks callers expecting Node contract

**File:** `src/farm-agent/farm_agent/extraction/seq_helper.py:189`

**Issue:** The Node source returns `{ ok: true, lastSeq: ..., source: ... }` (camelCase).
The Python port returns `{ "ok": True, "last_seq": ..., "source": ... }` (snake_case).
Any pipeline caller that ports the Node call site and accesses `result["lastSeq"]` will
get `None` silently -- a classic fail-open masked key miss. The fidelity spec states the
port is byte-faithful and the Node source is truth; this renames the contract key without
annotation, so callers that do `result.get("lastSeq")` receive `None` and assign
wrong starting SEQs, minting colliding block names.

**Fix:** Either standardize on snake_case and document the deviation explicitly in the
docstring + any callers, or keep the Node key name:
```python
return {
    "ok": True,
    "lastSeq": max_seq,           # matches Node contract
    "source": "none" if max_seq is None else "signal_draft",
}
```
If the project prefers snake_case (acceptable Python convention), add a prominent
note in the module docstring and update every call site atomically.

---

### CR-02: `sum_usage` always returns a non-null dict; Node `sumUsage` returns `null` when all usages are absent

**File:** `src/farm-agent/farm_agent/extraction/extractor.py:150-166`

**Issue:** Node's `sumUsage` tracks an `any` flag and returns `null` when every usage
in the list was null (no actual usage data). Python's `sum_usage` always returns the
zeroed dict `{"input_tokens": 0, ...}`. The Node `packResult` does `usage: usage || null`
defensively. Any downstream consumer that checks `if result["usage"] is None` to detect
"no usage data recorded" (e.g. to skip telemetry writes or detect degraded-path calls)
will receive a false-positive zeroed dict from the Python port. This is a silent fidelity
divergence on every failure path that still produces a usage object.

**Fix:** Mirror the Node `any` flag:
```python
def sum_usage(usages: list) -> dict | None:
    total: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    any_data = False
    for u in usages:
        if u is None:
            continue
        any_data = True
        for key in total:
            total[key] += getattr(u, key, 0)
    return total if any_data else None
```
Then in `pack_result`, pass through as-is (no change needed since `None` is already
the correct sentinel).

---

## Warnings

### WR-01: `downscale_if_needed` claims "never raises" but has no try/except

**File:** `src/farm-agent/farm_agent/extraction/multimodal.py:44-67`

**Issue:** The docstring states "Always returns (bytes, str); never raises." But the
function body is entirely unguarded: `Image.open(io.BytesIO(buf))` can raise
`UnidentifiedImageError` on a corrupt JPEG/PNG; `img.resize` can raise on
zero-dimension edge cases; `img.save` can raise on internal Pillow errors. The Node
port (`downscaleIfNeeded`) wraps the entire body in `try/catch` and returns
`{ok:false, reason}` on any error. In the Python port the outer `read_image_to_base64`
does catch all exceptions, so the pipeline-level fail-open contract holds. But
`downscale_if_needed` itself violates its own stated contract, and any future direct
caller (unit tests, the Foray island export) will be surprised.

**Fix:** Wrap the function body in try/except matching the Node:
```python
def downscale_if_needed(buf: bytes, media_type: str) -> tuple[bytes, str]:
    try:
        img = Image.open(io.BytesIO(buf))
        # ... rest of logic ...
        return out.getvalue(), "image/jpeg"
    except Exception:
        # Pass through unchanged; caller is responsible for logging
        return buf, media_type
```
Alternatively, remove the "never raises" claim from the docstring and document that
callers must wrap.

---

### WR-02: Observer fires only on success -- diverges from Node's `finally` guarantee

**File:** `src/farm-agent/farm_agent/extraction/extractor.py:228-234`

**Issue:** Node's `callWithObserver` fires `onLlmCall` in a `finally` block, so the
observer receives the call record (with `error: err.message`) even when the API call
throws. The Python port only invokes `on_llm_call` after `resp = await client...` returns
successfully. When a `Timeout` or `APIConnectionError` is raised, the Python observer
is never called. The backfill harness uses this observer to persist every paid-API call
to `responses.jsonl`; a timeout that still costs tokens (partial response) will not be
recorded. This is a fidelity gap and a data-integrity risk for the backfill harness.

**Fix:** Mirror the Node pattern:
```python
async def _call_with_observer(req: dict, _capture_id: str | None = None):
    resp = None
    exc = None
    try:
        resp = await client.with_options(timeout=_timeout_s).messages.create(**req)
        return resp
    except Exception as e:
        exc = e
        raise
    finally:
        if on_llm_call is not None:
            try:
                result = on_llm_call(req, resp, exc)
                if inspect.iscoroutine(result):
                    await result
            except Exception as obs_err:
                _log.warning("[extractor] observer error: %s", obs_err)
```

---

### WR-03: `corpus_context` type guard omits the Node `typeof === 'object'` check

**File:** `src/farm-agent/farm_agent/extraction/extractor.py:119`

**Issue:** Node guards `if (corpusContext && typeof corpusContext === 'object')` -- only
emits the block when corpus_context is a non-null dict/object. Python checks
`if corpus_context is not None:` -- any truthy non-None value (string, list, integer)
will be serialized as JSON and emitted. If a call site passes a string corpus context
by mistake, Node would silently skip it; Python would inject `corpus_context: "bad-string"`
into the user turn, potentially confusing the model or being injected from unvalidated
input (T-44-04-01 adjacent concern: non-dict values from untrusted input could
construct unexpected prompt text).

**Fix:**
```python
if corpus_context is not None and isinstance(corpus_context, dict):
    blocks.append({
        "type": "text",
        "text": f"corpus_context: {json.dumps(corpus_context)}",
    })
```

---

### WR-04: `inspect.iscoroutine(result)` used instead of `inspect.iscoroutinefunction(on_llm_call)`

**File:** `src/farm-agent/farm_agent/extraction/extractor.py:231`

**Issue:** The code calls `on_llm_call(req, resp)` (which for an async callable returns a
coroutine object) and then checks `inspect.iscoroutine(result)`. This works correctly
for async callables, but has an unintended side effect: if a sync callable returns a
coroutine object for any reason (e.g. a sync wrapper that returns a cached coroutine),
it would also be `await`-ed, consuming the coroutine silently. The fidelity spec says
`iscoroutinefunction -> await`. The correct guard is to test the callable before calling:

```python
if on_llm_call is not None:
    try:
        if inspect.iscoroutinefunction(on_llm_call):
            await on_llm_call(req, resp)
        else:
            on_llm_call(req, resp)
    except Exception as obs_err:
        _log.warning("[extractor] observer error: %s", obs_err)
```

---

## Info

### IN-01: `extractSeqsFromRow` handles bare-list `child_block_names` -- undocumented Node extension

**File:** `src/farm-agent/farm_agent/extraction/seq_helper.py:127-133`

**Issue:** The Node source only handles the Provenanced shape `{value: [...]}` for
`child_block_names`. The Python port adds a bare-list branch (`elif isinstance(cbn, list)`).
This is a silent behavioural extension beyond the Node source. It may be intentional for
Python-native callers that skip provenance wrapping, but it is undocumented and could
mask missing provenance wrapping in upstream callers (the model should always emit the
provenanced shape per schema). Worth annotating as an explicit policy decision.

**Fix:** Add a comment explaining the extension:
```python
# Extension vs Node: also handle bare list for Python-native callers
# that do not wrap in {value: [...]}. The model schema requires the
# provenanced shape; this branch is defensive-only.
elif isinstance(cbn, list):
    values = cbn
```

---

### IN-02: `SUBMISSION_JSON_SCHEMA` is a mutable module-level dict

**File:** `src/farm-agent/farm_agent/extraction/schemas/submission.py:66`

**Issue:** `Submission.model_json_schema()` returns a plain dict. If any code path (test,
Foray consumer) mutates the returned dict, all subsequent calls to `build_tool_spec()` and
any cached schema references will see the corrupted value. The dict is not frozen or
copied before use in `build_tool_spec()`.

**Fix:** Freeze it at module level:
```python
import copy
SUBMISSION_JSON_SCHEMA: dict = copy.deepcopy(Submission.model_json_schema())
```
Or in `build_tool_spec`, pass a copy:
```python
"input_schema": dict(SUBMISSION_JSON_SCHEMA),  # shallow copy is sufficient for read-only consumers
```

---

_Reviewed: 2026-06-26_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

**Finding count: 2 Critical, 4 Warning, 2 Info (8 total)**
