# 43-FIXTURES.md -- Phase 43 Test Fixture Sources

**Purpose:** Authoritative fixture documentation for Plan 43-05 chain integration tests.
**D-16 mandate:** Test 2 (activity-relocate, the 2026-05-15 regression guard) MUST use the real captured transcript, not a paraphrase.

---

## Verbatim transcript (Whisper output, 2026-05-15 23:30:51 UTC)

```
Two days ago, I put a lion's mane block into the fruiting chamber to fruiting Two days ago forgot to tell to tell you so yeah log it up Lion
```

**Source:** `.planning/notes/2026-05-15-lion-mane-bridged-uat.md` line 25 (Timeline table row, UTC column 23:30:51)
**Speaker:** Santi (f1, +59892893012)
**Draft ID:** `1fb28e709118807ed301b4c3b45f5042f194eabb9ab0000f288e9163fec93733`
**Audio capture ID:** `01KRPZMZ79370J0YQM9SKTWJZ2`

This is the audio note Santi sent about moving a lion's mane block to the fruiting chamber. Whisper transcription is verbatim -- including the repetition ("Two days ago" appears twice) and the trailing incomplete word ("Lion"). The extractor receives this exact text as farmer input.

---

## Phase 38 extractor output (live, 2026-05-15 23:30:57 UTC)

Per bridged-uat note line 26 (Timeline table row, UTC column 23:30:57):

```json
{
  "log_type": "activity",
  "name": "relocate",
  "asset_ref": "<UNKNOWN>",
  "event_timestamp": "2026-05-13T00:00:00Z",
  "conf": {
    "asset_ref": 0.0,
    "event_timestamp": 0.6
  }
}
```

**Notes:**
- `asset_ref: "<UNKNOWN>"` -- the audio says "lion's mane" but no specific block ID appears in the speech. Extractor correctly returns the UNKNOWN sentinel.
- `event_timestamp: "2026-05-13T00:00:00Z"` -- "two days ago" from 2026-05-15, conf 0.6.
- `name: "relocate"` -- activity name inferred from "put ... into the fruiting chamber".

---

## EDIT-loop message (2026-05-15 23:31:54 UTC) -- preview-jargon complaint

```
I dont understand what asset-ref means. Please speak in farmer to me.
```

**Source:** `.planning/notes/2026-05-15-lion-mane-bridged-uat.md` line 27 (Timeline table row, UTC column 23:31:54)

**IMPORTANT -- do NOT include this EDIT in Test 2's fixture chain.**

This EDIT was a preview-readability complaint (finding 1d: jargon in farmer-facing preview), NOT a correction that provides the missing asset ref. The extractor, when re-run with this as `farmerCorrection`, would still produce `asset_ref: "<UNKNOWN>"` because the farmer still has not named a specific block ID. Including this EDIT would add noise to the regression guard without changing the commit outcome.

The actual asset ref `260415_LIMA_1` came from the **operator bridge at 23:46:30**, well after farmer YES -- not from the farmer's EDIT.

---

## Asset ref provenance (operator bridge, 2026-05-15 23:46:30 UTC)

Per bridged-uat note lines 32-34:

- **No LIMA blocks existed in prod-farmOS at the time of the commit attempts.** Only SHI/DT/WIN/KOY were present from the 2026-04-25 paper-log backfill.
- Operator created LIMA block `260415_LIMA_1` (uuid `e0be0952-e77b-4316-8be6-28abdc62b134`) via direct farmOS POST at 23:46:30.
- Operator then manually reshaped draft_json: `qr_codes=["LIMA-260415-1"]`, `activity_subtype="relocate"`, `timestamp=1778630400`. Cleared `asset_ref` and `event_timestamp` ISO fields.
- After reshape, watchdog retry succeeded: commit_success HTTP 201, log uuid `92632908-e88c-4480-a04a-cbac4ffce999`.

The reshape the operator performed manually is exactly what normalize.js will automate.

---

## Test 2 fixture recipe

### Input to the chain

Feed this single farmer message through the chain (no EDIT):

```
Two days ago, I put a lion's mane block into the fruiting chamber to fruiting Two days ago forgot to tell to tell you so yeah log it up Lion
```

### Option A: Commit-failure path (regression guard -- canonical Test 2)

**What it tests:** The normalizer translates extractor-shape to commit-shape cleanly; the commit router then fails with a CLASSIFIABLE reason (`no_target_asset_for_activity`) instead of dying on a schema mismatch earlier.

**Chain assertions:**

1. **Post-extract shape** (extractor-shape markers present):
   - `draft_json.log_type === 'activity'`
   - `draft_json.name === 'relocate'`
   - `draft_json.asset_ref === '<UNKNOWN>'`
   - `draft_json.event_timestamp` matches ISO string around `"2026-05-13T00:00:00Z"` (or similar two-days-ago value)

2. **Post-normalize shape** (commit-shape markers present):
   - `normalized.draft_json.activity_subtype === 'relocate'` (renamed from `name`)
   - `normalized.draft_json.qr_codes` deep-equals `[]` (asset_ref `<UNKNOWN>` filtered by D-03 common transform)
   - `normalized.draft_json.timestamp` is a number (unix seconds, floor of event_timestamp)
   - `normalized.draft_json.asset_ref` is ABSENT or undefined (removed by normalizer)

3. **Post-commit outcome:**
   - `commit_success === false`
   - `commit_failed_reason === 'no_target_asset_for_activity'`

**Why this is the regression guard:** Before normalize.js, commit-activity crashed on the schema mismatch (wrong field names) before it could classify the failure. After normalize.js, it reaches the `no_target_asset_for_activity` check cleanly. The test distinguishes "mismatch crash" from "classifiable failure."

### Option B: Happy-path with synthetic LIMA block

**What it tests:** Full commit_success path, but requires a modification to the input.

**Constraint:** The lion's-mane audio produces `asset_ref: "<UNKNOWN>"` because the farmer never named a specific block ID. After normalize, `qr_codes: []`, which means commit-activity cannot resolve a target regardless of what assets exist in mock-client.

**Viable approach for Option B:** Write a SEPARATE Test 2b with a SYNTHETIC audio message that DOES contain a parseable asset ref (e.g., "I moved block 260415_LIMA_1 to the fruiting chamber two days ago"), seed mock-client with a LIMA asset (`id_tag: 'LIMA-260415-1'`), and assert `commit_success: true`. This proves the normalize -> commit happy path works for activity/relocate, but uses synthetic input (not the real transcript).

**Recommendation:** Use Option A as the canonical Test 2 regression guard. Option B is a separate test using synthetic data -- it does not satisfy D-16 and should not be labeled as the "2026-05-15 regression guard."

---

## Prod corpus search results

Searches performed 2026-05-16:

**1.** `ls /mnt/mossrock/shared/mushdatadump-prod/ | grep -i "2026-05-15|lion|mane|santi"`
Result: No match. Only `2026-05-12_inoc_santi`, `2026-05-13_backlog_unprocessed`, and milestone audit files present.

**2.** `find /mnt/mossrock/shared/mushdatadump-prod/ -path '*2026-05-15*' -type f`
Result: No output. No session capture exists for 2026-05-15.

**3.** `grep -rln "lion" /mnt/mossrock/shared/mushdatadump-prod/`
Result: No output. No files in the prod corpus reference "lion".

**4.** `grep -rln "1fb28e709118807ed301b4c3b45f5042f194eabb9ab0000f288e9163fec93733" /mnt/mossrock/shared/`
Result: No output. The draft ID is not present in any corpus file.

**5.** `grep -rln "lion" .planning/milestones/v1.7-findings/`
Result: Directory does not exist (`v1.7-findings/` is not present under `.planning/milestones/`).

**Conclusion:** Prod corpus does NOT preserve a session capture for the 2026-05-15 lion's-mane event. The bridged-uat note (`.planning/notes/2026-05-15-lion-mane-bridged-uat.md`) is the **authoritative and sole source** for the verbatim transcript. This is acceptable per D-14: chain tests use a mocked Anthropic responder, not the Phase 38 eval corpus. The bridged-uat note preserves the transcript verbatim at line 25 (Timeline table), which is sufficient for Plan 43-05 to build the fixture.

No escalation required: the transcript is findable and cited above.

---

## Extractor mock recipe (for Plan 43-05 test author)

Since the chain test mocks the Anthropic responder (D-14), configure the mock to return the Phase 38 extraction result for the lion's-mane audio. Based on live behavior at 23:30:57:

```js
// Mock LLM response for the lion's-mane audio input
mockAnthropicResponse({
  log_type: 'activity',
  name: 'relocate',
  asset_ref: '<UNKNOWN>',
  event_timestamp: '2026-05-13T00:00:00Z',
  // Include conf fields if the extractor schema requires them
});
```

Cross-reference `src/agents/alerter/src/extraction/schemas/activity.js` for the full Zod shape to ensure the mock response satisfies all required fields.

---

*Documented: 2026-05-16*
*Source authority: `.planning/notes/2026-05-15-lion-mane-bridged-uat.md`*
*Plan: 43-04*
