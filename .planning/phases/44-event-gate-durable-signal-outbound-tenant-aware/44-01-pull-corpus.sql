-- Phase 44 Plan-01: ship-gate corpus pull from elder-plops Timescale.
-- Per D-20/D-21 sourcing recipe (.planning/notes/2026-05-17-prod-corpus-survey.md §5).
--
-- DEVIATION (Rule 3, blocking-issue auto-fix): plan called for LIMIT 500 with
-- floor captured_at >= '2026-05-10'. Live `signal_capture` on elder-plops
-- holds only 108 rows total (99 since 2026-05-10, 9 in 2026-04). The 500-row
-- target is structurally unreachable. Floor widened to '2026-04-01' to pull
-- the FULL available corpus (108 rows). Hand-classification of 100 still
-- works (100 of 108 = 92.5% coverage) and preserves D-20 ship-gate intent.
--
-- Run from elder-plops host:
--   set -a && source .env && set +a
--   docker exec -e PGPASSWORD="$TIMESCALE_PASSWORD" mushy-timescale-1 \
--     psql -U postgres -d postgres -tAc "SELECT row_to_json(t) FROM ( $(cat 44-01-pull-corpus.sql) ) t" \
--     > 44-01-raw-corpus.jsonl

SELECT
  id,
  captured_at,
  sender,
  message_type,
  raw_text,
  transcript,
  COALESCE(array_length(attachment_paths, 1), 0) AS attachment_count,
  attachment_paths,
  llm_reply,
  farmos_person,
  reply_target_kind,
  group_id
FROM signal_capture WHERE captured_at >= '2026-04-01'
ORDER BY captured_at DESC
LIMIT 500
