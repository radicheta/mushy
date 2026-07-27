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

# Every Foray (extractable-island) package. chamber/ is deliberately absent —
# it is the forbidden TARGET of the seam, and may freely import these (D-00).
# Kept honest by test_foray_packages_covers_every_package_on_disk below.
FORAY_PACKAGES = [
    "farm_agent/tenancy",
    "farm_agent/persistence",
    "farm_agent/extraction",
    "farm_agent/signal_io",
    "farm_agent/confirm",
    "farm_agent/farmos",
    "farm_agent/capture",
    "farm_agent/gate",
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


def test_foray_packages_covers_every_package_on_disk():
    """Drift guard (Pitfall 8): FORAY_PACKAGES must not fall behind the filesystem.

    Phase 56 wrote the list by hand with 3 entries. Phases 57-62 added five more
    packages and nobody updated it, so the primary seam gate was grepping 3/8 of
    the island. Derive the expected set from disk so this cannot recur.

    chamber/ is EXCLUDED by design: it is the forbidden target of the contract, not
    a source module. A chamber/ that imports signal_io is correct (D-00).
    """
    farm_agent_root = Path(__file__).parent.parent
    pkg_root = farm_agent_root / "farm_agent"

    on_disk = {
        f"farm_agent/{p.name}"
        for p in pkg_root.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    }
    on_disk.discard("farm_agent/chamber")  # forbidden target, never a source

    missing = on_disk - set(FORAY_PACKAGES)
    stale = set(FORAY_PACKAGES) - on_disk

    assert not missing, (
        f"FORAY_PACKAGES does not scan these real packages: {sorted(missing)}. "
        "The seam gate is blind to them — add them to the list."
    )
    assert not stale, (
        f"FORAY_PACKAGES lists packages that no longer exist: {sorted(stale)}."
    )
