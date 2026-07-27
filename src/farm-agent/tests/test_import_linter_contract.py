"""
test_import_linter_contract.py -- Phase 63 D-00: the Foray seam's SECONDARY gate.

Phase 56 committed .lint-imports but deliberately left it out of the pytest run
("Do NOT add import-linter to the pytest run until Phase 63"). This is Phase 63.

Primary gate is the subprocess grep in test_foray_seam.py. This one catches what
grep cannot: transitive imports (foray -> helper -> chamber) that never literally
spell `from farm_agent.chamber` inside a Foray package.

Guards Pitfall 7: source_modules drift. import-linter 2.11 HARD-ERRORS on a
source_modules entry that does not resolve, so a package rename that is not
mirrored into .lint-imports turns the gate red here instead of silently inert.
"""

import subprocess
from pathlib import Path

FARM_AGENT_ROOT = Path(__file__).parent.parent


def test_lint_imports_exits_zero():
    """The foray-seam contract must be satisfiable AND satisfied."""
    result = subprocess.run(
        ["uv", "run", "lint-imports", "--config", ".lint-imports"],
        capture_output=True,
        text=True,
        cwd=str(FARM_AGENT_ROOT),
    )
    assert result.returncode == 0, (
        f"lint-imports failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "1 kept, 0 broken" in result.stdout, (
        f"Expected 'Contracts: 1 kept, 0 broken' in output, got:\n{result.stdout}"
    )
