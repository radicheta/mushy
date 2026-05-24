# Session-as-asset-group — design note for the farmos team

**Date:** 2026-05-24
**Author:** Santi (via radicheta-claude)
**Audience:** farmos-side claude (zoy-claude) + farm team
**Status:** Open question; mushy side has shipped an interim no-session workaround for v1.9

## TL;DR

Phase 48 (mushy) shipped the seeding_session commit handler with a Gray Area A LOCK that modeled the session as **an anonymous `asset--fungi`**. Live-fire on dev farmOS today (`http://10.68.155.50:18080`) rejected that shape with HTTP 422 because farmOS field config enforces `fungi_type NOT NULL`. The Plan 02 design assumption was wrong against real farmOS.

Patching the lock with a sentinel `fungi_type:(unassigned)` or `fungi_type:session` smuggles a non-strain into a strain field — violates B6 (which scoped `(unassigned)` to legacy migration only) and conflates the field's semantics.

Santi's framing: **"session is to block like Playlist is to version in ShotGrid"** — both first-class entities of *different kinds*, whose membership pointers are the session/playlist's primary data. The right farmOS shape is therefore **`asset--group`** (from the stock `farm_group` module), not `asset--fungi`.

## What mushy shipped today as the interim (no-session) workaround

Commit on the mushy side, post-this-note:
- `commit-seeding-session.js`: removed the session-asset preflight; children commit with `parent=[sourceBlockId]` only.
- Hermetic tests updated: 16 asset POSTs (5 source + 11 children) + 11 seeding logs; no session asset; no secondary parent edge.
- Live-fire dev run 2026-05-24 ~13:55 ART: 16 assets + 11 seeding logs landed cleanly in dev farmOS in 4.4s; lineage walks return single source-block parent.
- Session identity is now recoverable by query: "all `seeding` logs on `event_date=2026-05-22` by `sender_name=Santi`". No entity backing the session.
- `_resolveSessionName()` + `COLLISION_MAX` removed from the handler — they're irrelevant without a session asset and would rot.
- `allowNoFungiType` flag in `assets.createFungiAsset()` left in place (still wired through `opts`) for the future case where it's the right answer, but no caller uses it anymore.

The interim is *intentionally lossy*: the May-22 session has no farmOS-side container entity until the design below lands. The 11 child blocks are real and queryable; the session is implicit.

## Proposed real shape — `asset--group` + group membership log

Stock farmOS pattern for "this is a heterogeneous container of other assets":

1. **Enable the `farm_group` module on dev + prod farmOS** (`drush en farm_group` on both; persist in `config/sync/` so it survives a config import). Verify: `curl /api/ | jq` lists `asset--group` after enable.

2. **Session = one `asset--group`** named `inoc YYYY-MM-DD` (or `inoc YYYY-MM-DD #N` on same-day collision). Carries:
   - `name`
   - `status: active`
   - `notes`: provenance trailer + draft id
   - no QR (sessions don't get scanned; the children carry QRs).

3. **Membership = one `group` log** dated `event_date`, with:
   - `asset[]` = the N child block UUIDs
   - `group[]` = `[sessionGroupAssetId]`
   - `name`: "inoc 2026-05-22 (N bags)"
   - timestamp = the day-grain epoch the seeding logs already use.

4. **Children unchanged**: `asset--fungi`, `fungi_xing:block`, `fungi_type:<strain>`, `parent=[sourceBlock]`. NO `parent=[sessionGroup]` — group membership is encoded by the group log, not the asset-to-asset parent edge. Stays true to C4 ("lineage = an event, not a property").

5. **Lineage walk from a child returns its strain parent**; "what session was this in?" answered by `GET /api/log/group?filter[asset.id]=<child_id>` → walk the group log → resolve `group[0]` → the session asset.

6. **Session-level events** (contam affecting the whole inoc round, a session-wide observation, etc.) attach to the group asset directly via standard log types.

Why this is the correct shape vs. an `asset--fungi` session:
- A session is not a strain; modeling it as fungi pollutes any "show me strain X" query unless callers learn to filter on a sentinel.
- The Playlist:Version analogy maps 1:1 to Group:Fungi in farmOS-stock.
- `asset--group` already gives you the membership-walks for free via the `group` log type — no custom membership table.
- It composes with substrate's log-only lock (`[[project_substrate_log_only_lock_2026_05_14]]`): seeding logs continue to be the substrate-recording surface; the group log handles the session-identity surface; nothing collides.

## Open questions for the farmos team

1. **Is `farm_group` already part of the farmOS distro we're running?** If yes, it's a one-line `drush en` + config-sync commit. If not, evaluate whether it's a contrib module or needs composer.
2. **Permissions:** the `farm_group` module probably adds CRUD perms on `asset/group` and `log/group`. mushy-bot needs both on prod once we cut over. Worth bundling with today's UAT-findings TODO ("Port runtime perm-grant to farmos repo config" — see `.planning/notes/2026-05-24-v1.9-uat-findings.md` line 120).
3. **Naming collision policy:** Phase 48 originally planned `inoc YYYY-MM-DD #2 ... #9`. Is `#N` the right convention farm-wide, or do you prefer `inoc YYYY-MM-DD-am` / `inoc YYYY-MM-DD-pm` to capture morning-vs-afternoon sessions?
4. **`group` log timestamp semantics:** does the farm team expect a single group log on `event_date` (creates the group + members on day 0), or a stream of group logs (members get added over time)? Phase 48 assumes the former — one-and-done at commit.
5. **Backfill of today's dev live-fire:** the 11 children currently in dev farmOS at `:18080` have no group. Once the design lands, those children can be retroactively wrapped by a group log. Worth doing in dev as a smoke before any prod cutover.
6. **Prod farmOS write decision** is separate from this design. Per the 2026-05-24 UAT findings, prod write is intentionally gated by `FARMOS_INTEGRATION=0` until observation-of-unknown-asset backfill ships. Sessions inherit that gate.

## Phase boundary on the mushy side once the farmos design lands

When `asset--group` is enabled on both instances:
- Re-introduce a session-asset preflight in `commit-seeding-session.js`, but creating `asset--group` instead of `asset--fungi`.
- Add a `groupLogs.createGroupLog()` call after the children are all created, with `asset[]=[childIds]` + `group[]=[sessionGroupId]`.
- Update integration tests: 17 asset POSTs (1 group + 5 source + 11 children) + 12 logs (1 group + 11 seeding).
- Children's `parent[]` stays single-source; secondary parent edge to the group asset is NOT added (membership lives on the log).

This is a Phase 51/52-ish-sized change on the mushy side — clean, isolated to `commit-seeding-session.js` + tests + the new `groupLogs` module.

## Cross-references

- mushy: `.planning/phases/48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-CONTEXT.md` Gray Area A (the now-reversed lock)
- mushy: `.planning/phases/48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md` Result section (2026-05-24 dev run, pending append)
- mushy: today's commit on `commit-seeding-session.js` + tests + fixture (no-session interim)
- farmos: `.planning/notes/2026-05-11-session-chat.md` C3/C4/B6 (the conventions this design honors)
- farmos: `.planning/notes/2026-05-24-v1.9-uat-findings.md` (the broader prod-write gating context)
- shared memory: `[[project_session_is_production_shape_per_bag_is_storage]]`, `[[project_substrate_log_only_lock_2026_05_14]]`, `[[reference_farmos_dev_vs_prod_on_elder_plops]]`
