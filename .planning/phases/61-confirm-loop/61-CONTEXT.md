# Phase 61: Confirm Loop - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 3 areas; all accepted as recommended (incl. curated-14-set for strain-confirm; 54.2 live-farmOS flip deferred to Phase 62)

<domain>
## Phase Boundary

Port the Node "confirm loop" to Python: the YES/NO/EDIT/expiry state machine as a PURE function
with 100% table-driven parity tests, an async watchdog that serializes ticks (nudge/expire) to
prevent duplicate-nudge / double-expire races, and the strain-confirm-before-mint intercept.
Faithful port; the Node source under `src/agents/alerter/src/confirm/` (+ `farmos/strain-resolver.js`,
`receive-loop.js`) on **main** is the source of truth.

**Scope boundary:** Phase 61 stops at the `confirmed` state + a commit-trigger/strain-approval
MARKER. The actual farmOS HTTP commit + the mint (`createMissingFungiType`) is **Phase 62 (Write
Path)** — which has the farmOS client. So SC "one farmOS commit attempt" = exactly one commit-trigger
emitted (proven by the dup-YES SQL guard), NOT a real HTTP call in Phase 61.

Success criteria (ROADMAP v1.12 Phase 61):
1. 100% parity test suite (pure function, no DB/network) over all valid+invalid transitions of the
   YES/NO/EDIT/expiry FSM; Node transition table == Python table on every case.
2. Sending YES twice → exactly one `confirmed` transition + one farmOS commit attempt (no double-commit).
3. Two concurrent `tick_once()` against the same `awaiting_farmer` row → exactly one nudge
   (conditional UPDATE `WHERE nudge_sent_at IS NULL RETURNING id` guards the race).
4. Strain-confirm-before-mint intercepts unknown codes and holds the draft pending farmer reply;
   known curated-14-code strains pass through without a double-check.

</domain>

<decisions>
## Implementation Decisions

### Area 1: FSM, module structure & guards
- **FSM:** a PURE `transition(status, event, ctx) -> {next_status, side_effects, guard}` function
  mirroring the Node `confirm/state-machine.js` table verbatim. States (5):
  `awaiting_farmer` (working), `confirmed`, `discarded`, `expired`, `needs_review` (all terminal).
  Transition table (port exactly):
  - `awaiting_farmer` + FARMER_YES → `confirmed` [send_confirm_ack]
  - `confirmed` + FARMER_YES (duplicate) → `confirmed` [send_confirm_idempotent_ack]
  - `awaiting_farmer` + FARMER_NO → `discarded` [send_discard_ack]
  - `awaiting_farmer` + FARMER_EDIT (edit_turn_count < cap) → `awaiting_farmer` [run_edit_reextraction], increment
  - `awaiting_farmer` + FARMER_EDIT (>= cap) → `needs_review` [send_edit_cap_msg]
  - `awaiting_farmer` + NUDGE_DUE (nudge_sent_at IS NULL) → `awaiting_farmer` [send_nudge, mark_nudge_sent]
  - `awaiting_farmer` + NUDGE_DUE (nudge_sent_at NOT NULL) → `awaiting_farmer` [noop] (restart-safe)
  - `awaiting_farmer` + EXPIRE_DUE → `expired` [send_expired_note]
  - `awaiting_farmer` + SUPERSEDED → `expired` [noop] (silent, no farmer msg)
  - any non-`awaiting_farmer` + any event → same [noop] (inactive)
- **Module layout:** new `farm_agent/confirm/` package mirroring the Node `confirm/` dir:
  `state_machine.py` (pure FSM), `watchdog.py` (tick loop), `confirm_repo.py` (DAO),
  `strain_ask_back.py` (template + reply parser). Plus the strain resolver (see Area 3).
- **DAO:** new `confirm_repo.py` — never-throws `{ok, reason}` (mirrors `capture_repo.py`), reads/writes
  `signal_draft` + appends `signal_draft_event`. The signal_draft schema already exists in the shared
  TimescaleDB (Phase 56 migrations) — NO Python DAO existed; this phase adds it. Columns used:
  id, status, edit_turn_count, nudge_sent_at, confirmed_at, expired_at, terminal_reason,
  needs_review_reason, draft_json, sender_e164, source_capture_ids, etc.
- **Idempotency + race guards = pure SQL conditional UPDATEs, verbatim from Node (NOT app-level):**
  - dup-YES: `UPDATE signal_draft SET status='confirmed', confirmed_at=NOW(), terminal_reason='farmer_yes', updated_at=NOW() WHERE id=$1 AND status='awaiting_farmer' RETURNING id` — rowcount 1 = transitioned (send ack + emit commit-trigger), 0 = already confirmed (send idempotent ack, no second trigger).
  - nudge race: `UPDATE signal_draft SET nudge_sent_at=NOW(), updated_at=NOW() WHERE id=$1 AND nudge_sent_at IS NULL RETURNING id` — rowcount 0 = race lost, return.
  - expire: `... WHERE id=$1 AND status='awaiting_farmer' RETURNING id` (prevents double-expire).

### Area 2: Watchdog wiring, timing & serialization
- **Wiring:** standalone `asyncio.create_task(confirm_watchdog_loop(pool, signal_client, config))` at
  boot, alongside `retention_loop` (mirrors Node's standalone watchdog; decoupled from ReceiveLoop).
- **Loop shape:** `tick_once()` runs immediately on boot (restart-safe), then interval-sleep; never-throws
  (swallow + WARNING + continue), mirroring `retention.py:retention_loop`.
- **Timing:** reproduce Node — nudge at `timeout_min * nudge_fraction` (~50%), expire at `timeout_min`
  (100%). Thresholds read from config/env (live alerter config is ENV, not tenant yaml —
  [[project_alerter_config_env_not_tenant_yaml_live]]); Node values as defaults. tick query uses
  `updated_at < NOW() - ($1 || ' minutes')::interval`.
- **Serialization:** the SQL `RETURNING id` guard is the CORRECTNESS mechanism (satisfies the SC race
  test: two concurrent tick_once → one nudge). ADDITIONALLY wrap `tick_once` in an `asyncio.Lock`
  (or in-flight flag) so a slow tick can't overlap the next interval — cheap belt-and-suspenders.

### Area 3: Strain-confirm source-of-truth, commit boundary & testing
- **Strain existence check = CURATED-14-SET (port Node main + ROADMAP SC-4).** The curated set:
  SHI SH2 KOY MAI MALI KOS DT CAS CAZ WIN ALM MOR BP LIMA
  ([[project_mossrock_active_strain_codes]]). Detection is EXACT-MATCH only (no fuzzy auto-resolve);
  Levenshtein `nearest_known()` is for SUGGESTION DISPLAY only, never remapping. Codes loaded from
  config (STRAIN_CODES env / TenantConfig), the 14 as documented default.
  - **DEFERRED (known delta):** the Phase-54.2 "live-farmOS-taxonomy source-of-truth" supersession
    ([[project_strain_confirm_before_mint]], [[project_farmos_fungi_type_24_terms_dev_prod_synced]])
    exists ONLY on the unmerged `fix/inoc-starting-seq-dispatch` branch and needs the Phase-62 farmOS
    client. Reconcile in Phase 62 / stranded-branch triage; enumerate as an intentional delta for the
    Phase 64 parity gate so it isn't miscounted. (See docs/NOTE-stranded-inoc-branch.md.)
- **Commit boundary:** Phase 61 stops at `confirmed` + the commit-trigger/strain-approval marker; the
  real farmOS commit + mint is Phase 62. No farmOS HTTP call in Phase 61.
- **Strain ask-back scope (Phase 61):** the intercept + hold (set
  `needs_review_reason='strain_unknown_pending_confirm'`) + reply parser
  (`confirm_new` / `correction` / `unknown`) + on confirm_new set
  `needs_review_reason='strain_confirm_approved'` then run the confirmDraft SQL; on correction with a
  known code rewrite `draft_json.species_code` inline (mirror Node receive-loop.js) then confirm; on
  unknown re-ask. The actual mint (createMissingFungiType) is Phase 62.
- **Testing:** (1) pure FSM table-parity test — no DB/network, assert Python table == Node table for
  every (status, event, condition) case incl. invalid transitions. (2) DB-gated tests (skip without
  :5434, like existing capture_repo DB tests) for the dup-YES idempotency + concurrent-tick nudge race
  (real Postgres needed to prove the conditional-UPDATE guard). No-silent-failure rule
  ([[feedback_no_silent_failure_after_farmer_confirm]]): every terminal post-YES state acks the farmer.

### Claude's Discretion
- Internal helper names, the exact event/side-effect enum spelling, file splits within `confirm/`,
  and test parametrization — provided the locked transition table, SQL guards, and module/commit
  boundaries hold.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `farm_agent/capture/capture_repo.py` — never-throws `{ok, reason}` DAO pattern for confirm_repo.py.
- `farm_agent/capture/retention.py` (`retention_loop`) — immediate-then-sleep never-throws async loop to mirror for the watchdog.
- `farm_agent/boot.py` — `asyncio.create_task(retention_loop(...))` wiring to mirror for the watchdog task.
- `farm_agent/persistence/pool.py` — shared AsyncConnectionPool (psycopg3) for the SQL conditional UPDATEs.
- `farm_agent/signal_io/` — outbound send (for nudge/ack/expired-note side effects) + ReceiveLoop (farmer YES/NO/EDIT inbound parse).
- `tests/conftest.py` — FakeCaptureRepo / fake fixtures + DB-skip gating pattern.

### Established Patterns
- Never-throws discriminated results; PII masking on logs; DB-gated tests skip without :5434.
- Idempotency/race via SQL conditional UPDATE returning id (rowcount 0 = lost), not app logic.

### Integration Points
- Consumes the Phase-60 extraction draft (status `awaiting_farmer` in signal_draft) + farmer inbound replies.
- Emits a commit-trigger/approval marker consumed by Phase 62 (farmOS Write Path) — which does the real commit + mint.
- Node reference (main): `src/agents/alerter/src/confirm/{state-machine,watchdog,confirm-db,strain-ask-back}.js`, `farmos/strain-resolver.js`, `receive-loop.js`.

</code_context>

<specifics>
## Specific Ideas

- Idempotency + race guards are the CRUX — port the exact Node SQL `WHERE ... RETURNING id` clauses; the rowcount is the gate.
- Restart-safety: tick immediately on boot; NUDGE_DUE with nudge_sent_at NOT NULL is a noop (re-entrant).
- No-silent-failure after YES: confirmed (and any terminal post-YES) MUST farmer-ack (success AND failure) — [[feedback_no_silent_failure_after_farmer_confirm]]. For f1=Santi the rule is relaxed but keep acks ([[feedback_hard_rules_relaxed_when_farmer_is_santi]]).
- Draft-expiry rate (21%) is a comms-broken artifact, not a defect to chase ([[project_draft_expiry_rate_comms_artifact]]).

</specifics>

<deferred>
## Deferred Ideas

- Phase-54.2 live-farmOS-taxonomy strain source-of-truth (supersedes curated-set) — Phase 62 / stranded-branch triage; logged as a parity delta.
- The real farmOS commit + createMissingFungiType mint — Phase 62 (Write Path).
- Reconciling the stranded `fix/inoc-starting-seq-dispatch` strain-detection commits — separate triage (docs/NOTE-stranded-inoc-branch.md), not this phase.

</deferred>
