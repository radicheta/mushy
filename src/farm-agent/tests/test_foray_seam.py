"""
FND-05: Foray CI seam gate.

Enforces the Foray island boundary: no foray package may import from chamber/.
chamber/ is the sole mushy-private package (added in Phase 63).

Primary mechanism: subprocess grep, zero external dependencies.
Secondary gate: .lint-imports (import-linter contract), committed now, activated
in Phase 63 when chamber/ lands.

NOTE on ROADMAP token divergence:
  ROADMAP.md success criterion 4 phrases the forbidden import as `from alerter.chamber`
  (reflecting the old Node alerter namespace). The real Python package is `farm_agent`,
  so the actual forbidden pattern is `from farm_agent.chamber` / `import farm_agent.chamber`.
  This test asserts on the real package name.
"""

import subprocess
import tempfile
import os
from pathlib import Path

# Phase 56 foray packages that exist now.
# signal_io, confirm, farmos_client, capture, llm are not created this phase.
FORAY_PACKAGES = [
    "farm_agent/tenancy",
    "farm_agent/persistence",
    "farm_agent/extraction",
]

# Pattern catches both `from farm_agent.chamber import X`
# and bare `import farm_agent.chamber` forms.
CHAMBER_IMPORT_PATTERN = r"^import farm_agent\.chamber|from farm_agent\.chamber"


def _run_grep(paths: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run the Foray seam grep against the given paths."""
    return subprocess.run(
        ["grep", "-rE", CHAMBER_IMPORT_PATTERN, "--include=*.py"] + paths,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_no_chamber_imports_in_foray():
    """FND-05: no foray package imports from chamber/.

    With no chamber/ present in Phase 56, this passes vacuously.
    It is wired now so it FAILS the moment a violation is introduced.
    """
    # Run from src/farm-agent/ so relative paths resolve correctly.
    farm_agent_root = Path(__file__).parent.parent
    result = _run_grep(FORAY_PACKAGES, cwd=str(farm_agent_root))
    assert result.returncode != 0 or result.stdout == "", (
        f"FORAY SEAM VIOLATION: non-chamber package imports from farm_agent.chamber:\n"
        f"{result.stdout}"
    )


def test_seam_trips_on_violation():
    """Proves the grep gate is armed, not vacuous.

    Constructs a temporary Python file containing a synthetic chamber import,
    runs the same grep against it, and asserts the grep MATCHES (exit 0, non-empty stdout).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        violation_file = os.path.join(tmpdir, "bad_module.py")
        with open(violation_file, "w") as f:
            f.write("from farm_agent.chamber import ChamberAlerter\n")

        result = subprocess.run(
            ["grep", "-rE", CHAMBER_IMPORT_PATTERN, "--include=*.py", "."],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        # grep exits 0 and produces output when it finds a match.
        assert result.returncode == 0, (
            "grep should have matched the synthetic violation but returned "
            f"exit {result.returncode}"
        )
        assert "farm_agent.chamber" in result.stdout, (
            f"Expected 'farm_agent.chamber' in grep stdout but got: {result.stdout!r}"
        )


def test_seam_trips_on_bare_import_form():
    """Proves the gate also catches the bare `import farm_agent.chamber` form (not just `from`)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        violation_file = os.path.join(tmpdir, "bad_module.py")
        with open(violation_file, "w") as f:
            f.write("import farm_agent.chamber\n")

        result = subprocess.run(
            ["grep", "-rE", CHAMBER_IMPORT_PATTERN, "--include=*.py", "."],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0, (
            "grep should have matched the bare `import` form but returned "
            f"exit {result.returncode}"
        )
        assert "farm_agent.chamber" in result.stdout
