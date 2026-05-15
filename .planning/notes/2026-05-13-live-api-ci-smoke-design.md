---
doc: live-api-ci-smoke-design
date: 2026-05-13
phase-class: process-tooling
status: design-spike, pre-discuss
flagged-by: v1.7 retrospective (Phases 38, 39, 40, 41 all had mocked PASS + live FAIL)
related-memory:
  - feedback_smoke_before_expensive_batch.md
  - feedback_real_data_before_ship_gate_pass.md
  - feedback_persist_paid_results_default.md
  - feedback_compose_env_passthrough_not_envfile.md
  - project_elder_plops_dual_role.md
---

# Live-API CI Smoke -- Design Doc

## Premise

Four v1.7 phases shipped mocked tests that passed while live integrations
broke on first contact:

| Phase | Mock said | Live said |
|-------|-----------|-----------|
| 38    | 125/125 unit tests GREEN against fake-anthropic | Plan 03 schema shape wrong (`{$ref, definitions}` vs top-level `type=object`); few-shot `tool_use` blocks missing matching `tool_result` -> HTTP 400 |
| 38    | scorer happy on curated fixtures | Whisper /health green while GPU memory drift -> 500s on real audio |
| 39    | confirm-loop unit tests green | signal-cli `/v1/receive` only works on primary device_id=1; linked secondaries cannot poll |
| 40    | farmOS client tests green against synthetic JSON:API | dev-farmOS lacks `species` bundle entirely (404); `fungi_type` is a required relationship not in the payload |
| 41    | 37 PASS / 5 skipped harness | harness-pipeline parity break (`loadImageBlocks` un-exported); image-wire signature mismatch |

The shared shape: every mock asserted a happy-path response we made up,
not a response the live API actually returned. Curated fixtures cannot
catch shape drift in an external API, schema drift in a sibling Drupal
instance, or capability drift in a sibling daemon (signal-cli mode).

The retro's pinned action item: **live-API smoke must run before ship-gate
attestation, and must surface "the API is reachable, auth works, and the
shape matches what our code expects to receive".** This doc designs the
tooling.

## 1. Scope -- External Service Inventory

These are the services mushy talks to in production. Internal-only
services (ROS2 DDS, TimescaleDB on localhost) are NOT in scope -- they
are already covered by container healthchecks and the Phase 33 outage
detector.

| Service | Endpoint (current) | Auth | Cost/call | Blast radius if shape drifts | Mocked today |
|---------|--------------------|------|-----------|------------------------------|--------------|
| **Anthropic Messages API** | `api.anthropic.com/v1/messages` via `@anthropic-ai/sdk` | `ANTHROPIC_API_KEY` (env) | $0.003-$0.015 per call (sonnet-4-6, depends on cache/tokens) | High: every Phase 38 extraction, every Phase 25 farmer reply, every Phase 39 EDIT cycle | Yes -- `tests/mock-anthropic` shape, see `src/agents/alerter/src/extraction/extractor.js:21`, `src/agents/alerter/src/llm-client.js:8` |
| **Whisper transcribe sibling** | `host.docker.internal:8090/transcribe` (compose-internal) | None (private network) | ~30-120s GPU wall-time per audio file | High: any voice note in capture pipeline blocks until 200000ms timeout if dead, `src/agents/alerter/src/transcribe-client.js:23` | Yes -- `fake-whisper-server` harness |
| **signal-cli REST** | `signal-cli:8080` (compose-internal, signal-net), also `127.0.0.1:8085` (bridge loopback) | Account state in `signal-cli-data` volume | Free, ~50-200ms RTT | Critical: outbound alerts AND inbound farmer messages, all of Phase 25/37/39 confirms; identity-trust drift is its own class (already has Phase 36 watchdog) | Yes -- `signal.js` factory accepts injected fetch in tests |
| **farmOS dev** | `http://10.68.155.50:18080` (LAN, P2 dev stack) | session cookie + CSRF, `src/agents/alerter/src/farmos/client.js:36` | Free, ~100-500ms | Medium: blocks dev-side commit pipeline only; current Backlog B blocker (species bundle 404, fungi_type required) | Partial -- `fetchImpl` injected in unit tests |
| **farmOS prod** | (env: `FARMOS_URL` post-cutover, host TBD) | same as dev | Free, similar RTT | Critical: real harvest/seeding writes; this is what the operator runs the farm on | Partial -- same factory, never run against prod in CI |
| **Bridge HTTP (self)** | `http://host.docker.internal:8081/{health,heartbeat-alert,...}` | None (loopback only) | Free | Critical: alerter <-> ROS2 telemetry, also Phase 33 heartbeat dispatch path | Yes -- spun up in `test/integration.test.js` |
| **ntfy.sh + uptime-kuma (VPS heartbeat)** | VPS-side; mushy posts to `bridge:8081/heartbeat-alert` which fans out via signal-cli; ntfy.sh is on VPS, not mushy-host, see `scripts/backup-tierA/mushy-tierA-backup.sh:12` | Bearer-style secret in `/etc/mushy-heartbeat/ntfy.env` (VPS) | Free | Medium: outage detection chain; if broken, mushy goes silent and operator finds out via Signal |  No |

**Six in-scope services:** Anthropic, Whisper, signal-cli, farmOS-dev,
farmOS-prod, bridge-self. The VPS heartbeat is out-of-scope because the
VPS already runs its own probe of mushy -- the smoke we want is the
**outbound** direction.

## 2. Smoke Matrix

For each service, two probes: a "cheap" probe (auth + reachability +
shape parse) and a "realistic" probe that exercises a code path that has
historically broken. The realistic probe is the load-bearing one --
cheap probes catch outages, realistic probes catch what bit us in
v1.7.

### 2.1 Anthropic Messages API

- **Cheap probe:** `client.messages.create({ model:'claude-sonnet-4-6', max_tokens: 8, messages:[{role:'user', content:'reply with the single word "ok"'}] })`. Confirms key + endpoint + SDK version compat. Cost ~$0.0003. Failure shapes: `401 invalid_api_key`, `429 rate_limit`, SDK throws `TypeError` if SDK major upgrade broke our call site.
- **Realistic probe:** one extractor invocation against a fixed 2-line transcript fixture, with full tool-use schema attached (the same one Plan 03 broke on). Asserts the response is shaped as `content: [{type:'tool_use', input:{...}}]` and that `Ajv.compile(toolSchema)(input)` is true. Cost ~$0.003-$0.01 with prompt caching. **This is the probe that would have caught Plan 03's `{$ref, definitions}` bug at-the-time.** Re-uses `src/agents/alerter/src/extraction/extractor.js` end-to-end with `EVAL_RUN_LIVE=1`, mirroring the Phase 41 stretch pattern.
- **Green:** tool_use block parses to a valid draft. **Red:** HTTP 400 (schema rejection), HTTP 401 (auth), or `validator.js` returns `{ok:false, reason:'schema_invalid'}`.

### 2.2 Whisper transcribe

- **Cheap probe:** `GET http://whisper:8090/health` -- but **only as a tripwire**. Phase 38 taught us this lies (`feedback`: "Whisper 'fake-green' healthcheck"). The cheap probe must be the deep probe: a 1-second-of-silence WAV at a fixed path. Cost: ~5s GPU. Green if `{ok:true, text:''}` (or text matching empty/whitespace). Red on HTTP 500 or text containing "thanks for watching" (the well-known Whisper hallucination tail on silence).
- **Realistic probe:** a 4-second known-good utterance fixture committed to repo at `tests/eval/ingestion/fixtures/whisper-canary.m4a` ("recording test one two three"). Assert transcript word-overlap with ground-truth >= 50%. Cost: ~15s GPU.
- **Green:** ground-truth overlap met, language detected. **Red:** 500, timeout, hallucinated tail. The hallucination class needs explicit detection -- not just exit code.

### 2.3 signal-cli REST

- **Cheap probe:** `GET /v1/about` -- proves the daemon is up and reports its mode. Cost: ~50ms. **Critical assertion: `mode === 'normal'` and `account.device_id === 1`.** Phase 39's "linked-device receive endpoint state" bug was that device_id had drifted to 2; `/v1/receive` 400s in that state with no obvious red flag. This probe codifies the invariant.
- **Realistic probe:** `POST /v2/send` to a configured smoke-channel recipient (NOT the farmer group -- see section 5 dedup), with body `"signal-cli smoke {timestamp}"`. Then `GET /v1/receive` and assert the just-sent message round-trips (since the bot is also the recipient on the smoke channel). Cost: free, ~2s wall.
- **Green:** send 200, receive returns the canary within 2s. **Red:** any non-200, mode!=normal, or device_id!=1. **The trust-identity probe (Phase 36 healthcheck) already exists at `scripts/signal/post-rebuild-trust-check.sh` -- reuse it as a third sub-probe, do not duplicate.**

### 2.4 farmOS dev

- **Cheap probe:** auth round-trip: `POST /user/login?_format=json` -> get cookie + csrf, then `GET /api/asset/fungi?page[limit]=1` with the cookie. Asserts both auth shape and JSON:API base path. Cost: free, ~300ms.
- **Realistic probe:** the *exact* call shape that Phase 40 broke on. (a) `GET /api/taxonomy_term/species?page[limit]=1` -- must NOT 404. (b) `GET /api/taxonomy_term/fungi_type?page[limit]=1` -- must return >= 1 row (the underseeded-taxonomy class of bug, current Backlog B). (c) `POST /api/asset/fungi` with a minimal valid payload INCLUDING the `fungi_type` relationship; assert 201 and DELETE the asset immediately (cleanup). Cost: free.
- **Green:** all three sub-probes pass, asset created+deleted cleanly. **Red:** 404 on bundle (taxonomy seeding gap), 422 on create (schema drift), 401 (cred drift). **The taxonomy-state probe is the highest-value single probe in this doc** -- it's the entire shape of the current open blocker.

### 2.5 farmOS prod

Same probes as dev. Two critical differences:
1. The "create+delete" sub-probe MUST use a clearly-marked smoke asset (name prefix `smoke-canary-YYYYMMDDTHHMMSS`) so an interrupted run leaves a legible footprint, and a daily janitor query can delete strays.
2. Frequency lower than dev (see section 4) because prod-farmOS has audit log implications -- every create/delete is a real db row.

### 2.6 Bridge HTTP self

- **Cheap probe:** `GET /health`. Asserts `ros.connected===true`, `camera.last_frame_age_sec < 60`, `humidifier.last_msg_ts` non-null. The existing `scripts/verify/phase-21-smoke.sh` is 80% of this.
- **Realistic probe:** subscribe to the bridge WS for 5 seconds, assert at least one telemetry frame arrives on `fc1/temperature` AND one on `fc1/humidity`. This catches the "bridge up but DDS link wedged" class.
- **Green:** both arrive within 5s. **Red:** timeout, /health malformed, ros.connected false.

## 3. Where It Runs -- Recommendation: Self-Hosted Container on elder-plops

The four candidate hosts:

| Option | Pros | Cons |
|--------|------|------|
| GitHub Actions runner | Cheap to set up, free for public repos, artifacts UI for free | Cannot reach `10.68.155.50:18080` (LAN-only dev farmOS), cannot reach `fc1` over wg-hub without baking secrets, cannot share `/data/signal-capture` mount for whisper. Setting up tunnels is non-trivial and the secret surface grows. |
| **Self-hosted runner on elder-plops** | Has LAN to dev farmOS, has wg-hub to fc1, has the same docker-compose mounts, no secret transport problem, free | Same box as prod -- the runner itself is a permanent process competing with prod for resources; needs container isolation; if the runner OOMs, prod is the canary |
| Cron job on elder-plops directly | Cheapest, zero-infra | No CI artifact UI, no PR-time gate, no historical run comparison, every output is fire-and-forget |
| Smoke-runner container in compose | All elder-plops pros + lifecycle-bound to the rest of the stack + runs on-deploy automatically | Not as easy to trigger from a PR or laptop; manual runs feel awkward |

**Recommendation: a `smoke-runner` container in `docker-compose.override.yml`,
networked to access bridge + signal-cli + whisper, with the same env-var
hygiene as the alerter.** Implementation: a small Node container with the
same SDK versions as the alerter (so SDK-major-bump bugs surface here),
exposing `/run-smoke` HTTP POST. Triggers:

1. Manual: `docker compose run --rm smoke-runner` -- the operator's pre-deploy gate.
2. Auto: a `make smoke` Makefile target wrapping the above, called from the deploy script.
3. Auto: cron `0 */6 * * *` -- every 6 hours, posts to `/run-smoke`, fans failures into the existing Signal alerter (see section 5).

Rationale for picking compose-container over GH Actions: **mushy is not a
cloud SaaS, it's a farm appliance with a LAN side**. The smoke must run
where the prod traffic runs. Adding a GH Actions tunnel would create a
new secret surface (PROD_SSH_KEY in GH secrets) that's strictly worse than
just running the smoke locally. The operator already trusts elder-plops;
adding a side-car on the same box is the smallest delta. The
"elder-plops is dual dev+prod" memory means we don't have a staging tier
to put this somewhere else anyway.

## 4. When It Runs -- Recommendation: Pre-Deploy + 6h Cron

Cadence options critiqued:

| Option | Cost/week | Catches | Misses |
|--------|-----------|---------|--------|
| Pre-commit hook | High (~$0.30 per commit at typical mushy commit rate, ~50/week = $15/wk just on Anthropic) | Local shape bugs | Drift between commits and deploys |
| Pre-push hook | Medium (~$0.05/wk if push cadence is daily, but only catches what you authored) | Same as pre-commit | Same |
| **Pre-deploy** (every `docker compose up --build`) | ~$0.05/wk (deploys are infrequent) | The class that bit us in v1.7 -- shipping mocked-passing code | Drift introduced after deploy by external state changes (a farmOS dev re-seed, a signal-cli account state change) |
| Nightly cron | ~$0.03/wk | Drift introduced overnight | A bad deploy that drift-injects in the morning |
| **6h cron** | ~$0.12/wk | Drift within a half-workday window | A bad deploy that ships at 09:00 if cron last ran 06:00 |
| On-demand only | $0 | Nothing automatically | Everything |

**Recommendation: two-tier.** Tier 1 = pre-deploy gate (must pass before
`docker compose up --build` proceeds; can be `--force` skipped with an
operator flag). Tier 2 = 6h cron (catches drift, especially in dev-farmOS
and signal-cli state, the two services that drift without code changes).

Estimated total cost: $0.17/week on Anthropic. The whisper/farmOS/signal
probes are free. **This is two orders of magnitude cheaper than one round
of "mocked PASS, live FAIL, rollback, debug" -- Phase 40's smoke alone
cost more in operator time than a year of this cadence.**

Skip the pre-commit and pre-push hooks. The signal-to-noise on local
commits is wrong -- most commits are docs, planning notes, or pure
refactors. Catch shape-drift bugs at the gate that matters: the gate
where they reach the runtime.

## 5. Output / Alerting -- Recommendation: Existing Signal Alerter, New Severity Class

Failures land in the **same Signal pipeline as everything else**. mushy
already has alert-storm control (`ALERT_COOLDOWN_MIN`,
`ALERT_CRITICAL_COOLDOWN_MIN`) and farmer-aware routing (Phase 37 group +
DM map). Inventing a second notification channel is the wrong call: the
operator already watches Signal, and the same dedup/cooldown rules apply.

Concrete plan:

- **New alert kind: `smoke_failed`** dispatched via the bridge
  `/heartbeat-alert` endpoint (already wired to signal-cli at
  `src/mission-control/bridge/src/index.js:620`). Smoke-runner POSTs the
  failure summary; bridge fans to operator DM.
- **Severity tiers:**
  - `critical` = any of {anthropic auth fail, whisper down, signal-cli
    mode!=normal, farmOS-prod create-asset 4xx/5xx}. These break user-facing
    pipelines.
  - `warning` = {farmOS-dev probe fail, anthropic shape drift on
    realistic probe but cheap probe PASS, whisper hallucination tail
    detected}. These are pre-production canaries.
  - `info` = first PASS after a previous FAIL ("recovered"). Suppresses the
    "is this still broken?" question.
- **Message shape** (operator-facing, no em-dashes, round numbers):
  ```
  [SMOKE FAIL - critical] farmOS-dev
  probe: create_fungi_with_fungi_type
  result: HTTP 422 (fungi_type required)
  last_pass: 2026-05-13 16:00 UTC (6h ago)
  run_id: smoke-20260513T220000Z
  ```
- **Partial failures = max(severity) of any sub-probe.** Dev down + prod up
  = warning. Anthropic 401 + everything else green = critical. The
  message body lists which probes failed; the severity gates whether the
  operator's phone rings tonight.
- **Idempotency / dedup:** reuse `ALERT_CRITICAL_COOLDOWN_MIN=60` from the
  alerter env. Same probe failing 4 consecutive times = ONE message per
  hour, not four. The smoke-runner writes a per-probe "last-fail-ts" file
  to a small SQLite db so the dedup state survives container restarts.
- **Append-only run log:** `/data/smoke/results/<run-id>.jsonl` --
  per-probe row, never overwritten, per `feedback_persist_paid_results_default`.
  Captures `estimated_spend_usd` per Anthropic call so the operator can
  catch a cost regression.
- **One tripwire we MUST add:** if the smoke-runner itself crashes (no
  run for >12h), the existing Phase 33 VPS heartbeat path catches it via
  silence detection. Reuse, don't invent.

## 6. Effort Estimate -- 4 Plans

Each plan ~1-2 dev sessions. Total scope: ~1 phase, call it Phase 42 if
v1.8 milestone shape adopts it.

### Plan 42-01: smoke-runner skeleton + cheap probes

- **Scope:** new container `src/agents/smoke-runner/` (node, alpine, same
  SDK versions as alerter). HTTP server with `POST /run-smoke?probes=cheap`.
  Implements cheap probes for all 6 services. Append-only JSONL output to
  `/data/smoke/results/`. Compose entry in override.yml with `signal-net`
  + `host.docker.internal` + `signal-cli` accessible. No alerting yet --
  exits non-zero if any probe red.
- **Files touched:** `src/agents/smoke-runner/{Dockerfile,package.json,src/index.js,src/probes/*.js}`, `docker-compose.override.yml` (new `smoke-runner:` block, ~30 lines).
- **DoD:** `docker compose run --rm smoke-runner` exits 0 on a healthy
  stack; exits 1 if I `docker stop whisper-transcribe` first. Output JSONL
  has 6 rows with `ok: true/false, latency_ms, probe_id`.
- **No-deps:** runs standalone.

### Plan 42-02: realistic probes + canary fixtures

- **Scope:** add realistic-probe sub-handlers for Anthropic (one extractor
  call, fixed fixture), Whisper (canary m4a), signal-cli (send+receive
  round-trip), farmOS (the 3-step taxonomy+create+delete). Adds
  `POST /run-smoke?probes=full`. Wires `EVAL_COST_CAP_USD` budget cap
  borrowed from Phase 41.
- **Files touched:** new files in `src/agents/smoke-runner/src/probes/`,
  fixture commit at `src/agents/smoke-runner/fixtures/{transcript.txt,whisper-canary.m4a}`.
- **DoD:** `?probes=full` completes in <120s wall, costs <$0.05 per run,
  catches the Phase 40 `fungi_type` 422 if I revert `farmos/assets.js` to
  pre-fix.
- **Deps:** 42-01 skeleton.

### Plan 42-03: alerting + dedup

- **Scope:** wire the smoke-runner to POST failures to
  `bridge:8081/heartbeat-alert` with the severity-tier message shape from
  section 5. Implement per-probe dedup via small SQLite at
  `/data/smoke/dedup.db`. Recovery `info` message on green-after-red.
- **Files touched:** `src/agents/smoke-runner/src/alerting.js`,
  `src/agents/smoke-runner/src/dedup.js`, README runbook section.
- **DoD:** induce a probe failure 4 times back-to-back; assert exactly 1
  signal message arrives at the operator phone over the hour. Then heal;
  assert 1 recovery message arrives.
- **Deps:** 42-01, 42-02. **Real-data ship-gate:** mandatory live signal
  send to operator phone, not curated assertion. Per
  `feedback_real_data_before_ship_gate_pass.md`.

### Plan 42-04: deploy gate + cron + ops runbook

- **Scope:** `make smoke` target. `scripts/deploy/pre-deploy-smoke.sh`
  wrapper that runs `?probes=full`, surfaces verdict, blocks deploy unless
  `--force` flag. Cron file: `scripts/cron/smoke-runner-6h.sh` installed
  to elder-plops `/etc/cron.d/`. Runbook page covering: how to read
  results JSONL, how to force-skip the gate (and when), how to add a new
  probe for a new external service.
- **Files touched:** `Makefile`, `scripts/deploy/pre-deploy-smoke.sh`,
  `scripts/cron/smoke-runner-6h.sh`, `docs/smoke-runbook.md` (or
  `.planning/notes/smoke-runbook.md`).
- **DoD:** an attempted `docker compose up -d --build bridge` with whisper
  stopped fails the gate; with `--force` proceeds. Cron entry visible in
  `crontab -l`. Operator hand-tests one cycle.
- **Deps:** 42-01..42-03 all green.

## 7. Open Questions for Don Santiago

1. **Smoke-channel Signal recipient -- new phone number or dev group?**
   The signal-cli realistic probe needs a recipient that isn't the
   farmer group (don't spam farmers with `signal-cli smoke ts=...`). Two
   choices: (a) register a second test recipient on the bot account
   (cheap; no extra SIM), (b) DM to operator phone only (simpler but
   operator phone gets ~28 messages/week from cron). Recommend (b) +
   ALERT_RECEIVE_POLL filter that auto-discards `^signal-cli smoke `.
2. **Pre-deploy gate -- hard block or soft warn?** Hard block forces
   discipline but is annoying on a 3am hotfix. Soft warn lets the
   operator override silently and the lesson re-learns. Recommend hard
   block + 30-second `--force` confirmation prompt, *not* a flag (a flag
   is too easy to alias in muscle memory).
3. **farmOS-prod realistic probe -- create+delete every 6h, or read-only?**
   Create+delete is the only way to catch schema drift on the write path,
   but it puts 28 phantom rows per week through audit logs. Read-only
   misses the entire Phase 40 class. Recommend create+delete every 6h
   with the `smoke-canary-` prefix; a daily janitor query confirms zero
   strays older than 24h.
4. **Anthropic budget cap -- $1/week, $5/week, or unbounded?** Section 4
   estimates $0.17/wk under recommended cadence. A cap of $1/wk is a 6x
   safety margin and would auto-page if the realistic probe ever runs
   away (e.g., extractor pulled a 16k-token output by accident). Set
   `EVAL_COST_CAP_USD` per-run = $0.05, per-week aggregate = $1.00, alert
   on either breach.
5. **Phase 42 vs sub-phase of v1.8 milestone?** This feels like
   foundational tooling that benefits every v1.8+ phase. Inclined to make
   it the **first** Phase of v1.8, ahead of any new feature work. Pre-req
   for any phase that touches an external API. Confirm milestone shape.

---

## Highest-Value Probes (TL;DR for skim-read)

If only three probes get built in plan 42-01, build these:

1. **farmOS taxonomy state probe** (cheap probe 2.4a + 2.4b). Codifies
   the current Backlog B blocker; catches the entire taxonomy-underseeded
   class. Highest yield per LOC.
2. **signal-cli `/v1/about` mode + device_id assertion** (cheap probe
   2.3a). Phase 39's whole bug class collapses to one mode-check.
3. **Anthropic realistic-shape probe** (realistic probe 2.1). The
   end-to-end extractor call against a fixed fixture is what would have
   caught Phase 38 Plan 03 at-the-time; cost is ~$0.005 per run.
