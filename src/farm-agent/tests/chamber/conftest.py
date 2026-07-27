"""
tests/chamber/conftest.py -- shared fixtures for the chamber (mushy-private) suite.

Mirrors tests/conftest.py::TEST_ENV. Plans 04-08 build on the chamber_config
factory rather than constructing ChamberConfig by hand.
"""

import pytest

from tests.conftest import TEST_ENV


@pytest.fixture
def tenant_config():
    """A real TenantConfig loaded from TEST_ENV (the D-02 injection source)."""
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    return load_config(TEST_ENV)


@pytest.fixture
def chamber_config(tenant_config):
    """Factory: chamber_config(**overrides) -> ChamberConfig.

    Overrides are applied as env keys, e.g. chamber_config(TZ="UTC") or
    chamber_config(ALERT_RH_TARGET="92.5"), so tests exercise the real parse path
    rather than bypassing it with dataclasses.replace.
    """
    from farm_agent.chamber.config import load as load_chamber  # noqa: PLC0415

    def _factory(**overrides):
        return load_chamber(env=dict(overrides), tenant_config=tenant_config)

    return _factory
