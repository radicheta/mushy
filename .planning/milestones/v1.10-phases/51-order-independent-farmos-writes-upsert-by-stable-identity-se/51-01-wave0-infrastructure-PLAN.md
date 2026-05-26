---
phase: 51
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agents/alerter/test/farmos/mock-client.js
  - src/agents/alerter/src/farmos/client.js
  - src/agents/alerter/src/farmos/audit-logger.js
  - src/agents/alerter/test/farmos/audit-logger.test.js
  - src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json
  - .planning/notes/2026-05-XX-phase-51-notes-roundtrip-probe.md
autonomous: false
requirements: [UPSERT-04, UPSERT-06]
must_haves:
  truths:
    - "mock-client exposes patch(), delete(), and GET-by-id"
    - "mock-client can return 412-then-200 on PATCH for a configured asset id"
    - "client.js _doFetch merges opts.headers onto default headers"
    - "audit-logger.logCommit emits outcome, conflicts, etag_source fields"
    - "multi-parent-inoc-trio.json fixture exists and parses"
    - "dev farmOS notes round-trip preserves '\\n---\\n' byte-identical (checkpoint receipt)"
  artifacts:
    - path: "src/agents/alerter/test/farmos/mock-client.js"
      provides: "extended factory with patch, delete, GET-by-id, 412 protocol"
      contains: "patch:"
    - path: "src/agents/alerter/src/farmos/audit-logger.js"
      provides: "payload with outcome/conflicts/etag_source"
      contains: "etag_source"
    - path: "src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json"
      provides: "May-22 + Jan-18 + Mar-04 trio for property tests"
  key_links:
    - from: "audit-logger.js payload"
      to: "audit-logger.test.js key-count assertion"
      via: "16 named keys (was 13)"
      pattern: "Object.keys.*length.*16|16 named keys"
---

<objective>
Front-load every Wave-0 enabling change so subsequent waves can build and test in isolation. Extends test infra (mock-client), transport plumbing (client.js opts.headers), observability surface (audit-logger payload), and ships the property-test fixture. Also runs a manual `curl` probe against dev farmOS to attest that `notes` field `\n---\n` separator survives Drupal text-field normalization byte-identical — this gates the merge dedup logic in Plan 02.

Purpose: Plans 02-05 depend on all four surfaces existing; without this the executor would have to invent them mid-wave and break parallelism.
Output: Extended mocks + transport + audit payload + fixture JSON + dev-farmOS round-trip receipt under .planning/notes/.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-SPEC.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-CONTEXT.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-RESEARCH.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-PATTERNS.md
@.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-VALIDATION.md
@.planning/notes/2026-05-24-prod-write-receipt-uuids.json
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Extend mock-client.js with patch, delete, GET-by-id, and 412 protocol</name>
  <files>src/agents/alerter/test/farmos/mock-client.js, src/agents/alerter/test/farmos/mock-client.test.js</files>
  <read_first>
    - src/agents/alerter/test/farmos/mock-client.js (full file — existing factory lines 13-87)
    - src/agents/alerter/src/farmos/client.js (lines 169-185 — real client.patch/delete signature)
    - 51-PATTERNS.md §mock-client.js (extension shape)
    - 51-RESEARCH.md §3 (front-loaded mock-client extension reasoning)
  </read_first>
  <behavior>
    - Test: factory exposes patch(path, body, opts) recording {method:'PATCH', path, body, headers}
    - Test: factory exposes delete(path, opts) recording {method:'DELETE', path}; returns {ok:true, status:204, data:null}
    - Test: GET on /api/asset/fungi/<uuid> returns the asset body from internal registry seeded via knownAssetsByName
    - Test: GET-by-id response includes attributes.drupal_internal__revision_id from registry seed
    - Test: configuring _force412 for an id makes first PATCH to that id return {ok:false, status:412} and subsequent PATCHes return {ok:true, status:200}
    - Test: patch() returns {ok:true, status:200, data:{id, type, attributes, relationships:<merged from body>}}
  </behavior>
  <action>
    Extend the factory object at mock-client.js:13-87 with three new jest.fn methods and one route addition:

    1. Add a `patch: jest.fn(async (path, body, opts) => { ... })` mirroring the existing `post` shape (lines 63-77). Push {method:'PATCH', path, body, headers: opts && opts.headers} into the calls array. Match `/api/asset/fungi/<id>` and `/api/log/<type>/<id>` via regex. Maintain a `_patched` registry keyed by id. Honor a `_force412` Set passed via factory opts: if id in set AND not yet consumed, splice id out and return _ok(412, {}); otherwise return _ok(200, {data:{id, type:'asset--fungi', attributes:{...mergedAttrs}, relationships:{...mergedRels}}}).

    2. Add `delete: jest.fn(async (path, opts) => { calls.push({method:'DELETE', path}); return _ok(204, null); })`.

    3. Extend the existing `get` regex dispatcher to match `^/api/asset/fungi/([0-9a-f-]{36})$` and `^/api/log/[a-z]+/([0-9a-f-]{36})$`. Look up the id in an internal `_byId` map populated at factory-construction time from `knownAssetsByName` (each entry needs an `id` + `attributes.drupal_internal__revision_id` seed — default revision_id = 1 if unspecified). Return the asset body wrapped as {data: asset}.

    4. Factory opts gain: `force412Ids` (array of asset ids to fail first PATCH on), `revisionIds` (map name -> revision_id integer override).

    5. Add a sibling `mock-client.test.js` covering all six behaviors above. Use Jest 29 syntax matching test/farmos/qr.test.js style.

    NEVER use node:test — Jest only (per VALIDATION.md framework correction).
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/mock-client.test.js --runInBand</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "patch:" src/agents/alerter/test/farmos/mock-client.js` returns ≥1
    - `grep -c "delete:" src/agents/alerter/test/farmos/mock-client.js` returns ≥1
    - `grep -c "force412Ids\\|_force412" src/agents/alerter/test/farmos/mock-client.js` returns ≥1
    - All six behaviors in <behavior> pass under Jest
  </acceptance_criteria>
  <done>mock-client.test.js green; new methods used by no other plan yet but available for Plans 02-05.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Plumb opts.headers through client._doFetch and extend audit-logger payload</name>
  <files>src/agents/alerter/src/farmos/client.js, src/agents/alerter/src/farmos/audit-logger.js, src/agents/alerter/test/farmos/audit-logger.test.js, src/agents/alerter/test/farmos/client.test.js</files>
  <read_first>
    - src/agents/alerter/src/farmos/client.js (lines 74-103 — _doFetch headers construction)
    - src/agents/alerter/src/farmos/audit-logger.js (full file — payload at lines 11-25)
    - src/agents/alerter/test/farmos/audit-logger.test.js (lines 28-40 — the 13-key length assertion)
    - 51-PATTERNS.md §client.js and §audit-logger.js
    - 51-CONTEXT.md §"Audit-log outcome dimension" and §"Etag-guarded PATCH" (soft-compare degrade)
  </read_first>
  <behavior>
    - Test: client.patch('/some/path', body, {headers:{'If-Match':'7'}}) results in the underlying fetch receiving 'If-Match':'7' alongside the default headers
    - Test: caller-supplied headers WIN over defaults (e.g. Accept override)
    - Test: audit-logger.logCommit({outcome:'patched', conflicts:[{field:'fungi_type'}], etag_source:'soft_compare'}) writes a payload with those three keys present
    - Test: missing outcome/conflicts/etag_source defaults to null/[]/null respectively (back-compat with non-upsert callers)
    - Test: payload now has exactly 16 named keys (was 13)
  </behavior>
  <action>
    1. In `client.js` `_doFetch` (lines 74-103), replace the hardcoded `const headers = {Accept, Cookie, 'X-CSRF-Token'}` block with `Object.assign({Accept:'application/vnd.api+json', Cookie:_session.cookie||'', 'X-CSRF-Token':_session.csrf||''}, (opts && opts.headers) || {})`. Per PATTERNS.md §client.js. This makes caller-supplied headers WIN. Note in a code comment: "Phase 51 UPSERT-04 (degraded): client honors opts.headers so callers may send If-Match. Soft revision_id compare lives at the call site (assets.js upsertFungiAsset); farmOS does not currently return 412 on If-Match mismatch (see 51-RESEARCH.md A4) but plumbing exists for future Drupal versions."

    2. In `audit-logger.js`, extend the payload object literal at lines 11-25 with three new fields AFTER `reason`, preserving alphabetical-after-reason insertion order for grep stability:
       - `outcome: result.outcome != null ? result.outcome : null` — string 'created'|'patched'|'noop'|'mixed'|null
       - `conflicts: Array.isArray(result.conflicts) ? result.conflicts : []`
       - `etag_source: result.etag_source != null ? result.etag_source : null` — 'soft_compare'|'absent'|null (NOT 'revision_id' per RESEARCH override; CONTEXT.md is corrected here)

    3. Update `audit-logger.test.js` 13-key assertion at lines ~32-35: increment to 16 keys, add 'outcome', 'conflicts', 'etag_source' to the expected key list. Add three new it() blocks: (a) outcome propagation, (b) conflicts default to [], (c) etag_source defaults to null when omitted.

    4. Add or extend `client.test.js` with one it() block confirming opts.headers reach the fetch mock and override Accept when supplied.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/farmos/audit-logger.test.js test/farmos/client.test.js --runInBand</automated>
  </verify>
  <acceptance_criteria>
    - `grep -nE "outcome|conflicts|etag_source" src/agents/alerter/src/farmos/audit-logger.js` returns ≥3 matches in payload literal
    - `grep -nE "Object.assign\\(.*opts.*headers" src/agents/alerter/src/farmos/client.js` returns ≥1 match
    - All five Jest behaviors pass
    - audit-logger.test.js key-count assertion is 16 (not 13)
  </acceptance_criteria>
  <done>opts.headers plumbed; audit payload extended; both test files green; downstream upsert plans can emit outcome/conflicts/etag_source.</done>
</task>

<task type="auto">
  <name>Task 3: Author multi-parent inoc trio fixture</name>
  <files>src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json</files>
  <read_first>
    - src/agents/alerter/test/fixtures/seeding-session-may22-commit/draft.json (existing seeding_session fixture shape — closest analog)
    - src/agents/alerter/src/farmos/commits/commit-seeding-session.js (lines 108-116 — groups parsing reveals required shape)
    - .planning/notes/2026-05-24-prod-write-receipt-uuids.json (the 4 stub ancestor UUIDs)
    - 51-PATTERNS.md §multi-parent-inoc-trio.json
  </read_first>
  <action>
    Create `src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json` with three inoc events covering the multi-parent batch shape (see project memory: N children from M>1 parents in one session):

    - Event 1: 2026-05-22 inoc — parent `260118_KOY_12` → 4 children `260522_KOY_1..4`, species KOY
    - Event 2: 2026-01-18 inoc — parents `260118_SHI_23`, `260118_SHI_26` (multi-parent) → 3 children `260118_SHI_C1..3`, species SHI
    - Event 3: 2026-03-04 inoc — parent `260304_SHI_5` → 2 children `260304_SHI_C1..2`, species SHI

    Top-level shape:
    ```json
    {
      "events": [
        {"label": "...", "event_date": "YYYY-MM-DD", "groups": [{"species":{"value":"KOY"}, "parent":{"value":"260118_KOY_12"}, "qty":{"value":4}, "child_block_names":{"value":["260522_KOY_1","260522_KOY_2","260522_KOY_3","260522_KOY_4"]}}]},
        ...
      ],
      "expected_final": {
        "asset_count": 13,
        "log_count": 9,
        "parent_lineage": {
          "260522_KOY_1": ["260118_KOY_12"],
          "260118_SHI_C1": ["260118_SHI_23","260118_SHI_26"]
        }
      },
      "stub_uuids": {
        "260304_SHI_5": "<uuid from prod-write-receipt-uuids.json>",
        "260118_SHI_23": "<uuid>",
        "260118_SHI_26": "<uuid>",
        "260118_KOY_12": "<uuid>"
      }
    }
    ```

    Use the actual stub UUIDs from `.planning/notes/2026-05-24-prod-write-receipt-uuids.json` for the four ancestors.

    File must be valid JSON, parse cleanly, and the multi-parent event MUST have len(parent.value) >= 2 OR represent parents in some array-bearing variant (consult commit-seeding-session.js groups parsing to confirm exact shape; if the current parser only accepts single parent strings, use TWO group entries in event 2's groups[] to express the multi-parent inoc as the codebase represents it today).
  </action>
  <verify>
    <automated>cd src/agents/alerter && node -e "const f=require('./test/farmos/fixtures/multi-parent-inoc-trio.json'); if(f.events.length!==3) process.exit(1); if(!f.stub_uuids['260118_KOY_12']) process.exit(2); console.log('ok')"</automated>
  </verify>
  <acceptance_criteria>
    - File parses as valid JSON
    - `events` array has exactly 3 entries
    - `stub_uuids` map contains all 4 ancestor names with non-empty UUID strings
    - `expected_final.parent_lineage` contains at least one multi-parent entry (value array length ≥ 2)
  </acceptance_criteria>
  <done>Fixture ready for Plan 05 property tests.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 4: CHECKPOINT — Dev farmOS notes round-trip probe</name>
  <what-built>
    Wave-0 enabling infra in place: mock-client extended, client.js headers plumbed, audit payload extended, fixture authored. Before merging Plan 02 (which encodes notes-dedup semantics), confirm experimentally that farmOS Drupal `notes` field preserves the `\n---\n` separator byte-identical on PATCH→GET round-trip.
  </what-built>
  <how-to-verify>
    1. Pick any existing asset on dev farmOS (e.g. one of the 4 stubs from `.planning/notes/2026-05-24-prod-write-receipt-uuids.json` if dev has them, otherwise create a throwaway).
    2. PATCH its `attributes.notes.value` to the literal string `entry_A\n---\nentry_B\n---\nentry_C`. Example:
       ```bash
       curl -u "$USER:$PASS" -X PATCH "$FARMOS_URL/api/asset/fungi/<uuid>" \
         -H 'Content-Type: application/vnd.api+json' -H 'Accept: application/vnd.api+json' \
         -d '{"data":{"type":"asset--fungi","id":"<uuid>","attributes":{"notes":{"value":"entry_A\n---\nentry_B\n---\nentry_C","format":"plain_text"}}}}'
       ```
    3. GET the same asset back. Byte-compare `data.attributes.notes.value` against the input.
    4. If byte-identical → write `.planning/notes/2026-05-XX-phase-51-notes-roundtrip-probe.md` with the receipt (curl commands, raw responses, verdict). Commit it. Type "approved".
    5. If NOT byte-identical (e.g. Drupal collapses `\n---\n`) → STOP. The merge dedup logic in Plan 02 must use whatever the round-tripped separator actually is. Document the actual round-tripped form in the receipt and report findings — Plan 02 will revise its dedup-separator constant.
  </how-to-verify>
  <resume-signal>Type "approved" with the path to the committed receipt, OR describe the actual round-tripped separator if it differs.</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| alerter → farmOS HTTP | alerter writes flow through client._doFetch into dev/prod farmOS JSON:API |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-51-01 | Tampering | client._doFetch caller-headers override | accept | opts.headers WINS over defaults by design; alerter is single-tenant single-writer; only internal callers reach _doFetch |
| T-51-02 | Information disclosure | audit-logger payload now includes conflict field values | accept | audit logs land in same store as existing payload; no new PII surface (fungi_type/fungi_xing are not sensitive) |
</threat_model>

<verification>
- All Jest tests touched by this plan pass
- Round-trip probe receipt committed to .planning/notes/
- No regressions in full farmos suite: `cd src/agents/alerter && npx jest test/farmos/ --runInBand`
</verification>

<success_criteria>
- mock-client.js exports patch, delete, GET-by-id, 412 protocol
- client.js _doFetch merges opts.headers
- audit-logger emits outcome/conflicts/etag_source (16 keys total)
- multi-parent-inoc-trio.json valid + UUIDs from prod-write-receipt
- Dev farmOS notes round-trip attested in .planning/notes/
</success_criteria>

<output>
Create `.planning/phases/51-order-independent-farmos-writes-upsert-by-stable-identity-se/51-01-SUMMARY.md` when done.
</output>
