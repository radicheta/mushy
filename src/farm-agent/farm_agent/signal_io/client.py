"""
signal_io/client.py -- SignalClient: wire-level Signal I/O choke-point.

Port of src/agents/alerter/src/signal.js createSignalClient() to Python.
Single send choke-point preserving Phase-37/44/50 behavior for Phase-64 parity.

Provides:
  SignalClient.send()              -- rate-capped, quoted, persisted send
  SignalClient.receive()           -- HTTP GET long-poll /v1/receive
  SignalClient.fetch_attachment()  -- binary GET /v1/attachments/{id}
  SignalClient.accounts()          -- GET /v1/accounts
  SignalClient.sends_this_hour()   -- current rate-cap window count
  SignalClient.ensure_groups_loaded() -- lazy /v1/groups cache for id-b64 translation
  SignalClient.is_valid_quote()    -- static shape validator (port of isValidQuote)

Design decisions:
  D-01: transport = httpx.AsyncClient against the REST container (not raw JSON-RPC socket)
  D-02: persist-after-send, fail-open (outbound insert failure never affects return value)
  D-04: in-memory sendHistory list + asyncio.Lock; resets on restart (matches Node)
  D-05: quote primitive coerces ts via int(str(ts)); invalid shape → unquoted + warn, never raise

Phase-64 parity delta (documented per RESEARCH Pattern 2 option (a)):
  Node appends to sendHistory only on POST success (signal.js:147).
  Python reserves the slot BEFORE the POST (inside the lock, before await) so two
  concurrent coroutines cannot both pass the cap check. A failed POST still consumes
  a slot (attempts vs successes). At 20/h this difference never matters in practice.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote_plus

import httpx

from farm_agent.tenancy.tenant import TenantConfig, mask_number

logger = logging.getLogger(__name__)

# config.js:175 -- parseIntEnv(env, 'ALERT_MAX_SENDS_PER_HOUR', 20).
# Phase 63 D-03: max_sends_per_hour moved to ChamberConfig, so this client no
# longer reads it off TenantConfig. boot.py injects the live value via
# get_max_sends_per_hour; this constant is the floor when no hook is wired, so
# an unhooked client is still rate-capped rather than unbounded (T-63-03).
_DEFAULT_MAX_SENDS_PER_HOUR = 20

# MUSHY-88: seconds added to the caller's long-poll window to get the httpx read
# timeout for /v1/receive. Generous on purpose -- a receive that aborts loses
# farmer messages outright, while a receive that waits too long only delays the
# next tick. Observed durations run 4.3-5.1s idle and 8.7s carrying attachments.
_RECEIVE_TIMEOUT_HEADROOM_S = 120


class SignalClient:
    """Wire-level Signal I/O client -- port of signal.js createSignalClient().

    Inject dependencies via constructor; never reads the environment directly.
    """

    def __init__(
        self,
        *,
        config: TenantConfig,
        http: httpx.AsyncClient,
        outbound_repo: Any = None,
        pool: Any = None,
        get_max_sends_per_hour: Callable[[], int] | None = None,
        log: logging.Logger | None = None,
        timeout_s: float = 10.0,
        tenant_id: str = "mossrock",
        default_target: str | dict | None = None,
    ) -> None:
        self._config = config
        self.http = http
        self._outbound_repo = outbound_repo
        self._pool = pool
        self._get_max_sends_per_hour = get_max_sends_per_hour
        self._logger = log or logger
        self._timeout_s = timeout_s
        self._tenant_id = tenant_id or config.tenant_id
        self._api_url = config.signal_api_url
        self._sender = config.signal_sender

        # Resolve effective default target (signal.js:8-11)
        # defaultTarget ?? recipient; raise if empty
        effective_default = default_target if default_target is not None else config.signal_recipient
        if not effective_default:
            raise ValueError("SignalClient: default_target or signal_recipient is required")
        self._effective_default = effective_default

        # Rate-cap state (D-04): in-memory list of ms-timestamps, guarded by Lock
        self._lock = asyncio.Lock()
        self._send_history: list[int] = []

        # Group-ID translation cache (signal.js:20-21)
        self._group_id_map: dict[str, str] = {}
        self._groups_loaded: bool = False

    # ------------------------------------------------------------------
    # Public static: quote shape validator (SC#3, signal.js:71-80)
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_quote(q: Any) -> bool:
        """Return True if q is a valid quote dict (port of signal.js isValidQuote).

        Valid shape: {timestamp: numeric-or-numeric-string, author: non-empty str, message: str}
        Empty message is allowed. Author must be a non-empty string.
        Timestamp validated via math.isfinite(float(str(ts))).
        """
        if not isinstance(q, dict):
            return False
        try:
            ts_ok = math.isfinite(float(str(q.get("timestamp"))))
        except (TypeError, ValueError):
            return False
        return (
            ts_ok
            and isinstance(q.get("author"), str) and len(q["author"]) > 0
            and isinstance(q.get("message"), str)
        )

    # ------------------------------------------------------------------
    # Rate-cap helpers (signal.js:41-56, D-04)
    # ------------------------------------------------------------------

    def _prune_history(self, now: int) -> None:
        """Drop sendHistory entries older than the last hour (signal.js:41-44)."""
        cutoff = now - 3_600_000
        self._send_history = [t for t in self._send_history if t >= cutoff]

    def _current_cap(self) -> int:
        """Return the effective cap (dynamic hook with fallback, signal.js:48-56)."""
        if self._get_max_sends_per_hour is not None:
            try:
                v = self._get_max_sends_per_hour()
                if isinstance(v, (int, float)) and math.isfinite(float(v)):
                    return int(v)
            except Exception:  # noqa: BLE001
                pass
        return _DEFAULT_MAX_SENDS_PER_HOUR

    def sends_this_hour(self) -> int:
        """Return current send count in the rolling hour window (signal.js:226-229)."""
        now = int(time.time() * 1000)
        self._prune_history(now)
        return len(self._send_history)

    # ------------------------------------------------------------------
    # Group-ID translation (signal.js:22-39, SC#2)
    # ------------------------------------------------------------------

    async def ensure_groups_loaded(self, force: bool = False) -> None:
        """Lazy-load /v1/groups, build internal_id→id-b64 map (signal.js:22-39).

        On exception logs a warning and continues (fail-open per RESEARCH Pattern 3).
        """
        if self._groups_loaded and not force:
            return
        try:
            r = await self.http.get(
                f"{self._api_url}/v1/groups/{quote_plus(self._sender)}",
                timeout=self._timeout_s,
            )
            r.raise_for_status()
            self._group_id_map.clear()
            for g in r.json():
                if not g or not g.get("id") or not g.get("internal_id"):
                    continue
                gid = g["id"]
                id_stripped = gid[len("group."):] if gid.startswith("group.") else gid
                self._group_id_map[g["internal_id"]] = id_stripped
            self._groups_loaded = True
            self._logger.info(
                "[signal] groups loaded (%d entries) for id translation", len(self._group_id_map)
            )
        except Exception as e:  # noqa: BLE001
            self._logger.warning(
                "[signal] groups list failed: %s — send may fail if recipient is internal_id form", e
            )

    # ------------------------------------------------------------------
    # Send (signal.js:82-203, SC#1/#2/#3/#4, D-02/D-04/D-05)
    # ------------------------------------------------------------------

    async def send(
        self,
        body: str,
        *,
        bypass_cap: bool = False,
        to: str | dict | None = None,
        intent: str | None = None,
        related_capture_id: str | None = None,
        related_draft_id: str | None = None,
        source_module: str = "signal_io",
        quote: dict | None = None,
    ) -> dict:
        """Send a Signal message (single choke-point, Phase-37 D-01).

        Returns {"ok": True, "timestamp": int} on success.
        Returns {"ok": False, "reason": "rate-cap"} when capped.
        Raises ValueError on invalid target, RuntimeError on HTTP error.
        """
        now = int(time.time() * 1000)

        # D-04 rate-cap: check+reserve inside Lock BEFORE any await
        async with self._lock:
            self._prune_history(now)
            cap = self._current_cap()
            if not bypass_cap and len(self._send_history) >= cap:
                self._logger.warning(
                    "[signal] cap reached (%d/%d/h) — dropping", len(self._send_history), cap
                )
                return {"ok": False, "reason": "rate-cap"}
            # Reserve the slot before the POST (option (a) -- counts attempts)
            self._send_history.append(now)

        # Target resolution (signal.js:91-112, Phase-37 D-01)
        target = to if to is not None else self._effective_default
        is_string_target = isinstance(target, str) and len(target) > 0
        is_group_target = (
            isinstance(target, dict)
            and isinstance(target.get("groupId"), str)
            and bool(target["groupId"])
        )
        if not is_string_target and not is_group_target:
            raise ValueError("invalid send target")

        resolved_group_id: str | None = None
        if is_group_target:
            await self.ensure_groups_loaded(False)
            resolved_group_id = self._group_id_map.get(target["groupId"], target["groupId"])  # type: ignore[index]

        recipients = (
            [target] if is_string_target else [f"group.{resolved_group_id}"]
        )

        # Build payload (signal.js:118-131, D-05 quote)
        payload: dict[str, Any] = {
            "message": body,
            "number": self._sender,
            "recipients": recipients,
        }
        if quote is not None:
            if self.is_valid_quote(quote):
                # signal-cli-rest-api /v2/send takes FLAT quote fields
                # (quote_timestamp/quote_author/quote_message), NOT a nested
                # `quote` object. A nested object is silently dropped (201, no
                # bubble). Confirmed against live 0.200-dev swagger; the nested
                # shape ported from the Node alerter rendered only on 0.14.2
                # (Phase-50 spike) and is broken on 0.200 (57-04 live-fire, A2).
                payload["quote_timestamp"] = int(str(quote["timestamp"]))
                payload["quote_author"] = quote["author"]
                payload["quote_message"] = quote["message"]
            else:
                try:
                    import json as _json
                    dump = _json.dumps(quote)
                except Exception:  # noqa: BLE001
                    dump = "[unstringifiable]"
                self._logger.warning("[signal] invalid quote arg, sending without quote: %s", dump)

        # POST /v2/send OUTSIDE the lock (never hold lock across network I/O)
        r = await self.http.post(
            f"{self._api_url}/v2/send",
            json=payload,
            timeout=self._timeout_s,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"signal-cli {r.status_code}: {r.text[:200]}")
        data = r.json() if r.content else {}

        # Log with masked number (T-57-02-03: PII masking)
        if is_string_target:
            label = mask_number(str(target))
        else:
            gid_str = str(target.get("groupId", "")) if isinstance(target, dict) else ""  # type: ignore[union-attr]
            label = f"group:{gid_str[:8]}..."
        self._logger.info("[signal] sent -> %s (%d chars)", label, len(body))

        ts_raw = data.get("timestamp")
        result_ts = int(ts_raw) if ts_raw is not None else now

        # D-02 fail-open persist hook (signal.js:158-196, after POST, outside Lock)
        if self._outbound_repo is not None and self._pool is not None:
            effective_intent = intent
            if not effective_intent:
                self._logger.warning(
                    "[signal] send() missing intent — defaulting to 'unknown'"
                )
                effective_intent = "unknown"

            recipient_col = (
                str(target) if is_string_target
                else f"group:{resolved_group_id or (target.get('groupId') if isinstance(target, dict) else '')}"
            )

            row = {
                "tenant_id": self._tenant_id,
                "sent_at": datetime.now(timezone.utc),
                "recipient_e164": recipient_col,
                "intent": effective_intent,
                "body": body,
                "attachments": None,
                "source_module": source_module,
                "source_line": None,
                "related_capture_id": related_capture_id,
                "related_draft_id": related_draft_id,
                "signal_msg_ts": int(ts_raw) if ts_raw is not None else None,
            }
            try:
                result = await self._outbound_repo.insert_outbound(self._pool, row)
                if result and result.get("ok") is False:
                    self._logger.warning(
                        "[signal] outbound persist failed (fail-open): %s", result.get("reason")
                    )
            except Exception as e:  # noqa: BLE001 -- D-02 defense-in-depth second layer
                self._logger.warning("[signal] outbound persist threw (fail-open): %s", e)

        return {"ok": True, "timestamp": result_ts}

    # ------------------------------------------------------------------
    # Receive (signal.js:205-210)
    # ------------------------------------------------------------------

    async def receive(
        self,
        *,
        timeout_sec: int = 1,
        ignore_attachments: bool = False,
    ) -> list:
        """HTTP GET long-poll /v1/receive/{sender} (D-01 transport: REST, not socket)."""
        url = (
            f"{self._api_url}/v1/receive/{quote_plus(self._sender)}"
            f"?timeout={timeout_sec}&ignore_attachments={str(ignore_attachments).lower()}"
        )
        # MUSHY-88: the read timeout must comfortably outlast a slow signal-cli.
        # /v1/receive is DESTRUCTIVE -- signal-cli dequeues when it answers, so a
        # client-side abort loses those messages permanently; they are not
        # redelivered on the next poll. The original `timeout_sec + 5` gave a 6s
        # ceiling against a 4.3-5.1s baseline, and a photo batch that took 8.657s
        # was dropped with an empty-string warning during the 2026-08-18 cutover.
        # Node has never bounded this call at all (signal.js:212). Keep a ceiling
        # so a wedged signal-cli cannot hang the loop forever, but put it far
        # above any plausible poll rather than one second above the median.
        r = await self.http.get(url, timeout=timeout_sec + _RECEIVE_TIMEOUT_HEADROOM_S)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Fetch attachment (signal.js:212-218)
    # ------------------------------------------------------------------

    async def fetch_attachment(self, attachment_id: str) -> bytes:
        """GET /v1/attachments/{id} and return raw bytes (arrayBuffer→r.content)."""
        r = await self.http.get(
            f"{self._api_url}/v1/attachments/{quote_plus(str(attachment_id))}",
            timeout=self._timeout_s,
        )
        r.raise_for_status()
        return r.content

    # ------------------------------------------------------------------
    # Accounts (signal.js:220-224)
    # ------------------------------------------------------------------

    async def accounts(self) -> list:
        """GET /v1/accounts and return parsed JSON list."""
        r = await self.http.get(f"{self._api_url}/v1/accounts", timeout=self._timeout_s)
        r.raise_for_status()
        return r.json()
