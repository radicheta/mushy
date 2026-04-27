"""GPU smoke test — opt-in only via `pytest -m gpu`.

Drives the LIVE container at WHISPER_URL (default http://localhost:8090) with a
real 30-second WAV fixture. Asserts duration_ms < 60_000 (well under the 3min
SPEC R3 budget) and that text + language come back.
"""
import os
import pathlib

import pytest
import requests

pytestmark = pytest.mark.gpu


def test_smoke_30s_clip():
    url = os.getenv("WHISPER_URL", "http://localhost:8090")
    fix = pathlib.Path(__file__).parent / "fixtures" / "sample-30s.wav"
    assert fix.exists(), f"fixture missing: {fix}"
    r = requests.post(
        f"{url}/transcribe",
        json={"audio_path": str(fix.resolve())},
        timeout=180,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    # text may be empty for pure-tone fixtures; assert key exists
    assert "text" in j
    assert j["duration_ms"] < 60000, f"duration_ms={j['duration_ms']} exceeds 60s budget"
    assert j["language"]
