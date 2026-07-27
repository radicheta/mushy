"""
capture/transcribe_client.py -- Never-throws httpx client to the whisper-transcribe sibling.

Port of src/agents/alerter/src/transcribe-client.js createTranscribeClient().

Provides:
  create_transcribe_client(api_url, http, timeout_ms, logger) -> {"transcribe": transcribe}

Design decisions (from 58-CONTEXT.md):
  D-01: Faithful HTTP port -- POSTs {audio_path} to /transcribe; container stays a sibling service.
  D-02: async def + await httpx call is non-blocking; no ProcessPoolExecutor needed.
  D-03: SC#2 wording superseded: off-loop via async HTTP, not ProcessPoolExecutor.
  D-04: Returns {ok:False, reason} on any failure; NEVER raises.

CAP-02: audio transcribed off-loop via async HTTP call.
T-58-02-04: httpx timeout= + never-throws prevents loop blockage on whisper hang.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


def create_transcribe_client(
    api_url: str,
    http: httpx.AsyncClient,
    timeout_ms: int = 200_000,
    log: logging.Logger | None = None,
) -> dict:
    """Factory returning {"transcribe": transcribe}. Port of createTranscribeClient().

    Holds the injected httpx.AsyncClient in the closure (mirror SignalClient -- do NOT
    create a client per call). The returned dict matches the injection shape expected by
    the capture pipeline and fake_transcribe_client fixture.

    Args:
        api_url:    Base URL of the whisper-transcribe container (no trailing slash).
        http:       Injected httpx.AsyncClient (injected for testability; reused across calls).
        timeout_ms: HTTP timeout in milliseconds (default 200s -- large audio files are slow).
        log:        Optional logger; defaults to module logger.

    Returns:
        {"transcribe": async_fn} where async_fn: (arg) -> {ok:True,...} | {ok:False,reason}
    """
    _log = log or logger
    _timeout_s = timeout_ms / 1000

    async def transcribe(arg) -> dict:
        """Transcribe audio at the given path via the whisper-transcribe /transcribe endpoint.

        Accepts either:
          - str: the audio file path directly
          - dict: {"audio_path": <path>}  (harness symmetry, mirrors Node dual-arg shape)

        Returns (NEVER raises):
          {ok: True, text: str, duration_ms: int, language: str}  on success
          {ok: False, reason: str}                                  on any failure
        """
        # Resolve audio_path from str or dict arg (mirrors transcribe-client.js:23-24)
        audio_path = arg if isinstance(arg, str) else (arg or {}).get("audio_path")
        if not audio_path:
            return {"ok": False, "reason": "missing audio_path"}

        try:
            r = await http.post(
                f"{api_url}/transcribe",
                json={"audio_path": audio_path},
                timeout=_timeout_s,
            )
            if r.status_code >= 400:
                body = r.text[:200] if r.content else ""
                return {"ok": False, "reason": f"whisper {r.status_code}: {body}"}
            data = r.json()
            return {
                "ok": True,
                "text": data.get("text") or "",
                "duration_ms": data.get("duration_ms", 0),
                "language": data.get("language") or "unknown",
            }
        except httpx.TimeoutException:
            _log.warning("[transcribe] timeout after %.0fs for path: %s", _timeout_s, audio_path)
            return {"ok": False, "reason": "timeout"}
        except Exception as e:  # noqa: BLE001 -- never raise from transcribe (D-01/D-04)
            _log.warning("[transcribe] error: %s", e)
            return {"ok": False, "reason": str(e)}

    return {"transcribe": transcribe}
