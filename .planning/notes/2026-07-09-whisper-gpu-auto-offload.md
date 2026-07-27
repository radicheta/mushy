---
date: "2026-07-09 13:45"
promoted: false
---

Roadmap candidate: auto-offload the Whisper model from GPU after idle.

The `mushy-whisper-transcribe-1` container (uvicorn `main:app` on :8090) keeps the Whisper model resident on the RTX 2060, holding ~1.7 GB of the 6 GB VRAM indefinitely between requests. On a shared GPU (Maya, Xorg, etc. also using it) this crowds out other work. Today it was manually freed with `docker restart mushy-whisper-transcribe-1` — the model reloads lazily on the next transcription.

Proposal: add an idle timer to the transcribe service that unloads the model (frees CUDA memory) after N minutes of no requests, and reloads on demand. Tradeoff = a cold-start latency penalty on the first request after idle; tune N so routine bursts stay warm. Alternatively expose a manual/scheduled offload endpoint if lazy reload proves too slow.
