# Phase 36: Signal Pre-gate — Context

**Gathered:** 2026-05-11
**Status:** Ready for planning

## Phase Boundary

Re-register the mushy-bot Signal account as **primary (deviceId=1)** on the 4G router SIM via SMS verification, replacing the current linked-secondary setup (deviceId=2) that has been returning HTTP 400 on `/v1/receive` since the Phase 25 deploy. Verify receive + reply round-trip from two specific farmers, and prove that subsequent alerter-only container rebuilds do not break Signal identity trust.

**What this phase does NOT do:**
- Multi-farmer routing logic (Phase 37 — ROUTE-01..03)
- Group-thread participation (Phase 37)
- farmOS person-record binding (Phase 37)
- Any LLM extraction or farmOS writes (Phases 38–42)

The whole point of this phase is "make `/v1/receive` return 200" — nothing more.

## Implementation Decisions

### Backup + Rollback Posture
- **D-01:** Before touching anything, snapshot the full `signal-cli-data` Docker volume into a tarball stored on elder-plops (not just the in-Phase-35 nightly backup — that's encrypted + remote, too slow for an abort). Date the tarball; keep at least 7 days.
- **D-02:** Independently capture the current device list (`GET /v1/devices/+<number>`) and identity DB (`GET /v1/identities/+<number>`) as JSON, also dated. Cheap, fast to diff against.
- **D-03:** **Verify** that Phase 35 Tier A backup actually includes the signal-cli volume's irreplaceable bits (account state file). If not, file as a Phase 35 gap and address before proceeding.
- **D-04:** Abort path: if SMS verification fails or the new primary lands in a bad state, restore the volume from the local tarball and the old linked-secondary device resumes (degraded but non-broken). Document the restore-from-tarball recipe in the runbook.
- **D-05:** Do not destroy the old linked-secondary device entry until the new primary has passed PRE-02 verification (D-12). Coexistence during the verification window is fine — the linked device just can't receive.

### Trust Re-issuance to Farmers
- **D-06:** After re-registration, the bot's Signal safety number WILL change. Do NOT use the auto-trust curl loop (`/v1/identities/.../trust/...?trust_all_known_keys=true`) for the initial re-acceptance — farmers re-accept manually on their phones. This is the safer trust posture and gives farmers a moment to notice "the bot is back".
- **D-07:** Pre-write a Signal message that the bot sends to each farmer immediately after re-registration completes: a friendly "I've been re-registered — please tap the safety-number warning to re-accept me, then reply 'ok' so I know it worked." This message IS the PRE-02 round-trip kickoff.
- **D-08:** **The auto-trust curl path remains a recovery tool**, not the default. Reserve it for the *post-rebuild trust-DB corruption* scenario documented in memory `project_signal_cli_rebuild_breaks_trust` — where the identity key has NOT changed but the trust table is stale. Include the curl invocation as a snippet in the runbook clearly labeled "use only when key is unchanged, trust table is stale". This is the distinction that separates initial re-reg (manual accept) from post-rebuild recovery (auto-trust).

### Artifact Form (Script vs Runbook)
- **D-09:** Phase 36's primary artifact is `36-RUNBOOK.md`, NOT a script. Reason: primary re-registration is a one-time event with a manual SMS captcha step that can't be automated; scripting around an interactive captcha is fragile and the recipe is stable enough to follow by hand.
- **D-10:** **One small idempotent script does land** — `scripts/signal/post-rebuild-trust-check.sh` — which (a) probes `/v1/identities/+<number>` for the bot account, (b) compares against a known-good identity fingerprint stored in repo, (c) if drifted, applies the `trust_all_known_keys=true` curl fix automatically, (d) emits a structured log line. This script is the *enforcement mechanism* for Success Criterion #3 (rebuild doesn't break trust). It runs in the alerter container's startup or as a healthcheck — exact wire-up is a planning decision.
- **D-11:** Runbook MUST include: pre-flight checklist (where to snapshot, how to capture identity DB), step-by-step SMS captcha flow, post-reg trust re-acceptance kickoff message text, verification queries, abort path with restore-from-tarball recipe, and a "what to tell the farmer" script for the moment the safety-number warning appears.

### Verification Recipients + Cadence
- **D-12:** PRE-02 recipients are **farmer #1 (Android, on-site farm operator)** and **farmer #2 (zoy, Android, dev-side)**. Both must complete one full round-trip (DM in → bot reply out → farmer "ok" back → bot ack) before the phase is considered shipped. Farmer #3 (iOS) is a nice-to-have if convenient but not gating — keep iOS exercise for an opportunistic add-on.
- **D-13:** Cadence: re-registration + immediate verification in one session. **Then re-run the same round-trip 24 hours later** to catch identity-trust drift, alerter restart, or any background-process churn that could regress trust silently. The 24h re-run is the *real* attestation of D-08's distinction (post-rebuild ≠ initial re-reg).
- **D-14:** Container-rebuild attestation (Success Criterion #3): rebuild the alerter container once during the verification window (after the 24h re-run, before phase close-out) and confirm `post-rebuild-trust-check.sh` runs clean and PRE-02 round-trip still completes. This is the load-bearing rebuild — without it, "rebuild doesn't break trust" is unverified.

### Claude's Discretion
- Backup + rollback specifics (file paths, tarball naming, exact restore commands) — straightforward sysadmin work; planner can decide concrete shapes.
- Whether the `post-rebuild-trust-check.sh` runs as an alerter healthcheck, a systemd timer on elder-plops, or a manual one-shot — planner picks based on the existing alerter compose patterns.
- The exact text of the farmer-facing re-acceptance kickoff message — planner can draft against the Phase 25 reply tone.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Schema lock (for context, not directly touched by Phase 36)
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-09-fungi-schema-strawman.md` — schema strawman
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md` — lock log

### Phase 25 (the predecessor that shipped the bidirectional pipeline)
- `.planning/milestones/v1.4-phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md` — original SPEC, contains the linked-device limitation that this phase resolves
- `.planning/milestones/v1.4-phases/25-bidirectional-signal-farmer-robot-capture-channel/` — full Phase 25 artifacts (deferred items, SUMMARYs)

### Signal-cli operational memory (LOAD-BEARING)
- `project_signal_cli_primary_reregister_path.md` — the spike-validated recipe for primary re-reg via 4G router SIM
- `project_phase25_pregate_spike_state.md` — 2026-04-27 spike PASS state
- `project_signal_cli_link_gotchas.md` — link-mode operational caveats
- `project_signal_cli_rebuild_breaks_trust.md` — the post-rebuild trust-DB recovery curl path
- `feedback_bridge_signal_cli_network_path.md` — bridge reaches signal-cli on host loopback (`127.0.0.1:8085`), alerter on compose net (`signal-cli:8080`)

### Codebase
- `src/agents/alerter/` — alerter container (Node.js); receive loop in `src/receive-loop.js` (env: `BRIDGE_HTTP_URL`, not `BRIDGE_URL` — per `feedback_alerter_env_convention_bridge_http_url`)
- `src/agents/alerter/README.md` — has older signal-cli setup notes; cross-check against the memory recipe before trusting
- `docker-compose.override.yml` — signal-cli service definition (`bbernhard/signal-cli-rest-api:0.200-dev`, volume `signal-cli-data`, ports `127.0.0.1:8085:8080` for bridge, internal `signal-cli:8080` for alerter)

### v1.7 requirements (this phase covers PRE-01..02)
- `.planning/REQUIREMENTS.md` § PRE

## Existing Code Insights

### Reusable Assets
- `signal-cli-rest-api` container — already running; the `/v1/register/`, `/v1/verify/`, `/v1/identities/`, `/v1/devices/` endpoints are the operational surface.
- Phase 35 Tier A backup — partial coverage of signal-cli state (verify in D-03).
- Existing alerter `receive-loop.js` — currently failing on HTTP 400; will start working as soon as deviceId=1 is reached. No alerter code changes expected in this phase.

### Established Patterns
- Two paths to signal-cli: compose-net (`signal-cli:8080`) from alerter; host-loopback (`127.0.0.1:8085`) from bridge. **Don't unify** — they're not interchangeable due to bridge's host-network mode.
- Memory-documented runbooks live in phase dirs (e.g. `32-RUNBOOK.md` for VPS). Same pattern here.

### Integration Points
- Alerter container — no code changes; just needs deviceId=1 to be true so its existing receive loop becomes functional.
- Bridge container — already wired to signal-cli via host loopback (Phase 33 D-09). Re-reg doesn't change this path.
- farmer phones — out-of-band but in scope (they're the verification surface).

## Specific Ideas

- Re-registration window: try to coordinate with farmer #1 to be reachable (~30-60 min slot) so PRE-02 doesn't drag. The "ok" reply IS the verification.
- The 24h re-run (D-13) is small but easy to skip — bake it into the runbook as a CHECK gate, not a footnote.
- `post-rebuild-trust-check.sh` (D-10) is the only piece of long-lived enforcement infrastructure this phase ships. Treat it as production code (tests, error handling, logging) — it's the thing that catches the silent regression class.

## Deferred Ideas

- **Auto-trust everywhere** (full curl-loop replacing manual farmer accept) — defer until at least one re-acceptance cycle has been observed manually; the trust-tradeoff calculus may shift after we see how farmers experience it.
- **Multi-account signal-cli setup** (separate bot accounts per farmer for full isolation) — different problem, different milestone. Note this if v1.7 group-thread routing surfaces conflicts.
- **Signal-CLI version pinning + upgrade story** — currently `0.200-dev`. Worth its own backlog item; not blocking PRE-01..02.
- **gumbald wg-hub peer** (999.47) — operator-side convenience; would let operator drive re-reg from the road instead of needing LAN access. Out of scope for this phase but cheap to slot later.

---

*Phase: 36-signal-pre-gate*
*Context gathered: 2026-05-11*
