# Phase 42 RUNBOOK -- SHI-on-Sawdust Pilot

Operator playbook for Don Santiago. Drives the SHI block lifecycle on the
dev-farmOS stack via natural Signal messages through the Phase 38 extraction
+ Phase 39 confirm + Phase 40 write pipeline.

Companion to `42-CONTEXT.md` (decisions), `42-PILOT-LOG.md` (paper trail of
the actual run), and `42-VERIFICATION.md` (ship-gate, currently
`status: human_needed`).

Style locks: no em-dashes; numerics use `fmtNum()` (1 decimal, strip trailing
`.0`, `?` for null); address operator as Don Santiago.

---

## 0. Pre-flight

Before sending the first Signal message, confirm:

```bash
# Dev-farmOS reachable
curl -sI http://10.68.155.50:18080/user/login | head -1
# Expected: HTTP/1.x 200 OK or 405

# Tools env wired (one terminal session)
export FARMOS_URL=http://10.68.155.50:18080
export FARMOS_USERNAME=<dev-account>
export FARMOS_PASSWORD=<dev-pass>

# Tool smoke (no live call yet -- just exits cleanly with --help)
node tools/farmos-current-stage.js --help
node tools/farmos-lineage.js --help
node tools/farmos-pilot-reconstruct.js --help

# Alerter container running + Signal bot reachable
docker compose ps alerter signal-cli
docker compose logs --tail 30 alerter | grep -E 'farmOS|signal|confirm'
```

If anything fails, fix before sending Signal messages. The pilot is real
biological time; do not burn a lifecycle on misconfigured plumbing.

## 0a. Dry-run rehearsal (recommended)

Phase 41 ships a synthetic-fixture corpus that mirrors every PILOT-NN message
shape. Rehearse the RUNBOOK against it before the real pilot to catch
ambiguities cheaply:

- Corpus: `src/agents/alerter/test/eval/ingestion/fixtures/synthetic/`
- Relevant fixtures: `01-seeding-text` (PILOT-02), `12-activity-cold-shock`
  (PILOT-03c), `13-activity-archive` (PILOT-05), `14-activity-contam`
  (failure mode).
- Run: `cd src/agents/alerter && npm run test:eval-ingestion`

The rehearsal does NOT write to farmOS. It validates that the message shape
flows through the extractor + scorer end to end.

---

## 1. PILOT-01 -- Sterilization batch

**Farm event:** Sterilized a batch of jars / bags (anonymous count, no QR
codes yet; per C3 individuation happens at inoc, not sterilize).

**Signal message (Don Santiago -> bot):**

```
sterilized 30 jars sawdust today
```

**Expected bot reply (Phase 39 confirm-loop):**

```
Got: sterilize 30 jars sawdust
Reply YES to write, anything else to cancel.
```

**Operator action:** Reply `YES`.

**farmOS verification:**

```bash
# No tool here -- the asset has no QR yet so no obvious lookup key.
# Search dev-farmOS for the most recent BATCH-* asset of type group:
curl -s -u "$FARMOS_USERNAME:$FARMOS_PASSWORD" \
  "$FARMOS_URL/api/asset/group?filter[name][operator]=STARTS_WITH&filter[name][value]=BATCH-&sort=-created&page[limit]=1" \
  | python3 -m json.tool
```

**Success criterion:** Response includes one `group` asset, name starts with
`BATCH-`, anonymous count visible in inventory or notes, no `farm_id_tag`
populated. Record the asset uuid in `42-PILOT-LOG.md`.

---

## 2. PILOT-02 -- Inoculation

**Farm event:** Don Santiago inoculates 1 sawdust block with SHI culture
and binds a QR sticker.

**Signal message:**

```
inoculated 1 block sawdust SHI, QR <code>
```

(Substitute the actual QR code from the sticker.)

**Expected bot reply:**

```
Got: seeding 1 block SHI on sawdust, qr=<code>
Reply YES to write, anything else to cancel.
```

**Operator action:** Reply `YES`.

**farmOS verification:**

```bash
# Lookup by QR code (per C2). Capture the block uuid for later steps.
curl -s -u "$FARMOS_USERNAME:$FARMOS_PASSWORD" \
  "$FARMOS_URL/api/asset/fungi?filter[farm_id_tag.qr_code]=<code>" \
  | python3 -m json.tool

# Stage check: expect "colonizing" (a seeding log just wrote)
node tools/farmos-current-stage.js <block_uuid>
```

**Success criterion:** Exactly one `fungi` asset with `species=SHI`,
`substrate=sawdust`, `farm_id_tag.qr_code=<code>`; tool reports
`stage: colonizing` with evidence pointing at the seeding log; `seeding`
log's `asset` relationships array includes both the new block uuid and the
PILOT-01 sterilization batch uuid (lineage).

---

## 3. PILOT-03 -- Colonize / cold_shock / fruiting transitions

**Real-world calendar:** 3-4 weeks colonize + 2-3 days cold_shock + 1+ weeks
of fruiting flushes. Do NOT rush this; the whole point of the pilot is to
exercise current-stage derivation at multiple checkpoints.

Send each Signal message AS the farm event happens. Reply `YES` to each
confirm. Record asset/log ids in PILOT-LOG.md after each.

### 3a. No-contam observation (~day 7)

```
no contam day 7 on block <ref>
```

Verify (stage should stay `colonizing`):

```bash
node tools/farmos-current-stage.js <block_uuid>
```

### 3b. Relocate to fruiting chamber (~day 21)

```
moved block <ref> to fruiting chamber
```

Verify (stage stays `colonizing`; relocate alone is not the trigger):

```bash
node tools/farmos-current-stage.js <block_uuid>
```

### 3c. Cold shock (the fruiting trigger)

```
cold shocked block <ref>
```

Verify (stage MUST flip to `fruiting`):

```bash
node tools/farmos-current-stage.js <block_uuid>
# Expected: { stage: "fruiting", evidence: { name: "cold_shock", ... } }
```

### 3d. Pin emergence

```
pins emerged on block <ref>
```

Verify (stage stays `fruiting`; observation does not change stage):

```bash
node tools/farmos-current-stage.js <block_uuid>
```

### 3e. First flush

```
first flush coming in on block <ref>
```

Verify same as 3d.

### 3f. Time-scoped checkpoint

After 3c lands, also verify the `--at` flag works retroactively:

```bash
# Stage at the day-7 checkpoint should report "colonizing" even after
# cold_shock has been filed.
node tools/farmos-current-stage.js <block_uuid> --at 2026-05-20T10:00:00Z
```

**Success criterion for PILOT-03:** Current-stage derivation returns the
correct stage at every checkpoint (colonizing through 3b, fruiting from 3c
onward, retroactive `--at` returns colonizing for day-7 timestamp).

---

## 4. PILOT-04 -- Bagging

**Farm event:** Harvested the block; weighed and bagged into N retail bags;
each bag has its own QR.

**Signal message:**

```
harvested 1.2kg from block <ref>, bagged into 6 bags QRs <q1,q2,q3,q4,q5,q6>
```

(Round weight to 1 decimal; the bot will format the reply with `fmtNum()`.)

**Expected bot reply:**

```
Got: harvest 1.2kg from block <ref>, 6 bags
Reply YES to write, anything else to cancel.
```

**Operator action:** Reply `YES`.

**farmOS verification:**

```bash
# Each bag should be a fungi asset with farm_id_tag.qr_code = its sticker
for q in q1 q2 q3 q4 q5 q6; do
  curl -s -u "$FARMOS_USERNAME:$FARMOS_PASSWORD" \
    "$FARMOS_URL/api/asset/fungi?filter[farm_id_tag.qr_code]=$q" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(q, len(d.get('data',[])))"
done

# Lineage walk on one bag should produce 4-hop chain.
node tools/farmos-lineage.js <bag_uuid>
# Expected: chain = [bag, harvest_batch, block, sterilization_batch]
```

**Success criterion:** All N bag assets created; each has its QR bound;
`harvest` log's `asset` relationships include the source block + the N new
bag uuids; lineage walk returns clean 4-hop chain.

---

## 5. PILOT-05 -- Archive_spent

**Farm event:** Block exhausted; no more flushes; physically discarded.

**Signal message:**

```
block <ref> spent, archived
```

**Expected bot reply:**

```
Got: archive_spent block <ref>
Reply YES to write, anything else to cancel.
```

**Operator action:** Reply `YES`.

**farmOS verification:**

```bash
node tools/farmos-current-stage.js <block_uuid>
# Expected: { stage: "spent", evidence: { name: "archive_spent", ... } }

node tools/farmos-lineage.js <bag_uuid>
# Expected: still returns clean chain (archive_spent doesn't break lineage).
```

**Success criterion:** Current-stage = `spent`; lineage walk still clean.

---

## 6. PILOT-06 -- End-to-end reconstruct

After all of 01-05 have landed, run the timeline reconstruct:

```bash
node tools/farmos-pilot-reconstruct.js <block_uuid> > /tmp/pilot-timeline.txt
cat /tmp/pilot-timeline.txt
```

**Success criterion:** Output is a timeline of every pilot event, sorted by
timestamp, with no Signal references. Manually compare against the events
journaled in `42-PILOT-LOG.md`; they must match within reasonable tolerance
(timestamps may differ by a few seconds due to confirm-loop delay).

Save the output as `/mnt/slime-kingdom/opt/mushy/.planning/phases/42-shi-pilot/42-pilot-timeline.txt`
(paper-trail rule: keep the artifact, do not overwrite).

---

## 7. Recovery and edge cases

### Stuck confirm loop

If the bot does not reply within 60s, check:

```bash
docker compose logs --tail 50 alerter | grep -E 'extract|confirm'
docker compose logs --tail 50 signal-cli | grep -i error
```

Common causes: signal-cli deviceId drift (Phase 31 lesson), FARMOS auth
expired, extractor maxTokens too low (Phase 38 lesson). Do NOT retry the
same Signal message blindly -- it will create a duplicate draft.

### Wrong stage after a transition

Re-fetch logs directly:

```bash
curl -s -u "$FARMOS_USERNAME:$FARMOS_PASSWORD" \
  "$FARMOS_URL/api/log?filter[asset.id]=<block_uuid>&sort=timestamp" \
  | python3 -m json.tool | less
```

If a log is missing, the write never landed; check `signal_draft_event`
table in alerter postgres. If a log is present but wrong `activity.name`,
file a Phase 38 D-N+1 entry (extractor regression) and patch via direct
farmOS edit only as a last resort -- the pilot is testing the pipeline.

### Pilot blocked on a real biological failure

Contamination, sterilizer breakdown, or any farm-side failure that ends the
lifecycle early: do NOT discard the pilot. Send the failure-mode Signal
message (`contam on block <ref>`); verify the stage flips to `contaminated`;
record the early-termination in PILOT-LOG.md; rerun PILOT-01 + PILOT-02 with
a fresh block when ready. The verification artifact accepts a contaminated
terminal outcome as long as all 6 criteria can still be attested.

---

*Phase 42 RUNBOOK -- 2026-05-13. Pilot duration estimate: 4-8 weeks
calendar.*
