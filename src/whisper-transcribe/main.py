"""whisper-transcribe FastAPI service.

POST /transcribe { audio_path } -> { text, duration_ms, language, language_probability }
GET  /health                    -> 200 { ok: true, model_loaded: bool }
                                -> 503 { ok: false, reason: "<short>" }

Deep health (Plan 09 Task 1, 2026-05-12): startup runs a synthetic 1-second
silent transcription. Catches GPU-drift, missing CUDA, broken
nvidia-container-toolkit cgroup mapping, etc., in seconds rather than when a
real /transcribe arrives. Result is cached so we don't re-probe CUDA on every
healthcheck once it's confirmed working.

On-demand GPU (MUSHY-33, 2026-08-19): the model no longer lives in this
process. It lives in a worker SUBPROCESS that is spawned on demand and reaped
after WHISPER_IDLE_UNLOAD_S seconds without a job. Before this, the medium
model sat on a shared 6GB RTX 2060 from container start to container stop --
2,050 MiB around the clock to serve 12 voice notes in four months.

A subprocess rather than an in-process `del model`: freeing the weights in
process leaves the CUDA context behind (~300 MiB) for the life of the
container. Killing the child returns everything.

The cold-load cost lands on the first request after idle. That is affordable
because the caller (farm_agent/capture/transcribe_client.py) already allows
200s, against a ~30-60s load.

Hallucination mitigation (Plan 09 footnote, 2026-05-12): /transcribe passes
vad_filter=True and condition_on_previous_text=False. The first dampens the
"9, 10, 11, 12..." counting tails on long audio (model hallucinating into
trailing silence); the second prevents the model's context from amplifying
earlier mistakes downstream in the same recording.
"""
import multiprocessing as mp
import os
import time
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

MODEL_NAME = os.getenv("WHISPER_MODEL", "medium")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
ALLOWED_ROOT = Path(os.getenv("ALLOWED_ROOT", "/data/signal-capture")).resolve()

# MUSHY-33: how long a loaded model stays warm after its last job. Sized to
# cover a farmer sending several notes in one session, then release.
IDLE_UNLOAD_S = int(os.getenv("WHISPER_IDLE_UNLOAD_S", "600"))
# Ceiling on a single job so a wedged child cannot hold the lock forever.
# Deliberately LONGER than the caller's 200s budget: the client should be the
# one that gives up on a slow transcription, this is only a backstop.
JOB_TIMEOUT_S = int(os.getenv("WHISPER_JOB_TIMEOUT_S", "900"))
# Cold model load. Generous: the medium model takes ~30-60s on a contended GPU.
LOAD_TIMEOUT_S = int(os.getenv("WHISPER_LOAD_TIMEOUT_S", "300"))
_REAP_TICK_S = max(5, min(30, IDLE_UNLOAD_S // 10))

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

_worker = None                        # active WorkerHandle, or None when reaped
_worker_lock = threading.RLock()      # serializes GPU access AND worker lifecycle
_last_job_at = 0.0
_probe_ok = False                     # set true after a synthetic transcription succeeds
_probe_reason = "probe not yet run"   # surfaced in 503 body until first probe completes


# ---------------------------------------------------------------------------
# Worker child
# ---------------------------------------------------------------------------


def _worker_main(conn, model_name, device, compute_type):  # pragma: no cover - child process
    """Entry point of the spawned child. Owns the model and the CUDA context.

    Never returns while the parent keeps the pipe open and keeps sending jobs.
    Exiting is how VRAM is freed, so there is deliberately no unload path here.
    """
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        conn.send({"ok": True, "event": "ready"})
    except BaseException as e:  # noqa: BLE001 -- must report, not crash silently
        conn.send({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return

    while True:
        try:
            msg = conn.recv()
        except EOFError:
            return
        if msg is None:
            return
        try:
            if msg.get("probe"):
                import numpy as np
                segments, _info = model.transcribe(
                    np.zeros(16000, dtype=np.float32), vad_filter=False
                )
                list(segments)  # force the lazy iterator
                conn.send({"ok": True, "probe": True})
                continue
            segments, info = model.transcribe(
                msg["audio_path"],
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            conn.send({
                "ok": True,
                "text": text,
                "language": info.language,
                "language_probability": float(info.language_probability),
            })
        except BaseException as e:  # noqa: BLE001
            conn.send({"ok": False, "error": f"{type(e).__name__}: {e}"})


class SubprocessWorker:
    """Parent-side handle on the model child.

    spawn, not fork: CUDA cannot be initialised in a forked child.
    """

    def __init__(self, model_name, device, compute_type):
        self._args = (model_name, device, compute_type)
        self._proc = None
        self._conn = None

    def start(self):
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        self._proc = ctx.Process(
            target=_worker_main,
            args=(child_conn, *self._args),
            name="whisper-worker",
            daemon=True,
        )
        self._proc.start()
        child_conn.close()  # the child owns its end now
        self._conn = parent_conn
        if not parent_conn.poll(LOAD_TIMEOUT_S):
            raise RuntimeError(f"worker did not load the model within {LOAD_TIMEOUT_S}s")
        ready = parent_conn.recv()
        if not ready.get("ok"):
            raise RuntimeError(ready.get("error") or "worker failed to load the model")

    def alive(self):
        return self._proc is not None and self._proc.is_alive()

    def call(self, payload, timeout_s=None):
        if not self.alive():
            raise RuntimeError("worker is not running")
        self._conn.send(payload)
        if not self._conn.poll(timeout_s or JOB_TIMEOUT_S):
            raise RuntimeError(f"worker timed out after {timeout_s or JOB_TIMEOUT_S}s")
        res = self._conn.recv()
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "worker error")
        return res

    def stop(self):
        try:
            if self._conn is not None:
                self._conn.send(None)
        except Exception:  # noqa: BLE001 -- best effort; terminate is the real close
            pass
        try:
            if self._proc is not None:
                self._proc.join(timeout=5)
                if self._proc.is_alive():
                    self._proc.terminate()
                    self._proc.join(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._proc = None
            self._conn = None


def _make_worker():
    """Seam: tests replace this with an in-process fake."""
    return SubprocessWorker(MODEL_NAME, DEVICE, COMPUTE_TYPE)


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------


def _stop_worker_locked():
    """Drop the worker. Caller MUST hold _worker_lock."""
    global _worker
    w, _worker = _worker, None
    if w is not None:
        w.stop()


def _submit(payload, timeout_s=None):
    """Run one job on the worker, spawning it if the GPU is currently free.

    Serialized: one job at a time, which the single GPU wants anyway, and which
    keeps spawn/reap from racing a job in flight.

    A failed job drops the worker rather than reusing it -- a child that raised
    may have a poisoned CUDA context, and the next voice note must not inherit
    it.
    """
    global _last_job_at
    with _worker_lock:
        global _worker
        if _worker is None or not _worker.alive():
            _stop_worker_locked()
            w = _make_worker()
            w.start()
            _worker = w
        try:
            res = _worker.call(payload, timeout_s)
        except Exception:
            _stop_worker_locked()
            raise
        _last_job_at = time.time()
        return res


def _reap_if_idle(now=None):
    """Terminate the worker once IDLE_UNLOAD_S has passed since the last job.

    Returns True when a worker was reaped. This is where the VRAM actually
    comes back, so it is a plain function the tests can drive with an explicit
    clock rather than something buried in a sleep loop.
    """
    with _worker_lock:
        if _worker is None:
            return False
        if (now if now is not None else time.time()) - _last_job_at < IDLE_UNLOAD_S:
            return False
        print(
            f"[whisper] idle {IDLE_UNLOAD_S}s: releasing the GPU (worker exit)",
            flush=True,
        )
        _stop_worker_locked()
        return True


def _reaper_loop():  # pragma: no cover - timing loop
    while True:
        time.sleep(_REAP_TICK_S)
        try:
            _reap_if_idle()
        except Exception as e:  # noqa: BLE001 -- the reaper must never die
            print(f"[whisper] reaper error: {type(e).__name__}: {e}", flush=True)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _resolve_safe(p: str):
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
    try:
        res = _submit({"audio_path": str(path)})
    except Exception as e:  # noqa: BLE001
        # Loud, not empty. An empty transcript is indistinguishable from a
        # farmer who said nothing, which is how this service fails silently.
        raise HTTPException(503, f"transcription failed: {type(e).__name__}: {e}")
    return {
        "text": res.get("text", ""),
        "duration_ms": int((time.time() - t0) * 1000),
        "language": res.get("language"),
        "language_probability": float(res.get("language_probability") or 0.0),
    }


def _probe_once():
    """One synthetic transcription through the real worker path. Records the result.

    Leaves the worker warm; the ordinary idle reaper takes it down, so a
    container that boots and is never used still ends at zero VRAM.
    """
    global _probe_ok, _probe_reason
    try:
        _submit({"probe": True}, timeout_s=LOAD_TIMEOUT_S)
        _probe_ok = True
        _probe_reason = "ok"
        return True
    except Exception as e:  # noqa: BLE001
        _probe_reason = f"{type(e).__name__}: {str(e)[:200]}"
        return False


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


def _warm_load_loop():  # pragma: no cover - timing loop
    """Probe with backoff; alert once if quick retries fail; then keep
    slow-retrying so the service self-heals when GPU memory frees up.

    Runs in a daemon thread so startup never blocks: /health returns 503 until
    the first probe succeeds (covered by the compose start_period), 200 after.
    """
    attempt = 0
    alerted = False
    while not _probe_ok:
        if _probe_once():
            if alerted:
                _notify("whisper-transcribe recovered: model loaded, transcription back online.")
            return
        attempt += 1
        print(f"[whisper warm-load] attempt {attempt} failed: {_probe_reason}", flush=True)
        if attempt >= len(_LOAD_BACKOFFS_S) and not alerted:
            _notify(
                f"whisper-transcribe DOWN: model load failed after {attempt} attempts "
                f"({_probe_reason[:120]}). Likely GPU out of memory from other "
                f"elder-plops activity. Auto-retrying every {_SLOW_RETRY_S // 60} min; "
                f"free VRAM to speed recovery."
            )
            alerted = True
        delay = _LOAD_BACKOFFS_S[attempt - 1] if attempt <= len(_LOAD_BACKOFFS_S) else _SLOW_RETRY_S
        time.sleep(delay)


@app.on_event("startup")
def _startup_probe():
    """Kick off the resilient warm-load, plus the idle reaper that frees VRAM."""
    threading.Thread(target=_warm_load_loop, name="whisper-warm-load", daemon=True).start()
    threading.Thread(target=_reaper_loop, name="whisper-reaper", daemon=True).start()


@app.get("/health")
def health():
    if _probe_ok:
        # model_loaded is now INFORMATIONAL, not the health verdict. An idle
        # service with no model resident is working exactly as designed; if
        # this still gated the 200 the reaper would mark the container
        # unhealthy every time it did its job.
        with _worker_lock:
            loaded = _worker is not None and _worker.alive()
        return {
            "ok": True,
            "model_loaded": loaded,
            "idle_unload_s": IDLE_UNLOAD_S,
        }
    return JSONResponse(
        status_code=503,
        content={"ok": False, "reason": _probe_reason},
    )
