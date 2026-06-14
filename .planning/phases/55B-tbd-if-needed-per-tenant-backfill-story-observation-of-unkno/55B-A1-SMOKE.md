---
phase: 55B-fidelity-corpus-unblock
plan: 01
artifact: A1-SMOKE
assumption: A1' (field-scoped binary upload links image to asset--group)
verdict: PASS
target: dev farmOS :18080
recorded: 2026-06-14T20:03:32.857Z
---

# A1 PATCH-associates-files dev smoke probe

Target: http://10.68.155.50:18080 (dev only; prod :8082 refused by script guard)

## Result: PASS

- dev_url: http://10.68.155.50:18080
- group_upsert: {"ok":true,"assetId":"b8dd9d40-72f0-48d8-a135-340ff719aadd","outcome":"created","http_status":201}
- image_upload: {"ok":true,"fileId":"8fe0d485-4a92-4eae-a60c-f3cf3edc0ccb"}
- linked_images: ["a1-smoke.jpg"]
- verdict: PASS
- cleanup_delete: {"ok":true,"http_status":204}

## Interpretation

A1' VERIFIED: a field-scoped binary POST to /api/asset/group/{uuid}/image (Content-Type octet-stream) creates the file AND links it to the group's image field in one call. files.uploadFieldAttachments uses this route; commit-seeding-session attaches page photos this way. No relationships.file PATCH needed.
