"""Unit tests for whisper-transcribe (no GPU; runs in CI).

Strategy: monkey-patch main.get_model to return a stub that yields fake segments.
ALLOWED_ROOT is reset per-test via env + importlib.reload(main).
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    os.environ["ALLOWED_ROOT"] = str(tmp_path)
    import main
    importlib.reload(main)

    def fake_model():
        class Seg:
            text = "stub"

        class Info:
            language = "en"
            language_probability = 0.99

        class M:
            def transcribe(self, p, **kwargs):
                return ([Seg()], Info())

        return M()

    monkeypatch.setattr(main, "get_model", fake_model)
    # TestClient must be entered as a context manager for FastAPI startup events
    # to fire (Plan 09: deep /health relies on a startup probe).
    with TestClient(main.app) as tc:
        yield tc, tmp_path


def test_health_ok_when_probe_succeeds(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["model_loaded"] is True


def test_health_503_when_cuda_fails(monkeypatch, tmp_path):
    """Plan 09 Task 1: GPU-drift / no-CUDA-device must surface as 503,
    not green-with-broken-transcribe (the 2026-05-12 incident shape)."""
    os.environ["ALLOWED_ROOT"] = str(tmp_path)
    import main
    importlib.reload(main)

    def boom():
        raise RuntimeError("CUDA failed with error no CUDA-capable device is detected")

    monkeypatch.setattr(main, "_probe_model", boom)
    with TestClient(main.app) as c:
        r = c.get("/health")
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
