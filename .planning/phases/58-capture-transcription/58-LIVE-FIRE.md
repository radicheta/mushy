# Phase 58 -- Live-Fire Operator Runbook

> SC#1 (non-null transcript) + SC#3 (on-disk attachment paths)
> Plan 58-04, Task 2 (checkpoint:human-verify, gate=blocking-human)

---

## Summary

This runbook gates the final Phase 58 acceptance on a REAL voice note sent through
the live, boot-wired Plan-03 capture pipeline. The `live_fire_58.py` harness is
READ-ONLY -- it only SELECTs from `signal_capture` and asserts the latest row. YOU
send the message from Signal; the running farm-agent boot daemon captures it.

---

## Prerequisites (complete ALL before running the harness)

### D-07: Whisper container health

The `mushy-whisper-transcribe-1` container has a known CUDA forward-compat hang
(`cuInit err 804` on GeForce). SC#1 (non-null transcript) CANNOT pass until this
is resolved.

```bash
# Check current health
docker inspect --format '{{.State.Health.Status}}' mushy-whisper-transcribe-1

# Check logs for the hang pattern
docker logs mushy-whisper-transcribe-1 2>&1 | tail -40

# Confirm /health returns 200 (also run by the harness preflight)
curl -fsS http://localhost:8090/health
```

If you see `cuInit 804` or the container is `unhealthy`, apply the fix described
in `[[project_whisper_cuda_compat_geforce_804]]`:
- Purge `cuda-compat` from the container image or use a compatible driver.
- Restart the container: `docker compose restart whisper-transcribe`
- Confirm: `curl -fsS http://localhost:8090/health` returns 200.

**Do not proceed until /health returns 200.**

### A5: Shared /data/signal-capture bind-mount

`whisper-transcribe` enforces `ALLOWED_ROOT=/data/signal-capture` on its side.
The `alerter-py` container MUST write audio files to the same physical host path
so that the path sent to `/transcribe` resolves correctly inside the Whisper
container.

```bash
# Inspect both containers for the bind-mount
docker inspect mushy-alerter-py-1 | python3 -c "import sys,json; [print(m) for c in json.load(sys.stdin) for m in c['HostConfig']['Binds'] if 'signal-capture' in m]"
docker inspect mushy-whisper-transcribe-1 | python3 -c "import sys,json; [print(m) for c in json.load(sys.stdin) for m in c['HostConfig']['Binds'] if 'signal-capture' in m]"
```

Both should show the SAME host path (e.g. `/data/signal-capture:/data/signal-capture`).
If they differ, update `docker-compose.override.yml` to align the mounts and
`docker compose up -d --no-deps alerter-py whisper-transcribe` to apply.

### Dual-poller caution

Phase 58 is the LIVE inbound-drain phase. If the Node alerter is also running
and polling the same farmer account, messages may be consumed by whichever
poller gets there first. Only ONE poller should be active for the test account
during this window.

```bash
# Check if the Node alerter container is polling
docker ps --filter name=alerter | grep -v "alerter-py"

# If the Node alerter is up and polling the same number, stop it for the test:
docker compose stop alerter   # (or whatever the Node alerter service name is)
# Remember to restart it after the live-fire.
```

### Farm-agent boot daemon running

The Plan-03 capture pipeline must be live (running in the farm-agent boot daemon).

```bash
docker logs mushy-alerter-py-1 --tail 20
# Expect: "[boot] ReceiveLoop started" or similar
```

---

## Execution Steps

### Step 1: Run the harness preflight

```bash
cd src/farm-agent && uv run python scripts/live_fire_58.py
```

The harness runs two preflights before touching the DB:
- **D-07:** GET `{WHISPER_URL}/health` -- must return 200; exits non-zero if not.
- **A5:** Logs the configured `capture_base_dir` (should be `/data/signal-capture`).

If D-07 preflight fails, resolve the container health first. Do not proceed.

### Step 2: Send a real voice note

From a KNOWN FARMER's Signal account (one in `SIGNAL_FARMER_MAP`), send a voice note
to the bot number (`+59891840205`). Use a short test message (5-10 seconds is fine).

Wait 10-30 seconds for the pipeline to process (receive -> download -> transcribe ->
insert_capture). Watch the alerter-py logs:

```bash
docker logs mushy-alerter-py-1 --follow --tail 30
# Expect: lines referencing the capture id, farmer slug, transcript result
# D-04 WARNING if transcription failed (but row still persists)
```

### Step 3: Run the harness assertion

```bash
cd src/farm-agent && uv run python scripts/live_fire_58.py
```

Expected output for SC#1 + SC#3 PASS:
```
PREFLIGHT D-07 PASS: whisper /health returned 200 (...)
PREFLIGHT A5 PASS: capture_base_dir == '/data/signal-capture'

--- latest signal_capture row ---
  id              : <26-char ULID>
  farmos_person   : f1
  message_type    : audio
  transcript      : 'Phase 58 test voice note ...'
  attachment_paths: ['/data/signal-capture/YYYY-MM-DD/HH-MM-SS-<ulid>-<att>.ogg']
  captured_at     : <timestamp>

SC#1 id     PASS: '<ULID>' is a 26-char ULID
SC#1 slug   PASS: farmos_person = 'f1' (known farmer)
SC#1 xscript PASS: transcript is non-null for message_type='audio'

SC#3 path   PASS: .../<filename>.ogg exists=True

RESULT  SC#1 = PASS
RESULT  SC#3 = PASS
Live-fire assertions PASSED.
```

### Step 4: SC#3 photo check (recommended)

Send a real PHOTO from a known farmer's Signal. Re-run the harness. Confirm:
- The row persists (D-04: photo-only captures still land even if transcript is null).
- SC#3 PASS: the image path exists on disk.

### Step 5: Record results

Paste the harness output (mask phone numbers) into a reply on this checkpoint.
Include:
- The SC#1 SELECT output (`id`, `farmos_person`, `transcript` snippet)
- SC#3 path-exists result
- Whether D-07 / A5 required any ops fix before the run

Type "approved" with the output to close this checkpoint.

---

## Failure Triage

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| PREFLIGHT D-07 FAIL | Whisper container unhealthy (cuInit 804) | D-07 ops fix (cuda-compat purge) |
| SC#1 xscript FAIL (transcript null) | Whisper 400 due to ALLOWED_ROOT mismatch | A5: align bind-mount in compose override |
| SC#1 xscript FAIL (transcript null) | Whisper 5xx / timeout | Check `docker logs mushy-whisper-transcribe-1` |
| SC#1 slug FAIL (unassigned) | Farmer number not in SIGNAL_FARMER_MAP | Verify farmer number mapping in tenant config |
| SC#3 path FAIL (exists=False) | alerter-py volume not mounted | Check CAPTURE_BASE_PATH bind-mount |
| SC#3 path FAIL (exists=False) | Path was NOT under ALLOWED_ROOT | Align alerter-py + whisper-transcribe mounts (A5) |
| No row in DB at all | Boot daemon not running / receive loop not started | `docker logs mushy-alerter-py-1` |
| Dual-poller contention | Node alerter consumed the message first | Stop Node alerter, resend voice note |

If transcription returns null despite a healthy Whisper container, capture:
1. alerter-py D-04 WARNING log line (includes reason from transcribe_client)
2. The /transcribe response body (add temporary debug logging to pipeline.py if needed)
Flag the finding before declaring SC#1.

---

## Acceptance Criteria

- [ ] SC#1: `signal_capture` row has 26-char ULID `id`, `farmos_person` != "(unassigned)",
      `transcript` IS NOT NULL for the voice note.
- [ ] SC#3: every path in `attachment_paths` exists on disk (`os.path.exists` True).
- [ ] D-04 verified: a photo-only or transcription-failure capture still persisted
      (row present, transcript null, degraded=True if applicable) -- no capture dropped.
- [ ] No dual-poller contention: the live Node alerter did not consume the test message.

---

*Runbook created: 2026-06-23 | Plan: 58-04 | Wave: 4*
