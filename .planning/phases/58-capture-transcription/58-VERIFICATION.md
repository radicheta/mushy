---
phase: 58-capture-transcription
verified: 2026-06-23T00:00:00Z
status: human_needed
score: 8/9 must-haves verified
overrides_applied: 0
human_verification:
  - test: >
      Run the live-fire harness after resolving D-07 (Whisper container health) and
      confirming A5 (shared /data/signal-capture bind-mount). Send a real voice note
      from a known farmer's Signal account to the bot (+59891840205). Then run:
        cd src/farm-agent && uv run python scripts/live_fire_58.py
    expected: >
      PREFLIGHT D-07 PASS, PREFLIGHT A5 PASS, signal_capture row with 26-char ULID id,
      farmos_person != "(unassigned)", non-null transcript for audio message_type;
      all attachment_paths exist on disk. RESULT SC#1 = PASS, RESULT SC#3 = PASS.
    why_human: >
      Requires a healthy Whisper GPU container (D-07 ops fix -- cuInit err 804 on GeForce),
      aligned cross-container bind-mount (A5), and a live Signal message from a real farmer
      account. Cannot be verified with code inspection or unit tests.
---

# Phase 58: Capture + Transcription Verification Report

**Phase Goal:** Inbound envelopes are reliably captured to `signal_capture` with attachments
downloaded and audio transcribed off-loop via Whisper, without blocking the event loop.
**Requirements:** CAP-01, CAP-02.
**Verified:** 2026-06-23
**Status:** human_needed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `handle(envelope)` produces a `signal_capture` row with a 26-char ULID `id` and resolved farmer slug | VERIFIED | `test_handle_text_only` passes; `_generate_capture_id` uses `ULID.from_datetime`; row includes `farmos_person` from `resolve_farmer` |
| 2 | Audio attachments are written to `baseDir/<YYYY-MM-DD>/<HH-MM-SS>-<ulid>.<ext>` (server-controlled name, never client filename) | VERIFIED | `build_path` in `pipeline.py:89-99` implements the exact ULID-based scheme; `safe_ext` maps content-type; `att.filename` is never referenced in executable code |
| 3 | D-05: downloaded path is existence-checked after `write_bytes`; missing file is dropped with `degraded=True`, WARNING logged, pipeline continues | VERIFIED | `pipeline.py:219-226`; `test_d05_missing_file_dropped` passes with `Path.exists` mocked to False |
| 4 | D-04: transcription failure (`{ok:False}`) leaves `transcript=None`, `degraded=True`; `insert_capture` is still called; capture is NOT dropped | VERIFIED | `pipeline.py:247-260`; `test_d04_transcription_failure` passes; `capture_repo.insert_capture` is fail-open (try/except, returns `{ok:False}` on DB error) |
| 5 | Unknown sender produces `farmos_person == "(unassigned)"` and capture is not dropped | VERIFIED | `test_unassigned_farmer` passes; `resolve_farmer` returns `"(unassigned)"` for numbers not in `signal_farmer_map` |
| 6 | SC#2 / D-02-D-03: transcription is off-loop -- `transcribe` is `async def` awaiting the httpx call; another coroutine can run while transcription is in progress | VERIFIED | `transcribe_client.py:52` is `async def transcribe`; `pipeline.py:243` `await transcribe_client["transcribe"](audio_path)`; `test_sc2_transcription_offloop` proves a concurrent task's flag flips during the 50ms transcription await |
| 7 | D-03: `handle()` never raises -- an unhandled exception in any step returns `None`, not an exception to the caller | VERIFIED | Outer `try/except Exception` at `pipeline.py:315-317`; `test_handle_never_raises` passes with `FakeSignalClient(should_raise=True)` |
| 8 | Capture pipeline is wired to `receive_loop` dispatch in `boot.py`; exactly one `ReceiveLoop` is started | VERIFIED | `boot.py:73-77`; `create_capture_pipeline` result used as `dispatch=pipeline["handle"]`; `ReceiveLoop` constructed once (T-58-03-05) |
| 9 | **Live SC#1**: real voice note produces a `signal_capture` row with non-null `transcript`; **SC#3**: all `attachment_paths` exist on disk | HUMAN-NEEDED | Harness `scripts/live_fire_58.py` exists and is complete; blocked on D-07 (Whisper container health) and A5 (bind-mount alignment) -- operator prerequisite, not missing code |

**Score:** 8/9 truths verified (9th is human-needed)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/farm-agent/farm_agent/capture/__init__.py` | Foray-island package marker | VERIFIED | Exists; created in Plan 01 (commit `0099365`) |
| `src/farm-agent/farm_agent/capture/pipeline.py` | `create_capture_pipeline` orchestrator | VERIFIED | 382 lines; full `handle()` + `record_reply_capture()`; all D-03/D-04/D-05 invariants implemented |
| `src/farm-agent/farm_agent/capture/transcribe_client.py` | Never-throws httpx client | VERIFIED | 92 lines; `async def transcribe`; httpx timeout; `{ok,text,duration_ms,language}` / `{ok:False,reason}` discriminated result |
| `src/farm-agent/farm_agent/capture/capture_repo.py` | Fail-open psycopg3 INSERT | VERIFIED | 132 lines; `insert_capture` + `mark_expired_older_than`; `attachment_paths` as `list[str]` (not Jsonb); `corpus_context` hard-coded `None` |
| `src/farm-agent/farm_agent/capture/capture_history.py` | SELECT context queries | VERIFIED | 111 lines; `select_recent_by_sender` + `select_recent_outbound_by_recipient`; fail-open |
| `src/farm-agent/farm_agent/capture/retention.py` | Daily soft-expiry loop | VERIFIED | 61 lines; run-once-then-sleep asyncio loop; port of `createRetentionJob` |
| `src/farm-agent/farm_agent/boot.py` | Wires pipeline into daemon | VERIFIED | Imports and wires `create_transcribe_client`, `create_capture_pipeline`, `retention_loop`; single `ReceiveLoop` |
| `src/farm-agent/tests/test_capture_pipeline.py` | 8 pipeline unit tests | VERIFIED | All 8 behaviors tested; all pass in 148-test suite run |
| `src/farm-agent/tests/test_transcribe_client.py` | Transcribe client tests | VERIFIED | ok / timeout / 5xx / missing-path via respx; all pass |
| `src/farm-agent/tests/test_capture_repo.py` | Repo insert + fail-open tests | VERIFIED | `insert_capture` ok + fail-open; `mark_expired_older_than`; all pass |
| `src/farm-agent/scripts/live_fire_58.py` | Live-fire assertion harness | VERIFIED | Complete; D-07 preflight exits non-zero; SC#1 ULID + slug + transcript checks; SC#3 `os.path.exists` per path |
| `.planning/phases/58-capture-transcription/58-LIVE-FIRE.md` | Operator runbook | VERIFIED | Full step-by-step procedure, failure triage, acceptance criteria |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `receive_loop.dispatch` | `capture pipeline handle()` | `ReceiveLoop(dispatch=pipeline["handle"])` in `boot.py:77` | WIRED | `boot.py` constructs `pipeline = create_capture_pipeline(...)` then passes `dispatch=pipeline["handle"]` |
| `pipeline.handle()` | `transcribe_client.transcribe()` | `await transcribe_client["transcribe"](audio_path)` in `pipeline.py:243` | WIRED | Dict-key call; async await confirmed |
| `pipeline.handle()` | `capture_repo.insert_capture()` | `await _repo.insert_capture(pool, row)` in `pipeline.py:280` | WIRED | Default `_repo` is the real `capture_repo` module |
| `pipeline.handle()` | `signal_client.fetch_attachment()` | `await signal_client.fetch_attachment(att_id)` in `pipeline.py:212` | WIRED | Per-attachment download loop |
| `boot.py` | `retention_loop` | `asyncio.create_task(retention_loop(pool, config))` in `boot.py:81` | WIRED | Daily expiry task started at boot |
| `transcribe_client` | `whisper-transcribe /transcribe` | `await http.post(f"{api_url}/transcribe", json={"audio_path": ...})` in `transcribe_client.py:69-73` | WIRED (HTTP) | Async httpx call with timeout; sibling container not re-implemented |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `pipeline.py handle()` | `transcript` | `transcribe_client["transcribe"](audio_path)` -> httpx POST to whisper | Yes (async HTTP, not static) | FLOWING (unit) / HUMAN-NEEDED (live) |
| `pipeline.py handle()` | `attachment_paths` | `signal_client.fetch_attachment(att_id)` -> bytes written to disk | Yes (fetched from signal-cli, not hardcoded) | FLOWING |
| `pipeline.py handle()` | `farmos_person` | `resolve_farmer(source, config)` from `signal_farmer_map` config dict | Yes (real farmer map lookup) | FLOWING |
| `capture_repo.insert_capture()` | DB row | `await pool.connection() / conn.execute(_INSERT_SQL, params)` | Real psycopg3 INSERT (not static return) | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full unit suite passes | `cd src/farm-agent && uv run pytest -q` | `148 passed, 17 skipped in 1.36s` | PASS |
| Capture pipeline tests pass | `uv run pytest tests/test_capture_pipeline.py -q` | All 8 tests in suite PASS | PASS |
| Transcribe client tests pass | `uv run pytest tests/test_transcribe_client.py -q` | All pass (5 skipped = DB-dependent) | PASS |
| `transcribe` is `async def` | `grep "async def transcribe" farm_agent/capture/transcribe_client.py` | Line 52: `async def transcribe(arg) -> dict:` | PASS |
| `handle` never uses `requests.post` (sync) | `grep "requests" farm_agent/capture/pipeline.py` | No match | PASS |
| Single ReceiveLoop in boot | `grep -c "ReceiveLoop(" farm_agent/boot.py` | `1` | PASS |

---

### Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probes for this phase. The phase-declared
live-fire harness (`scripts/live_fire_58.py`) requires a live DB + Whisper container and is
classified as human-needed (see Human Verification Required below).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CAP-01 | 58-03, 58-02 | Inbound envelopes captured to `signal_capture` (ULID id) with attachments downloaded; farmer slug resolved | SATISFIED (code) / live-fire pending | `pipeline.handle()` implements all steps; unit tests cover all CAP-01 behaviors; live DB row pending operator action |
| CAP-02 | 58-02, 58-03 | Audio transcribed off-loop; transcript feeds extraction | SATISFIED (code) / live-fire pending | `transcribe_client` is async httpx; SC#2 off-loop test passes; live non-null transcript pending D-07 ops fix |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | -- | No `TBD`, `FIXME`, `XXX`, `return null`, `return {}`, `return []` stub patterns in any phase-58 file | -- | -- |

Checked files: `capture/__init__.py`, `pipeline.py`, `transcribe_client.py`, `capture_repo.py`,
`capture_history.py`, `retention.py`, `boot.py`, `scripts/live_fire_58.py`. No debt markers,
no placeholder returns, no hardcoded-empty renders.

---

### Human Verification Required

#### 1. Live voice-note round-trip (SC#1 + SC#3)

**Test:** Resolve prerequisites then run the harness:
1. Confirm `mushy-whisper-transcribe-1` is healthy: `curl -fsS http://localhost:8090/health` returns 200. If `cuInit err 804` is in container logs, apply the cuda-compat purge documented in `[[project_whisper_cuda_compat_geforce_804]]`.
2. Confirm `alerter-py` and `whisper-transcribe` share the same `/data/signal-capture` bind-mount in `docker-compose.override.yml` (A5).
3. Confirm only ONE poller (alerter-py, not the Node alerter) is active for the test account.
4. Confirm the farm-agent boot daemon is running: `docker logs mushy-alerter-py-1 --tail 20`.
5. Run the harness preflight: `cd src/farm-agent && uv run python scripts/live_fire_58.py` -- must show `PREFLIGHT D-07 PASS`.
6. Send a real voice note from a known farmer's Signal account to `+59891840205`.
7. Wait 10-30 seconds. Re-run the harness.

**Expected:**
```
PREFLIGHT D-07 PASS: whisper /health returned 200
PREFLIGHT A5 PASS: capture_base_dir == '/data/signal-capture'
SC#1 id     PASS: '<26-char ULID>' is a 26-char ULID
SC#1 slug   PASS: farmos_person = 'f1' (known farmer)
SC#1 xscript PASS: transcript is non-null for message_type='audio'
SC#3 path   PASS: .../<filename>.ogg exists=True
RESULT  SC#1 = PASS
RESULT  SC#3 = PASS
Live-fire assertions PASSED.
```

**Why human:** Requires a live Signal message, a healthy GPU Whisper container (D-07 ops fix for cuInit err 804), and aligned cross-container bind-mount (A5). These are infrastructure prerequisites, not code gaps. Full step-by-step procedure and failure triage in `.planning/phases/58-capture-transcription/58-LIVE-FIRE.md`.

---

### Gaps Summary

No gaps. All phase-58 code is complete and substantively implemented. The unit suite runs 148
tests (17 DB-dependent skips expected) with 0 failures. The single outstanding item is the
operator-driven live-fire round-trip (SC#1 + SC#3), which is correctly gated on external ops
prerequisites (Whisper container health, bind-mount alignment, real Signal message) -- not on
missing or incorrect code.

---

_Verified: 2026-06-23_
_Verifier: Claude (gsd-verifier)_
