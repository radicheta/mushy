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
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

MODEL_NAME = os.getenv("WHISPER_MODEL", "medium")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
ALLOWED_ROOT = Path(os.getenv("ALLOWED_ROOT", "/data/signal-capture")).resolve()

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


@app.on_event("startup")
def _startup_probe():
    """Eagerly load model + run synthetic transcription at startup.

    Why: compose healthcheck timeout is short (5s) but cold-loading the medium
    model on cuda takes ~30s. If we probed lazily in /health, the first
    healthcheck would time out, compose would mark unhealthy, restart the
    container, and loop forever. Loading at startup means /health is cheap
    and the slow cost lives in the boot window (start_period in compose).
    """
    global _health_ok, _health_reason
    try:
        _probe_model()
        _health_ok = True
        _health_reason = "ok"
    except Exception as e:
        _health_reason = f"{type(e).__name__}: {str(e)[:200]}"


@app.get("/health")
def health():
    if _health_ok:
        return {"ok": True, "model_loaded": True}
    return JSONResponse(
        status_code=503,
        content={"ok": False, "reason": _health_reason},
    )
