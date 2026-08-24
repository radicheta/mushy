"""Unit tests for whisper-transcribe (no GPU; runs in CI).

Strategy: replace main._make_worker with an in-process fake that returns
canned segments. MUSHY-33 moved the model out of this process into a spawned
child, so the injection seam is the worker handle, not get_model.

ALLOWED_ROOT is reset per-test via env + importlib.reload(main).
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


class _FakeWorker:
    """Stands in for the spawned model child."""

    def __init__(self, fail_on_start=False):
        self._fail_on_start = fail_on_start
        self._alive = False

    def start(self):
        if self._fail_on_start:
            raise RuntimeError("CUDA failed with error no CUDA-capable device is detected")
        self._alive = True

    def alive(self):
        return self._alive

    def call(self, payload, timeout_s=None):
        if payload.get("probe"):
            return {"ok": True, "probe": True}
        return {"ok": True, "text": "stub", "language": "en", "language_probability": 0.99}

    def stop(self):
        self._alive = False


@pytest.fixture
def client(monkeypatch, tmp_path):
    os.environ["ALLOWED_ROOT"] = str(tmp_path)
    import main
    importlib.reload(main)
    monkeypatch.setattr(main, "_make_worker", lambda: _FakeWorker())
    # No lifespan: the startup probe runs in a daemon thread, and a test that
    # asserts on probe state must drive it synchronously rather than race it.
    yield TestClient(main.app), tmp_path


def test_health_ok_when_probe_succeeds(monkeypatch, tmp_path):
    os.environ["ALLOWED_ROOT"] = str(tmp_path)
    import main
    importlib.reload(main)
    monkeypatch.setattr(main, "_make_worker", lambda: _FakeWorker())

    assert main._probe_once() is True

    r = TestClient(main.app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Still warm right after the probe; the idle reaper takes it down later.
    assert body["model_loaded"] is True


def test_health_503_when_cuda_fails(monkeypatch, tmp_path):
    """Plan 09 Task 1: GPU-drift / no-CUDA-device must surface as 503,
    not green-with-broken-transcribe (the 2026-05-12 incident shape)."""
    os.environ["ALLOWED_ROOT"] = str(tmp_path)
    import main
    importlib.reload(main)
    monkeypatch.setattr(main, "_make_worker", lambda: _FakeWorker(fail_on_start=True))

    assert main._probe_once() is False

    r = TestClient(main.app).get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert "CUDA" in body["reason"]


def test_404_on_missing(client):
    c, root = client
    r = c.post("/transcribe", json={"audio_path": str(root / "missing.wav")})
    assert r.status_code == 404


def test_400_on_path_traversal(client):
    c, _ = client
    r = c.post("/transcribe", json={"audio_path": "/etc/passwd"})
    assert r.status_code == 400


def test_400_on_dotdot(client):
    c, root = client
    bad = str(root / ".." / ".." / "etc" / "passwd")
    r = c.post("/transcribe", json={"audio_path": bad})
    assert r.status_code == 400


def test_health_goes_503_after_a_live_transcription_failure(monkeypatch, tmp_path):
    """The 2026-08-23 shape: the probe passed at boot, then the GPU vanished.

    _probe_ok used to latch True forever, so /health kept answering 200 through
    an outage where every transcription 503'd, and the container stayed
    `healthy`. A live failure must retract the probe's verdict.
    """
    os.environ["ALLOWED_ROOT"] = str(tmp_path)
    import main
    importlib.reload(main)

    # Boot healthy, exactly as the real service does.
    monkeypatch.setattr(main, "_make_worker", lambda: _FakeWorker())
    assert main._probe_once() is True
    c = TestClient(main.app)
    assert c.get("/health").status_code == 200

    # The GPU disappears mid-life: the worker is gone and cannot be restarted.
    # Silence the retry loop -- restarting it is a separate behaviour, and left
    # live it would race this assertion by re-probing against the fake.
    monkeypatch.setattr(main, "_warm_load_loop", lambda: None)
    with main._worker_lock:
        main._worker = None
    monkeypatch.setattr(main, "_make_worker", lambda: _FakeWorker(fail_on_start=True))

    audio = tmp_path / "note.wav"
    audio.write_bytes(b"not really audio")
    r = c.post("/transcribe", json={"audio_path": str(audio)})
    assert r.status_code == 503

    r = c.get("/health")
    assert r.status_code == 503, "health still green while transcription is broken"
    assert "CUDA" in r.json()["reason"]


# ---------------------------------------------------------------------------
# MUSHY-93: no-speech audio is an empty transcript, not a failure
# ---------------------------------------------------------------------------


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeInfo:
    language = "es"
    language_probability = 0.91


class _NoSpeechModel:
    """faster-whisper 1.0.3 with vad_filter=True and no speech in the audio."""

    def transcribe(self, *_a, **_kw):
        raise ValueError("max() arg is an empty sequence")


class _BrokenModel:
    """A ValueError that is NOT the no-speech signature must stay an error."""

    def transcribe(self, *_a, **_kw):
        raise ValueError("invalid compute type")


class _SpeechModel:
    def transcribe(self, *_a, **_kw):
        return iter([_FakeSegment(" hola "), _FakeSegment("mundo ")]), _FakeInfo()


def test_no_speech_returns_empty_transcript_not_an_error():
    import main

    res = main._transcribe_once(_NoSpeechModel(), "/tmp/silent.wav")

    assert res["ok"] is True, "no-speech must not be reported as a failure"
    assert res["text"] == ""
    assert res["no_speech"] is True


def test_other_value_errors_still_propagate():
    import main

    with pytest.raises(ValueError, match="invalid compute type"):
        main._transcribe_once(_BrokenModel(), "/tmp/x.wav")


def test_real_speech_is_unchanged_and_not_flagged_no_speech():
    import main

    res = main._transcribe_once(_SpeechModel(), "/tmp/voice.wav")

    assert res["ok"] is True
    assert res["text"] == "hola mundo"
    assert res["no_speech"] is False
    assert res["language"] == "es"
