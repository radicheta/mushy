# Phase 25: Bidirectional Signal — farmer↔robot capture channel — Context

**Gathered:** 2026-04-27
**Status:** Ready for planning

<domain>
## Phase Boundary

When the farmer sends a Signal message (text / voice note / photo) to the robot's number, the robot receives it, persists raw content + metadata, transcribes audio locally on GPU, runs the message (with rolling 24h sender history + current sensor snapshot) through Claude Sonnet, and replies with either a session-tag receipt or a clarifying question — within SPEC latency budgets (60s text, 3min audio, 60s degraded). Snooze stays working. FarmOS writes are deferred to a later phase.

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**7 requirements are locked.** See `25-SPEC.md` for full requirements, boundaries, acceptance criteria, and pre-gate.

Downstream agents MUST read `25-SPEC.md` before planning or implementing. Requirements are not duplicated here.

**In scope (from SPEC.md):**
- Receive-loop infrastructure unblock (path proven via spike 001 — primary re-registration on B310s-518)
- Capture persistence layer
- Local transcription service (containerized on elder-plops)
- Anthropic LLM call for session inference + reply composition
- Simplified snooze UX (single 24h global mute; legacy grammar accepted)
- Degraded-mode replies when transcription or LLM unavailable
- Single-farmer model (existing `SIGNAL_RECIPIENT` whitelist)

**Out of scope (from SPEC.md):**
- FarmOS event creation from captured content
- Multi-recipient routing / farmOS people directory
- QR-tag linking
- Robot-initiated conversations
- Per-alert-type snooze UX
- Retention beyond 30 days / cold storage / S3
- Voice synthesis / TTS replies
- Image content understanding (LLM sees metadata only — visual inference belongs to Phase 24+ CV)

**Pre-gate:** RESOLVED 2026-04-27. Spike 001 PASS — full SMS roundtrip proven; root cause of prior 108006 was a typo'd password in the spike README. Primary re-registration of `+59891840205` via the B310s-518 SIM is the unblocking implementation step.

</spec_lock>

<decisions>
## Implementation Decisions

### Container topology
- **D-01:** Capture pipeline lives **inside** the existing `alerter` container. New modules: `capture.js` (persistence orchestration), `transcribe-client.js` (HTTP client to whisper container), `llm-client.js` (Anthropic SDK wrapper). Alerter is no longer "alerts + snooze" — it's the comms hub.
- **D-02:** Transcription runs in a **dedicated `whisper-transcribe` container** (sibling of alerter in compose). HTTP API: `POST /transcribe { audio_path }` → `{ text, duration_ms, language }`. Reusable later for any audio source.
- **D-03:** **Alerts must keep flowing if capture fails.** All capture-pipeline errors are caught and logged; existing send path + heartbeat continue uninterrupted. Capture failure → degraded reply per SPEC R6 (acknowledge receipt, skip transcription/LLM). Operator visibility: capture errors surface in alerter logs and a sensor_health-style indicator (Phase 16 panel).

### Storage layer
- **D-04:** Capture metadata in **TimescaleDB**, new table `signal_capture` (or schema `capture`). Reuse bridge's `db.js` connection pattern — alerter is on host network so `TIMESCALE_HOST=localhost` resolves (matches Phase 23 timelapse pattern). Hypertable on `(captured_at)`. Schema sketch: `(id ULID PK, captured_at timestamptz, sender text, message_type text, raw_text text, attachment_paths text[], transcript text NULLABLE, llm_session_tag text NULLABLE, llm_reply text NULLABLE, expired boolean default false)`.
- **D-05:** Attachment files at `/data/signal-capture/YYYY-MM-DD/HH-MM-SS-{ULID}.{ext}`. ULID gives collision-free time-sortable names; original extension preserved for ffmpeg/whisper. Per-day directories ease backups. `/data` is the RAID symlink (per project memory).
- **D-06:** **Soft 30-day flag, never auto-delete.** A daily job sets `expired=true` on rows ≥30 days old; rows + files stay on disk. Diverges from a strict retention policy — SPEC R2 only requires "queryable for last 30 days," and the farmer prefers long-term access to past sessions. Disk pressure can be revisited if it becomes real.

### Whisper variant + model
- **D-07:** **faster-whisper** (CTranslate2), **medium** model, CUDA `float16` on elder-plops NVIDIA GPU (6GB VRAM). ~3-5s for 30s audio; comfortable headroom on the 3min SPEC budget.
- **D-08:** **Auto-detect language** per message (farmer speaks primarily English but may mix in Spanish or species names). Slight per-call cost is acceptable.
- **D-09:** `whisper-transcribe` container declares GPU access via docker-compose `deploy.resources.reservations.devices`. Future GPU consumers (Phase 24+ CV work) share the GPU via NVIDIA driver scheduling — `medium` uses ~3GB VRAM in fp16, leaving ~3GB free.

### LLM session/context
- **D-10:** **Rolling 24-hour window** from the same sender as LLM context. Volume is low (single farmer); 24h covers a typical inoc or harvest day. Older messages excluded from the prompt.
- **D-11:** LLM prompt **includes current sensor snapshot** (latest temp / humidity / CO2 + any alerts active in the last hour) — raw values only, no trend summaries. Compact (~10 lines), enables context-aware replies ("RH dropped to 82% — venting?"). Source: bridge's existing telemetry endpoints.
- **D-12:** Anthropic model **`claude-sonnet-4-6`**, `max_tokens=150`. Sweet spot for receipt-style replies (≤2 lines per SPEC) plus occasional clarifying questions. Latency ~3-5s, well under 60s/3min budgets.

### Claude's Discretion
- Exact `signal_capture` schema column types and indexes (within the sketch in D-04)
- LLM system prompt wording and few-shot examples
- Healthcheck design for `whisper-transcribe` container
- Retention job mechanism (cron vs systemd timer vs in-process scheduler)
- Receive-loop poll cadence after primary re-registration (current `ALERT_RECEIVE_POLL_SEC` may need re-tuning)
- Log format / verbosity for capture pipeline events
- Concurrency model in `capture.js` (one envelope at a time vs queue with worker)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 25 specs
- `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md` — locked requirements, latency budgets, acceptance criteria. **Read first.**

### Existing alerter (extend, don't replace)
- `src/agents/alerter/src/signal.js` — proven `/v2/send` client; reuse for replies
- `src/agents/alerter/src/receive-loop.js` — polling + sender whitelist; needs the unblocked `/v1/receive` endpoint after primary re-registration
- `src/agents/alerter/src/snooze.js` — existing grammar; preserve, expand "snooze/mute/quiet → 24h global"
- `src/agents/alerter/src/config.js` — env var pattern; new vars for capture (TIMESCALE_*, WHISPER_URL, ANTHROPIC_API_KEY, CAPTURE_BASE_PATH)
- `src/agents/alerter/Dockerfile` — node:20-alpine baseline
- `src/agents/alerter/test/` — existing fake-server pattern for snooze tests; mirror for capture tests

### Storage / Timescale pattern
- `src/mission-control/bridge/src/db.js` — connection pattern, `time` aliased as `captured_at`
- `.planning/phases/23-time-lapse-composition-ffmpeg/23-CONTEXT.md` — `network_mode: host` + `TIMESCALE_HOST=localhost` precedent for new container reaching Timescale

### Spike findings (load-bearing)
- `.planning/spikes/001-huawei-router-sms-roundtrip/README.md` — proves SMS roundtrip on B310s-518 at `192.168.8.1`; recipe for primary re-registration of `+59891840205`

### Compose / deployment
- `docker-compose.yml` + `docker-compose.override.yml` (repo root) — live deployment target; bridge override applies host networking + tailscale CycloneDDS config
- Memory `feedback_verify_runtime_compose.md` — verify against repo-root compose, not `src/docker-compose.yml`
- Memory `project_data_path_on_raid.md` — `/data` is a symlink to `/mnt/slime-kingdom/data`; bind mounts stay `/data/...`

### Related context
- `.planning/phases/18-farmer-dashboard-api/18-CONTEXT.md` — farmer-facing surface conventions
- `.planning/phases/16-system-health-panel/16-CONTEXT.md` — sensor_health indicator pattern (for D-03 capture-error visibility)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `signalClient.send()` — already proven in prod for outbound; reuse verbatim for capture replies and degraded-mode acks
- `receive-loop.js` polling + whitelist — keep, swap the broken `/v1/receive` endpoint after re-registration
- `snooze.js` grammar parser — extend to accept the `snooze`/`mute`/`quiet` simplified UX while keeping the legacy `snooze rh 4h` form
- bridge `db.js` Timescale connection pattern — clone for capture writes
- alerter test pattern (fake server in `test/`) — mirror for capture pipeline tests

### Established Patterns
- Network: alerter uses `network_mode: host`; new whisper container can be host or bridge, but easiest is host (TIMESCALE_HOST=localhost just works)
- Env vars: snake-case in code, SCREAMING_SNAKE in env, masked in logs (`maskNumber` pattern)
- Error handling: catch + warn + continue ticking — never let one bad envelope crash the loop (Pitfall 4 already documented in receive-loop.js)
- Compose: `--build` always required when alerter source changes (cached image trap, per CLAUDE.md)

### Integration Points
- Alerter receive-loop dispatch fan-out: today → snooze handler. After Phase 25 → snooze handler + capture pipeline (both consume same envelope; snooze is fast-path, capture is async)
- Capture writes → Timescale `signal_capture` table; future Phase 18+ farmer dashboard could surface a "recent messages" panel
- Whisper container exposes HTTP; capture pipeline calls it; no direct GPU dependency in alerter container

</code_context>

<specifics>
## Specific Ideas

- The LLM should be able to write replies like "Logged 3 photos + 1 audio for inoc-2026-04-27. Substrate type?" — i.e., it sometimes asks one short clarifying follow-up rather than always emitting a pure receipt.
- Snooze remains a *fast path* — it should be detected and dispatched before the capture pipeline runs, so a `snooze` text always gets the 30s ack even if capture is degraded.
- Pre-gate spike 001 was the unlock; primary re-registration of `+59891840205` is implementation step zero. Identity-trust loss with the farmer (`+59892893012`) is expected and recovery is a re-trust-via-curl call (per memory `project_signal_cli_rebuild_breaks_trust`).

</specifics>

<deferred>
## Deferred Ideas

- **FarmOS event creation** from captured sessions (LLM drafts farmOS log/observation/activity from accumulated session) — next phase candidate (SEED-002 already noted)
- **Image content understanding** by LLM — belongs in v1.4 CV phases (24+); Phase 25 LLM only sees image metadata (filename, count, timestamp)
- **Trend summaries in LLM context** — current decision (D-11) is raw values only; trend-aware replies are a follow-up if farmer asks for them
- **Multi-recipient / farmOS people directory routing** — single-farmer model preserved; directory seeded but not built
- **Hard retention / cold archival** — soft 30-day flag (D-06) means files grow forever; revisit when disk pressure shows up
- **GPU contention design** with future CV phases — current D-09 assumes "share the 6GB"; if Phase 24+ CV needs more, the design may need scheduling/queue
- **Robot-initiated conversations** ("good morning, RH is 91% — log tray check?") — proactive direction is its own phase

</deferred>

---

*Phase: 25-bidirectional-signal-farmer-robot-capture-channel*
*Context gathered: 2026-04-27*
