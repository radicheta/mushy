---
phase: 57-signal-i-o
verified: 2026-06-22T00:30:00Z
status: passed
score: 5/5
overrides_applied: 0
human_verification:
  - test: "57-04 live-fire (SC#1 signal_msg_ts non-null bigint round-trip + SC#3 native quote bubble) against the live signal-cli-rest-api container with prod secrets"
    expected: "self-send bot->bot returns 201; signal_outbound.signal_msg_ts is non-null bigint (pg_typeof); the quote-threaded second message renders as a native quote bubble on the Signal client"
    why_human: "Needs the live signal-cli container + prod secrets + a human-observed quote bubble on a real Signal client"
    result: "DONE 2026-06-21 — Verdict PASS (recorded in 57-LIVE-FIRE.md, commit 045ab07). SC#1 PASS: rows 1782054669365 / 1782054675982 non-null bigint. SC#3 PASS after a blocking fix the gate caught: signal-cli 0.200-dev /v2/send takes FLAT quote_timestamp/quote_author/quote_message, not the nested quote{} object the ported client first sent; fixed in client.py, re-fired, operator confirmed the native bubble visually."
gaps: []
notes:
  - "SC#2 group-id translation is verified by code + test_signal_groups.py, NOT by a live group send — the 57-04 live-fire was self-send DM only (live inbound drain + broader live traffic deferred to Phase 58 by design, per 57-LIVE-FIRE.md and RESEARCH A3/A4). This is an accepted coverage deferral, not a defect: the /v1/groups internal_id->id-b64 translation path is unit-proven and will exercise naturally once live traffic flows."
  - "Out-of-scope finding surfaced by the live-fire (backlogged, NOT a Phase 57 gap): the live Node alerter shares the same 0.200-dev container and still builds the nested quote object (src/agents/alerter/src/signal.js:118-131), so Phase-50 quote-threading is likely silently broken in Node prod until cutover. See memory signal-cli-quote-flat-fields-not-nested."
---

# Phase 57: Signal I/O Verification Report

**Phase Goal:** The Python stack can send and receive Signal messages through the live `signal-cli-rest-api` HTTP container (REST->httpx 1:1 port per D-01; the SIG-01 "JSON-RPC socket" phrasing is SUPERSEDED), with durable fail-open outbound persistence, asyncio.Lock rate-cap, correct multi-farmer routing, and the intent-agnostic wire-level quote primitive that folds in the Phase-50 fixes.
**Verified:** 2026-06-22T00:30:00Z
**Status:** passed (5/5)
**Re-verification:** No — initial verification (retroactive closeout; build + live-fire completed 2026-06-21)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Live round-trip send; `signal_outbound.signal_msg_ts` populated as bigint (not null, not float-coerced) | VERIFIED (live-fire) | 57-04 live-fire PASS 2026-06-21: both `/v2/send` returned 201; rows `1782054669365` / `1782054675982` non-null `bigint` (`pg_typeof` confirmed); harness exited `SC#1 PASS`. Schema: `migrations.py:322` `signal_outbound ADD COLUMN signal_msg_ts bigint` + partial index. Repo stores caller-int()'d value (`outbound_repo.py:76`) |
| 2 | Group message lands in the Signal group; group ID translated via `/v1/groups` cache, not raw `internal_id` | VERIFIED (unit) | `client.py:145-165` `ensure_groups_loaded()` lazy-loads `/v1/groups`, builds `internal_id -> id-b64` map (port of signal.js:22-39); `test_signal_groups.py` green. Live group-send not part of 57-04 (self-send DM only) — see frontmatter note |
| 3 | Quote-threaded reply with string `timestamp` passes `int(str(ts))` coercion, renders native quote bubble; invalid quote shapes fail-open (unquoted + warn, no exception) | VERIFIED (live-fire + unit) | 57-04 SC#3 PASS after shape-drift fix (operator confirmed native bubble). `client.py:96 is_valid_quote()` validates `{timestamp,author,message}` via `float(str(ts))`; invalid -> unquoted + warn (D-05). `test_signal_quote.py` green |
| 4 | Rate-cap history protected by `asyncio.Lock`; two concurrent sends do not exceed `maxSendsPerHour` | VERIFIED | `client.py:84 self._lock = asyncio.Lock()` guarding the in-memory ms-timestamp history (D-04, port of signal.js:41-56); `test_signal_ratecap.py` (concurrent-send cap) green |
| 5 | Unknown sender numbers tagged `(unassigned)` and processed, never dropped | VERIFIED | `router.py:187 return config.signal_farmer_map.get(source) or "(unassigned)"` (port of receive-loop.js); `test_signal_router.py` green |

**Score:** 5/5 truths verified (SC#1, SC#3 via live-fire; SC#2, SC#4, SC#5 via code + unit tests).

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/farm-agent/farm_agent/signal_io/client.py` | VERIFIED | httpx SignalClient: send/receive/fetch_attachment/accounts, quote primitive, group translation, asyncio.Lock rate-cap, fail-open persist |
| `src/farm-agent/farm_agent/signal_io/router.py` | VERIFIED | whitelist + DM/group + triggers + `(unassigned)` resolution |
| `src/farm-agent/farm_agent/signal_io/receive_loop.py` | VERIFIED | sequential poll + `dispatch(envelope)` seam (the Phase-58 entry point) |
| `src/farm-agent/farm_agent/persistence/outbound_repo.py` | VERIFIED | never-throws fail-open INSERT; `signal_msg_ts` stored as-is |
| `signal_outbound.signal_msg_ts bigint` migration | VERIFIED | `migrations.py:322` additive + partial index |
| `scripts/live_fire_57.py` + `57-LIVE-FIRE.md` | VERIFIED | self-send harness + operator runbook + recorded PASS verdict |
| `tests/test_signal_*.py` | VERIFIED | client, groups, persist, quote, ratecap, receive_loop, router |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| SignalClient.send | signal-cli `/v2/send` | httpx POST (flat quote fields) | VERIFIED (live-fire 201) |
| SignalClient.send | outbound_repo.insert_outbound | fail-open persist after send | VERIFIED (`test_signal_persist`) |
| SignalClient | `/v1/groups` cache | internal_id -> id-b64 map | VERIFIED (`test_signal_groups`) |
| receive_loop | router.resolve_farmer | whitelist + `(unassigned)` | VERIFIED (`test_signal_router`, `test_signal_receive_loop`) |
| receive_loop | dispatch(envelope) | sequential single entry (Phase-58 seam) | VERIFIED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 57 signal unit suite | `cd src/farm-agent && uv run pytest tests/test_signal_*.py -q` | 79 passed, 5 skipped (DB-gated skip cleanly) | PASS |
| Live round-trip bigint | `scripts/live_fire_57.py` (2026-06-21) | `SC#1 PASS`, both rows non-null bigint | PASS |
| Native quote bubble | operator visual on Signal client (2026-06-21) | rendered after flat-field fix | PASS |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| SIG-01 | Send/receive via signal-cli REST (httpx); live round-trip + signal_msg_ts bigint | VERIFIED | SC#1 live-fire; receive() unit-covered |
| SIG-02 | Durable fail-open outbound persistence | VERIFIED | outbound_repo never-throws; `test_signal_persist` |
| SIG-03 | Multi-farmer routing; `(unassigned)`; sequential dispatch | VERIFIED | SC#5; router + receive_loop tests |
| SIG-04 | Intent-agnostic wire-level quote primitive (folds Phase-50 fixes) | VERIFIED | SC#3 live-fire + is_valid_quote; flat-field fix |

### Gaps Summary

No blocking gaps. All five success criteria are verified; the human-verification live-fire (SC#1 + SC#3) completed 2026-06-21 with a PASS that also caught and fixed a real shape-drift bug (nested -> flat quote fields on signal-cli 0.200-dev).

Two recorded notes (in frontmatter), neither a Phase 57 defect:
1. SC#2's live group-send was not exercised in 57-04 (self-send DM only; broader live traffic deferred to Phase 58 by design). Group-id translation is unit-proven.
2. The live Node alerter still builds the nested quote object on the shared 0.200-dev container, so Phase-50 quote-threading is likely silently broken in Node prod until cutover (out-of-scope, backlogged).

---

_Verified: 2026-06-22T00:30:00Z_
_Verifier: Claude (inline — subagent path was API-overloaded; verification run in main loop against code + tests + live-fire record)_
