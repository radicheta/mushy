---
phase: 57
slug: signal-i-o
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-15
---

# Phase 57 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.0 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `src/farm-agent/pyproject.toml` (Phase 56) |
| **Quick run command** | `cd src/farm-agent && uv run pytest tests/test_signal_*.py -x` |
| **Full suite command** | `cd src/farm-agent && uv run pytest` |
| **Estimated runtime** | ~10 seconds (unit suite, httpx mocked) |

> **Test layout: FLAT** `tests/test_signal_*.py` (matches Phase-56 on-disk convention),
> NOT the nested `tests/unit/signal_io/` the research test-map assumed. Reconciled by
> the planner per PATTERNS.md (flat matches what exists on disk).

---

## Sampling Rate

- **After every task commit:** Run `cd src/farm-agent && uv run pytest tests/test_signal_*.py -x`
- **After every plan wave:** Run `cd src/farm-agent && uv run pytest`
- **Before `/gsd:verify-work`:** Full unit suite green **and** SC#1 + SC#3 live-fire (Plan 04) passes
- **Max feedback latency:** ~10 seconds (unit); live-fire is manual / `autonomous: false`

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 57-02-T1 | 57-02 | 2 | SIG-01 | — | send/receive/fetch_attachment/accounts shape; quote primitive | unit | `uv run pytest tests/test_signal_client.py tests/test_signal_quote.py -x` | ❌ W0 | ⬜ pending |
| 57-04-T2 | 57-04 | 3 | SIG-01/SC#1 | T-57-04-01 | live round-trip, `signal_msg_ts` bigint non-null | live-fire (manual) | self-send bot→bot; SELECT signal_outbound | ❌ W0 | ⬜ pending |
| 57-02-T3 / 57-01-T3 | 57-02 / 57-01 | 2 / 1 | SIG-02 | T-57-01-01 | persist-after-send fail-open; insert never blocks send | unit | `uv run pytest tests/test_signal_persist.py -x` | ❌ W0 | ⬜ pending |
| 57-02-T2 | 57-02 | 2 | SIG-02/SC#4 | T-57-02-01 (DoS) | asyncio.Lock prevents cap overrun under concurrency | unit | `uv run pytest tests/test_signal_ratecap.py -x` | ❌ W0 | ⬜ pending |
| 57-02-T2 | 57-02 | 2 | SIG-03/SC#2 | — | group internal_id→id-b64 translation; no drop | unit | `uv run pytest tests/test_signal_groups.py -x` | ❌ W0 | ⬜ pending |
| 57-03-T1 | 57-03 | 2 | SIG-03/SC#5 | T-57-03-01 (Spoofing) | unknown sender → `(unassigned)`, not dropped | unit | `uv run pytest tests/test_signal_router.py -x` | ❌ W0 | ⬜ pending |
| 57-03-T2 | 57-03 | 2 | SIG-03 | T-57-03-04 (DoS) | sequential dispatch (attribution); loop-never-dies | unit | `uv run pytest tests/test_signal_receive_loop.py -x` | ❌ W0 | ⬜ pending |
| 57-02-T1 | 57-02 | 2 | SIG-04/SC#3 | T-57-02-02 (Input Validation) | valid quote payload; string-ts coercion; invalid → fail-open | unit | `uv run pytest tests/test_signal_quote.py -x` | ❌ W0 | ⬜ pending |
| 57-04-T2 | 57-04 | 3 | SIG-04/SC#3 | — | native quote bubble renders on client (0.200-dev gate, A2) | live-fire (visual) | self-send w/ quote; screenshot | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> Wave 0 = the test files + conftest fixtures that must exist before/with the implementation.
> Created within each plan's TDD tasks (RED-first). Flat layout.

- [ ] `tests/conftest.py` — httpx mock fixture (`respx`-based) + raising `FakeOutboundRepo` (Plan 01 Task 3)
- [ ] `tests/test_signal_persist.py` — fail-open outbound (Plan 01 Task 3 + Plan 02 Task 3)
- [ ] `tests/test_signal_client.py` — send/receive/fetch_attachment/accounts (Plan 02 Task 1)
- [ ] `tests/test_signal_quote.py` — quote shape + coercion + fail-open (Plan 02 Task 1)
- [ ] `tests/test_signal_ratecap.py` — concurrent-send cap test (Plan 02 Task 2)
- [ ] `tests/test_signal_groups.py` — group translation (Plan 02 Task 2)
- [ ] `tests/test_signal_router.py` — whitelist + DM/group + `(unassigned)` (Plan 03 Task 1)
- [ ] `tests/test_signal_receive_loop.py` — sequential dispatch + loop-never-dies (Plan 03 Task 2)
- [ ] httpx mocking approach decided: **`respx`** (declarative). NEW dev dep — added + legitimacy-gated in Plan 01 (Task 1 blocking-human checkpoint, Task 2 add).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live round-trip + `signal_msg_ts` bigint | SIG-01/SC#1 | Needs live signal-cli + DB; receive-loop contention with Node loop | Plan 04: self-send bot→bot (Phase-50 pattern); `SELECT signal_msg_ts, pg_typeof(signal_msg_ts) FROM signal_outbound WHERE intent='live_fire_57'` is non-null bigint |
| Native quote bubble renders | SIG-04/SC#3 | Visual confirmation on Signal client; 0.200-dev quote shape only spiked on 0.14.2 (A2) | Plan 04: self-send a quote-threaded reply; screenshot the native quote bubble (or document shape drift) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (live-fire tasks `autonomous: false`)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s (unit)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned 2026-06-15
