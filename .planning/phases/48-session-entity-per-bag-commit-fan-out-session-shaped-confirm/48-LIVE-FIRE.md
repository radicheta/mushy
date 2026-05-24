# Phase 48 Live-Fire — May 22 fixture commit replay against farmOS dev

**Status:** OPERATOR-DEFERRED (gated behind `EVAL_RUN_LIVE=1` + `FARMOS_DEV_URL` + `FARMOS_API_TOKEN`)
**Hermetic ship-gate:** PASS (7 tests in 3 files, <0.5s) -- `npx jest test/farmos/integration/seeding-session-commit --no-coverage`
**Operator runbook last revised:** 2026-05-23 (paired with 48-05 SUMMARY)

This document mirrors the [47-LIVE-FIRE.md](../47-multi-source-extraction-fusion-groups-shape-inoc-draft/47-LIVE-FIRE.md) paper-trail format. Phase 48's hermetic integration tests cover the full producer-to-consumer chain (commit-watchdog -> commit-router -> commit-seeding-session -> assets/logs -> outcome-ack dispatch -> commitDb state machine) with a mock farmOS client; the live-fire path below is the mock-vs-real proof.

## Why operator-deferred

Per the Phase 47-05 precedent: live-fire is the proof that mock and real farmOS agree on payload shape, parent[] array order, response codes, and DELETE semantics. The hermetic tests cannot catch mock drift; only a real farmOS write can. The 47-05 live-fire turned up the ask-back path that the hermetic tests had over-specified (Gray Area 3) -- a class of finding only live-fire surfaces.

For Phase 48 the same pattern: a hermetic green is necessary but not sufficient. The operator should run the steps below against farmOS dev when they have ~10 minutes and farmOS dev is reachable, then update the "Result" section at the bottom of this file.

## Prerequisites

1. **farmOS dev reachable.** Confirm `FARMOS_DEV_URL` is set in the environment or in `.env` at the alerter root. From project memory ([[reference_farmos_project]]) the dev project lives at `/mnt/slime-kingdom/shared/farmos/`; the dev URL is typically `http://farmos-dev.local` or a Tailscale host. Verify with:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" "$FARMOS_DEV_URL/api"
   # Expect: 200 (or 401 if no token; 401 still proves reachability)
   ```

2. **Bearer token.** Set `FARMOS_API_TOKEN` to a token with write scope on `asset/fungi` and `log/seeding` + delete scope on `asset/fungi`. Reuse the token from Phase 40 / 43 live-fires if still valid.

3. **fungi_xing 'block' term exists.** Phase 40 schema lock confirmed it; no action needed if you've done a prior live-fire. Verify:

   ```bash
   curl -s "$FARMOS_DEV_URL/api/taxonomy_term/fungi_xing?filter[name][value]=block" \
     -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
   # Expect: 1
   ```

4. **'session' fungi_type taxonomy term NOT required.** Per the 48-02 SUMMARY decision, the session asset uses `allowNoFungiType:true` -- relationships.fungi_type is omitted entirely. No taxonomy provisioning step is needed. If a future plan tightens to require the term, this section will need a one-time `POST /api/taxonomy_term/fungi_type` step.

5. **fungi_type terms for SHI + KOY exist.** Phase 40 work covers this. Verify:

   ```bash
   for s in SHI KOY; do
     echo -n "$s: "
     curl -s "$FARMOS_DEV_URL/api/taxonomy_term/fungi_type?filter[name][value]=$s" \
       -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
   done
   # Expect: SHI: 1, KOY: 1
   ```

6. **No pre-existing 'inoc 2026-05-22' asset.** First-run only; if a prior live-fire left one in dev, expect the handler to mint `inoc 2026-05-22 #2` (informative; see Step 6 below). Sweep with:

   ```bash
   curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=inoc 2026-05-22" \
     -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data[].id'
   # If non-empty: DELETE them or accept the #N collision branch
   ```

## Operator steps

### Step 1 -- Run the hermetic ship-gate (sanity check)

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
npx jest test/farmos/integration/seeding-session-commit --no-coverage
```

Expect: `Test Suites: 3 passed, 3 total` / `Tests: 7 passed, 7 total`. If this is red, do NOT proceed -- fix the hermetic regression first.

### Step 2 -- Run live-fire (currently operator-only)

Phase 48-05 does NOT wire an `EVAL_RUN_LIVE=1` automated branch into the integration tests (per [[feedback_real_data_before_ship_gate_pass]] curated-fixtures-are-not-sufficient -- but per Plan 05 scope, the live wiring is operator-deferred). To exercise the live path, an operator runs a small Node script that wires the REAL farmOS client (`src/farmos/client.js`) into the same `commitSeedingSession` handler under test:

```bash
cd /mnt/slime-kingdom/opt/mushy/src/agents/alerter
EVAL_RUN_LIVE=1 \
  FARMOS_DEV_URL="$FARMOS_DEV_URL" \
  FARMOS_API_TOKEN="$FARMOS_API_TOKEN" \
  node -e "
    (async () => {
      const fs = require('fs');
      const path = require('path');
      const { createFarmOSClient } = require('./src/farmos/client');
      const commitSeedingSession = require('./src/farmos/commits/commit-seeding-session');
      const draftJson = JSON.parse(fs.readFileSync(
        path.join(__dirname, 'test', 'fixtures', 'seeding-session-may22-commit', 'draft.json'), 'utf8'));
      const client = createFarmOSClient({
        baseUrl: process.env.FARMOS_DEV_URL,
        token: process.env.FARMOS_API_TOKEN,
        logger: console,
      });
      const draft = { id: 'live-fire-' + Date.now(), log_type: 'seeding_session', draft_json: draftJson };
      const auditLogger = { logCommit: async (e, d, r) => console.log('[audit]', e, r) };
      const t0 = Date.now();
      const r = await commitSeedingSession(client, draft, { auditLogger });
      console.log(JSON.stringify({ elapsed_ms: Date.now() - t0, ...r }, null, 2));
    })().catch(e => { console.error(e); process.exit(1); });
  "
```

Capture the JSON output (asset UUIDs + log UUIDs + elapsed_ms) into the "Result" section below.

### Step 3 -- Verify the session asset

```bash
SESSION_UUID=$(curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=inoc 2026-05-22" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq -r '.data[0].id')
echo "session=$SESSION_UUID"
# Expect: a non-null UUID
```

### Step 4 -- Verify lineage walk on a child block

```bash
curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=260522_KOY_7&include=parent" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data[0].relationships.parent.data'
# Expect: array of length 2; data[0] resolves to 260118_KOY_12; data[1] = $SESSION_UUID
```

### Step 5 -- Verify session asset's children count

```bash
curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[parent.id]=$SESSION_UUID" \
  -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq '.data | length'
# Expect: 11
```

### Step 6 -- (optional) Re-run for name-collision branch

Without cleanup, re-run Step 2. The handler should mint a second session asset named `inoc 2026-05-22 #2` and 11 NEW child blocks. Informative; document the result.

### Step 7 -- Cleanup

```bash
# Delete the test session asset's 11 children, the 5 source blocks (only the ones
# the live-fire CREATED -- skip pre-existing 260118_*, 260304_*, 260425_*), and
# the session asset itself.

for name in 260522_SHI_1 260522_SHI_2 260522_SHI_3 \
            260522_KOY_4 260522_KOY_5 260522_KOY_6 260522_KOY_7 \
            260522_KOY_8 260522_KOY_9 260522_KOY_10 260522_KOY_11; do
  uuid=$(curl -s "$FARMOS_DEV_URL/api/asset/fungi?filter[name][value]=$name" \
    -H "Authorization: Bearer $FARMOS_API_TOKEN" | jq -r '.data[0].id // empty')
  if [ -n "$uuid" ]; then
    curl -s -X DELETE "$FARMOS_DEV_URL/api/asset/fungi/$uuid" \
      -H "Authorization: Bearer $FARMOS_API_TOKEN"
    echo "deleted child $name = $uuid"
  fi
done

if [ -n "$SESSION_UUID" ]; then
  curl -s -X DELETE "$FARMOS_DEV_URL/api/asset/fungi/$SESSION_UUID" \
    -H "Authorization: Bearer $FARMOS_API_TOKEN"
  echo "deleted session $SESSION_UUID"
fi
```

Source blocks (`260118_*`, `260304_*`, `260425_*`) are intentionally left in farmOS dev -- they represent real parents and may be reused by future live-fires.

### Step 8 -- Update this file

Append the live-fire result to the "Result" section at the bottom. Include:
- Date + operator (Santi / radicheta / farmer1)
- Elapsed_ms from the Node script
- The 17 asset UUIDs + 11 log UUIDs
- Lineage walk JSON snippet (Step 4 output, verbatim)
- Children count from Step 5 (should be 11)
- Cleanup outcome
- Any deviations from hermetic expectations -- IF ANY, file a Phase 49 follow-up; do NOT silently fix in 48

## Deviation policy

If the live-fire returns a result that differs from the hermetic spec, FAIL the gate and open a Phase 49 follow-up. Specifically:

- farmOS rejects the parent[] array (e.g. expects `taxonomy_term--fungi_xing` not `asset--fungi`): 48-02 lineage encoding decision is wrong; re-open.
- `allowNoFungiType:true` produces a 422 (farmOS schema requires the relationship): fall back to provisioning a `session` fungi_type term.
- The 11-children count from Step 5 is wrong: cleanup branch may have fired silently; investigate.
- The DELETE in cleanup returns 4xx: investigate FK constraints between session asset and children.

Do NOT patch silently in Phase 48-05. The deviation is the signal.

## Result

(empty -- to be filled in by the operator who runs Step 2 against farmOS dev)

```
Date:
Operator:
Elapsed_ms:
Session UUID:
Child UUIDs:
Log UUIDs:
Lineage walk JSON (260522_KOY_7 parents):
Children count for session:
Cleanup outcome:
Deviations from hermetic:
Verdict (PASS / FAIL):
```

## Files

- Hermetic tests: `src/agents/alerter/test/farmos/integration/seeding-session-commit-{may22,partial-fail,idempotent}.test.js`
- Harness: `src/agents/alerter/test/farmos/integration/_session-commit-harness.js`
- Fixture: `src/agents/alerter/test/fixtures/seeding-session-may22-commit/{draft.json,expected-farmos-payloads.json}`
- Handler under test: `src/agents/alerter/src/farmos/commits/commit-seeding-session.js`
- Router: `src/agents/alerter/src/farmos/commits/commit-router.js` (DISPATCH.seeding_session)
- Watchdog: `src/agents/alerter/src/farmos/commit-watchdog.js`

## Cross-references

- [47-LIVE-FIRE.md](../47-multi-source-extraction-fusion-groups-shape-inoc-draft/47-LIVE-FIRE.md) -- the precedent paper-trail format
- 48-CONTEXT.md, 48-02-SUMMARY.md, 48-04-SUMMARY.md
- Phase 49: real-corpus eval + May 22 prod reprocess (the final v1.9 ship gate)
