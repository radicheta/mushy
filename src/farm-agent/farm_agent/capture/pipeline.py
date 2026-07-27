"""
capture/pipeline.py -- Capture pipeline orchestrator (CAP-01/CAP-02).

Port of src/agents/alerter/src/capture.js createCapturePipeline().

Factory: create_capture_pipeline(pool, signal_client, transcribe_client, config,
           capture_repo=None, dispatch_result=None, logger=None)
         -> {"handle": handle, "record_reply_capture": record_reply_capture}

Key invariants (from 58-CONTEXT.md and 58-PLAN.md):
  D-03: handle() NEVER raises -- outer try/except returns None on any unhandled error.
  D-04: Transcription failure is fail-open -- row persisted with transcript=None, degraded=True.
  D-05: Path.exists() checked AFTER write_bytes -- path only added if file confirmed on disk.
  D-06: No farmer-facing acks at capture stage (PRE-confirmation).
  SC#2: transcription is async HTTP -- loop yields during await, not blocked.
  V7:   mask_number(source) on every log line referencing the sender e164.
  V12:  build_path derives name from server ULID + safe_ext(contentType) ONLY -- att.filename NEVER used.

CAP-01: envelope -> signal_capture row (ULID id, farmer slug, attachments downloaded).
CAP-02: audio transcribed off-loop via async HTTP call to whisper-transcribe.
T-58-03-01: path traversal -- build_path ignores att.filename (V12).
T-58-03-02: PII -- mask_number(source) on all log lines; attachment path uses ULID only.
T-58-03-03: DoS -- outer try/except D-03; receive loop continues on any error.
T-58-03-04: corpus_context -- hard-coded None (never from live envelope).
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from psycopg_pool import AsyncConnectionPool
from ulid import ULID

from farm_agent.capture import capture_repo as _default_capture_repo
from farm_agent.signal_io.router import _read_dm, mask_number, resolve_farmer
from farm_agent.tenancy.tenant import TenantConfig

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level pure helpers (port of capture.js:12-44)
# ---------------------------------------------------------------------------

AUDIO_TYPES = frozenset([
    "audio/aac", "audio/mp4", "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm",
])
IMAGE_TYPES = frozenset([
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "image/gif",
])
SAFE_EXT_MAP: dict[str, str] = {
    "audio/aac": "aac", "audio/mp4": "m4a", "audio/mpeg": "mp3",
    "audio/ogg": "ogg", "audio/wav": "wav", "audio/webm": "webm",
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/heic": "heic", "image/heif": "heif", "image/gif": "gif",
}

# Audio extensions for finding the first audio path in attachment_paths
_AUDIO_EXTS = re.compile(r"\.(aac|m4a|mp3|ogg|wav|webm)$", re.IGNORECASE)


def classify(text: str | None, attachments: list[dict]) -> str:
    """Classify a message as text/audio/image/mixed. Port of capture.js:classify."""
    has_audio = any(
        a.get("contentType") in AUDIO_TYPES or a.get("voiceNote") is True
        for a in attachments
    )
    has_image = any(a.get("contentType") in IMAGE_TYPES for a in attachments)
    if has_audio and (has_image or text):
        return "mixed"
    if has_audio:
        return "audio"
    if has_image:
        return "image"
    return "text"


def safe_ext(content_type: str | None) -> str:
    """Map content-type to a safe file extension. Port of capture.js:safeExt."""
    return SAFE_EXT_MAP.get(content_type or "", "bin")


def build_path(base_dir: str, captured_at_ms: int, file_id: str, ext: str) -> str:
    """Build server-controlled attachment path. Port of capture.js:buildPath (V12 hardening).

    Pattern: base_dir/<YYYY-MM-DD>/<HH-MM-SS>-<file_id>.<sanitized_ext>
    NEVER uses client-supplied filename -- only ULID + safe extension (T-58-03-01).
    """
    dt = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
    day = dt.strftime("%Y-%m-%d")
    time_part = dt.strftime("%H-%M-%S")
    sanitized_ext = re.sub(r"[^a-z0-9]", "", ext, flags=re.IGNORECASE)
    return str(Path(base_dir) / day / f"{time_part}-{file_id}.{sanitized_ext}")


def _coerce_ts(v: Any) -> int | None:
    """Coerce a numeric or numeric-string timestamp to int. Returns None if invalid.

    Port of capture.js:134-136 (Number.isFinite(Number(x)) equivalent).
    """
    if v is None:
        return None
    try:
        f = float(str(v))
        return int(f) if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _generate_capture_id(captured_at_ms: int) -> str:
    """Generate a ULID string seeded with captured_at_ms. Port of capture.js:ulid(capturedAtMs).

    Uses A1-RESOLVED call form from 58-01-SUMMARY: from ulid import ULID; ULID.from_datetime(dt).
    """
    dt = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
    return str(ULID.from_datetime(dt))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_capture_pipeline(
    pool: AsyncConnectionPool | None,
    signal_client: Any,
    transcribe_client: dict,
    config: TenantConfig,
    capture_repo: Any = None,
    dispatch_result: Callable | None = None,
    log: logging.Logger | None = None,
    gate: dict | None = None,
    extractor: dict | None = None,
) -> dict:
    """Factory returning {"handle": handle, "record_reply_capture": record_reply_capture}.

    Port of createCapturePipeline() from capture.js.

    Args:
        pool:             Injected psycopg3 pool (may be None for unit tests with fake capture_repo).
        signal_client:    Duck-typed client with async fetch_attachment(id) -> bytes.
        transcribe_client: {"transcribe": async(arg) -> {ok,...}} dict (Plan 02 leaf unit).
        config:           TenantConfig -- the sole env-reader (FND-02).
        capture_repo:     Optional override for capture_repo module (for testing).
                          Defaults to the real capture_repo module (insert_capture function).
        dispatch_result:  Optional Phase 59+ seam. If set, called with the CaptureResult
                          after insert_capture completes (fire-forward, also try/except'd).
        log:              Optional logger; defaults to module logger.
        gate:             Optional Phase 59 event-gate dict
                          {"classify": async(env_ctx, last_bot_outbound, now_ms) -> {...}}.
                          Default None = gate disabled (backward-compatible). When set,
                          the gate is called fail-open after transcription -- a gate error
                          never blocks capture from being persisted (T-59-03-02).

    Returns:
        {"handle": handle, "record_reply_capture": record_reply_capture}
    """
    _log = log or _LOG
    _repo = capture_repo if capture_repo is not None else _default_capture_repo

    # ---------------------------------------------------------------------------
    # handle(envelope)
    # ---------------------------------------------------------------------------

    async def handle(envelope: dict) -> dict | None:
        """Process one inbound Signal envelope into a signal_capture row.

        Steps 1-4 (see PLAN.md task 1 <action>):
          1. Parse envelope (source, dm, text, attachments, farmer slug, ULID, classify)
          2. Download attachments (per-att try/except; D-05 disk-existence gate)
          3. Transcribe first audio attachment (D-04 fail-open)
          4. Persist signal_capture row (fail-open)
          5. Return CaptureResult dict; optionally fire dispatch_result seam (Phase 59+)

        NEVER raises (D-03). Returns None on unhandled error.
        """
        try:
            # --- Step 1: parse envelope ---
            env = envelope.get("envelope") or envelope
            source: str = env.get("source") or env.get("sourceNumber") or ""
            dm = _read_dm(envelope)
            text: str | None = dm.get("message") or None
            attachments: list[dict] = dm.get("attachments") or []
            group_info = dm.get("groupInfo") or {}
            group_id: str | None = group_info.get("groupId") or None
            reply_target_kind = "group" if group_id else "dm"

            captured_at_ms = _coerce_ts(dm.get("timestamp")) or int(time.time() * 1000)
            capture_id = _generate_capture_id(captured_at_ms)
            farmos_person = resolve_farmer(source, config)
            message_type = classify(text, attachments)

            # Phase 50 timestamp fields (port of capture.js:134-144)
            signal_msg_ts = _coerce_ts(dm.get("timestamp"))
            q = dm.get("quote") or {}
            quote_msg_ts_raw = q.get("id") if q.get("id") is not None else q.get("timestamp")
            quote_msg_ts = _coerce_ts(quote_msg_ts_raw)
            quote_author: str | None = None
            if q:
                if isinstance(q.get("author"), str) and q.get("author"):
                    quote_author = q["author"]
                elif isinstance(q.get("authorNumber"), str) and q.get("authorNumber"):
                    quote_author = q["authorNumber"]

            attachment_paths: list[str] = []
            degraded = False
            transcript: str | None = None

            # --- Step 2: download attachments (per-attachment try/except) ---
            for att in attachments:
                try:
                    att_id = att.get("id") or ""
                    buf = await signal_client.fetch_attachment(att_id)
                    ext = safe_ext(att.get("contentType"))
                    file_id = f"{capture_id}-{att_id}"
                    path_str = build_path(config.capture_base_dir, captured_at_ms, file_id, ext)
                    Path(path_str).parent.mkdir(parents=True, exist_ok=True)
                    Path(path_str).write_bytes(buf)
                    # D-05: verify file exists on disk before adding to paths
                    if not Path(path_str).exists():
                        _log.warning(
                            "[capture] attachment missing after write (D-05): sender=%s att_id=%s",
                            mask_number(source),
                            att_id,
                        )
                        degraded = True
                        continue
                    attachment_paths.append(path_str)
                except Exception as exc:  # noqa: BLE001
                    _log.warning(
                        "[capture] attachment download failed: sender=%s att_id=%s err=%s",
                        mask_number(source),
                        att.get("id"),
                        exc,
                    )
                    degraded = True

            # --- Step 3: transcribe first audio attachment (D-04 fail-open) ---
            audio_path: str | None = next(
                (p for p in attachment_paths if _AUDIO_EXTS.search(p)), None
            )
            if audio_path:
                try:
                    r = await transcribe_client["transcribe"](audio_path)
                    if r.get("ok"):
                        transcript = r.get("text")
                    else:
                        _log.warning(
                            "[capture] transcription fail-open (D-04): sender=%s reason=%s",
                            mask_number(source),
                            r.get("reason"),
                        )
                        degraded = True
                        # transcript stays None -- D-04
                except Exception as exc:  # noqa: BLE001
                    _log.warning(
                        "[capture] transcription error (D-04): sender=%s err=%s",
                        mask_number(source),
                        exc,
                    )
                    degraded = True

            # --- Step 3b: gate call (Phase 59 event-gate, fail-open) ---
            # T-59-03-02: gate error never blocks capture from being persisted.
            # T-59-03-01: log only gate outcome + masked sender; never env_ctx text/transcript.
            extraction_gate: str | None = None
            if gate is not None:
                try:
                    env_ctx = {
                        "text": text,
                        "transcript": transcript,
                        "attachmentCount": len(attachment_paths),
                    }
                    # TODO(Phase 60): wire last_bot_outbound from capture_history.select_recent_outbound_by_recipient
                    # so rule_negative can fast-reject short acks within the 30-min attestation window.
                    gate_result = await gate["classify"](env_ctx, None, int(time.time() * 1000))
                    extraction_gate = gate_result.get("gate")
                    _log.info(
                        "[capture] gate=%s allow_extract=%s sender=%s",
                        gate_result.get("gate"),
                        gate_result.get("allow_extract"),
                        mask_number(source),
                    )
                except Exception as exc:  # noqa: BLE001
                    _log.warning(
                        "[capture] gate error (fail-open): sender=%s err=%s",
                        mask_number(source),
                        exc,
                    )
                    # extraction_gate stays None -- capture is still persisted (T-59-03-02)

            # --- Step 4: persist signal_capture row (fail-open) ---
            row = {
                "id": capture_id,
                "captured_at": datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc),
                "sender": source,
                "message_type": message_type,
                "raw_text": text,
                "attachment_paths": attachment_paths,
                "transcript": transcript,
                "degraded": degraded,
                "group_id": group_id,
                "farmos_person": farmos_person,
                "reply_target_kind": reply_target_kind,
                "signal_msg_ts": signal_msg_ts,
                "quote_msg_ts": quote_msg_ts,
                "quote_author_e164": quote_author,
                # corpus_context: always None for live captures (T-58-03-04)
                "extraction_gate": extraction_gate,  # Phase 59; VARCHAR(32), migration 007
            }
            persist_result = await _repo.insert_capture(pool, row)
            if not persist_result.get("ok"):
                _log.warning(
                    "[capture] insert_capture failed (D-04 fail-open): sender=%s reason=%s",
                    mask_number(source),
                    persist_result.get("reason"),
                )
                degraded = True

            # --- Step 5: return CaptureResult and optionally fire Phase 59+ seam ---
            result = {
                "capture_id": capture_id,
                "sender": source,
                "farmos_person": farmos_person,
                "raw_text": text,
                "transcript": transcript,
                "attachment_paths": attachment_paths,
                "reply_target_kind": reply_target_kind,
                "group_id": group_id,
                "captured_at_ms": captured_at_ms,
                "signal_msg_ts": signal_msg_ts,
                "quote_msg_ts": quote_msg_ts,
                "quote_author_e164": quote_author,
                "degraded": degraded,
                "message_type": message_type,
            }

            if dispatch_result is not None:
                try:
                    await dispatch_result(result)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("[capture] dispatch_result seam error: %s", exc)

            return result

        except Exception as exc:  # noqa: BLE001 -- D-03: errors never escape handle()
            _log.warning("[capture] unhandled error in handle(): %s", exc)
            return None

    # ---------------------------------------------------------------------------
    # record_reply_capture(envelope)
    # ---------------------------------------------------------------------------

    async def record_reply_capture(envelope: dict, ctx: dict | None = None) -> None:
        """Persist a confirm-thread reply (YES/NO/EDIT) WITHOUT downloading attachments
        or transcribing. Port of capture.js:recordReplyCapture.

        This exists so confirm-thread messages land in signal_capture for Phase 50
        quote-routing and the farmer paper trail. No Step 2/3 (attachment/transcription)
        and no CaptureResult return.
        """
        ctx = ctx or {}
        try:
            env = envelope.get("envelope") or envelope
            source: str = env.get("source") or env.get("sourceNumber") or ""
            dm = _read_dm(envelope)
            text: str | None = dm.get("message") or None
            attachments: list[dict] = dm.get("attachments") or []
            group_info = dm.get("groupInfo") or {}
            group_id: str | None = ctx.get("group_id") or group_info.get("groupId") or None
            farmos_person = resolve_farmer(source, config)
            reply_target_kind = ctx.get("reply_target_kind") or ("group" if group_id else "dm")
            captured_at_ms = _coerce_ts(dm.get("timestamp")) or int(time.time() * 1000)
            capture_id = _generate_capture_id(captured_at_ms)

            signal_msg_ts = _coerce_ts(dm.get("timestamp"))
            q = dm.get("quote") or {}
            quote_msg_ts_raw = q.get("id") if q.get("id") is not None else q.get("timestamp")
            quote_msg_ts = _coerce_ts(quote_msg_ts_raw)
            quote_author: str | None = None
            if q:
                if isinstance(q.get("author"), str) and q.get("author"):
                    quote_author = q["author"]
                elif isinstance(q.get("authorNumber"), str) and q.get("authorNumber"):
                    quote_author = q["authorNumber"]

            row = {
                "id": capture_id,
                "captured_at": datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc),
                "sender": source,
                "message_type": classify(text, attachments),
                "raw_text": text,
                "attachment_paths": [],  # persist-only: no download
                "transcript": None,     # persist-only: no transcription
                "degraded": False,
                "group_id": group_id,
                "farmos_person": farmos_person,
                "reply_target_kind": reply_target_kind,
                "signal_msg_ts": signal_msg_ts,
                "quote_msg_ts": quote_msg_ts,
                "quote_author_e164": quote_author,
            }
            await _repo.insert_capture(pool, row)
            _log.debug(
                "[capture] reply persisted (confirm-thread) sender=%s ts=%s",
                mask_number(source),
                signal_msg_ts,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("[capture] record_reply_capture failed: %s", exc)

    return {"handle": handle, "record_reply_capture": record_reply_capture}
