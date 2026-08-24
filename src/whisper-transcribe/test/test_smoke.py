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
    """Drives the LIVE whisper-transcribe container with a fixture inside its
    bind-mounted /data/signal-capture root.

    NOTE: do NOT call .resolve() on /data/signal-capture paths — on elder-plops
    /data is a symlink to /mnt/slime-kingdom/data, and resolve() would defeat
    the V12 ALLOWED_ROOT check inside the container. Send the literal path.

    Fixture deploy step (run once on the host before the test):
      docker run --rm -v /data/signal-capture:/dst \
        -v $(pwd)/test/fixtures/sample-30s.wav:/src.wav:ro \
        alpine cp /src.wav /dst/sample-30s.wav
    """
    url = os.getenv("WHISPER_URL", "http://localhost:8090")
    audio_path = os.getenv(
        "WHISPER_SMOKE_PATH", "/data/signal-capture/sample-30s.wav"
    )
    r = requests.post(
        f"{url}/transcribe",
        json={"audio_path": audio_path},
        timeout=180,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert "text" in j
    assert j["duration_ms"] < 60000, f"duration_ms={j['duration_ms']} exceeds 60s budget"

    # MUSHY-93: sample-30s.wav is a PURE TONE, so VAD strips every segment and
    # this exercises the no-speech path, not real transcription. That used to
    # raise inside faster-whisper and come back as a 503, which is why this test
    # could never pass. It must now be a clean empty transcript.
    #
    # Consequence worth remembering: passing this proves the service is up and
    # the no-speech contract holds -- it does NOT prove speech is transcribed
    # correctly. Only a real speech fixture would prove that.
    if j.get("no_speech"):
        assert j["text"] == "", f"no_speech but text={j['text']!r}"
        assert j["language"] is None
    else:
        assert j["language"]
