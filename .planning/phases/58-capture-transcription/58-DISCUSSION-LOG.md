# Phase 58: Capture + Transcription - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 58-capture-transcription
**Areas discussed:** Transcription architecture, Whisper container health, Failure semantics, Capture pipeline seam

---

## Transcription architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Faithful HTTP port | Python httpx `transcribe_client` → existing `whisper-transcribe` container; async = off-loop; no ProcessPoolExecutor | ✓ |
| In-process Whisper (ProcessPoolExecutor) | ROADMAP SC#2 literal wording; re-implement Whisper in-process; drops sibling container; more Foray-portable | |

**User's choice:** "you decide" → Faithful HTTP port (Claude-recommended).
**Notes:** Claude flagged the ROADMAP SC#2 "ProcessPoolExecutor" wording as contradicting the
actual architecture (whisper-transcribe is already a standalone FastAPI GPU container; only the
alerter slice ports). In-process Whisper would duplicate a hardened service (deep CUDA health
probe, VAD, hallucination mitigation). SC#2 wording superseded by CONTEXT D-03. In-process
Whisper preserved as a Deferred Idea for the Foray carve-out.

---

## Whisper container health

| Option | Description | Selected |
|--------|-------------|----------|
| Prerequisite ops fix (flagged blocker) | Container is `unhealthy` (CUDA err-804); fix is ops, not phase code, but gates SC#1 | ✓ |
| Fold container fix into Phase 58 | Treat the CUDA-compat fix as in-scope implementation work | |

**User's choice:** "you decide" → Prerequisite ops fix, flagged as a live-fire blocker (D-07).
**Notes:** Root cause is the documented GeForce forward-compat hang (`project_whisper_cuda_compat_geforce_804`).

---

## Failure semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Fail-open | Persist capture row, null transcript on Whisper failure, proceed with available modalities; WARNING log | ✓ |
| Fail-closed / retry | Drop or retry the capture when transcription/attachment fails | |

**User's choice:** "you decide" → Fail-open (D-04..D-06).
**Notes:** Capture is pre-confirmation, so the no-silent-failure-after-YES rule does not bind.
Attachment-download race (SC#3): verify path exists before passing to extractor; drop the
modality + WARNING if missing — never hand the extractor a path to a missing file.

---

## Capture pipeline seam

| Option | Description | Selected |
|--------|-------------|----------|
| Light constraint, planner decides internals | `handle(envelope)` entry mirroring Node `createCapturePipeline`; keep transcribe_client / capture_repo / slug-resolver separable (Foray) | ✓ |

**User's choice:** "you decide" → Light constraint (D-08); internal structure is the planner's call.
**Notes:** Wires to Phase 57's `dispatch(envelope)` seam.

## Claude's Discretion

All four areas were delegated by Santi ("you decide"). Claude made the recommended calls
D-01..D-08; the planner retains latitude on internal module structure, attachment-dir layout
(port the Node ULID scheme), and error taxonomy, provided D-01..D-06 hold.

## Deferred Ideas

- In-process Whisper (ProcessPoolExecutor) for Foray self-containment — revisit at the Foray milestone.
- Durable Whisper CUDA-compat fix — ops/infra concern beyond this phase.
- Alerter timezone fix — pre-accepted v1.12 delta, tracked separately.
</content>
