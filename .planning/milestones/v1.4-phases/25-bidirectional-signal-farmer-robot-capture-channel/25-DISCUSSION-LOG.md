# Phase 25: Bidirectional Signal — farmer↔robot capture channel — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 25-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-27
**Phase:** 25-bidirectional-signal-farmer-robot-capture-channel
**Areas discussed:** Container topology, Storage layer, Whisper variant + model, LLM session/context

---

## Container topology

### Q: Where should the new capture pipeline (persistence + transcription dispatch + LLM call) live?

| Option | Description | Selected |
|---|---|---|
| Extend alerter | Add capture/transcribe-client/llm-client modules inside src/agents/alerter | ✓ |
| New signal-capture container | Sibling container, alerter unchanged | |
| Receive-loop in alerter, capture in new container | Alerter routes to in-process snooze + IPC capture container | |

### Q: Whisper transcription should run as:

| Option | Description | Selected |
|---|---|---|
| Dedicated whisper container | New container exposes HTTP /transcribe; reusable for any audio source | ✓ |
| Sidecar process inside capture container | Subprocess in same container; ~2GB image | |

### Q: If capture crashes, what happens to alerts (Phase 17 send path)?

| Option | Description | Selected |
|---|---|---|
| Alerts keep flowing | Capture errors caught + logged; degraded reply per SPEC R6; visibility via sensor_health | ✓ |
| Container restarts (lose alert continuity briefly) | Crash + restart policy | |

---

## Storage layer

### Q: Where should capture metadata rows be stored?

| Option | Description | Selected |
|---|---|---|
| TimescaleDB | New table signal_capture; reuse bridge db.js pattern | ✓ |
| SQLite on RAID | /data/signal-capture/capture.db | |
| Filesystem only + JSON manifest | Per-message JSON sidecar; no DB | |

### Q: Attachment file naming under /data/signal-capture/YYYY-MM-DD/?

| Option | Description | Selected |
|---|---|---|
| Timestamp + ULID + original ext | e.g., 14-30-22-01HQXYZ.jpg | ✓ |
| Hash of content + original ext | Dedup but not time-sortable | |
| Signal envelope ID + original ext | Faithful to source; format may drift | |

### Q: Retention policy for the 30-day window?

| Option | Description | Selected |
|---|---|---|
| Hard 30-day delete | Daily cron prunes rows + files | |
| Soft 30-day flag, never delete | Mark expired, keep files; disk grows | ✓ |
| 30 days metadata, 7 days files | Keep DB rows 30d, delete files after 7d | |

**Notes:** User accepted the divergence from a strict 30-day retention — SPEC says "queryable for 30 days," not "delete after 30 days." Farmer prefers historical access; revisit on disk pressure.

---

## Whisper variant + model

### Q: Which Whisper implementation?

| Option | Description | Selected |
|---|---|---|
| faster-whisper | CTranslate2 reimplementation; 4x faster than openai-whisper | (via 'Other' note) |
| whisper.cpp | C++/GGML; smallest container | |
| openai-whisper | PyTorch reference implementation | |
| Other | "farmer speaks english. we have a NVIDIA with 6GB ram in elder-plops, we could use it" | ✓ |

**Notes:** User correction — farmer is English-speaking (not Spanish as I'd assumed); elder-plops has a 6GB NVIDIA GPU available. Settled on **faster-whisper with CUDA float16** in the GPU follow-up question below.

### Q: Which model size?

| Option | Description | Selected |
|---|---|---|
| small | ~244M, ~1GB RAM | |
| base | ~74M, ~500MB RAM | |
| medium | ~769M; on CPU tight, on GPU comfortable | ✓ |
| large-v3 | ~1550M; needs GPU | |

### Q: Spanish-specific tuning?

| Option | Description | Selected |
|---|---|---|
| Lock language=es | Skip auto-detect | |
| Auto-detect every message | Handles mixed-language farmer | ✓ |

### Q: Use the NVIDIA GPU for Whisper, or stick with CPU?

| Option | Description | Selected |
|---|---|---|
| GPU (CUDA), faster-whisper medium | float16 on CUDA; ~3-5s per 30s audio | ✓ |
| CPU only | Leaves GPU 100% free for v1.4 CV | |
| GPU but smaller model (small) | Frees VRAM for coexistence | |

### Q: Container topology when using GPU?

| Option | Description | Selected |
|---|---|---|
| Whisper container has GPU access | docker-compose deploy.resources.reservations.devices | ✓ |
| Document GPU as 'whisper-only' for now | Reserve full GPU; future CV negotiates | |

---

## LLM session/context

### Q: How much context should the LLM see when generating its reply?

| Option | Description | Selected |
|---|---|---|
| Rolling window: last 30 min from same sender | Heuristic session boundary | (via 'Other' note) |
| Stateless per message | Simple, predictable | |
| Explicit session start command | Friction; farmer must remember | |
| Rolling window: last 5 messages, any time | No time constraint | |
| Other | "rolling window is fine but make it 24 hours. should be low volume anyway" | ✓ |

**Notes:** User extended the window from my proposed 30 min to 24 hours, citing low message volume. Captured as D-10 in CONTEXT.md.

### Q: Should the LLM have access to recent farm telemetry/alerts when replying?

| Option | Description | Selected |
|---|---|---|
| No, capture-only context | Smallest prompt, focused role | |
| Yes, include last hour of alerts + sensor state | Context-aware replies | ✓ |

### Q: Anthropic model + reply length?

| Option | Description | Selected |
|---|---|---|
| claude-haiku-4-5 + 80 tokens | Fast, cheap, receipt-style | |
| claude-sonnet-4-6 + 150 tokens | Better at clarifying questions | ✓ |
| claude-opus-4-7 + 200 tokens | Overkill | |

### Q: Telemetry context scope — what does "last hour of alerts + sensor state" mean concretely?

| Option | Description | Selected |
|---|---|---|
| Current values only | Latest temp/humidity/CO2 + active alerts; ~10 lines | ✓ |
| Current values + 1h trend summary | Bridge computes trend; ~20 lines | |
| Full last-hour series (raw data) | Big prompt; LLM picks signal | |

---

## Claude's Discretion

Captured in CONTEXT.md decisions section. Notable items left to downstream agents:
- Exact `signal_capture` schema column types and indexes
- LLM system prompt wording / few-shot examples
- Whisper container healthcheck design
- Retention job mechanism (cron vs systemd timer vs in-process)
- Receive-loop poll cadence after primary re-registration
- Capture pipeline concurrency model
- Log format / verbosity

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section:
- FarmOS event creation from sessions
- Image content understanding by LLM
- Trend summaries in LLM context
- Multi-recipient / farmOS people directory
- Hard retention / cold archival
- GPU contention design with future CV
- Robot-initiated conversations
