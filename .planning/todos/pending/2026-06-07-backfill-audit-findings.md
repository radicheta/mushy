# 2026-06-07 Backfill audit findings (Santi, reviewing the prod 10-page set)

Living list of findings from Santi's hands-on audit of the prod 10-page backfill
set (run 2026-06-07T23-39-18-403Z; see
`.planning/notes/2026-06-07-prod-smoke-fidelity-audit.md`). The full corpus run
is PARKED until these + the fidelity gaps are addressed.

## F1 -- Log events must have the notebook page photo attached

**Observed:** committed log events carry no picture of the source notebook page.
**Want:** each log (or its session, see F2) shows the notebook page image so the
farmer can see provenance.

**Codebase read (feasibility = wiring, not new capability):**
- `src/farmos/files.js` `uploadAttachment`/`uploadAttachments` already POST to
  `/api/file/file`.
- The backfill already carries the page path: synthetic capture sets
  `attachment_paths: [page]` (backfill-notebook.js ~189).
- BUT only `commit-observation.js` uploads attachments. `commit-seeding`,
  `commit-harvest`, `commit-activity`, `commit-input` have ZERO attachment code
  -- so the bulk of backfill logs drop the image.
- Known gotcha: farmOS private-files 500 unless `/data` bind-mounted +
  `file_private_path` set ([[project_farmos_private_files_and_mushy_silent_photo_drop]]).
- Best target: attach the page image once at the SESSION level (F2), not N times
  per block.

## F2 -- Need a SESSION view that matches a notebook page side-by-side

**Observed:** one log event per block; no way to see THE SESSION. Can't lay the
farmOS view next to the physical notebook page and reconcile.
**Want:** a per-page/session grouping in farmOS the farmer can match 1:1 to a
notebook page. This is the long-standing
[[project_session_is_production_shape_per_bag_is_storage]] requirement
("session is production shape; per-bag is storage; farmer compares to notebook").

**Codebase read (mechanism exists, backfill doesn't use it):**
- `commit-seeding-session.js` already creates a SESSION GROUP ASSET (via
  `groupAssets.upsertGroupAsset`) that groups the per-block assets; router maps
  `log_type: 'seeding_session'` -> it.
- BUT the backfill emits plain `log_type: 'seeding'` (one of the locked 5 shapes)
  -> routed to per-block `commit-seeding` -> no session group. So blocks land
  ungrouped.
- Fix direction: have the backfill emit session-shaped commits (one session per
  notebook page) so blocks group under a session asset; the page = the session.

## Converged design

F1 + F2 are one feature: **one session entity per notebook page, with the page
image attached to it, and the per-block logs/assets as its members.** Opening the
session in farmOS then IS the side-by-side-with-the-notebook view. Scope this
with the fidelity fix (commit-time ground-truth cross-check) before the full run.

## Open / more notes incoming
- (Santi is still dropping audit notes -- append below.)
