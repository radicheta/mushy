"""capture -- Signal capture + transcription pipeline for farm_agent.

NOTE: this package is NOT a pure Foray island. pipeline.py imports
_read_dm, mask_number, and resolve_farmer from farm_agent.signal_io.router.
pool and config are also injected externally, but the signal_io.router
coupling means extraction into a standalone Foray module will require
moving those primitives to a shared utility first.

Provides:
  create_capture_pipeline: factory returning {handle, record_reply_capture}
  create_transcribe_client: factory returning {transcribe} (httpx, never-throws)
  insert_capture: persist one signal_capture row (psycopg3, never-throws)
"""
