---
phase: 51
plan: 06
type: execute
wave: 4
depends_on: ["51-05"]
files_modified:
  - src/agents/alerter/scripts/live-fire-51.js
  - .planning/notes/2026-05-XX-phase-51-live-fire.md
autonomous: false
requirements: [UPSERT-07]
user_setup:
  - service: dev-farmOS
    why: "Live-fire attestation requires writing to the dev farmOS instance at elder-plops :18080"
    env_vars:
      - name: FARMOS_URL
        source: "Use http://elder-plops:18080 or as configured for dev"
      - name: FARMOS_USERNAME
        source: "Dev farmOS account with write access (Mossrock API user)"
      - name: FARMOS_PASSWORD
        source: "Dev farmOS account password"
    dashboard_config:
      - task: "Pre-seed the 4 ancestor stubs on dev farmOS if not already present"
        location: "Dev farmOS UI or curl POST per .planning/notes/2026-05-24-prod-write-receipt.md stub recipe"
must_haves:
  truths:
    - "Live-fire script runs cleanly against dev farmOS"
    - "Replaying May-22 inoc against pre-stubbed dev → 4 stub assets patched (enriched, not duplicated)"
    - "Children's parent[] resolves to the existing stub UUIDs (no duplicate POSTs)"
    - "Audit log captures outcome per asset/log write"
    - "Receipt committed under .planning/notes/2026-05-XX-phase-51-live-fire.md"
  artifacts:
    - path: "src/agents/alerter/scripts/live-fire-51.js"
      provides: "Live-fire harness sibling-copy of live-fire-48.js with upsert-aware assertions"
      min_lines: 60
    - path: ".planning/notes/2026-05-XX-phase-51-live-fire.md"
      provides: "Attestation receipt with outcome counts + verdict"
  key_links:
    - from: "live-fire-51.js"
      to: "test/fixtures/seeding-session-may22-commit/draft.json"
      via: "require / fs.readFileSync"
      pattern: "may22-commit"
---

<objective>
Author and run the UPSERT-07 live-fire attestation: replay the May-22 inoc session against dev farmOS (which already has the 4 ancestor stubs from the 48-LIVE-FIRE run) and assert outcome counts. This is the end-to-end ship gate — unit tests + property tests are necessary but not sufficient ([feedback_real_data_before_ship_gate_pass]).

Purpose: Prove the upsert layer survives the network round-trip + real Drupal field normalization, and that the audit log captures outcome dimensions as designed.
Output: live-fire-51.js script + a committed receipt with verdict.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-SPEC.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-CONTEXT.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-PATTERNS.md
@src/agents/alerter/scripts/live-fire-48.js
@.planning/notes/2026-05-24-prod-write-receipt.md
@.planning/notes/2026-05-24-prod-write-receipt-uuids.json
</context>

<tasks>

<task type="auto">
  <name>Task 1: Author scripts/live-fire-51.js as sibling of live-fire-48.js</name>
  <files>src/agents/alerter/scripts/live-fire-51.js</files>
  <read_first>
    - src/agents/alerter/scripts/live-fire-48.js (full file, ~62 lines — fork directly)
    - src/agents/alerter/test/fixtures/seeding-session-may22-commit/draft.json (fixture replayed against dev)
    - 51-PATTERNS.md §live-fire-51.js (env-var preamble, client construction, result-write, phase-51 deltas)
    - .planning/notes/2026-05-24-prod-write-receipt-uuids.json (the 4 stub UUIDs to assert against)
  </read_first>
  <action>
    Fork `src/agents/alerter/scripts/live-fire-48.js` verbatim into `scripts/live-fire-51.js`. Keep the env-var contract, client construction, audit-logger, and result-write idiom (PATTERNS.md §live-fire-51.js lists every line range to copy).

    **Phase-51 specific deltas:**

    1. **Outcome tally:** wrap the audit-logger so it accumulates outcome counts:
       ```javascript
       const tally = { asset: { created:0, patched:0, noop:0, mixed:0 }, log: { created:0, patched:0, noop:0, mixed:0 } };
       const auditLogger = {
         async logCommit(event, draft, result) {
           if (result && result.outcome && event === 'upsert_outcome') {
             const kind = (result.asset_ids && result.asset_ids.length) ? 'asset' : 'log';
             tally[kind][result.outcome] = (tally[kind][result.outcome] || 0) + 1;
           }
           console.log('[audit]', event, result && result.outcome, result && result.http_status);
         },
       };
       ```

    2. **Assertion block** (per SPEC UPSERT-07 acceptance):
       ```javascript
       const stubUuids = require('../../../.planning/notes/2026-05-24-prod-write-receipt-uuids.json');
       const expectedStubNames = Object.keys(stubUuids);  // ['260304_SHI_5','260118_SHI_23','260118_SHI_26','260118_KOY_12']

       // Assert no duplicate UUIDs minted
       const allMintedIds = result.asset_ids || [];
       const uniqueIds = new Set(allMintedIds);
       if (uniqueIds.size !== allMintedIds.length) {
         console.error('FAIL: duplicate UUIDs in result.asset_ids');
         process.exit(1);
       }

       // Assert tally.asset.patched >= 4 (the 4 stubs enriched)
       if (tally.asset.patched < 4) {
         console.error('FAIL: expected ≥4 stub assets patched; got', tally.asset.patched);
         process.exit(1);
       }

       // Assert tally.asset.created === 0 (stubs and children already exist if replay is true replay; if first run on dev, 11 children may be created — script reports either way and the receipt records both scenarios)
       console.log('TALLY:', JSON.stringify(tally));
       ```

    3. **Lineage walk** — for each child block name in the draft, GET `/api/asset/fungi?filter[name][value]=<childName>` to resolve id, then GET the body, and assert `relationships.parent.data[].id` matches the expected stub UUID(s) from `stubUuids`. If mismatch → `process.exit(1)`.

    4. **Output path:** default `/tmp/51-live-fire-result.json`; write the full result JSON including tally and lineage check verdict.

    5. **Process exit:** 0 on green, 1 on runtime/assert failure, 2 on missing env (mirror live-fire-48.js).

    Commit:
    `feat(51-06): scripts/live-fire-51.js — UPSERT-07 attestation harness`
  </action>
  <verify>
    <automated>node -e "const path=require('path'); const fs=require('fs'); const p='src/agents/alerter/scripts/live-fire-51.js'; if(!fs.existsSync(p)) process.exit(1); const src=fs.readFileSync(p,'utf8'); if(!src.includes('FARMOS_URL')||!src.includes('tally')||!src.includes('260118_KOY_12')&&!src.includes('stubUuids')) process.exit(2); console.log('script structure ok');"</automated>
  </verify>
  <acceptance_criteria>
    - File exists at src/agents/alerter/scripts/live-fire-51.js
    - File length ≥ 60 lines
    - References FARMOS_URL / FARMOS_USERNAME / FARMOS_PASSWORD env vars
    - References the prod-write-receipt-uuids.json stub map (or hardcodes the 4 names)
    - Implements tally + assertion block + lineage walk
    - `node -c src/agents/alerter/scripts/live-fire-51.js` — syntactically valid (run via Node parse check)
  </acceptance_criteria>
  <done>Script authored, committed; ready for human-supervised execution against dev farmOS.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: CHECKPOINT — Execute live-fire against dev farmOS + commit receipt</name>
  <what-built>
    `scripts/live-fire-51.js` (from Task 1) is the UPSERT-07 attestation harness. The migrated upsert primitives (Plans 03/04/05) need a real-network attestation before Phase 51 ships.
  </what-built>
  <how-to-verify>
    1. Confirm dev farmOS is reachable: `curl -s -o /dev/null -w "%{http_code}\n" "$FARMOS_URL/api"` returns 200.
    2. Confirm the 4 ancestor stubs exist on dev. If not, pre-seed them:
       - Either copy the stubs from prod via the dump-replay path used in 48-LIVE-FIRE, OR
       - Run a one-shot script that POSTs the 4 stubs with `notes.value = 'STUB - awaits 2025-paper-scan backfill'` — record stub UUIDs in `/tmp/51-prefly-stubs.json` for the assertion step.
    3. Execute:
       ```bash
       cd src/agents/alerter
       FARMOS_URL=... FARMOS_USERNAME=... FARMOS_PASSWORD=... node scripts/live-fire-51.js
       ```
    4. Inspect output:
       - `tally.asset.patched >= 4` (the 4 stubs were enriched, not duplicated)
       - `tally.asset.created` is either 0 (true replay) or 11 (first run on a dev with no children yet); record which scenario
       - Lineage walk passes (children's parent[] = expected stub UUIDs, no duplicates)
       - Process exits 0
    5. Author `.planning/notes/2026-05-DD-phase-51-live-fire.md` (DD = actual date of run) with:
       - Pre-flight state (stub UUIDs, dev asset count before)
       - Full stdout of the script
       - Tally object
       - Lineage walk verdict
       - Post-flight state (dev asset count after)
       - Verdict: PASS / FAIL with reason
    6. Commit the receipt:
       ```bash
       git add .planning/notes/2026-05-DD-phase-51-live-fire.md
       git commit -m "docs(51-06): live-fire UPSERT-07 attestation receipt — <verdict>"
       ```
    7. If FAIL: do NOT mark this checkpoint approved. Report the failure to the orchestrator so root-cause analysis can run before re-attempting.
  </how-to-verify>
  <resume-signal>Type "approved" with the path to the committed receipt, OR describe the failure mode.</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| live-fire script → dev farmOS | real-network write side-effects against dev tenant |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-51-12 | Tampering | live-fire run against prod by mistake | mitigate | env-var contract requires explicit FARMOS_URL; default-unset; checkpoint instructs dev URL; receipt records URL used |
| T-51-13 | DoS | live-fire creates runaway duplicates if upsert silently fails | mitigate | tally + duplicate-id check + lineage walk all gate process.exit(1); script never auto-cleans, leaves audit trail |
</threat_model>

<verification>
- Receipt committed under .planning/notes/
- Tally shows patched ≥ 4
- No duplicate UUIDs in asset_ids
- Lineage walk green
</verification>

<success_criteria>
- live-fire-51.js script committed
- Dev attestation executed by human; receipt committed
- Phase 51 ship gate satisfied (UPSERT-07 acceptance criteria green)
</success_criteria>

<output>
Create `.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-06-SUMMARY.md` when done.
</output>
