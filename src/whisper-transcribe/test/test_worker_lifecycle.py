"""MUSHY-33: the model must not sit on the GPU between transcriptions.

whisper-transcribe held the medium model resident on a shared 6GB RTX 2060
from container start until container stop -- 2,050 MiB around the clock to
serve 12 voice notes in four months.

The model now lives in a worker SUBPROCESS that is spawned on demand and
reaped after an idle window, so the CUDA context dies with it and VRAM
returns to zero rather than to the ~300 MiB an in-process unload would leave
behind.

These tests drive the manager with a fake worker: the lifecycle rules are the
thing under test, not faster_whisper.
"""
import importlib
import os
import time

import pytest
from fastapi.testclient import TestClient


class FakeWorker:
    """In-process stand-in for the spawned child. Records its own lifecycle."""

    instances: list["FakeWorker"] = []

    def __init__(self, *, fail_on_start=False, fail_on_call=False):
        self.started = False
        self.stopped = False
        self.calls: list[dict] = []
        self._fail_on_start = fail_on_start
        self._fail_on_call = fail_on_call
        FakeWorker.instances.append(self)

    def start(self):
        if self._fail_on_start:
            raise RuntimeError("CUDA failed with error no CUDA-capable device is detected")
        self.started = True

    def alive(self):
        return self.started and not self.stopped

    def call(self, payload, timeout_s=None):
        if self._fail_on_call:
            raise RuntimeError("worker died")
        self.calls.append(payload)
        if payload.get("probe"):
            return {"ok": True, "probe": True}
        return {"ok": True, "text": "stub", "language": "en", "language_probability": 0.99}

    def stop(self):
        self.stopped = True


@pytest.fixture
def mod(monkeypatch, tmp_path):
    os.environ["ALLOWED_ROOT"] = str(tmp_path)
    os.environ["WHISPER_IDLE_UNLOAD_S"] = "600"
    import main
    importlib.reload(main)
    FakeWorker.instances = []
    monkeypatch.setattr(main, "_make_worker", lambda: FakeWorker())
    return main, tmp_path


# ---------------------------------------------------------------------------
# Spawn on demand
# ---------------------------------------------------------------------------


def test_no_worker_exists_before_any_job(mod):
    main, _ = mod
    assert main._worker is None, "importing the service must not touch the GPU"


def test_first_transcribe_spawns_the_worker(mod):
    main, root = mod
    audio = root / "note.m4a"
    audio.write_bytes(b"stub")

    c = TestClient(main.app)  # no lifespan: the endpoint is what is under test
    r = c.post("/transcribe", json={"audio_path": str(audio)})

    assert r.status_code == 200, r.text
    assert r.json()["text"] == "stub"
    assert any(w.started for w in FakeWorker.instances)


def test_a_burst_reuses_one_worker(mod):
    """Three notes in a session must pay the model load once, not three times."""
    main, root = mod
    audio = root / "note.m4a"
    audio.write_bytes(b"stub")

    for _ in range(3):
        main._submit({"audio_path": str(audio)})

    started = [w for w in FakeWorker.instances if w.started]
    assert len(started) == 1, f"expected one worker for a burst, spawned {len(started)}"
    assert len(started[0].calls) == 3


# ---------------------------------------------------------------------------
# Idle reaping -- the whole point of the ticket
# ---------------------------------------------------------------------------


def test_worker_survives_inside_the_idle_window(mod):
    main, root = mod
    main._submit({"audio_path": str(root / "a.m4a")})

    reaped = main._reap_if_idle(now=main._last_job_at + 599)

    assert reaped is False
    assert main._worker is not None
    assert not FakeWorker.instances[0].stopped


def test_worker_is_reaped_once_the_idle_window_passes(mod):
    main, root = mod
    main._submit({"audio_path": str(root / "a.m4a")})

    reaped = main._reap_if_idle(now=main._last_job_at + 601)

    assert reaped is True
    assert main._worker is None, "the handle must be dropped, not just stopped"
    assert FakeWorker.instances[0].stopped, "the child must be terminated to free VRAM"


def test_reaping_when_no_worker_exists_is_a_noop(mod):
    main, _ = mod
    assert main._reap_if_idle(now=time.time()) is False


def test_a_reaped_worker_is_respawned_on_the_next_note(mod):
    """VRAM goes to zero, and the next voice note still transcribes."""
    main, root = mod
    audio = root / "a.m4a"
    main._submit({"audio_path": str(audio)})
    main._reap_if_idle(now=main._last_job_at + 601)

    result = main._submit({"audio_path": str(audio)})

    assert result["ok"] is True
    started = [w for w in FakeWorker.instances if w.started]
    assert len(started) == 2, "a second worker must be spawned after the reap"
    assert started[0].stopped and not started[1].stopped


# ---------------------------------------------------------------------------
# Failure must be loud. A silently-degraded voice note is the documented
# failure mode of this service.
# ---------------------------------------------------------------------------


def test_a_dead_worker_surfaces_an_error_rather_than_empty_text(mod, monkeypatch):
    main, root = mod
    audio = root / "note.m4a"
    audio.write_bytes(b"stub")
    monkeypatch.setattr(main, "_make_worker", lambda: FakeWorker(fail_on_call=True))

    c = TestClient(main.app)
    r = c.post("/transcribe", json={"audio_path": str(audio)})

    assert r.status_code >= 500, "an empty transcript would look like a silent farmer"
    assert "text" not in r.json() or not r.json().get("text")


def test_a_failed_worker_is_dropped_so_the_next_call_starts_clean(mod, monkeypatch):
    main, root = mod
    monkeypatch.setattr(main, "_make_worker", lambda: FakeWorker(fail_on_call=True))

    with pytest.raises(Exception):
        main._submit({"audio_path": str(root / "a.m4a")})

    assert main._worker is None, "a half-dead worker must never be reused"
    assert FakeWorker.instances[0].stopped


# ---------------------------------------------------------------------------
# Health semantics: idle is NOT unhealthy.
# ---------------------------------------------------------------------------


def test_health_is_ok_while_the_model_is_deliberately_unloaded(mod):
    """The reason /health could not simply keep meaning 'model loaded'."""
    main, root = mod
    main._submit({"audio_path": str(root / "a.m4a")})
    main._probe_once()
    main._reap_if_idle(now=main._last_job_at + 601)

    c = TestClient(main.app)
    r = c.get("/health")

    assert r.status_code == 200, "an idle service is working as designed, not broken"
    body = r.json()
    assert body["ok"] is True
    assert body["model_loaded"] is False, "health must report the model is not resident"


def test_health_503_while_cuda_is_broken(mod, monkeypatch):
    main, _ = mod
    monkeypatch.setattr(main, "_make_worker", lambda: FakeWorker(fail_on_start=True))

    main._probe_once()

    c = TestClient(main.app)
    r = c.get("/health")

    assert r.status_code == 503
    assert "CUDA" in r.json()["reason"]
