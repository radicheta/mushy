"""
farm_agent/farmos/client.py -- Faithful Python port of the Node farmOS HTTP client.

Source-of-truth: src/agents/alerter/src/farmos/client.js

Session-cookie + X-CSRF-Token auth, 10s per-call timeout, exponential backoff
retry on transient (5xx + network) errors, single 401/403 re-auth retry, JSON:API
content type, octet-stream binary upload. Never-throws envelope. Every later farmOS
module (assets, logs, files, commits, watchdog) consumes this via dependency injection.

Design decisions (Phase 62 FWR-01):
  D-01: Faithful port -- all method names mirror client.js identifiers.
  D-02: Session state held in closure dict _session (mirror JS _session object).
  D-03: Never raises on network failure -- always returns envelope dict.
  D-04: No password/cookie/csrf logged (T-62-04).
  D-05: Injectable _sleep for test backoff spying (no real sleeps in tests).

No em-dashes in source artifacts. No hardcoded credentials.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)


def create_farmos_client(
    farmos_url: str,
    username: str,
    password: str,
    http: httpx.AsyncClient,
    *,
    backoff_ms: tuple[int, ...] = (1000, 4000, 16000),
    timeout_ms: int = 10000,
    retry_max: int = 3,
    log: logging.Logger | None = None,
    _sleep=None,
) -> dict:
    """Factory returning a dict of async callables for farmOS HTTP operations.

    Port of createFarmosClient() from client.js (Phase 40 D-01a / D-01b).

    Args:
        farmos_url:  Base URL of the farmOS instance (no trailing slash).
        username:    farmOS username (never logged).
        password:    farmOS password (never logged).
        http:        Injected httpx.AsyncClient (reused across calls for connection pooling).
        backoff_ms:  Backoff sequence in milliseconds for transient retries.
        timeout_ms:  Per-request timeout in milliseconds (default 10s; binary uses 30s).
        retry_max:   Maximum total attempts before giving up (default 3).
        log:         Optional logger; defaults to module logger.
        _sleep:      Injectable sleep callable (ms: int) -> Awaitable; defaults to asyncio.sleep.
                     Injected in tests to spy on backoff calls without real delays.

    Returns:
        Dict with async callables: {"get", "post", "patch", "post_binary", "head", "delete",
        "_session"} where _session exposes the closure session for test introspection.

    Never-throws contract: all callables catch httpx errors and return an envelope dict.
    """
    if not farmos_url:
        raise ValueError("create_farmos_client: farmos_url is required")

    _log = log or logger
    _timeout_s = timeout_ms / 1000

    # Session state in closure (mirror JS _session = {cookie, csrf, authedAt})
    _session: dict = {"cookie": None, "csrf": None, "authed_at": None}

    async def _sleep_ms(ms: int) -> None:
        """Sleep for ms milliseconds using injected sleep (asyncio.sleep by default)."""
        if _sleep is not None:
            await _sleep(ms)
        else:
            await asyncio.sleep(ms / 1000)

    async def _authenticate() -> None:
        """POST /user/login?_format=json; store cookie + csrf in closure _session.

        Mirrors client.js _authenticate() lines 36-64.
        Raises on auth failure or malformed response.
        Does NOT log password or credentials (T-62-04).
        """
        url = f"{farmos_url}/user/login?_format=json"
        try:
            resp = await http.post(
                url,
                json={"name": username, "pass": password},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=_timeout_s,
            )
        except Exception as e:
            _log.warning("[farmos] auth request failed: %s", type(e).__name__)
            raise

        if resp.status_code >= 400:
            _log.warning("[farmos] auth failed: status=%d", resp.status_code)
            raise RuntimeError(f"auth_failed_status_{resp.status_code}")

        set_cookie = resp.headers.get("set-cookie") or ""
        cookie = set_cookie.split(";")[0].strip() if set_cookie else None
        try:
            body = resp.json()
        except Exception:
            body = {}
        csrf = body.get("csrf_token") if isinstance(body, dict) else None

        if not cookie or not csrf:
            _log.warning("[farmos] auth response missing cookie or csrf_token")
            raise RuntimeError("auth_response_malformed")

        _session["cookie"] = cookie
        _session["csrf"] = csrf
        _session["authed_at"] = time.time()

    def _is_transient_error(exc: BaseException) -> bool:
        """Return True for network-level errors that warrant a retry.

        Mirrors client.js _isTransientError() lines 66-72.
        Covers: httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError
        and message patterns from the Node original (ECONNRESET etc.).
        """
        if isinstance(exc, httpx.TransportError):
            return True
        msg = str(getattr(exc, "message", "") or str(exc)).lower()
        return bool(
            any(
                token in msg
                for token in ("econnreset", "econnrefused", "etimedout", "enotfound", "network", "abort")
            )
        )

    async def _do_fetch(
        method: str,
        path: str,
        body: object,
        opts: dict,
    ) -> httpx.Response:
        """Build headers + dispatch to httpx; mirrors _doFetch() lines 74-108.

        Never-throws: callers must wrap in try/except.
        Caller-supplied opts["headers"] WIN over defaults (Phase 51 UPSERT-04 pattern).
        """
        url = path if path.startswith("http") else f"{farmos_url}{path}"
        headers: dict[str, str] = {
            "Accept": "application/vnd.api+json",
            "Cookie": _session["cookie"] or "",
            "X-CSRF-Token": _session["csrf"] or "",
        }
        # Caller-supplied headers override defaults (soft If-Match support)
        headers.update(opts.get("headers") or {})

        fetch_body = None
        call_timeout = opts.get("timeout_ms", timeout_ms) / 1000

        if method not in ("GET", "HEAD"):
            if opts.get("binary"):
                headers["Content-Type"] = "application/octet-stream"
                filename = opts.get("filename")
                if filename:
                    headers["Content-Disposition"] = f'file; filename="{filename}"'
                fetch_body = body
            elif body is not None:
                headers["Content-Type"] = "application/vnd.api+json"
                fetch_body = body  # httpx serializes via json= kwarg

        # For binary, content= is bytes; for JSON, json= for auto-serialization
        if opts.get("binary") and fetch_body is not None:
            return await http.request(
                method,
                url,
                content=fetch_body,
                headers=headers,
                timeout=call_timeout,
            )
        elif not opts.get("binary") and method not in ("GET", "HEAD") and body is not None:
            return await http.request(
                method,
                url,
                json=fetch_body,
                headers=headers,
                timeout=call_timeout,
            )
        else:
            return await http.request(
                method,
                url,
                headers=headers,
                timeout=call_timeout,
            )

    async def _request(
        method: str,
        path: str,
        body: object = None,
        opts: dict | None = None,
    ) -> dict:
        """Core request loop: lazy auth, transient retry, one-shot reauth, never-throws.

        Mirrors client.js _request() lines 110-170.

        Returns envelope {"ok", "status", "body", "latency_ms"} always.
        Adds "error" key on network failure. Never raises.
        """
        opts = opts or {}

        # Lazy authenticate on first non-skip-auth call (mirror JS: cookie == null check)
        if _session["cookie"] is None and not opts.get("skip_auth"):
            try:
                await _authenticate()
            except Exception as exc:
                return {
                    "ok": False,
                    "status": None,
                    "body": None,
                    "latency_ms": 0,
                    "error": str(exc),
                }

        attempt = 0
        did_reauth = False
        t0 = time.monotonic()

        while True:
            resp: httpx.Response | None = None
            try:
                resp = await _do_fetch(method, path, body, opts)
            except Exception as exc:
                if _is_transient_error(exc) and attempt < retry_max - 1:
                    wait = backoff_ms[min(attempt, len(backoff_ms) - 1)]
                    await _sleep_ms(wait)
                    attempt += 1
                    continue
                latency_ms = int((time.monotonic() - t0) * 1000)
                return {
                    "ok": False,
                    "status": None,
                    "body": None,
                    "latency_ms": latency_ms,
                    "error": str(exc),
                }

            # 401/403 -> one-shot reauth (mirror JS lines 134-143)
            if resp.status_code in (401, 403) and not did_reauth:
                did_reauth = True
                try:
                    await _authenticate()
                except Exception:
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    return {
                        "ok": False,
                        "status": resp.status_code,
                        "body": None,
                        "latency_ms": latency_ms,
                        "error": "reauth_failed",
                    }
                continue

            # 5xx transient retry (mirror JS lines 146-151)
            if resp.status_code >= 500 and attempt < retry_max - 1:
                wait = backoff_ms[min(attempt, len(backoff_ms) - 1)]
                await _sleep_ms(wait)
                attempt += 1
                continue

            # Parse body by content-type (mirror JS lines 154-166)
            parsed: object = None
            if method != "HEAD":
                try:
                    ct = resp.headers.get("content-type") or ""
                    if "vnd.api+json" in ct or "application/json" in ct:
                        parsed = resp.json()
                    elif resp.content:
                        parsed = resp.text
                except Exception:
                    parsed = None

            ok = 200 <= resp.status_code < 300
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {
                "ok": ok,
                "status": resp.status_code,
                "body": parsed,
                "latency_ms": latency_ms,
            }

    # Public wrapper callables (mirror JS lines 172-183)
    async def get(path: str, opts: dict | None = None) -> dict:
        return await _request("GET", path, None, opts)

    async def post(path: str, body: object = None, opts: dict | None = None) -> dict:
        return await _request("POST", path, body, opts)

    async def patch(path: str, body: object = None, opts: dict | None = None) -> dict:
        return await _request("PATCH", path, body, opts)

    async def post_binary(
        path: str,
        data: bytes,
        filename: str | None = None,
        opts: dict | None = None,
    ) -> dict:
        """POST bytes with octet-stream content type and 30s timeout.

        Mirrors client.js postBinary() lines 175-178.
        """
        merged = {"binary": True, "timeout_ms": 30000, "filename": filename}
        if opts:
            merged.update(opts)
        return await _request("POST", path, data, merged)

    async def head(path: str, opts: dict | None = None) -> dict:
        return await _request("HEAD", path, None, opts)

    async def delete(path: str, opts: dict | None = None) -> dict:
        return await _request("DELETE", path, None, opts)

    return {
        "get": get,
        "post": post,
        "patch": patch,
        "post_binary": post_binary,
        "head": head,
        "delete": delete,
        "_session": _session,  # test introspection (mirror JS)
    }
