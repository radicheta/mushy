# Phase 57: Signal I/O - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 57-Signal I/O
**Areas discussed:** Transport, Outbound durability, Receive model, Rate-cap state, Quote scope

---

## Transport

| Option | Description | Selected |
|--------|-------------|----------|
| Port REST→httpx | Keep `signal-cli-rest-api:0.200-dev` container, port fetch→httpx 1:1. Lowest parity risk, "same compose topology" literal. | (default) |
| Raw JSON-RPC UNIX socket | signal-cli daemon + raw socket per research Option A. Matches roadmap wording, drops REST container, but net-new code + parity delta; research rationale was factually wrong. | |
| Decide during planning | Defer to researcher; verify 0.200-dev's actual support; default to REST→httpx. | ✓ |

**User's choice:** Decide during planning (researcher verifies, default REST→httpx)
**Notes:** Live topology is the bbernhard REST container at `signal-cli:8080`, not a UNIX socket. Roadmap/SIG-01 text says "JSON-RPC UNIX socket"; research's pro-socket claim ("Node already uses the socket") is false. Researcher to confirm whether a transport switch is worth the non-parity risk; default to porting REST→httpx.

---

## Outbound durability

| Option | Description | Selected |
|--------|-------------|----------|
| Persist-after-send, 1:1 | Port Node verbatim: send then write row best-effort/fail-open. | ✓ |
| Persist-first true queue | pending→sent lifecycle, crash-safe, drainable; NOT a 1:1 port. | |
| Let planning decide | Flag Phase-65 "drain" wording; default persist-after. | |

**User's choice:** Persist-after-send, 1:1
**Notes:** Phase-65 cutover "signal_outbound queue drained" step reduces to a sanity check (no persist-first pending rows by design) — flagged for the cutover author.

---

## Receive model

| Option | Description | Selected |
|--------|-------------|----------|
| Keep long-poll, 1:1 | Port `/v1/receive?timeout=1` loop. | (default) |
| Persistent push stream | WS / JSON-RPC notifications, sub-second, more moving parts. | |
| Follows Transport | Falls out of the Transport decision (poll if REST, push if socket). | ✓ |

**User's choice:** Follows Transport (default poll)
**Notes:** Not decided independently of D-01.

---

## Rate-cap state

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory array, 1:1 | Port `sendHistory` ms-ts list, asyncio.Lock guarded, resets on restart. | ✓ |
| DB-derived count | COUNT from `signal_outbound`; survives restart; SELECT per send. | |

**User's choice:** In-memory array, 1:1 (asyncio.Lock per SC#4)
**Notes:** Dynamic-cap `getMaxSendsPerHour` hook ports as-is.

---

## Quote scope

| Option | Description | Selected |
|--------|-------------|----------|
| Primitive here, wiring later | Phase 57 ports intent-agnostic quote primitive in signal_io; extraction_preview/ask_back coverage + ask_back resolver carry to confirm-path phase. | ✓ |
| Fold full coverage into 57 | Pull outbound-confirm.js into this phase to wire the two intents now. | |

**User's choice:** Primitive here, wiring later
**Notes:** Todo `2026-05-24-phase50-quote-thread-missing...` is tagged `resolves_phase:57` but its code site is `confirm/outbound-confirm.js` (a later port phase). Re-track it there.

## Claude's Discretion

- Transport (D-01) explicitly deferred to planning/research with REST→httpx default.
- Group-ID `internal_id`↔`id-b64` translation, recipient-encoding scheme — port verbatim, no decision needed.

## Deferred Ideas

- Quote-coverage wiring for `extraction_preview` + `ask_back` (+ new ask_back resolver) → confirm-path phase.
- Persist-first durable outbound queue → only if a future phase needs crash-safe re-send.
