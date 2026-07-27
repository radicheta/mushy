# Phase 58: Capture + Transcription - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Port the Node capture pipeline (`src/agents/alerter/src/capture.js` + siblings) to
Python `farm_agent`. Inbound whitelisted Signal envelopes arriving on Phase 57's
`receive_loop` `dispatch(envelope)` seam are turned into `signal_capture` rows
(ULID id, farmer slug resolved from the farmOS people directory, attachments
downloaded to disk), audio attachments are transcribed via the existing
`whisper-transcribe` HTTP service, and the resulting capture (text + transcript +
verified image path) is handed to the next stage (gate/extraction, Phases 59-60).

Requirements: **CAP-01**, **CAP-02**.

This is a PORT phase under v1.12 — "port + opportunistic cleanup, not strict 1:1
parity," "only the alerter slice ports." The Node source is the behavioral spec.
`whisper-transcribe` and `farmos-agent` are sibling services and are NOT re-ported.
</domain>

<decisions>
## Implementation Decisions

### Transcription architecture (the central decision)
- **D-01:** Transcription is a **faithful HTTP port**. Build a Python `transcribe_client`
  (httpx) that POSTs `{audio_path}` to the existing `whisper-transcribe` FastAPI
  container's `/transcribe`, mirroring `transcribe-client.js` (factory shape, timeout,
  never-throws `{ok, text, duration_ms, language}` / `{ok:false, reason}` discriminated
  result). The container stays a sibling service — it is NOT re-implemented in-process.
- **D-02:** **"Off-loop" is satisfied natively by async I/O.** An `await transcribe_client.transcribe(path)`
  is a non-blocking network call; the receive loop continues processing other envelopes
  during a long transcription. **No `ProcessPoolExecutor` is used or needed.**
- **D-03 (SUPERSEDES ROADMAP SC#2 wording):** ROADMAP Phase-58 SC#2 literally says
  "Whisper transcription runs in a `ProcessPoolExecutor` (off-loop)." That wording
  assumes an in-process Whisper re-architecture which conflicts with "only the alerter
  slice ports" and would duplicate a hardened GPU service (deep `/health` CUDA probe,
  VAD filtering, hallucination mitigation in `whisper-transcribe/main.py`).
  **The authoritative SC#2 for this phase is:** "audio is transcribed off-loop via an
  async HTTP call to the `whisper-transcribe` sibling; the receive loop is not blocked
  during a long transcription." The verifier MUST use this interpretation, not the
  literal "ProcessPoolExecutor" phrasing. (In-process Whisper for Foray self-containment
  is a real future option — see Deferred Ideas — but out of scope for the port.)

### Failure semantics
- **D-04:** **Fail-open on transcription failure.** When `transcribe_client` returns
  `{ok:false}` (timeout / whisper 5xx / container down), the `signal_capture` row is
  still persisted with a NULL transcript and the pipeline proceeds with whatever
  modalities exist (text and/or image). A WARNING is logged. Transcription failure
  never drops a capture. (Note: SC#1's "non-null transcript" is the SUCCESS-PATH
  assertion for a voice note when Whisper is healthy — it is not a hard gate that
  forbids null transcripts on the failure path.)
- **D-05:** **Attachment-download race (SC#3) is fail-safe, not fail-open-blind.** A
  downloaded attachment path MUST be verified to exist on disk before it is passed to
  the extractor. If a download fails or the file is absent, that modality is dropped
  (treated as not-present) and a WARNING logged — the extractor never receives a path
  to a missing file. The capture row still persists with the modalities that did land.
- **D-06:** Capture is PRE-confirmation (it happens before any farmer YES), so the
  "no-silent-failure-after-farmer-confirm" rule does NOT bind here. Fail-open + WARNING
  is the correct posture; do not add farmer-facing acks at the capture stage.

### Whisper container health (prerequisite, not phase code)
- **D-07:** `mushy-whisper-transcribe-1` is currently **`unhealthy`** — almost certainly
  the documented CUDA forward-compat hang (cuInit err 804 on GeForce; see
  `[[project_whisper_cuda_compat_geforce_804]]`). Getting it healthy is a **prerequisite
  ops fix, NOT Phase 58 implementation scope.** BUT the phase's live-fire gate (SC#1's
  non-null transcript) cannot pass until the container is healthy. **Flagged blocker:**
  resolve container health before the Phase 58 live-fire/parity verification.

### Capture-pipeline seam (Foray-readiness)
- **D-08:** The capture pipeline is a single module exposing a `handle(envelope)`-style
  entry, mirroring the Node `createCapturePipeline({...})` factory, wired to Phase 57's
  `dispatch(envelope)` seam. Keep `transcribe_client`, the capture persistence repo
  (`capture_repo`, mirroring `outbound_repo` shape), and the farmer-slug / people-directory
  resolver as **separable units** (Foray seam goal). Exact internal structure is the
  planner's call.

### Claude's Discretion
- Santi said "you decide" — all decisions above (D-01..D-08) were Claude-recommended and
  Santi-delegated. The planner has latitude on internal module structure, file/dir layout
  for downloaded attachments (port the Node ULID-based `baseDir/day/time-id.ext` scheme),
  and the capture/transcribe error taxonomy, provided D-01..D-06 hold.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Node source — the behavioral spec to port
- `src/agents/alerter/src/capture.js` — capture pipeline orchestrator (`createCapturePipeline`); classify (text/audio/image/mixed), `safeExt`, ULID `buildPath`, attachment download, D-03 "errors never escape `handle()`".
- `src/agents/alerter/src/capture-db.js` — `insertCapture` (the `signal_capture` row shape; mirror as `capture_repo`).
- `src/agents/alerter/src/transcribe-client.js` — HTTP client to port 1:1 (factory + timeout + never-throws discriminated result).
- `src/agents/alerter/src/capture-history.js` — capture history (dedupe / recent-context) behavior to port.
- `src/agents/alerter/src/capture-retention.js` — retention cron behavior (port or confirm sibling-owned).
- `src/agents/alerter/src/receive-loop.js` — Node reference for how capture wires into the receive loop (Python seam already built in Phase 57).

### Whisper service contract (sibling — do NOT re-port)
- `src/whisper-transcribe/main.py` — `/transcribe {audio_path} -> {text, duration_ms, language, language_probability}` and deep `/health`. The HTTP contract `transcribe_client` must match.

### Python target — what Phase 56/57 already built (reuse, don't reinvent)
- `src/farm-agent/farm_agent/signal_io/receive_loop.py` — the `dispatch(envelope)` seam (Phase-58 entry point).
- `src/farm-agent/farm_agent/signal_io/client.py` — `SignalClient.fetch_attachment` (attachment download), PII `mask_number`.
- `src/farm-agent/farm_agent/persistence/pool.py` + `persistence/outbound_repo.py` — pool injection (PITFALL 4) + repo pattern to mirror for `capture_repo`.
- `src/farm-agent/farm_agent/tenancy/tenant.py` — sole env reader (FND-02); source for `baseDir`, whisper API URL, people-directory config.

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — CAP-01, CAP-02.
- `.planning/ROADMAP.md` §"Phase 58" — goal + success criteria. **SC#2 wording superseded by D-03 above.**

### Relevant memory (background, verify against current code)
- `[[project_whisper_cuda_compat_geforce_804]]` — the unhealthy-container root cause.
- `[[feedback_friction_policy_missing_vs_mismatch]]`, `[[feedback_no_silent_failure_after_farmer_confirm]]` — failure-posture rationale (D-04..D-06).
- `[[project_farmos_people_directory_seed]]`, `[[project_farmer_phone_map]]` — farmer-slug resolution source.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SignalClient.fetch_attachment` (Phase 57) — attachment download; capture builds on it.
- `outbound_repo` + `build_pool` (Phase 56) — the never-throws repo + injected-pool pattern to mirror for `capture_repo` (fail-open persistence already proven).
- `receive_loop.dispatch(envelope)` seam (Phase 57) — sequential, single entry point; capture pipeline plugs in here.
- `whisper-transcribe` FastAPI container — already deployed (currently unhealthy); the transcription backend, reached over HTTP.

### Established Patterns
- Fail-open persistence + WARNING logging (Phase 56/57) — carry into capture.
- Discriminated `{ok, ...}` / `{ok:false, reason}` results (signal/transcribe clients) — `transcribe_client` follows this.
- Sequential dispatch (no concurrent capture) from Phase 57 — transcription's async-await yields the loop without concurrency hazards.

### Integration Points
- IN: `receive_loop` → `dispatch(envelope)` → capture `handle(envelope)`.
- OUT (Phase 59/60): capture result (text + transcript + verified image path + farmer slug + capture id) → event gate → extractor.
- SIDE: `signal_capture` table (Timescale), attachment files on disk under `baseDir/day/`, `whisper-transcribe` HTTP.
</code_context>

<specifics>
## Specific Ideas

- Port the Node ULID-based attachment path scheme verbatim: `baseDir/<YYYY-MM-DD>/<HH-MM-SS>-<ulid>.<safeExt>` — server-controlled name, never trust client filename (V12 file/resource hardening already in `capture.js:buildPath`).
- `transcribe_client` should accept both a string path and `{audio_path}` (the Node client does, for harness symmetry) — low cost, keeps the fake-whisper test harness portable.
</specifics>

<deferred>
## Deferred Ideas

- **In-process Whisper for Foray self-containment.** Running Whisper inside the Python
  package via a ProcessPoolExecutor (the ROADMAP SC#2 literal reading) would make the
  alerter a single self-contained unit with no sibling-container dependency — attractive
  for the eventual Apache-2.0 Foray carve-out. Deliberately NOT done in the port (out of
  scope; re-architecture; duplicates the hardened GPU service). Revisit during the Foray
  extraction milestone if container-coupling proves to be a carve-out blocker.
- **Whisper CUDA-compat permanent fix** — beyond getting the container healthy for this
  phase's gate, a durable fix for the GeForce forward-compat hang
  (`[[project_whisper_cuda_compat_geforce_804]]`) is an ops/infra concern, not alerter code.
- **Alerter timezone fix** (todo `2026-05-21-alerter-tz-montevideo-...`) — reviewed, NOT
  folded; it's a pre-accepted v1.12 delta tracked separately, not capture/transcription scope.

### Reviewed Todos (not folded)
- "Port alerter -> farm-agent" — the v1.12 milestone umbrella, not a phase-specific item.
- "Fix alerter timezone (America/Toronto -> Montevideo)" — pre-accepted delta, separate from Phase 58.
- (~9 low-score / "Untitled" generic todo matches — noise, not folded.)
</deferred>

---

*Phase: 58-capture-transcription*
*Context gathered: 2026-06-21*
</content>
