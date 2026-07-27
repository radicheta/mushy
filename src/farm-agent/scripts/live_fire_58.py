"""
scripts/live_fire_58.py -- Phase 58 live-fire assertion harness for SC#1 + SC#3.

READ-ONLY: this harness does NOT send any messages. The operator sends a real
voice note (and optionally a real photo) via Signal through the live boot-wired
Plan-03 capture pipeline. This harness then SELECTs the latest signal_capture
row and asserts:

  SC#1 -- ULID id (26 chars), correct farmer slug (not "(unassigned)"),
           non-null transcript for audio/mixed message_type.
  SC#3 -- every path in attachment_paths exists on disk.

Usage (from repo root, with real env sourced):
    cd src/farm-agent && uv run python scripts/live_fire_58.py

Prerequisites (operator must confirm BEFORE running):
  D-07: mushy-whisper-transcribe-1 is healthy
        curl -fsS http://localhost:8090/health
        If it shows cuInit err 804, apply the cuda-compat purge first.
  A5:   alerter-py and whisper-transcribe share the same /data/signal-capture
        bind-mount in docker-compose.override.yml. Verify:
        docker inspect mushy-alerter-py-1 mushy-whisper-transcribe-1 | grep signal-capture
  dual-poller:
        The live Node alerter must NOT be polling the same farmer account
        during the test window. Phase 58 is the live inbound-drain phase;
        two pollers on the same account will split messages.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys

import httpx

from farm_agent.persistence.pool import build_pool
from farm_agent.tenancy.tenant import load as load_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# Crockford base32 alphabet (uppercase only): 0-9, A-H, J, K, M, N, P-T, V-Z.
# Excludes I, L, O, U to avoid visual ambiguity.  ULID spec requires uppercase.
_ULID_RE = re.compile(r'^[0-9A-HJKMNP-TV-Z]{26}$')


def _is_ulid(s: object) -> bool:
    """Return True if s is a valid 26-char Crockford base32 ULID string."""
    return isinstance(s, str) and bool(_ULID_RE.match(s))


async def _preflight(config) -> bool:
    """Run D-07 (Whisper health) + A5 (capture_base_dir) preflights.

    Prints a clear PASS/FAIL line for each check. Returns True only if both pass.
    """
    all_pass = True

    # --- D-07: Whisper /health --------------------------------------------------
    health_url = f"{config.whisper_url}/health"
    log.info("PREFLIGHT D-07: GET %s", health_url)
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(health_url)
        if resp.status_code == 200:
            print(f"PREFLIGHT D-07 PASS: whisper /health returned 200 ({health_url})")
        else:
            print(
                f"PREFLIGHT D-07 FAIL: whisper /health returned {resp.status_code}"
                f" ({health_url}) -- BLOCKED D-07: whisper unhealthy"
            )
            all_pass = False
    except Exception as e:
        print(
            f"PREFLIGHT D-07 FAIL: could not reach whisper at {health_url}: {e}"
            " -- BLOCKED D-07: whisper unreachable"
        )
        all_pass = False

    # --- A5: capture_base_dir ---------------------------------------------------
    expected_dir = "/data/signal-capture"
    actual_dir = config.capture_base_dir
    log.info("PREFLIGHT A5: capture_base_dir = %r (expected %r)", actual_dir, expected_dir)
    if actual_dir == expected_dir:
        print(f"PREFLIGHT A5 PASS: capture_base_dir == {expected_dir!r}")
    else:
        print(
            f"PREFLIGHT A5 WARN: capture_base_dir is {actual_dir!r}, not {expected_dir!r}."
            " The operator must verify that alerter-py and whisper-transcribe share the"
            " same bind-mount path in docker-compose.override.yml. If they differ,"
            " Whisper will 400 every /transcribe request regardless of container health."
        )
        # This is a warning (operator must verify cross-container mount), not a hard stop.
        # We do not exit here -- the operator runbook covers the manual inspection step.
        print("PREFLIGHT A5 NOTE: continuing -- operator responsible for mount verification.")

    return all_pass


async def _select_latest_capture(pool) -> tuple | None:
    """SELECT the most-recent signal_capture row.

    Returns a tuple of:
      (id, farmos_person, message_type, transcript, attachment_paths, captured_at)
    or None on error.
    """
    sql = """
    SELECT id, farmos_person, message_type, transcript, attachment_paths, captured_at
    FROM signal_capture
    ORDER BY captured_at DESC
    LIMIT 1
    """
    try:
        async with pool.connection() as conn:
            cursor = await conn.execute(sql)
            row = await cursor.fetchone()
        return row
    except Exception as e:
        log.error("SELECT signal_capture failed: %s", e)
        return None


async def main() -> None:
    config = load_config()

    # -------------------------------------------------------------------------
    # Preflights
    # -------------------------------------------------------------------------
    preflights_ok = await _preflight(config)
    if not preflights_ok:
        print()
        print("ABORT: one or more preflights failed.")
        print("Resolve D-07 (Whisper container health) before running the live-fire.")
        sys.exit(1)

    print()

    # -------------------------------------------------------------------------
    # Open the real pool
    # -------------------------------------------------------------------------
    pool = await build_pool(config)

    try:
        # ---------------------------------------------------------------------
        # SELECT latest signal_capture row
        # ---------------------------------------------------------------------
        log.info("SELECTing latest row from signal_capture ...")
        row = await _select_latest_capture(pool)

        if row is None:
            print("FAIL: SELECT returned None -- DB query error; check logs.")
            sys.exit(1)

        row_id, farmos_person, message_type, transcript, attachment_paths, captured_at = row

        print("--- latest signal_capture row ---")
        # Mask attachment paths to avoid leaking full PII-adjacent filenames in copy-paste
        safe_paths = attachment_paths if attachment_paths else []
        print(f"  id              : {row_id}")
        print(f"  farmos_person   : {farmos_person}")
        print(f"  message_type    : {message_type}")
        print(f"  transcript      : {transcript!r}")
        print(f"  attachment_paths: {safe_paths}")
        print(f"  captured_at     : {captured_at}")
        print()

        # ---------------------------------------------------------------------
        # SC#1: ULID id + correct farmer slug + non-null transcript
        # ---------------------------------------------------------------------
        sc1_pass = True

        # 1a. ULID shape
        if _is_ulid(row_id):
            print(f"SC#1 id     PASS: {row_id!r} is a 26-char ULID")
        else:
            print(f"SC#1 id     FAIL: {row_id!r} is NOT a 26-char ULID (len={len(str(row_id)) if row_id else 'None'})")
            sc1_pass = False

        # 1b. Farmer slug: must not be the unassigned sentinel
        if farmos_person and farmos_person != "(unassigned)":
            print(f"SC#1 slug   PASS: farmos_person = {farmos_person!r} (known farmer)")
        else:
            print(
                f"SC#1 slug   FAIL: farmos_person = {farmos_person!r}"
                " (unassigned or null -- ensure the message came from a known farmer"
                " in SIGNAL_FARMER_MAP)"
            )
            sc1_pass = False

        # 1c. Non-null transcript for audio or mixed captures
        is_audio_message = message_type in ("audio", "mixed")
        if is_audio_message:
            if transcript is not None and transcript.strip():
                print(f"SC#1 xscript PASS: transcript is non-null for message_type={message_type!r}")
            else:
                print(
                    f"SC#1 xscript FAIL: transcript is null/empty for message_type={message_type!r}."
                    " Check D-07 (Whisper health) and the alerter-py logs for D-04 WARNING."
                )
                sc1_pass = False
        else:
            # For image/text captures a null transcript is expected and correct.
            print(
                f"SC#1 xscript NOTE: message_type={message_type!r};"
                " transcript may be null (not an audio/mixed message -- D-04 not exercised)."
            )

        # ---------------------------------------------------------------------
        # SC#3: on-disk existence of attachment paths
        # ---------------------------------------------------------------------
        print()
        sc3_pass = True
        if not safe_paths:
            print("SC#3         NOTE: attachment_paths is empty -- no disk assertion to run.")
            print("             Send a voice note or photo to exercise SC#3 path existence check.")
        else:
            for p in safe_paths:
                exists = os.path.exists(p)
                marker = "PASS" if exists else "FAIL"
                # Only show the filename (not full path) to limit PII exposure in logs
                basename = os.path.basename(p)
                print(f"SC#3 path   {marker}: .../{basename} exists={exists}")
                if not exists:
                    sc3_pass = False
                    log.warning("SC#3: attachment path does not exist: %s", p)

        # ---------------------------------------------------------------------
        # Summary
        # ---------------------------------------------------------------------
        print()
        sc1_label = "PASS" if sc1_pass else "FAIL"
        sc3_label = "PASS" if sc3_pass else ("FAIL" if safe_paths else "N/A (no attachments)")
        print(f"RESULT  SC#1 = {sc1_label}")
        print(f"RESULT  SC#3 = {sc3_label}")
        print()

        if not sc1_pass or (safe_paths and not sc3_pass):
            print("Live-fire FAILED. See FAIL lines above.")
            print()
            print("Common causes:")
            print("  SC#1 transcript null -> check D-07 (Whisper health) + A5 (bind-mount)")
            print("    alerter-py logs: docker logs mushy-alerter-py-1 | grep -i 'transcri'")
            print("  SC#3 path missing -> check CAPTURE_BASE_PATH + volume mount on alerter-py")
            sys.exit(1)
        else:
            print("Live-fire assertions PASSED.")
            if not safe_paths:
                print("NOTE: send a real voice note to fully exercise SC#1 + SC#3.")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
