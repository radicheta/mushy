"""
Scaffold smoke test: verifies the package is importable and the test suite
collects cleanly. This is the Phase 56-01 bootstrap test; substantive tests
land in Plans 02-05.
"""


def test_farm_agent_imports():
    """farm_agent and all Foray sub-packages import cleanly under Python 3.12."""
    import farm_agent  # noqa: F401
    import farm_agent.tenancy  # noqa: F401
    import farm_agent.persistence  # noqa: F401
    import farm_agent.extraction  # noqa: F401
    import farm_agent.extraction.schemas  # noqa: F401
