"""Unit tests for farmos_agent.farmos_client."""

from unittest.mock import MagicMock, patch
import pytest
import requests
import farmos_agent.farmos_client as farmos_client


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------

def test_get_session_sets_headers():
    """get_session POSTs to /user/login and sets CSRF + JSON:API headers."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {'csrf_token': 'abc123'}
    mock_resp.raise_for_status.return_value = None

    with patch('farmos_agent.farmos_client.requests.Session') as MockSession:
        session_instance = MagicMock()
        session_instance.post.return_value = mock_resp
        MockSession.return_value = session_instance

        farmos_client.get_session('http://farmos.local', 'vikki', 'secret')

    session_instance.headers.update.assert_called_once()
    call_kwargs = session_instance.headers.update.call_args[0][0]
    assert call_kwargs['X-CSRF-Token'] == 'abc123'
    assert call_kwargs['Content-Type'] == 'application/vnd.api+json'
    assert call_kwargs['Accept'] == 'application/vnd.api+json'


# ---------------------------------------------------------------------------
# get_asset_uuid
# ---------------------------------------------------------------------------

def test_get_asset_uuid_found(mock_farmos_session):
    """Returns UUID when FC-1 is in the response data."""
    mock_farmos_session.get.return_value.json.return_value = {
        'data': [
            {'id': 'uuid-001', 'attributes': {'name': 'FC-1'}},
            {'id': 'uuid-002', 'attributes': {'name': 'FC-2'}},
        ]
    }
    mock_farmos_session.get.return_value.raise_for_status = MagicMock()

    cache = {}
    result = farmos_client.get_asset_uuid(mock_farmos_session, 'http://farmos.local', 'FC-1', _cache=cache)
    assert result == 'uuid-001'


def test_get_asset_uuid_not_found(mock_farmos_session):
    """Returns None when no asset matches the name."""
    mock_farmos_session.get.return_value.json.return_value = {'data': []}
    mock_farmos_session.get.return_value.raise_for_status = MagicMock()

    cache = {}
    result = farmos_client.get_asset_uuid(mock_farmos_session, 'http://farmos.local', 'FC-1', _cache=cache)
    assert result is None


def test_get_asset_uuid_caches(mock_farmos_session):
    """Only one GET request made when called twice with same parameters."""
    mock_farmos_session.get.return_value.json.return_value = {
        'data': [{'id': 'uuid-001', 'attributes': {'name': 'FC-1'}}]
    }
    mock_farmos_session.get.return_value.raise_for_status = MagicMock()

    cache = {}
    first = farmos_client.get_asset_uuid(mock_farmos_session, 'http://farmos.local', 'FC-1', _cache=cache)
    second = farmos_client.get_asset_uuid(mock_farmos_session, 'http://farmos.local', 'FC-1', _cache=cache)

    assert first == second == 'uuid-001'
    assert mock_farmos_session.get.call_count == 1


# ---------------------------------------------------------------------------
# upload_photo
# ---------------------------------------------------------------------------

def test_upload_photo_uses_session_post(mock_farmos_session):
    """upload_photo calls session.post, NOT bare requests.post."""
    mock_farmos_session.post.return_value.ok = True
    mock_farmos_session.post.return_value.json.return_value = {'data': {'id': 'file-uuid-001'}}

    with patch('farmos_agent.farmos_client.requests') as mock_requests_module:
        farmos_client.upload_photo(mock_farmos_session, 'http://farmos.local', b'\xff\xd8\xff')

    mock_farmos_session.post.assert_called_once()
    # bare requests.post must NOT be called
    mock_requests_module.post.assert_not_called()


def test_upload_photo_sets_content_type(mock_farmos_session):
    """upload_photo sends Content-Type: application/octet-stream."""
    mock_farmos_session.post.return_value.ok = True
    mock_farmos_session.post.return_value.json.return_value = {'data': {'id': 'file-uuid-002'}}

    farmos_client.upload_photo(mock_farmos_session, 'http://farmos.local', b'\xff\xd8\xff', 'test.jpg')

    _, kwargs = mock_farmos_session.post.call_args
    assert kwargs['headers']['Content-Type'] == 'application/octet-stream'
    assert 'test.jpg' in kwargs['headers']['Content-Disposition']


def test_upload_photo_success(mock_farmos_session):
    """Returns file UUID on successful upload."""
    mock_farmos_session.post.return_value.ok = True
    mock_farmos_session.post.return_value.json.return_value = {'data': {'id': 'file-uuid-003'}}

    result = farmos_client.upload_photo(mock_farmos_session, 'http://farmos.local', b'\xff\xd8\xff')
    assert result == 'file-uuid-003'


def test_upload_photo_failure(mock_farmos_session):
    """Returns None when the server responds with a non-ok status."""
    mock_farmos_session.post.return_value.ok = False

    result = farmos_client.upload_photo(mock_farmos_session, 'http://farmos.local', b'\xff\xd8\xff')
    assert result is None


# ---------------------------------------------------------------------------
# create_observation
# ---------------------------------------------------------------------------

def test_create_observation_with_image(mock_farmos_session):
    """Image relationship is included when file_id is provided."""
    mock_farmos_session.post.return_value.raise_for_status = MagicMock()
    mock_farmos_session.post.return_value.json.return_value = {'data': {'id': 'obs-uuid-001'}}

    result = farmos_client.create_observation(
        mock_farmos_session,
        'http://farmos.local',
        asset_uuid='asset-uuid-001',
        name='FC-1 Daily Report 2026-04-12',
        notes='| Metric | Avg |',
        file_id='file-uuid-001',
    )

    assert result == 'obs-uuid-001'
    _, kwargs = mock_farmos_session.post.call_args
    body = kwargs['json']
    assert 'image' in body['data']['relationships']
    assert body['data']['relationships']['image']['data'][0]['id'] == 'file-uuid-001'


def test_create_observation_without_image(mock_farmos_session):
    """Image relationship is absent when file_id is None."""
    mock_farmos_session.post.return_value.raise_for_status = MagicMock()
    mock_farmos_session.post.return_value.json.return_value = {'data': {'id': 'obs-uuid-002'}}

    result = farmos_client.create_observation(
        mock_farmos_session,
        'http://farmos.local',
        asset_uuid='asset-uuid-001',
        name='FC-1 Daily Report 2026-04-12',
        notes='| Metric | Avg |',
        file_id=None,
    )

    assert result == 'obs-uuid-002'
    _, kwargs = mock_farmos_session.post.call_args
    body = kwargs['json']
    assert 'image' not in body['data']['relationships']


# ---------------------------------------------------------------------------
# observation_exists_for_date
# ---------------------------------------------------------------------------

def test_observation_exists_true(mock_farmos_session):
    """Returns True when at least one observation is found."""
    mock_farmos_session.get.return_value.raise_for_status = MagicMock()
    mock_farmos_session.get.return_value.json.return_value = {
        'data': [{'id': 'obs-uuid-001', 'attributes': {'name': 'FC-1 Daily Report 2026-04-12'}}]
    }

    result = farmos_client.observation_exists_for_date(
        mock_farmos_session, 'http://farmos.local', '2026-04-12'
    )
    assert result is True


def test_observation_exists_false(mock_farmos_session):
    """Returns False when no observations are found."""
    mock_farmos_session.get.return_value.raise_for_status = MagicMock()
    mock_farmos_session.get.return_value.json.return_value = {'data': []}

    result = farmos_client.observation_exists_for_date(
        mock_farmos_session, 'http://farmos.local', '2026-04-12'
    )
    assert result is False


def test_observation_exists_uses_exact_match(mock_farmos_session):
    """observation_exists_for_date uses '=' operator, not CONTAINS."""
    mock_farmos_session.get.return_value.raise_for_status = MagicMock()
    mock_farmos_session.get.return_value.json.return_value = {'data': []}

    farmos_client.observation_exists_for_date(
        mock_farmos_session, 'http://farmos.local', '2026-04-12'
    )

    _, kwargs = mock_farmos_session.get.call_args
    params = kwargs.get('params', {})
    assert params.get('filter[name][operator]') == '='
