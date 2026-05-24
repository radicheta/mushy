# 2026-05-22 inoc session — prod farmOS write receipt

**Date written:** 2026-05-24
**Operator:** Santi (via radicheta-claude, explicit `! yes do the stubs then write` authorization)
**Target:** http://10.68.155.50:8082 (prod farmOS, `farmos-www-1`)
**Identity used:** mushy-bot / farm_manager (perms granted in today's UAT session per `[[notes/2026-05-24-v1.9-uat-findings.md]]`)
**Source draft:** test fixture `src/agents/alerter/test/fixtures/seeding-session-may22-commit/draft.json` (the 2026-05-22 5-group / 11-child shape extracted in Phase 47 live-fire)

## Ancestor stubs (4 created)

The 2025-paper-log scan hasn't run yet; the Jan/Mar 2026 inoc sessions that produced these blocks exist only in Santi's paper notebook. To anchor the May-22 children's lineage without losing the parent edges, 4 stub fungi assets were minted with a structured notes trailer:

> STUB - awaits 2025-paper-scan backfill; created 2026-05-24 as ancestor anchor for 2026-05-22 inoc session (260522_*); upsert layer (Phase 51) will enrich in-place on backfill arrival.

| Name | UUID | fungi_type | fungi_xing |
| --- | --- | --- | --- |
| 260304_SHI_5 | 5de992ca-1a12-4609-9749-3a26b5eea9e9 | SHI | block |
| 260118_SHI_23 | 5d70eaec-0f9b-40c4-9ff5-b7d373ec8fb2 | SHI | block |
| 260118_SHI_26 | 92f83fe6-ea43-4d7a-8061-552eb5094457 | SHI | block |
| 260118_KOY_12 | 91459b30-156d-42b6-9706-a6ba1ff2194f | KOY | block |

The 5th parent (`260425_KOY_4`) already existed in prod; not stubbed.

## May-22 children + seeding logs (11 + 11)

Created via `scripts/live-fire-48.js` against prod; elapsed 3.48s; all-or-nothing transactional intent (handler reverse-deletes on partial failure). `findAssetByName` reused all 5 source parents — zero source duplicates.

Child block names: 260522_SHI_1, 260522_SHI_2, 260522_SHI_3, 260522_KOY_4..11.

Sample lineage walks:
- 260522_SHI_1 → 260304_SHI_5
- 260522_KOY_7 → 260118_KOY_12
- 260522_KOY_11 → 260425_KOY_4

Full asset_ids + log_ids in `/tmp/48-live-fire-prod-result.json` (also archive at `.planning/notes/2026-05-24-prod-write-receipt-uuids.json`).

## Open follow-ups

1. **Session entity not modeled.** Per the asset--group design note (`.planning/notes/2026-05-24-session-as-asset-group-design.md`), the session-as-entity is on hold pending the farm_group module enable on dev + prod. Until then "show me the May-22 session" is a query: `GET /api/log/seeding?filter[timestamp][operator]=BETWEEN&filter[timestamp][value][]=<may22-day-start>&filter[timestamp][value][]=<may23-day-start>`.
2. **Stubs are placeholders.** When the 2025-paper-scan pipeline lands and processes the Jan/Mar inoc sessions, the Phase 51 upsert layer will enrich these 4 stubs in place (notes-replace, add qr_codes, add a `seeding` log creating them from a sterilization batch, add parent-batch refs). Until Phase 51 ships, a manual reconciliation script can do the same.
3. **No farmer ack.** This write went around the Phase 45 ack pipeline (it ran via the harness script, not via a confirmed `signal_draft` row). Santi was the operator; no Signal-side acknowledgement required.
4. **`signal_draft` row 6edaaba** (the May-22 inoc draft that originally `status=expired`) was already discarded earlier this session with reason "superseded by Phase 49 reprocess (v1.9 ship-gate)" — see commit `7ac92ea`. The reprocess is now real and complete.

## Verification one-liner (current session, repeatable)

```bash
curl -s -b /tmp/prod-c.txt -H "X-CSRF-Token: $PCSRF" -H "Accept: application/vnd.api+json" \
  "http://10.68.155.50:8082/api/log/seeding?filter%5Btimestamp%5D%5Boperator%5D=BETWEEN&filter%5Btimestamp%5D%5Bvalue%5D%5B%5D=2026-05-22T00:00:00&filter%5Btimestamp%5D%5Bvalue%5D%5B%5D=2026-05-23T00:00:00" \
  | jq '.data | length'
# Expect: 11
```
