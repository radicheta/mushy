---
phase: 42-shi-pilot
type: research
status: draft
---

# Phase 42 Research

Short research notes for the SHI-on-sawdust pilot scaffolding. Source-of-truth is the locked farmOS schema in `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md` (B1..B7 + C1..C5 + P1..P5).

Calendar-blocked phase: research only covers what the autonomous run ships (tools + RUNBOOK + scaffolds). Actual lifecycle reality belongs in `42-PILOT-LOG.md` once events land.

## 1. C1 current-stage derivation

Locked rule: stage is NOT a property on the `fungi` asset. It is derived from log history at read time.

Five stages (per B7, pinning folded into fruiting):

| Stage           | Entered via                                  | Terminal? |
|-----------------|----------------------------------------------|-----------|
| 0 pre-inoc      | (no logs yet) or batch asset only            | no        |
| 1 colonizing    | `seeding` log against the block              | no        |
| 2 fruiting      | `activity` log with `name=cold_shock`        | no        |
| 3 spent         | `activity` log with `name=archive_spent`     | yes       |
| 4 contaminated  | `activity` log with `name=contam`            | yes       |

Algorithm (pseudocode):

```
stageAt(assetUuid, at = now):
  logs = GET /api/log?filter[asset.id]=<uuid>&filter[timestamp][<=]=<at>&sort=timestamp
  if any log.activity.name == "contam":         return "contaminated"
  if any log.activity.name == "archive_spent":  return "spent"
  if any log.activity.name == "cold_shock":     return "fruiting"
  if any log.type == "seeding":                 return "colonizing"
  return "pre-inoc"
```

Notes:
- Terminal stages dominate. Once `contam` or `archive_spent` appears, the block stays there even if later logs are filed.
- Order between contam vs archive_spent is irrelevant for derivation -- both are terminal; we report the one that actually happened first, but for the pilot a tie cannot happen.
- Time scoping (`--at <iso>`) lets the operator ask "what stage was block X on 2026-05-20?" -- crucial for PILOT-03 checkpoint verification.

## 2. Three tools (pseudocode)

All three import `src/agents/alerter/src/farmos/client.js` via `createFarmosClient({...})`. All three are GET-only. All three accept `FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` from env (same convention as Phase 40 alerter container).

### `tools/farmos-current-stage.js <asset_uuid> [--at <iso>]`

```
main(argv):
  uuid, at = parseArgs(argv)
  client = createFarmosClient(envCreds())
  logs = await fetchLogs(client, uuid, at)
  stage = deriveStage(logs)
  print { asset: uuid, at: at || "now", stage, evidence: lastRelevantLog }
```

### `tools/farmos-lineage.js <asset_uuid>`

Walks parent refs through `harvest` and `seeding` logs. A `bag` asset's parent is the harvest log's source block; a `block` asset's parent is the seeding log's source batch.

```
main(argv):
  uuid = parseArgs(argv)
  client = createFarmosClient(envCreds())
  chain = []
  cur = await fetchAsset(client, uuid)
  while cur:
    chain.push({ uuid: cur.id, name: cur.attributes.name, type: cur.type })
    parentLog = await findParentLog(client, cur.id)   // harvest or seeding referencing cur as output
    if !parentLog: break
    cur = await fetchAsset(client, firstSourceAssetId(parentLog))
  print { chain }
```

Expected pilot output: `bag -> harvest_batch -> block -> sterilization_batch` (four hops).

### `tools/farmos-pilot-reconstruct.js <block_uuid>`

Operator-readable timeline derived ENTIRELY from farmOS logs (no Signal refs). One line per event, sorted by timestamp.

```
main(argv):
  uuid = parseArgs(argv)
  client = createFarmosClient(envCreds())
  logs = await fetchAllLogsTouching(client, uuid)  // includes lineage descendants (bags, harvest batches)
  for log in logs.sortedByTimestamp():
    print fmtTimelineRow(log)  // "[2026-05-20T10:00Z] seeding  block-XYZ <- batch-ABC  qr=Q12345"
```

## 3. Signal message templates (operator playbook source)

The operator drives the pilot by sending these messages from the f1 (Santi) phone to the alerter bot. Per Phase 39, every message goes through the confirm loop -- operator replies YES before any farmOS write.

| PILOT step | Operator Signal message (template)                                                 |
|------------|------------------------------------------------------------------------------------|
| PILOT-01   | "sterilized 30 jars sawdust today"                                                 |
| PILOT-02   | "inoculated 1 block sawdust SHI, QR <code>"                                        |
| PILOT-03a  | "no contam day 7 on block <ref>" (observation)                                     |
| PILOT-03b  | "moved block <ref> to fruiting chamber" (relocate activity)                        |
| PILOT-03c  | "cold shocked block <ref>" (activity name=cold_shock)                              |
| PILOT-03d  | "pins emerged on block <ref>" (observation)                                        |
| PILOT-03e  | "first flush coming in on block <ref>" (observation)                               |
| PILOT-04   | "harvested 1.2kg from block <ref>, bagged into 6 bags QRs <list>"                  |
| PILOT-05   | "block <ref> spent, archived"                                                      |
| PILOT-06   | (no Signal message; operator runs `farmos-pilot-reconstruct.js`)                   |

Numerics in any operator-facing line in this doc or RUNBOOK use `fmtNum()` semantics (1 decimal, strip trailing .0, `?` for null). The Signal text above is the OPERATOR speaking; the bot reply is what we format.

## 4. Verification tooling vs CI

Per CONTEXT D-06: no CI tests for Phase 42 because every criterion requires real farm-side reality. The three tools DO get unit tests (mocked farmOS responses) so the derivation logic is exercised before the operator depends on it. Tests live in `tools/test/`.

## 5. Calendar-blocked closure

Per D-01a + D-05b: the autonomous run ships scaffolding only. Operator picks up from RUNBOOK at PILOT-01. PILOT-03 needs 4-8 weeks. v1.7 milestone close is partial-blocked here.

---

*Phase 42 research draft, 2026-05-13.*
