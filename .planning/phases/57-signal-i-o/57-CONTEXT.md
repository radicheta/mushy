# Phase 57: Signal I/O - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

The Python `signal_io/` package — the send/receive layer between the Python stack and signal-cli. Delivers: outbound send through signal-cli (durable-persisted + rate-capped), inbound envelope receive + routing, group-ID translation, attachment fetch, and the wire-level quote-threading primitive (the Phase-50 fixes). This is a **1:1 port** of the live Node `src/agents/alerter/src/signal.js` (+ the receive-loop / outbound-db / message routing it touches), preserving behavior for the Phase-64 parity gate.

Requirements in scope: **SIG-01, SIG-02, SIG-03, SIG-04** (see REQUIREMENTS.md).

**NOT in scope:** capture-to-`signal_capture` + Whisper transcription (Phase 58), event gating (Phase 59), extraction (Phase 60), confirm/commit (later). Specifically, wiring the quote primitive into the `extraction_preview` / `ask_back` outbound intents lives in `confirm/outbound-confirm.js` and ports in the confirm-path phase — see Deferred.

</domain>

<decisions>
## Implementation Decisions

### Transport (the dominant decision — cascades into receive model)
- **D-01 (Claude's discretion + research task):** The live topology is the **`bbernhard/signal-cli-rest-api:0.200-dev` HTTP container** at `http://signal-cli:8080` (verified in `docker-compose.override.yml`), reached via `fetch()` against `/v2/send`, `/v1/receive`, `/v1/groups`, `/v1/attachments`, `/v1/accounts`. **The roadmap goal / SIG-01 text say "JSON-RPC UNIX socket" and research recommended Option A (raw socket) — but research's stated rationale ("the Node alerter already uses the socket") is FACTUALLY WRONG; Node uses the REST container.** Santi deferred the call to planning.
  - **Stated default: port `fetch → httpx.AsyncClient` 1:1 against the same REST container.** Lowest parity risk, satisfies "same compose topology" literally, ~line-for-line port.
  - **Research task for gsd-phase-researcher:** verify what `signal-cli-rest-api:0.200-dev` actually supports (it has internal json-rpc + a `/v1/receive` WS endpoint, but NOT a raw UNIX socket — the raw socket is `signal-cli daemon`, a different container). Confirm whether switching transport is worth the non-parity risk given the big-bang + parity-gate strategy. Default to REST→httpx unless research finds a concrete blocker.

### Outbound durability (SIG-02)
- **D-02:** **Persist-after-send, 1:1.** Port Node behavior verbatim: send first, then write the `signal_outbound` row (incl. `signal_msg_ts` from the send response) best-effort / fail-open — an outbound-insert failure NEVER affects the send return value or throws. No persist-first "pending → sent" queue in this phase.
  - **Cross-phase flag for Phase 65 (Cutover):** the runbook's "`signal_outbound` queue drained" step then reduces to a **sanity check** (no persist-first pending rows exist by design). The cutover author must not expect a drainable queue; what matters is no in-flight confirmed/awaiting drafts (already covered by the `signal_draft` count check).

### Receive model
- **D-03:** **Follows D-01 transport.** Long-poll `/v1/receive?timeout=1` if REST→httpx (the Node default, parity-preserving, ~1s worst-case latency — fine for farmer messages); persistent push (WS / notifications) only if D-01 lands on a socket/WS transport. **Default: long-poll.** Do not decide independently of transport.

### Rate-cap state (SC#4)
- **D-04:** **In-memory `sendHistory` array, 1:1.** Port the Node list of ms-timestamps pruned to the last hour, guarded by an **`asyncio.Lock`** so two concurrent `send` coroutines cannot exceed `maxSendsPerHour` (SC#4). Cap resets on restart (matches Node). The dynamic-cap `getMaxSendsPerHour` hook (Tier-C `alerter_globals.max_sends_per_hour`) ports as-is. NOT DB-derived.

### Quote-threading primitive (SIG-04)
- **D-05:** Phase 57 ports the **intent-agnostic quote primitive** in `signal_io`: any caller may pass `quote={timestamp, author, message}`; `timestamp` coerced via `int(str(ts))` (signal-cli returns ms-ts stringified), valid-shape check (`isValidQuote`), **fail-open** to an unquoted send + `warn` log on invalid shape (never throw, never silently drop the message). This is the verbatim port of `signal.js`'s `isValidQuote` + `payload.quote` logic. The Phase-50 wire-level fixes are folded in here.

### Claude's Discretion
- **D-01 transport** is explicitly deferred to planning/research with the REST→httpx default stated above.
- Group-ID `internal_id`↔`id-b64` translation (lazy-load `/v1/groups`, cache, force-refresh-once-on-miss) ports as-is from `signal.js` `ensureGroupsLoaded` — implementation detail, no decision needed.
- Recipient encoding for `signal_outbound.recipient_e164` (1:1 = `+NNN`; group = `group:<id-b64>` prefix, the Phase-44 path-b decision) ports verbatim.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone scope + strategy
- `.planning/REQUIREMENTS.md` — SIG-01..04 (this phase); CAP/GATE/XTR are later phases
- `.planning/PROJECT.md` §"Current Milestone: v1.12 Farm-Agent Python Port" — big-bang port + parity-gate strategy
- `.planning/ROADMAP.md` §"Phase 57: Signal I/O" — goal + 5 success criteria (round-trip ts as bigint, group translation, quote coercion, asyncio.Lock cap, `(unassigned)` tagging)

### Prior phase context (carry forward)
- `.planning/phases/56-foundation/56-CONTEXT.md` — psycopg3 (D-01), additive-only schema (D-02), `signal_io/` Foray-island package + `boot.py`-only cross-imports (D-03), `TenantConfig` config flow

### Research (committed `c702eea`)
- `.planning/research/STACK.md` §"The signal-cli Interop Decision" — Options A–D. **NOTE: its claim that "Node already uses the JSON-RPC socket" is FALSE (Node uses the REST container) — re-evaluate Option A on its actual merits, not that premise.**
- `.planning/research/ARCHITECTURE.md` — package layout, dependency arrows, build order
- `.planning/research/PITFALLS.md` — ID-type drift (relevant to `signal_msg_ts` bigint-not-float, SC#1)

### Code to port (source of truth — this phase ports these)
- `src/agents/alerter/src/signal.js` — **the primary port target**: `createSignalClient`, `send` (rate-cap, quote payload, durable persist), `receive`, `fetchAttachment`, `accounts`, `ensureGroupsLoaded` (group translation), `isValidQuote`
- `src/agents/alerter/src/receive-loop.js` — inbound poll loop + envelope dispatch
- `src/agents/alerter/src/outbound-db.js` — `signal_outbound` schema + `insertOutbound` (table DDL already captured in Phase 56 persistence migrations)
- `src/agents/alerter/src/message.js` — envelope routing helpers (source extraction, DM vs group, `(unassigned)` tagging — SIG-03)
- `src/agents/alerter/src/config.js` — `signalApiUrl`/`signalSender`/`signalRecipient`/`maxSendsPerHour` config tiers to map onto `TenantConfig`

### Phase-50 quote-threading (SIG-04 lineage)
- `.planning/phases/50-signal-native-quote-threading/50-CONTEXT.md` — locked quote shape `{timestamp, author, message}`, D-05 fail-open, D-04 quote-resolution algorithm
- `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE_ack-quote.jpg` — what a native quote bubble looks like on the client (SC#3 acceptance shape)

### Live topology (verify before transport decision)
- `docker-compose.override.yml` — the `signal-cli` service (`bbernhard/signal-cli-rest-api:0.200-dev`), `signal-net` network, `SIGNAL_API_URL=http://signal-cli:8080`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `signal.js` is self-contained (~234 LOC, single factory `createSignalClient`) — a clean, near-mechanical port unit. Already has the Phase-37/44/50 fixes baked in (group translation, durable persist hook, quote payload).
- Phase 56 already created the `signal_outbound` table via additive-only migrations — Phase 57 only writes rows, no DDL.
- `signal_io/` Foray-island package already scaffolded in Phase 56.

### Established Patterns
- **Single send choke-point** (Phase 37 D-01): all sends go through one `send()` with a per-call `{to}` override of `defaultTarget`; `defaultTarget` may be a string phone OR `{groupId}`. Preserve this.
- **Fail-open everywhere on the send path** (Phase 44 D-03 / Phase 50 D-05): durable-persist failures and invalid-quote shapes degrade gracefully (warn + proceed), never throw. This is load-bearing for `[[feedback_no_silent_failure_after_farmer_confirm]]`.
- **Dynamic cap resolution** (Phase 29): cap read per-send via `getMaxSendsPerHour()` hook so live Tier-C changes take effect on the next send.
- Config layering: live alerter behavior is **compose ENV, not tenant YAML** (`[[project_alerter_config_env_not_tenant_yaml_live]]`) — map onto `TenantConfig`'s env layer.

### Integration Points
- The same `signal-cli` REST container the Node alerter + bridge use (`signal-net`); Python `signal_io` joins it. No new Signal infra in this phase.
- `signal_msg_ts` must persist as **bigint** (SC#1) — signal-cli returns it stringified; `Number()`/`int()` coerces. ID-type drift is the PITFALLS.md #-risk; the parity gate checks this.

</code_context>

<specifics>
## Specific Ideas

- The transport conflict is the single thing to resolve first in planning: roadmap/SIG-01 say "JSON-RPC UNIX socket," but the live + ported stack is the `signal-cli-rest-api` HTTP container, and research's pro-socket argument was built on a false premise. Default = port REST→httpx; only switch if research finds a concrete, parity-worth-it reason.
- SC acceptance shapes to design backward from: `signal_msg_ts` bigint-not-float (SC#1), group message lands via `/v1/groups`-translated id (SC#2), string-`timestamp` quote passes `int(str(ts))` + renders a native bubble + invalid shape fails open (SC#3), asyncio.Lock prevents cap overrun under concurrency (SC#4), unknown sender tagged `(unassigned)` + processed not dropped (SC#5).

</specifics>

<deferred>
## Deferred Ideas

- **Quote-threading coverage expansion to `extraction_preview` + `ask_back`** (todo `2026-05-24-phase50-quote-thread-missing-on-extraction-preview-and-ask-back.md`, tagged `resolves_phase: 57`): Phase 57 ships only the intent-agnostic quote *primitive* (D-05). The actual wiring of these two intents — and the new `ask_back` resolver (sender-scoped "latest inbound from sender", not draft-scoped) — lives in `confirm/outbound-confirm.js` and **carries forward to the confirm-path port phase**. Re-tag/track it there. (Decided with Santi 2026-06-15: "primitive here, wiring later.")
- **Persist-first durable outbound queue** (true pending→sent lifecycle with retry/drain): not needed for parity; revisit only if a future phase needs crash-safe re-send. Phase 65 cutover "drain" is a sanity check, not a queue-drain, given D-02.

### Reviewed Todos (not folded)
- `2026-05-24-phase50-quote-thread-missing-on-extraction-preview-and-ask-back.md` — reviewed; **primitive folded (D-05), coverage-wiring deferred** to the confirm-path phase (see above). Not a Phase 57 deliverable despite its `resolves_phase: 57` tag.

</deferred>

---

*Phase: 57-Signal I/O*
*Context gathered: 2026-06-15*
