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
