"""whisper-transcribe FastAPI service.

POST /transcribe { audio_path } -> { text, duration_ms, language, language_probability }
GET  /health                    -> 200 { ok: true, model_loaded: true }
                                -> 503 { ok: false, reason: "<short>" }

Deep health (Plan 09 Task 1, 2026-05-12): /health constructs the model and runs
a synthetic 1-second silent transcription. Catches GPU-drift, missing CUDA,
broken nvidia-container-toolkit cgroup mapping, etc., in seconds rather than
when a real /transcribe arrives. Result is cached so we don't re-probe CUDA
on every healthcheck once it's confirmed working; cache invalidated only by
process restart (Docker compose healthcheck will restart on persistent 503).

Hallucination mitigation (Plan 09 footnote, 2026-05-12): /transcribe passes
vad_filter=True and condition_on_previous_text=False. The first dampens the
"9, 10, 11, 12..." counting tails on long audio (model hallucinating into
trailing silence); the second prevents the model's context from amplifying
earlier mistakes downstream in the same recording.
"""
import os
import time
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

MODEL_NAME = os.getenv("WHISPER_MODEL", "medium")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
ALLOWED_ROOT = Path(os.getenv("ALLOWED_ROOT", "/data/signal-capture")).resolve()

# --- model-load resilience (2026-06-21) ---
# elder-plops shares one 6GB GPU across desktop + other workloads, so the medium
# model load intermittently hits "CUDA out of memory". A single failed load used
# to wedge the service unhealthy forever (nothing retried). Instead: retry with
# backoff to ride out transient contention, alert the operator once if the quick
# retries are exhausted, then keep slow-retrying so it self-heals when VRAM frees.
_LOAD_BACKOFFS_S = [5, 15, 45, 120]   # quick recovery attempts before alerting
_SLOW_RETRY_S = 300                   # steady self-heal cadence after alerting
ALERT_URL = os.getenv("WHISPER_ALERT_URL", "http://127.0.0.1:8085")
ALERT_SENDER = os.getenv("SIGNAL_SENDER", "")
# Ops alert -> operator. Prefer an explicit recipient; fall back to the shared one.
ALERT_RECIPIENT = os.getenv("WHISPER_ALERT_RECIPIENT") or os.getenv("SIGNAL_RECIPIENT", "")

app = FastAPI()
_model = None
_health_ok = False  # set true after a synthetic transcription succeeds
_health_reason = "probe not yet run"  # surfaced in 503 body until first probe completes


def get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def _resolve_safe(p: str):
    resolved = Path(p).resolve()
    try:
        resolved.relative_to(ALLOWED_ROOT)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(400, f"path not allowed: outside {ALLOWED_ROOT}")
    return resolved


def _probe_model():
    """Construct model + run a 1s silent synthetic transcription. Raises on failure."""
    import numpy as np
    m = get_model()
    silence = np.zeros(16000, dtype=np.float32)  # 1s @ 16kHz
    segments, _info = m.transcribe(silence, vad_filter=False)
    # Force the generator -- faster-whisper returns lazy iterators.
    list(segments)


class TranscribeReq(BaseModel):
    audio_path: str


@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    path = _resolve_safe(req.audio_path)
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(404, f"audio not found: {path}")
    t0 = time.time()
    segments, info = get_model().transcribe(
        str(path),
        vad_filter=True,
        condition_on_previous_text=False,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return {
        "text": text,
        "duration_ms": int((time.time() - t0) * 1000),
        "language": info.language,
        "language_probability": float(info.language_probability),
    }


def _notify(message: str):
    """Best-effort ops alert to the operator via signal-cli REST. Never raises."""
    if not (ALERT_SENDER and ALERT_RECIPIENT):
        print(f"[whisper alert suppressed: SIGNAL_SENDER/recipient unset] {message}", flush=True)
        return
    try:
        import httpx
        httpx.post(
            f"{ALERT_URL}/v2/send",
            json={"message": message, "number": ALERT_SENDER, "recipients": [ALERT_RECIPIENT]},
            timeout=10.0,
        )
    except Exception as e:
        print(f"[whisper alert send failed: {type(e).__name__}: {e}] {message}", flush=True)


def _warm_load_loop():
    """Load the model with backoff; alert once if quick retries fail; then keep
    slow-retrying so the service self-heals when GPU memory frees up.

    Runs in a daemon thread so startup never blocks: /health returns 503 until
    the model is loaded (covered by the compose start_period), 200 thereafter.
    """
    global _model, _health_ok, _health_reason
    attempt = 0
    alerted = False
    while not _health_ok:
        try:
            _probe_model()
            _health_ok = True
            _health_reason = "ok"
            if alerted:
                _notify("whisper-transcribe recovered: model loaded, transcription back online.")
            return
        except Exception as e:
            _model = None  # drop any half-built model so the next attempt is clean
            attempt += 1
            _health_reason = f"{type(e).__name__}: {str(e)[:200]} (attempt {attempt})"
            print(f"[whisper warm-load] attempt {attempt} failed: {_health_reason}", flush=True)
            if attempt >= len(_LOAD_BACKOFFS_S) and not alerted:
                _notify(
                    f"whisper-transcribe DOWN: model load failed after {attempt} attempts "
                    f"({type(e).__name__}: {str(e)[:120]}). Likely GPU out of memory from other "
                    f"elder-plops activity. Auto-retrying every {_SLOW_RETRY_S // 60} min; "
                    f"free VRAM to speed recovery."
                )
                alerted = True
            delay = _LOAD_BACKOFFS_S[attempt - 1] if attempt <= len(_LOAD_BACKOFFS_S) else _SLOW_RETRY_S
            time.sleep(delay)


@app.on_event("startup")
def _startup_probe():
    """Kick off the resilient warm-load in the background (see _warm_load_loop)."""
    threading.Thread(target=_warm_load_loop, name="whisper-warm-load", daemon=True).start()


@app.get("/health")
def health():
    if _health_ok:
        return {"ok": True, "model_loaded": True}
    return JSONResponse(
        status_code=503,
        content={"ok": False, "reason": _health_reason},
    )
