"""whisper-transcribe FastAPI service.

POST /transcribe { audio_path } -> { text, duration_ms, language, language_probability }
GET  /health                    -> { ok: bool, model_loaded: bool }

Lazy-loads faster-whisper WhisperModel singleton on first /transcribe call (Pitfall 5).
V12 mitigation: rejects any audio_path that does not resolve under ALLOWED_ROOT.
"""
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MODEL_NAME = os.getenv("WHISPER_MODEL", "medium")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
ALLOWED_ROOT = Path(os.getenv("ALLOWED_ROOT", "/data/signal-capture")).resolve()

app = FastAPI()
_model = None  # lazy-load — see Pitfall 5


def get_model():
    global _model
    if _model is None:
        # Imported lazily so unit tests that monkey-patch get_model never need
        # faster-whisper / CUDA libs to be present.
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def _resolve_safe(p: str) -> Path:
    """V12 mitigation: reject any path that does not resolve inside ALLOWED_ROOT."""
    resolved = Path(p).resolve()
    try:
        resolved.relative_to(ALLOWED_ROOT)
    except ValueError:
        raise HTTPException(400, f"path not allowed: outside {ALLOWED_ROOT}")
    return resolved


class TranscribeReq(BaseModel):
    audio_path: str


@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    path = _resolve_safe(req.audio_path)
    if not path.exists():
        raise HTTPException(404, f"audio not found: {path}")
    t0 = time.time()
    segments, info = get_model().transcribe(str(path))  # auto-detect lang per D-08
    text = " ".join(s.text.strip() for s in segments).strip()
    return {
        "text": text,
        "duration_ms": int((time.time() - t0) * 1000),
        "language": info.language,
        "language_probability": float(info.language_probability),
    }


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _model is not None}
