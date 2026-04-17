# Phase 14: fc_camera idle-stall hotfix — Context

**Gathered:** 2026-04-17 (farm team + dev team in the room)
**Status:** Ready for planning
**Milestone:** v1.2.1 hotfix

<domain>
## Phase Boundary

Fix the v1.2 Phase 12 regression where `fc_camera` transitions to idle
mode (0.000278 fps) and never recovers to active mode on viewer connect.
Symptom: Mission Control shows a frozen image; the bridge re-saves the
same cached frame every 15 min. In-scope: the root-cause fix plus a
minimal "is the camera alive?" signal surfaced in MC so the failure
mode is legible to the farmer. Out of scope: a broader system-health
panel (filed as Phase 16), camera history persistence (999.14), camera
subscriber architecture redesign.

</domain>

<decisions>
## Implementation Decisions

### D-01: Fix strategy — diagnose before fixing
- Reproduce the stall before writing the fix. Either on fc1 (controlled
  restart + long idle window + viewer connect, watching
  `get_subscription_count()` and timer state) or on a spare Pi / test
  harness if possible.
- Do NOT patch the symptom with a generic "heartbeat timer that always
  captures" without understanding why the designed idle→active
  transition failed. The whole point of Phase 12 was to make this
  subscriber-aware; we shouldn't undo it because we got impatient.
- If diagnosis reveals a DDS discovery / `get_subscription_count()`
  quirk, the fix may look structural (switch to a ROS service call
  from the bridge on client-connect, or poll the topic statistics
  endpoint instead of `get_subscription_count()`). That's acceptable —
  decide based on what the root cause actually is.

### D-02: Test strategy — both unit and live soak
- **Unit test** in `test_camera.py`: extend `FakeNode/FakePublisher` to
  simulate a long idle → subscriber-count transitions → verify the
  active timer is created and frames are published.
- **Live soak** on fc1: deploy the fix, run for ~30 min with at least
  one viewer-connect-and-disconnect cycle, verify snapshot file sizes
  change hour-over-hour (proves idle captures still work too) and that
  MJPEG stream frames flow within a few seconds of connect.
- Both gates must pass before we mark Phase 14 done.

### D-03: MC freshness signal — two status lights (narrow)
- Add two indicator lights to the MC camera panel:
  1. **"Feed live"** — green if `last_frame_age_sec` < N (threshold
     TBD during planning, likely 10-30s when a viewer is connected),
     else red.
  2. **"Camera subscribed"** — green if the bridge is currently
     subscribed to `/fc1/camera/compressed`, else grey/off (not a
     failure — just "we're not asking for frames right now").
- This is the narrow version. Explicitly setting the stage for a
  broader system-health panel in Phase 16 — two lights now, more
  lights later. The same `/health` signals should be reusable by
  Phase 16 without rework.
- Visual style: small, inline with the camera panel — not a separate
  widget. Farm team can tell at a glance whether a black image is
  "stream just started" (green feed light) or "something is wrong"
  (red feed light).

### D-04: Observability — bundle `/health` changes now
- Add `camera.last_frame_age_sec` to the bridge `/health` JSON
  response. Value is `null` when no frame has ever been received,
  else wall-clock seconds since `latestFrame` was last updated.
- Keep the existing `camera.subscribed: true|false` field — the two
  lights in D-03 consume both.
- This is the minimum signal Phase 16 (system health panel) will
  need for the camera row; we're touching the bridge anyway so
  there's no point deferring.

### Claude's Discretion
- Exact stall-diagnosis methodology (log instrumentation, test
  harness design, whether to involve DDS packet capture — depends
  on what early investigation suggests).
- Exact MC layout for the two lights (inline above/below feed,
  color palette — match existing MC chrome).
- Internal structure of the fix once root cause is known (timer
  reconstruction pattern, polling cadence, grace-period
  interaction).
- Whether to add logging hooks that help Phase 16 without being
  used here.

</decisions>

<specifics>
## Specific Ideas

- Farmer's guiding principle carried forward: **gap over noise**
  (feedback_gap_over_noise.md). A red "feed not live" light is
  preferable to a black-but-labeled-green image that silently lies
  about the camera's actual state.
- "Setting the stage for broad later" — Phase 14's two lights are
  deliberately the same primitives Phase 16 will multiply. Don't
  invent a one-off UI pattern; pick something that scales to
  N lights.
- Recovery-in-30s test comes from today's incident: the farmer
  expects that reconnecting (or a restart) brings the feed back
  within a reasonable window. Define "reasonable" during planning.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 12 (what this phase is fixing)
- `.planning/phases/12-subscriber-aware-camera/12-CONTEXT.md` —
  Original subscriber-aware design decisions and canonical refs.
- `.planning/phases/12-subscriber-aware-camera/12-01-PLAN.md` —
  Implementation plan the regression came from.
- `.planning/phases/12-subscriber-aware-camera/12-02-PLAN.md` —
  Bridge-side subscription changes.
- `.planning/phases/12-subscriber-aware-camera/12-VERIFICATION.md` —
  What was supposed to be guaranteed after Phase 12.

### Code touched by this phase
- `src/chambers/fc-core/fc_core/fc_camera.py` — idle/active timer
  logic, subscriber polling; primary fix site.
- `src/chambers/fc-core/fc_core/test/test_camera.py` — regression
  test lives here.
- `src/chambers/fc-core/config/fc_config.yaml` — camera parameters
  (may add diagnostic/threshold params).
- `src/mission-control/bridge/src/index.js` — `/health` endpoint
  (`last_frame_age_sec`) + any MJPEG-state exposure needed for the
  two lights. Current subscribe/unsubscribe logic at lines 73, 86;
  snapshot timer at line 381.
- `src/mission-control/openmct/` (exact file TBD during planning) —
  MC camera panel UI where the two lights render.

### Today's incident findings
- `.planning/phases/999.14-index-camera-snapshots-in-timescale/FINDINGS-2026-04-17.md` —
  Full writeup of the stall observation and the idle-pulse-not-
  persisted design issue (latter is 999.14's scope, not Phase 14's).

### Memory (farmer constraints that apply)
- `feedback_gap_over_noise.md` — prefer visible gaps over wrong
  values; drives D-03.
- `project_phase12_camera_stall.md` — current state of the two
  live issues.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fc_camera.py` — existing timer-based capture + CompressedImage
  publisher pattern. Fix extends this, doesn't replace it.
- `test_camera.py` — FakeNode/FakePublisher harness; already used
  by Phase 12 tests. Extend for idle→active transition simulation.
- Bridge `/health` JSON — existing `camera.subscribed` field is
  the first "green light" primitive; `last_frame_age_sec` is the
  second.
- Bridge `latestFrame` state — already tracks most recent frame
  bytes; need to also track its timestamp so `/health` can report
  age.

### Established Patterns
- `get_subscription_count()` polling inside fc_camera timer callbacks
  (introduced by Phase 12). If diagnosis shows this is unreliable,
  switching to a service-based "viewer present" hint from the bridge
  is an option but would be a notable pattern change — document it
  clearly in the plan.
- Bang-bang / discrete state transitions (idle ↔ active). Keep this
  shape — don't introduce a third "recovering" state unless
  diagnosis demands it.
- `/health` as the single source of truth for frontend status
  queries. Two lights in D-03 should read from `/health`, not poll
  multiple endpoints.

### Integration Points
- MC camera panel: wherever Phase 8 (Pi Camera Feed in MC) wired
  the MJPEG stream — that's where the two lights render.
- Phase 15 (sensor warmup) will also add status signals; any
  shared primitive (e.g., a `StatusLight` component) should be
  shaped so Phase 15 can reuse it.
- Phase 16 (system health panel — new, filed alongside this) will
  consume the same `/health` signals; don't over-specialize the
  data shape for the two-lights case.

</code_context>

<deferred>
## Deferred Ideas

- **Broad system health panel** — filed as Phase 16. Two lights
  now, full panel later; do NOT expand scope here.
- **Idle-pulse persistence gap** — covered by 999.14 (camera
  history). Acknowledge in planning that this phase intentionally
  does not address it.
- **Recovery log heartbeat when healthy-idle** — nice to have for
  distinguishing "stuck idle" from "healthy idle" in logs, but only
  if the diagnosis makes it cheap to add. If it adds noise, defer.
- **DDS / ROS discovery deep-dive** — if diagnosis reveals a DDS
  quirk as root cause, we document it but don't fix DDS itself;
  fixing the consequence is Phase 14 scope.

</deferred>

---

*Phase: 14-fc-camera-idle-stall-hotfix*
*Context gathered: 2026-04-17*
