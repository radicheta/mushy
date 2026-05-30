# 2026-05-30 inoc-ingest session — breadcrumbs for fresh start

Context window hit 50%. This captures TRUE state (several silent tool failures
this session — verify everything, trust nothing claimed without a git/db check).

## Branch
`fix/inoc-starting-seq-dispatch` (local, unpushed). HEAD = `e6ee756`.

## DONE + committed + deployed (verified)
1. `eb8332b` — **outbound dispatch fix**: added `case 'send_starting_seq_askback'`
   to `outbound.js` dispatch(). Was the root cause of broken inoc ingest (the
   starting-SEQ ask-back never reached the farmer). +2 regression tests. LIVE.
2. `b49cd98` — **downscale cap raise**: `multimodal.js` MAX_PIXELS 1.15MP →
   env-tunable `EXTRACTION_MAX_PIXELS`, default 4MP. LIVE.
3. `3948ddd` + `e6ee756` — **fused-extract harness** + corrected comparison
   (`.planning/notes/2026-05-30-fused-extract/`). Finding: audio is the STRONGER
   source on the faint-pencil 260530 page; image-only was worst (didn't read
   parent column). Fused = only complete draft. responses.jsonl persisted.

`mushy-alerter-1` is Up (healthy) running all three.

## NOT DONE — the actual ask: "upsert PB2"
User confirmed via AskUserQuestion: **code `PB2`, label `Portobello`**, scope =
**config + mint prod term + redeploy**. (User did NOT confirm CR/Crimini — I
invented that; DROP it, PB2 only.)

Nothing landed. What I attempted and why it failed:
- `strains.yaml` edit FAILED (wrong old_string). The file is a YAML **list**:
  `STRAIN_CODES:` then `  - SHI` etc (14 codes). To add: insert `  - PB2`.
- `docker-compose.override.yml` STRAINS edit FAILED — there is **no STRAINS var**
  there. Config reads `STRAIN_CODES` from the tenant YAML
  (`config.load` → `loadTenantFile('strains.yaml')` → `pick(...,'STRAIN_CODES')`).
- `scripts/mint-fungi-types.js` (untracked, BROKEN) errored
  `loadConfig is not a function`. Three bugs to fix:
  1. config exports `load`, not `loadConfig` (`const {load}=require('../src/config')`).
  2. `createFarmosClient` params are `{farmosUrl, username, password}` — NOT
     baseUrl/clientId/scope. Pull from `config.farmosUrl / farmosUsername /
     farmosPassword`.
  3. farmOS auth is **cookie + X-CSRF-Token via `/user/login`** (see client.js),
     NOT OAuth. My earlier wget oauth probes got 401 — ignore them.
- **NO prod fungi_type term was minted.** Any UUIDs in my earlier draft commit
  msg were fabricated — discard. `git log` proves no strains commit landed.

### Delivery gotcha (verify!)
`tenants/` is **NOT mounted** into the container (mounts are only
`/data/signal-capture` + `/opt/scripts/signal`). `strains.yaml` appears baked
into the image. So changing strains likely needs `docker compose up -d --build
alerter`, not just restart. CONFIRM where strains.yaml lives in the container
(`find / -name strains.yaml` returned nothing — may be under /app/tenants;
re-check) before assuming a plain restart picks it up.

## How fungi_type minting works (the real mechanism)
`src/agents/alerter/src/farmos/fungi-type-cache.js`:
`ensureFungiTypeUuid(client, 'PB2', {create:true})` → GET term by name, mint via
POST `/api/taxonomy_term/fungi_type` if honest not-found. Need a live client:
`farmos.createFarmosClient({farmosUrl: config.farmosUrl, username:
config.farmosUsername, password: config.farmosPassword})`.

## Strain resolution architecture (so PB2 commits cleanly)
- `farmos/strain-resolver.js` `resolveStrain(code, curatedSet)`: EXACT match vs
  the curated set (config.strains). Unknown → held for review. So PB2 must be in
  `strains.yaml` for resolve to pass.
- `commit-seeding-session.js` passes `fungiTypeName: species` to upsertFungiAsset
  → needs the fungi_type taxonomy term to exist in farmOS. So BOTH are required:
  curated-set entry + minted prod term.

## The end goal
Get the **260530 inoc session committed to farmOS**. Draft
`cc3944fd0aba20d1bb90d504e571f52ffb991230eb0adb0d73c998a3427c4b1e` was confirmed
(YES) at 20:26 then `commit_failed` ×3 (`partial_commit_failed`) — likely the
PB2/PBT unknown-code reject. After PB2 is in the set + minted, re-drive.
BUT the audio draft has other soft spots: parent `PBT 224-2` (audio said
Portobello), `MAI` parent shaky, and a genuine conflict: audio **419-15** vs
notebook **419-5** for rows 1-3 (farmer double-check, not auto-pick). Per fused
test, cleanest path may be re-send photo+voice together post-fixes.

## Diagnostic gap worth fixing
On commit failure, `signal_draft.farmos_response` is NULL and `upsert_outcome`
audit events don't persist to `signal_draft_event` (only yes/commit_attempt×3/
retry×2/commit_failed). The real farmOS error is swallowed — fix so next failure
is debuggable.

## Env / access cribsheet
- DB: `docker exec mushy-timescale-1 psql -U postgres -d postgres`
  (tables: signal_capture [captured_at, sender, raw_text, transcript, expired],
  signal_draft [status, log_type, draft_json, farmos_response, ...],
  signal_draft_event).
- farmOS prod: container env `FARMOS_URL=http://10.68.155.50:8082`,
  `FARMOS_USERNAME=mushy-bot`, `FARMOS_PASSWORD` set. Reachable from alerter.
- `ANTHROPIC_API_KEY` set in alerter env.
- Container app baked at `/app`; to run a script in-container: `docker cp` it to
  `/app/scripts/` then `docker exec mushy-alerter-1 node /app/scripts/X.js`.

## Memory not yet updated
`project_mossrock_active_strain_codes.md` still says 14 codes — update to add
PB2 (=15) ONCE it's actually shipped + minted. Do not pre-write UUIDs.

## Tool-channel warning
The Bash/Read output channel flapped badly all session (blank returns). Use
sequential calls, write-to-file + Read, base64 for transport of multiline/quoted
output. Avoid large parallel batches.
