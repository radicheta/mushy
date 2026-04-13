"""Shared pytest fixtures for farmos_agent tests."""

import pytest
from unittest.mock import MagicMock
import requests
import farmos_agent.farmos_client as _farmos_client_module


@pytest.fixture(autouse=True)
def clear_asset_uuid_cache():
    """Clear the module-level UUID cache between tests to prevent state bleed."""
    _farmos_client_module._asset_uuid_cache.clear()
    yield
    _farmos_client_module._asset_uuid_cache.clear()


@pytest.fixture
def mock_farmos_session():
    """A requests.Session mock with pre-set JSON:API headers."""
    session = MagicMock(spec=requests.Session)
    session.headers = {
        'X-CSRF-Token': 'test-csrf-token',
        'Content-Type': 'application/vnd.api+json',
        'Accept': 'application/vnd.api+json',
    }
    return session


@pytest.fixture
def sample_telemetry_rows():
    """List of tuples matching query_daily_summary SQL output for all 4 topics."""
    return [
        ('fc.co2',        845.00, 620.00, 1180.00, 1440),
        ('fc.humidifier', 0.45,   0.00,   1.00,    1440),
        ('fc.humidity',   82.3,   78.1,   86.5,    1440),
        ('fc.temperature', 21.4,  19.8,   23.1,    1440),
    ]


@pytest.fixture
def sample_summary_dict():
    """Pre-built dict matching query_daily_summary output."""
    return {
        'fc.humidity':    {'avg': 82.3, 'min': 78.1, 'max': 86.5, 'samples': 1440},
        'fc.temperature': {'avg': 21.4,  'min': 19.8,  'max': 23.1,  'samples': 1440},
        'fc.co2':         {'avg': 845.0, 'min': 620.0, 'max': 1180.0,'samples': 1440},
        'fc.humidifier':  {'avg': 0.45,  'min': 0.0,   'max': 1.0,   'samples': 1440},
    }
