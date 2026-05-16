---
date: 2026-05-16
type: discussion-prep
covers:
  - .planning/notes/2026-05-15-rambo-th-window-unscripted-run.md
  - .planning/notes/2026-05-15-lion-mane-bridged-uat.md
mode: read-only research; no code/data mutations
session: pre-discussion for v1.8 scoping
---

# farmOS no-target observations + strain coverage audit

Two real failure modes hit prod on 2026-05-15:

1. **Vikki / Rambo / TH window** -> `observation_requires_target` because the
   tropical-house greenhouse (TH) isn't a registered farmOS asset and the
   commit-router only knows about fungi assets.
2. **Santi / lion's mane / fruiting chamber move** -> `no_target_asset_for_activity`
   because NO LIMA blocks exist in prod-farmOS (the 2026-04-25 backfill
   only covered SHI/DT/WIN/KOY).

Both rejections came from mushy-side validators, not upstream farmOS.
This note splits the problem into two parts:

- **Part 1.** "Farm-level events that don't tie to any tracked asset" --
  is the schema actually requiring asset on these logs, or is the
  validator over-strict? What are the four fix options worth?
- **Part 2.** "Strain coverage gap" -- audit which strain codes have
  farmer history but no farmOS asset; propose a backfill recipe and/or
  an on-demand create-block fallback for the commit-router.

---

## Part 1: farmOS no-target / farm-level patterns

### 1.1 Is `asset` required on logs upstream?

**Verdict: NO. `asset` is an OPTIONAL multi-cardinality reference field
on every log type. The `observation_requires_target` rejection is a
mushy-side policy choice, not a farmOS schema constraint.**

Three independent lines of evidence, all read-only:

#### Evidence A: upstream farmOS source

`modules/core/log/modules/asset/src/Hook/FieldHooks.php` on
`farmOS/farmOS@4.x` registers the asset reference on logs as:

```php
$field_info = [
  'type' => 'entity_reference',
  'label' => $this->t('Assets'),
  'description' => $this->t('What assets do this log pertain to?'),
  'target_type' => 'asset',
  'multiple' => TRUE,
  'weight' => [ 'form' => 0, 'view' => 0 ],
];
$fields['asset'] = $this->farmFieldFactory->baseFieldDefinition($field_info);
```

No `'required' => TRUE` flag is set. `multiple` is true (so the field
already accepts `[]`). `LogTypeBase::buildFieldDefinitions()` is empty;
no per-bundle override marks asset required.

#### Evidence B: prod-farmOS already contains many no-asset logs

Live `GET /api/log/<type>?page[limit]=50` against prod
(http://10.68.155.50:8082) on 2026-05-16:

| log_type     | total fetched | with asset | NO asset |
|--------------|---------------|------------|----------|
| seeding      | 14            | 14         | 0        |
| harvest      | 1             | 1          | 0        |
| activity     | 30            | 2          | **28**   |
| observation  | 18            | 15         | **3**    |
| input        | 4             | 0          | **4**    |

(Asset relationship counted as 0 when `relationships.asset.data` is an
empty array.)

Examples (verbatim names + notes-prefix from the prod data):

- observation, no asset: `"Buy chaveta"`, `"Visit agrovet San Carlos rotonda"`,
  `"Call Natalia at Agrovet"` -- all tagged `"Pending task from planner."`
- activity, no asset: `"Buy food"`, `"Get cash"`, `"Buy micro tape"`,
  `"Airhood components need from Santi"` -- a mix of planner-tasks and
  free-text construction-list notes.
- input, no asset: `"Rocky -- worm medication"`, `"Rambo -- flea spray"`,
  `"Rocky -- flea spray"`, `"Rambo -- worm medication"` -- dog-medication
  entries. (Rambo here is one of the farm dogs, distinct from the goat
  that broke the TH window. Worth noting for the Phase 37 LLM-convo
  prompt-pin sweep: "Rambo" is genuinely ambiguous in the farm domain.)

So the farmOS instance not only ACCEPTS no-asset logs, it already
contains a sizeable corpus of them. Vikki's TH window draft would have
landed fine if mushy hadn't rejected it client-side.

#### Evidence C: our own commit modules already handle the missing-asset case as a soft path on seeding

`src/agents/alerter/src/farmos/commits/commit-seeding.js` lines 26-58
treat "no QR resolves" as **Path A: create the block from scratch**
rather than rejecting. Only observation / activity / input bail on
zero-asset, and harvest fails differently (`missing_source_block`).
There's no architectural reason observation has to be the strict one.

### 1.2 What's the canonical "farm-level log" pattern?

farmOS doesn't have a first-class "farm-level log" type. The convention
is just: omit (or empty) the asset relationship. The relationship key
needs to be PRESENT in the payload but `data` can be `[]`:

```json
{
  "data": {
    "type": "log--observation",
    "attributes": { "name": "...", "timestamp": 1778..., "status": "done", "notes": {...} },
    "relationships": { "asset": { "data": [] } }
  }
}
```

Our `farmos/logs.js:createLog` already constructs this shape -- line 32
emits `asset: { data: assetIds.map(...) }`, which produces `data: []`
when assetIds is empty. The HTTP call would succeed. **The only thing
in the way is the early-return at commit-observation.js:23 and
commit-activity.js:27 / commit-input.js:22.**

### 1.3 Fix-option assessment

Lifting the Rambo note's four options out and pricing each against the
evidence above.

#### Option A: farm-level observation fallback

**Sketch:** when zero QRs resolve, post the log anyway with
`asset.data: []` rather than returning `observation_requires_target`.
Generalize to activity + input.

**Files touched:**

- `src/agents/alerter/src/farmos/commits/commit-observation.js`
  (delete the early-return at line 22-24; pass `assetIds = []` through
  to `logs.createLog`)
- `src/agents/alerter/src/farmos/commits/commit-activity.js`
  (delete early-return line 26-28; same)
- `src/agents/alerter/src/farmos/commits/commit-input.js`
  (delete early-return line 21-23; same)
- `src/agents/alerter/src/farmos/logs.js` -- the empty-array relationship
  may need a guard: today `relationships.asset.data = []` is valid JSON:API.
  Confirmed by the prod corpus (28 activity logs with no asset present
  via the UI flow). No change needed in `createLog`.
- `test/farmos/commits/*` unit tests: add zero-QR-passes assertions.
  Today they assert the rejection reason; flip to assert HTTP 201 with
  empty asset relationship.

**Estimated complexity: S.** ~30 LOC delete + ~80 LOC test rewrite.
The hard part is the policy question, not the code.

**Open questions for farmOS team:**

- Is the convention to set `asset.data = []` or to omit the
  `asset` relationship key entirely? Both seem to work; prod
  shows farmOS UI submits `asset.data = []`. Prefer matching UI.
- For observations specifically, should we also fill `location` or
  some `tags` taxonomy field to give the log discoverable context when
  there's no asset to filter by? (Currently we leave both unset.)
- Is there a target-of-record convention for "farm-level" logs --
  e.g. a "Farm" asset or `tags` term tagged `farm-level` -- that the
  farmOS team uses elsewhere for reporting?

#### Option B: register non-fungi assets (greenhouses, structures, animals)

**Sketch:** add support for `asset--structure` (or whatever bundle the
farmOS team standardizes on) so TH resolves to a real asset. Same
pattern as the fungi bundle but without the fungi_type/fungi_xing
required-relationship cost.

**Files touched:**

- New `src/agents/alerter/src/farmos/structures.js` mirroring
  `assets.js` (find-by-name, create, cache).
- `src/agents/alerter/src/farmos/qr.js` -- broaden `resolveQr` to look
  across multiple asset bundles, OR add a parallel `resolveStructureQr`.
- Phase 38 extractor -- needs a new asset_class hint
  (fungi | structure | animal | other) on the draft so the router
  knows which bundle to query.
- `commit-router.js` -- dispatch by `asset_class` not just `log_type`.
- prod-farmOS -- needs farmOS-team-side schema work to expose the
  structure (and animal?) bundles via JSON:API, plus initial seed of
  greenhouse / shed / animal records. Same kind of conversation as
  the 2026-05-14 fungi-type reply note triggered for fungi.

**Estimated complexity: L.** This is a v1.9 conversation, not a
same-week fix.

**Open questions for farmOS team:**

- Does the farmOS instance already have a structure bundle? Land bundle?
- What's the per-bundle taxonomy expectation? (fungi requires
  fungi_type + fungi_xing; presumably structures wouldn't have those
  constraints, but the lesson from 2026-05-14 is to not assume.)
- For animals like Rambo-the-goat, is there a `livestock` bundle?
- Naming conventions for ad-hoc structures -- "TH", "tropical-house",
  "greenhouse-1"?

#### Option C: farmer-facing nudge

**Sketch:** when the commit would fail because no asset resolved,
reply to the farmer: "couldn't match that to a block/structure I
know about. Log as a farm-level note instead? (yes/no)". On yes,
commit with empty asset.data (Option A).

**Files touched:**

- `src/agents/alerter/src/farmos/commits/commit-watchdog.js` or
  the receive-loop -- on terminal `observation_requires_target`,
  enqueue a farmer-facing prompt instead of dropping silently.
- `src/agents/alerter/src/farmos/preview-builder.js` (probable
  location of the prompt template).
- Receive-loop YES/NO handling: needs a new state
  `awaiting_farm_level_confirmation` distinct from `awaiting_farmer`,
  because the question is downstream of the EDIT loop. OR repurpose
  the existing askback machinery with a new tag.

**Estimated complexity: M.** Most of the cost is the new state in the
draft state machine. The prompt + commit-with-empty-asset is small.

**Open questions:**

- Do we want C without A (ask, then route to a structure asset)? That
  raises the same B problem -- you need somewhere for the log to go
  besides farm-level.
- C bundled with the existing "Finding 3 commit_failed silence" fix --
  same surface, same code path? The Rambo note explicitly recommends
  bundling these.
- What's the farmer-language phrasing? "block ID" failed for Santi
  (Finding 1d, "I dont understand what asset_ref means"). For C the
  prompt is even further from farmer vocabulary -- "no asset matched"
  is jargon. Probably needs to be something like "I couldn't tell
  which block this is about. Save it as a general note? (yes / no)".

#### Option D: defer scope

**Sketch:** keep mushroom-only, tell farmers explicitly that the bot
only logs mushroom events, document the limitation.

**Files touched:**

- `src/agents/alerter/src/farmos/preview-builder.js` -- add a "this
  channel handles mushroom events only" reply when the extractor
  emits log_type=observation with no qr_codes that resolve.
- Phase 38 extractor prompt -- could be tightened to refuse to draft
  for non-mushroom events. But this just pushes the failure earlier.

**Estimated complexity: S.** But the cost is paid in farmer trust:
they tried, they got told no, they route around the bot. Memory
`feedback_no_farmer_bookkeeping_tax` warns explicitly against this --
farmers will send what they send and the tool needs to absorb it.

**Open questions:**

- How do farmers route the not-a-mushroom-event observations today?
  (Vikki's image-with-caption was the only path she had.) If we say
  no, where does she put it?

### 1.4 Recommendation

**Recommend Option A + Option C in the same patch, with B reserved
for v1.9 when the structure/animal bundles get farmOS-side schema work.**

Concretely:

1. Delete the three early-returns in commit-observation/activity/input.
   When zero assets resolve, post the log with `asset.data = []`.
   (Option A.)
2. Add a farmer-facing acknowledgment on the success path: "Saved as
   a general farm note since I couldn't match a specific block."
   This is more honest than silently treating a farm-level log as
   equivalent to a fungi log, and gives the farmer a chance to
   correct it via a follow-up (which the EDIT loop now supports).
3. Patch the NORTH-STAR violation (Finding 3 from the Rambo note) at
   the same time: commit_failed terminal state MUST emit a farmer-facing
   reply, period.

Option D is unacceptable per `feedback_no_farmer_bookkeeping_tax`.
Option B is v1.9.

The combined patch is small enough (estimate: 200 LOC including
tests + state machine update) to ship same-week, not v1.8. It
also makes the Vikki/Rambo case land correctly without any farmOS-side
schema change.

---

## Part 2: strain coverage gap audit

### 2.1 Coverage matrix

Sources:

- prod-farmOS `GET /api/asset/fungi?page[limit]=200`
  (18 assets total; 17 blocks + 2 bags + 1 unnamed-strain SHI test asset)
- prod-farmOS `GET /api/taxonomy_term/fungi_type` (14 terms)
- timescale `signal_capture` (64 rows) and `signal_draft` (29 rows)
  via case-insensitive regex on raw_text || transcript || draft_json::text

| Strain | fungi_type term in prod? | # blocks in prod (asset--fungi, xing=block) | Most recent block | Captures mentioning strain | Drafts mentioning strain |
|--------|--------------------------|---------------------------------------------|-------------------|----------------------------|--------------------------|
| SHI    | yes (`6c78411b`)         | 6 (5 dated `260425`, 1 `SHI-260425-1`)      | 2026-05-14T18:54:51 | 7 (incl. "shiitake" mentions) | 8 |
| SH2    | yes (`dbd8da73`)         | 0                                           | n/a               | 0                          | 0                        |
| KOY    | yes (`1c3ba431`)         | 2                                           | 2026-05-14T18:54:22 | 0                          | 2                        |
| MAI    | yes (`6d466ba6`)         | 0                                           | n/a               | 0                          | 0                        |
| MALI   | yes (`83de45b3`)         | 0                                           | n/a               | 0                          | 0                        |
| KOS    | yes (`12fc3209`)         | 0                                           | n/a               | 0                          | 0                        |
| DT     | yes (`1f269eeb`)         | 5 (3 blocks `260425_DT_9..11`, 1 smoke `260514_DT_998`, 2 bags) | 2026-05-14T18:54:50 | 0 | 8 |
| CAS    | yes (`a9f27ca0`)         | 0                                           | n/a               | 5 (incl. "chestnut") -- Vikki harvest msgs | 2 |
| CAZ    | yes (`07243cea`)         | 0                                           | n/a               | 0                          | 0                        |
| WIN    | yes (`57351384`)         | 3                                           | 2026-05-14T18:54:23 | 0                          | 3                        |
| ALM    | yes (`24d5e313`)         | 0                                           | n/a               | 0                          | 0                        |
| MOR    | yes (`1a3757ad`)         | 0                                           | n/a               | 0                          | 0                        |
| BP     | yes (`caa5b55f`)         | 0                                           | n/a               | 0                          | 0                        |
| LIMA   | yes (`12c82ef3`)         | 1 (`260415_LIMA_1`, operator-bridged 2026-05-15) | 2026-05-15T23:46:47 | 1 ("lion's mane" via Santi audio capture) | 1 |

Notes:

- All 14 active strain codes from `project_mossrock_active_strain_codes`
  ARE seeded as fungi_type terms (2026-05-13 farmOS-side seeding lift
  appears to have run). The schema vocabulary is complete.
- Block-level coverage is the gap: 4 strains have blocks (SHI / KOY /
  DT / WIN + the operator-bridged LIMA = 5), 9 strains have zero
  blocks despite being in the active-strain memory.
- The `SHI-260425-1` is the dev/test fungi asset from before the
  paper-log backfill -- predates the convention. Cosmetic; ignore.
- The two `HBATCH-2026-05-14-DT-001-bag-{1,2}` are harvest bags
  (xing=fruit) from Phase 40 smoke, parent=DT block.
- Farmer history hit on **5 strains: SHI, KOY, DT, WIN, CAS, LIMA**.
  Of these only CAS lacks any block (chestnut showed up 5 times in
  Vikki's harvest captures -- "CAS 200g from fruiting chamber block,
  ID unknown" -- yet no chestnut block has ever been registered;
  guaranteed to trip the same failure mode if she tries to log
  a CAS harvest through the bot in its current state).

### 2.2 What broke for each gap

For any strain in the table with `# blocks = 0`, ANY Signal-channel
event referencing it will hit `no_target_asset_for_*`:

- activity (move/relocate/check): `no_target_asset_for_activity`.
  Reproduces Santi's LIMA case.
- input (substrate amendment, etc.): `no_target_asset_for_activity`
  (sic; commit-input uses the same reason code as activity).
- observation: `observation_requires_target`. Reproduces the Vikki case
  for the strain-scoped version.
- harvest: `missing_source_block`. Vikki's CAS harvest message
  (`01KRGY702WWYPE4ADVJD3AG0H3`) would terminate here on commit
  attempt. (It hasn't been confirmed yet; the draft sits earlier in the
  pipeline.)
- seeding: would self-recover via Path A (creates the block), so this
  is the ONE log type where a missing strain block isn't a blocker.
  Caveat: Path A still requires `block_name` and `strain` in the
  draft_json; Phase 38 extractor must fill them.

### 2.3 Backfill sweep approach

**Recipe per strain with farmer-history-but-no-prod-asset:**

For each strain in {CAS, plus any others farmers reference in the
next 7 days} that has no `asset--fungi` of xing=block:

1. Operator (mushy-side) issues a single direct POST to prod-farmOS
   creating a placeholder block:

   ```json
   {
     "data": {
       "type": "asset--fungi",
       "attributes": {
         "name": "PLACEHOLDER_<strain>_1",
         "status": "active",
         "notes": { "value": "Placeholder block created to absorb farmer events before a real seeding log was committed. Created by: mushy-bot operator. See: .planning/notes/2026-05-16-farmos-no-target-and-strain-coverage.md", "format": "plain_text" }
       },
       "relationships": {
         "fungi_type": { "data": [{ "type": "taxonomy_term--fungi_type", "id": "<term-uuid>" }] },
         "fungi_xing": { "data": [{ "type": "taxonomy_term--fungi_xing", "id": "f5fbb8e0-33d8-46b7-a309-d03d3daa2672" }] }
       }
     }
   }
   ```

   `fungi_xing=block` UUID is `f5fbb8e0-33d8-46b7-a309-d03d3daa2672`
   per the 2026-05-15 LIMA bridge work.

2. Audit trail: same convention Santi used for LIMA -- preserve the
   `260415_LIMA_1` style name; the placeholder name `PLACEHOLDER_<strain>_1`
   makes it explicit so the farmOS team can sweep these later. Notes
   field carries the provenance trailer.

3. The id_tag (QR) field stays empty: no QR sticker exists yet. When
   the farmer eventually says "logged 5 jars in tent A, inoculation
   today, strain CAS" or scans a sticker, the seeding-Path-A logic
   creates the REAL block and the placeholder remains as the
   ledger-of-record for any earlier observations/activities that
   landed on it. (If we want, a v1.8.x "merge placeholder into real
   block" sweep can collapse them later -- not for the same-week
   patch.)

**Risk / rollback story:**

- Risk: a placeholder block accumulates logs that should really
  attach to a specific QR-labelled block once that block exists.
  Mitigation: the placeholder name is grep-able (`^PLACEHOLDER_`)
  and a future sweep can re-parent the logs.
- Risk: the farmer never confirms the strain identity correctly and
  we accumulate noise on the wrong placeholder. Mitigation: the
  edit-loop already lets the farmer correct strain; misroutes are
  recoverable.
- Rollback: archive (status: archived, not delete) any
  placeholder block that turns out to be wrong; the linked logs
  remain attached. farmOS soft-delete semantics handle this.

**Estimated effort:** ~30 minutes operator-side to write the
sweep script + run once. Most of the cost is deciding the
naming/notes convention and getting farmOS-team sign-off on the
PLACEHOLDER_ prefix. No code change in mushy.

### 2.4 Create-on-demand fallback in commit-router

**Sketch:** add a pre-step that auto-creates a fungi asset when the
QR / asset_ref doesn't resolve to anything, for activity / observation
/ input log types. Today this works ONLY in commit-seeding (Path A).

**Pre-step logic:**

```
if log_type in {activity, observation, input} and no QR resolves:
  if dj.strain is set:
    # we have enough to create a placeholder block
    name = "PLACEHOLDER_" + dj.strain + "_" + <short-suffix>
    block = assets.createFungiAsset(client, {
      name, fungiTypeName: dj.strain, fungiXingName: 'block', draftId
    })
    assetIds = [block.id]
    # mark log notes with auto-create provenance
  else:
    # no strain identified; can't create -- fall through to Option-A
    # farm-level fallback (empty asset.data)
```

**Inferred fields:**

- `name`: `PLACEHOLDER_<strain>_<unix>` (deterministic; unique by time).
- `fungiTypeName`: from `dj.strain` / `dj.fungi_type` / `dj.species_code`.
- `fungiXingName`: hardcoded `block` (we don't auto-create bags/fruits;
  fruits only come from harvest paths).
- `notes`: `"Auto-created placeholder block. Source draft: mushy:draft:<id>. Strain inferred from <field>=<value> (confidence=<c>)."`

**Confidence gate:**

- Phase 38 emits `per_field_confidence` per draft. Read
  `per_field_confidence.strain` (or `.species_code`) and refuse to
  auto-create if confidence < 0.7. Fall through to Option A.
- Cross-check: if `dj.strain` came from `asset_ref` parsing rather than
  an explicit strain field, treat as low confidence regardless.

**Rollback story if the inference is wrong:**

- Auto-created blocks have `PLACEHOLDER_` prefix -- discoverable.
- Notes field carries the inference provenance, including which
  draft_id triggered it; the operator can grep:
  ```
  GET /api/asset/fungi?filter[name][operator]=STARTS_WITH&filter[name][value]=PLACEHOLDER_
  ```
- A farmOS-side action can `status: archived` the wrong placeholder
  and re-parent its logs (manual today, scriptable in v1.8.x).

**Open questions:**

- Where does the strain come from on an *observation*? Today
  extractor schema doesn't require strain on observations. Probably
  the right move is: try, fall through to farm-level if absent.
- Should auto-create be a per-farmer policy, an org-wide setting,
  or always-on? Probably always-on but with the confidence gate;
  the farmer can edit the strain via the EDIT loop if wrong.
- Auditing: should auto-create be logged to `signal_draft_event`
  as a new event_type `auto_create_placeholder`? Yes; same pattern
  as `commit_attempt`. Cost is one line.

**Files touched:**

- `src/agents/alerter/src/farmos/commits/commit-router.js` -- new
  pre-step calling `_maybeAutoCreatePlaceholder`. ~25 LOC.
- `src/agents/alerter/src/farmos/assets.js` -- already has
  `createFungiAsset`. No change.
- `src/agents/alerter/src/farmos/commits/commit-observation.js`,
  `commit-activity.js`, `commit-input.js` -- accept passed-in
  assetIds rather than always doing their own QR resolution OR
  the pre-step mutates `draft.draft_json.qr_codes`. Prefer the
  former for cleanliness.
- `src/agents/alerter/src/farmos/audit-logger.js` -- new
  `auto_create_placeholder` event.
- Tests: new fixture for auto-create-success and confidence-gate-blocks.

**Estimated complexity: M.** ~150 LOC + tests.

### 2.5 Recommendation: hybrid

**Recommend a hybrid: one-shot backfill sweep now (Part 2.3) + the
auto-create fallback in commit-router (Part 2.4) shipped same-week.**

Reasoning:

- The backfill sweep is the surgical fix for **known** strain gaps
  (CAS especially, since Vikki has been pinging chestnut harvests
  for weeks). Operator pays the audit-trail cost ONCE; runtime
  loop never sees those failures.
- The auto-create fallback is the structural fix for **unknown**
  future strain mentions. Without it, we re-enter the same bridged-UAT
  loop every time a strain appears that wasn't in the original
  backfill set.
- Together they cover the "no LIMA blocks in prod" failure mode
  surfaced in the bridged-UAT note -- Santi's lion's mane move
  would have either landed on the placeholder LIMA block (if seeded
  already) or auto-created one with the strain extracted from the
  transcript ("Two days ago, I put a lion's mane block into the
  fruiting chamber"; `lion's mane` -> LIMA mapping in the
  extractor; confidence high).

**Bundled with Part 1's recommendation (A+C):**

A single same-week patch could ship:

1. Empty-asset commit paths for observation/activity/input (Part 1 / A)
2. Farmer-facing commit-failed reply (Rambo Finding 3)
3. Auto-create-placeholder pre-step in commit-router (Part 2.4)
4. Operator-side backfill sweep run as a one-shot, with the
   `PLACEHOLDER_<strain>_1` convention captured in a runbook
   under `.planning/phases/40-farmos-write-path/40-PLACEHOLDER-SWEEP.md`
5. Telemetry: new audit-log event types for `farm_level_commit` and
   `auto_create_placeholder` so the next backfill audit is grep-able.

Estimated combined size: ~400 LOC + ~300 LOC tests + one one-shot
script. Smaller than Phase 40 itself was.

---

## Cross-cutting observations

### A. The "no asset" / "wrong strain" failures share one root cause

Both failure modes are the same thing seen from different angles: the
commit-router insists on a registered fungi asset for every non-seeding
log, but the asset population is sparser than the event stream.
Lifting the "fungi-only" constraint (Part 1) and densifying the asset
population (Part 2) are independent levers; both are required to make
the bot useful for the events farmers actually send.

### B. fungi_type vocabulary is complete; xing is hard-coded

All 14 strain codes from `project_mossrock_active_strain_codes` exist
as fungi_type taxonomy terms in prod. The blocker isn't vocabulary;
it's the **block-tier asset** layer that's behind. Suggests the auto-create
pre-step is safe (no risk of "strain term doesn't exist" failure).

`fungi_xing=block` is hardcoded for auto-creates because there's only
one structural classifier that makes sense for a placeholder. fruit
assets come from harvest commit paths only.

### C. The 2026-05-15 LIMA bridge is the template

The operator-bridged LIMA block (`260415_LIMA_1`, uuid
`e0be0952-e77b-4316-8be6-28abdc62b134`) is exactly what an auto-create
would have produced, just routed through the operator's hands. The
backfill sweep should mirror its shape: name `<yymmdd>_<strain>_N` for
manually-seeded, `PLACEHOLDER_<strain>_<unix>` for auto-created so we
can tell them apart.

### D. Bot user `mushy-bot` has the necessary write scope

Confirmed via session cookie + the LIMA bridge succeeding. No farmOS-side
permission work needed for the same-week patch.

### E. Drafts with strain mentions vs captures with strain mentions diverge

Drafts had `DT=8` mentions but captures had `DT=0`. This is because the
DT strain code appears in extracted draft_json (e.g. from the 2026-04-25
inoc sheet OCR extraction) but never came up in Signal text/audio
transcripts. SHI and CAS show the opposite pattern -- they came up in
farmer messages well before any inoc-sheet extraction. The auto-create
pre-step should use whichever surface has the strain, not require both.

### F. "Rambo" is a real ambiguity in the farm domain

The prod input logs include `"Rambo -- worm medication"` and
`"Rocky -- worm medication"` -- the farm has at least two dogs whose
names blur with the goat that broke the window. Phase 37 LLM-convo
prompt-pin (Finding 1c+1d) should include a glossary of known farm
animals, not just block IDs. This is downstream of the no-target work
but related.

---

## Open questions to discuss

1. **Same-week patch or v1.8 scope decision?** Recommendation says
   same-week (400 + 300 LOC); Don Santiago to ratify.
2. **Backfill sweep naming convention.** `PLACEHOLDER_<strain>_1` vs
   reuse the `<yymmdd>_<strain>_N` shape from the 2026-04-25 backfill.
   The former is grep-able and self-documenting; the latter is
   uniform with what exists.
3. **Auto-create confidence threshold.** Default 0.7? Tune higher
   (0.85) for first month then relax as we calibrate?
4. **Farmer-facing language for the "saved as farm note" path.**
   Probably needs farmer-language wording on par with the 1d jargon
   fix. Spanish + English variants.
5. **farmOS team coordination for Option B (structures / animals).**
   v1.9 ticket to file now, or wait for the third unscripted event
   that hits this gap?
6. **Should auto-create also fire for the harvest path?** Today
   `missing_source_block` is terminal. If a farmer sends "harvested
   200g of CAS from fruiting chamber block ID unknown" (which Vikki
   literally did, capture `01KREQB2M3QM8BWW80FM0BTKEW` context), we
   could auto-create a CAS block and parent the bags to it. Less
   correct (no real source block) but recoverable later via the
   placeholder re-parent sweep.
7. **Re-parenting tooling.** The placeholder cleanup story assumes we
   can re-parent logs from PLACEHOLDER_X_1 to REAL_X_QR_3 later. Is
   that a farmOS-side capability or do we need to ship a re-parent
   tool? (PATCH on log relationships should work via JSON:API but
   needs verification.)

---

## Artifacts referenced

- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commits/commit-observation.js:22-24`
  -- early-return to delete for Option A
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commits/commit-activity.js:26-28`
  -- same
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commits/commit-input.js:21-23`
  -- same
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commits/commit-seeding.js:26-58`
  -- Path A reference implementation for the auto-create pre-step
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/assets.js:53-101`
  -- `createFungiAsset` primitive the pre-step would call
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commits/commit-router.js`
  -- where the pre-step inserts (before `DISPATCH[logType]`)
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/logs.js:32`
  -- already emits `asset.data = []` when assetIds is empty; no change needed
- farmOS upstream: `farmOS/farmOS@4.x:modules/core/log/modules/asset/src/Hook/FieldHooks.php`
  -- canonical proof asset field is optional + multiple
- Prod-farmOS data probed read-only:
  - 18 fungi assets via `GET /api/asset/fungi?page[limit]=200`
  - 14 fungi_type terms via `GET /api/taxonomy_term/fungi_type`
  - 67 logs (14 seeding / 1 harvest / 30 activity / 18 observation / 4 input)
    via `GET /api/log/<type>` per bundle
- Timescale read-only:
  - 64 signal_capture rows; 29 signal_draft rows
  - Per-strain regex counts in Part 2.1

EOF -- pick up in discussion session.
