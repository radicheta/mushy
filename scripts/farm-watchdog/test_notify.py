"""MUSHY-99: the seam between the decision and the state file.

The pure decision is covered in test_checks.py. This drives the real
`notify()` against a real file on disk, because that join -- decide, push,
persist -- is exactly the shape of seam that unit tests kept missing
(MUSHY-90, MUSHY-97): each half fine, nothing exercising the join.

Run:  src/farm-agent/.venv/bin/python -m pytest scripts/farm-watchdog -q

ASCII-only. No em-dashes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import checks  # noqa: E402
import farm_watchdog as fw  # noqa: E402


def summary(**states):
    return checks.summarise([checks.verdict(n, s, "detail") for n, s in states.items()])


@pytest.fixture
def sent(monkeypatch):
    """Capture pushes instead of hitting the network."""
    pushes = []
    monkeypatch.setattr(fw, "push", lambda payload: pushes.append(payload) or True)
    return pushes


class TestTheStateFileRoundTrips:
    def test_a_standing_fault_pushes_once_across_two_runs(self, tmp_path, sent):
        """The whole point of MUSHY-99, end to end."""
        state = tmp_path / "state.json"
        fw.notify(summary(whisper=checks.BROKEN), state_file=state)
        fw.notify(summary(whisper=checks.BROKEN), state_file=state)
        assert len(sent) == 1

    def test_recovery_pushes_the_all_clear(self, tmp_path, sent):
        state = tmp_path / "state.json"
        fw.notify(summary(whisper=checks.BROKEN), state_file=state)
        fw.notify(summary(whisper=checks.OK), state_file=state)
        assert len(sent) == 2
        assert "recovered" in sent[1]["body"]

    def test_a_healthy_farm_writes_state_but_pushes_nothing(self, tmp_path, sent):
        state = tmp_path / "state.json"
        assert fw.notify(summary(whisper=checks.OK), state_file=state) is False
        assert sent == []
        assert json.loads(state.read_text())["failures"] == {}

    def test_an_unwritable_state_path_still_pushes(self, tmp_path, sent):
        """Losing the memory must degrade to the OLD behaviour, not to silence."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        fw.notify(summary(whisper=checks.BROKEN), state_file=blocker / "state.json")
        assert len(sent) == 1


class TestAnUndeliveredPushIsNotQuiet:
    def test_a_failed_push_is_retried_on_the_next_run(self, tmp_path, monkeypatch):
        """Otherwise a single ntfy blip buys six hours of silence."""
        state = tmp_path / "state.json"
        attempts = []
        monkeypatch.setattr(fw, "push", lambda p: attempts.append(p) or False)
        fw.notify(summary(whisper=checks.BROKEN), state_file=state)
        fw.notify(summary(whisper=checks.BROKEN), state_file=state)
        assert len(attempts) == 2
        assert json.loads(state.read_text())["notified_at"] is None

    def test_a_delivered_push_stamps_the_time(self, tmp_path, sent):
        state = tmp_path / "state.json"
        fw.notify(summary(whisper=checks.BROKEN), state_file=state)
        assert json.loads(state.read_text())["notified_at"] > 0
