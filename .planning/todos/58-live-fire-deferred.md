# DEFERRED — Phase 58 live-fire (SC#1 + SC#3)

**Deferred:** 2026-06-23 (autonomous run, operator chose defer-and-continue)
**Status:** code + harness complete (8/9 verified); operator live round-trip pending

Run `src/farm-agent/scripts/live_fire_58.py` per `.planning/phases/58-capture-transcription/58-LIVE-FIRE.md` once:
1. D-07 fixed — `mushy-whisper-transcribe-1` healthy (`curl -fsS $WHISPER_URL/health` = 200); purge cuda-compat if cuInit err 804 (see memory project_whisper_cuda_compat_geforce_804).
2. A5 — alerter-py + whisper-transcribe share `/data/signal-capture` bind-mount.
3. Node alerter idle for the test account (no dual-poller).
4. Boot daemon running → send real voice note + photo → harness prints PASS for SC#1 (non-null transcript) + SC#3 (on-disk paths).
