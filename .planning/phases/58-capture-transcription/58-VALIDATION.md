---
phase: 58
slug: capture-transcription
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-21
---

# Phase 58 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `58-RESEARCH.md` § Validation Architecture. Locked decisions
> D-01..D-08 in `58-CONTEXT.md` are authoritative. **SC#2 is validated per D-03
> (async-HTTP off-loop), NOT the literal "ProcessPoolExecutor" wording.**

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.0 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `src/farm-agent/pyproject.toml` (Phase 56, unchanged) |
| **Quick run command** | `cd src/farm-agent && uv run pytest tests/test_capture_*.py -x` |
| **Full suite command** | `cd src/farm-agent && uv run pytest` |
| **Estimated runtime** | ~10 seconds (unit suite, all HTTP mocked) |

> **Test layout: FLAT** `tests/test_capture_*.py` (matches Phase 56/57 on-disk
> convention — not nested subdirs). All HTTP (Whisper) mocked in the unit suite.

---

## Sampling Rate

- **After every task commit:** `cd src/farm-agent && uv run pytest tests/test_capture_*.py -x`
- **After every plan wave:** `cd src/farm-agent && uv run pytest` (full suite, ~10s)
- **Before `/gsd:verify-work`:** Full unit suite green **and** SC#1 live-fire
  (non-null `transcript` in DB) passes. Live-fire is **BLOCKED on D-07** (Whisper
  container health) — resolve before the live-fire task runs.
- **Max feedback latency:** ~10 seconds (unit); live-fire is manual / `autonomous: false`

---

## Per-Behavior Verification Map

> Plan/Task IDs are assigned by the planner. Rows are keyed by requirement + the
> behavior each Success Criterion / locked decision demands.

| Requirement | SC / Decision | Behavior to prove | Test Type | Automated Command | File Exists | Status |
|-------------|---------------|-------------------|-----------|-------------------|-------------|--------|
| CAP-01 | — | `handle(envelope)` text-only → `signal_capture` row; farmer slug via `resolve_farmer`; capture id is a valid ULID string | unit | `uv run pytest tests/test_capture_pipeline.py::test_handle_text_only -x` | ❌ W0 | ⬜ pending |
| CAP-01 | — | audio attachment written to `baseDir/<day>/<time>-<ulid>.<ext>`; path in `attachment_paths` (`text[]`) | unit | `uv run pytest tests/test_capture_pipeline.py::test_handle_audio_attachment -x` | ❌ W0 | ⬜ pending |
| CAP-01 | SC#3 / D-05 | disk-existence gate: if `Path(p).exists()` is False after download, path NOT added; modality dropped, `degraded=True`, WARNING logged | unit | `uv run pytest tests/test_capture_pipeline.py::test_d05_missing_file_dropped -x` | ❌ W0 | ⬜ pending |
| CAP-01 | D-04 (persist) | `insert_capture` fail-open: DB failure does NOT raise from `handle()`; pipeline continues | unit | `uv run pytest tests/test_capture_repo.py::test_insert_fail_open -x` | ❌ W0 | ⬜ pending |
| CAP-01 | — | unknown sender → `farmos_person = (unassigned)`, capture NOT dropped | unit | `uv run pytest tests/test_capture_pipeline.py::test_unassigned_farmer -x` | ❌ W0 | ⬜ pending |
| CAP-02 | — | `transcribe_client.transcribe(path)` → `{ok:True, text, duration_ms, language}` on Whisper 200 (dual-arg: str path or `{audio_path}`) | unit (respx) | `uv run pytest tests/test_transcribe_client.py::test_ok -x` | ❌ W0 | ⬜ pending |
| CAP-02 | D-04 (fail-open) | timeout / 5xx → `{ok:False, reason}`; `handle()` sets `transcript=None`, `degraded=True`, capture NOT dropped, WARNING logged | unit | `uv run pytest tests/test_transcribe_client.py::test_timeout_fail_open tests/test_capture_pipeline.py::test_d04_transcription_failure -x` | ❌ W0 | ⬜ pending |
| CAP-02 | SC#2 / D-02·D-03 | off-loop: `transcribe()` is `async def` awaiting the HTTP call; receive loop yields during a slow transcription (another coroutine runs) | unit (event-loop tick) | `uv run pytest tests/test_capture_pipeline.py::test_sc2_transcription_offloop -x` | ❌ W0 | ⬜ pending |
| CAP-01 + CAP-02 | SC#1 | **Live-fire:** real voice note → `signal_capture` row with ULID id, correct farmer slug, **non-null `transcript`** | live-fire (manual, `autonomous: false`) | `docker exec timescale psql -c "SELECT id, farmos_person, transcript FROM signal_capture ORDER BY captured_at DESC LIMIT 1"` | ❌ W0 | ⬜ **BLOCKED D-07** |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · 🚧 blocked*

---

## SC#2 Off-Loop Test Strategy (D-02 / D-03)

SC#2's claim — "the receive loop is not blocked during a long transcription" — is
validated **against D-03's async-HTTP interpretation**, not the ROADMAP's literal
`ProcessPoolExecutor` phrasing (superseded). Two complementary proofs:

1. **Behavioral (unit):** inject a `transcribe_client` whose `transcribe()` awaits
   `asyncio.sleep(0.1)`; assert that a concurrently-scheduled `asyncio.create_task`
   flag flips while `handle()` is mid-transcription — proving the loop yields.
2. **Structural (code-review level):** `transcribe_client.transcribe()` MUST be
   `async def` and MUST `await` the httpx call. A synchronous `requests.post()`
   would block — its presence is a hard fail.

The verifier MUST score SC#2 by these two checks, not by searching for a
`ProcessPoolExecutor`.

---

## Whisper Fake / Stub Strategy

Live Whisper is unhealthy (D-07), so the entire unit suite uses fakes:

- **`tests/test_capture_pipeline.py`** — inject a fake `transcribe_client` (a small
  object/dict whose `transcribe` is an `async def` returning a canned
  `{ok:True,...}` or `{ok:False, reason}`). No network, fully deterministic.
- **`tests/test_transcribe_client.py`** — exercise the *real* httpx client against a
  **respx** mock of `POST {whisper_url}/transcribe` (200 ok, timeout, 5xx, missing
  `audio_path`), mirroring Phase 57's respx approach.

---

## Wave 0 Requirements

> Wave 0 = test files + conftest fixtures that must exist before/with the
> implementation. Flat layout.

- [ ] `tests/conftest.py` — add `fake_transcribe_client` fixture (async, canned result) + `whisper_http` respx fixture
- [ ] `tests/test_capture_pipeline.py` — text/audio/image/mixed; D-04 fail-open transcription; D-05 disk-exists gate; unassigned farmer; SC#2 off-loop assertion
- [ ] `tests/test_capture_repo.py` — `insert_capture` ok + fail-open; `mark_expired_older_than`
- [ ] `tests/test_transcribe_client.py` — ok / timeout / 5xx / missing `audio_path`
- [ ] `tests/test_capture_history.py` — `select_recent_by_sender` + `select_recent_outbound_by_recipient` shapes
- [ ] NEW dep `python-ulid` — legitimacy-gated + Wave 0 API probe (A1: confirm `ULID.from_datetime` vs `from_timestamp`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Non-null `transcript` from real voice note | CAP-01 + CAP-02 / SC#1 | Needs live signal-cli + healthy Whisper GPU container + DB | **Prereq: resolve D-07** (`docker logs mushy-whisper-transcribe-1`; CUDA err 804). Then send a real voice note; `SELECT id, farmos_person, transcript FROM signal_capture ORDER BY captured_at DESC LIMIT 1` → ULID id, correct slug, non-null transcript |
| `ALLOWED_ROOT` mount alignment | CAP-02 (prereq) | Cross-container bind-mount; can't be unit-tested | Verify `alerter-py` and `whisper-transcribe` share the same `/data/signal-capture` mount in `docker-compose.override.yml` before live-fire (A5) — else Whisper 400s every request regardless of health |

---

## Flagged Blocker (D-07)

The SC#1 live-fire gate **cannot pass** until `mushy-whisper-transcribe-1` is healthy.
This is a **prerequisite ops fix, not Phase 58 implementation scope** — but it gates
phase completion. The unit suite (all of Wave 0) lands independently of D-07; only the
single live-fire task is blocked. Plan accordingly: mark the live-fire task
`autonomous: false` and depend it on the ops fix, not on code.

---

## Validation Sign-Off

- [x] Every behavior maps to an automated verify or an explicit manual/live-fire task
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING test references
- [x] No watch-mode flags
- [x] Feedback latency < 15s (unit)
- [x] SC#2 validated per D-03 (async-HTTP), not literal ProcessPoolExecutor
- [x] D-07 live-fire blocker explicitly flagged + isolated to one `autonomous: false` task
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned 2026-06-21
