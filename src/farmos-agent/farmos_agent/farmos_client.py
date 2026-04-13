"""
FarmOS session-cookie auth + observation CRUD.

Uses the proven session-cookie pattern from
/mnt/slime-kingdom/shared/farmos/logger/server.py.
Credentials are NEVER hardcoded here — load from env or caller config (T-13-02).
"""

from datetime import datetime
import requests

# Module-level UUID cache to avoid re-querying FarmOS on every call
_asset_uuid_cache: dict = {}


def get_session(farmos_url: str, username: str, password: str) -> requests.Session:
    """
    Authenticate to FarmOS via session-cookie and return an authenticated Session.

    POSTs to /user/login?_format=json, extracts csrf_token, and sets headers:
      - X-CSRF-Token (T-13-03: required for all write operations)
      - Content-Type: application/vnd.api+json
      - Accept: application/vnd.api+json

    Raises requests.HTTPError on authentication failure.
    Timeout of 10s prevents hung connections (T-13-05).
    """
    session = requests.Session()
    resp = session.post(
        f"{farmos_url}/user/login",
        params={'_format': 'json'},
        json={'name': username, 'pass': password},
        timeout=10,
    )
    resp.raise_for_status()
    csrf = resp.json()['csrf_token']
    session.headers.update({
        'X-CSRF-Token': csrf,
        'Content-Type': 'application/vnd.api+json',
        'Accept': 'application/vnd.api+json',
    })
    return session


def get_asset_uuid(
    session: requests.Session,
    farmos_url: str,
    asset_name: str = 'FC-1',
    _cache: dict | None = None,
) -> str | None:
    """
    Look up the UUID of a structure asset by name via the FarmOS JSON:API.

    FC-1 has drupal internal ID 28 but we need the UUID (different value).
    Result is cached in _asset_uuid_cache after the first lookup.

    Args:
        _cache: optional external cache dict for dependency injection in tests.
                If None, uses the module-level _asset_uuid_cache.

    Returns the UUID string or None if not found.
    Timeout of 10s (T-13-05).
    """
    cache = _cache if _cache is not None else _asset_uuid_cache
    cache_key = f"{farmos_url}:{asset_name}"
    if cache_key in cache:
        return cache[cache_key]

    resp = session.get(
        f"{farmos_url}/api/asset/structure",
        timeout=10,
    )
    resp.raise_for_status()
    for item in resp.json().get('data', []):
        if item['attributes'].get('name') == asset_name:
            uuid = item['id']
            cache[cache_key] = uuid
            return uuid
    return None


def upload_photo(
    session: requests.Session,
    farmos_url: str,
    jpeg_bytes: bytes,
    filename: str = 'fc1-daily.jpg',
) -> str | None:
    """
    Upload a JPEG to FarmOS as a file entity.

    Uses application/octet-stream with Content-Disposition header.
    Photo upload uses 30s timeout for potentially large files (T-13-05).

    Returns the file UUID string or None on failure.
    """
    resp = session.post(
        f"{farmos_url}/api/log/observation/image",
        headers={
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': f'file; filename="{filename}"',
        },
        data=jpeg_bytes,
        timeout=30,
    )
    if resp.ok:
        return resp.json()['data']['id']
    return None


def create_observation(
    session: requests.Session,
    farmos_url: str,
    asset_uuid: str,
    name: str,
    notes: str,
    file_id: str | None = None,
) -> str:
    """
    Create a FarmOS observation log linked to a structure asset.

    Builds a log--observation with:
      - asset relationship to asset--structure with asset_uuid
      - optional image relationship to file--file with file_id
      - status: 'done'
      - notes in default format (renders markdown if enabled in FarmOS)

    Returns the observation UUID.
    Timeout of 15s (T-13-05).
    X-CSRF-Token header is already set on session from get_session (T-13-03).
    """
    data: dict = {
        'data': {
            'type': 'log--observation',
            'attributes': {
                'name': name,
                'timestamp': int(datetime.now().timestamp()),
                'status': 'done',
                'notes': {'value': notes, 'format': 'default'},
            },
            'relationships': {
                'asset': {
                    'data': [{'type': 'asset--structure', 'id': asset_uuid}]
                }
            },
        }
    }

    if file_id is not None:
        data['data']['relationships']['image'] = {
            'data': [{'type': 'file--file', 'id': file_id}]
        }

    resp = session.post(
        f"{farmos_url}/api/log/observation",
        json=data,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()['data']['id']


def observation_exists_for_date(
    session: requests.Session,
    farmos_url: str,
    date_str: str,
) -> bool:
    """
    Check whether an FC-1 daily report observation already exists for date_str (D-09).

    Queries /api/log/observation with a CONTAINS filter on the log name.
    Log names follow: "FC-1 Daily Report YYYY-MM-DD".

    Returns True if at least one matching observation is found, False otherwise.
    Timeout of 10s (T-13-05).
    """
    resp = session.get(
        f"{farmos_url}/api/log/observation",
        params={
            'filter[name][value]': f'FC-1 Daily Report {date_str}',
            'filter[name][operator]': '=',
        },
        timeout=10,
    )
    resp.raise_for_status()
    return len(resp.json().get('data', [])) > 0
