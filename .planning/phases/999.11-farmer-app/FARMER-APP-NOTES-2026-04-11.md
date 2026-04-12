# Farmer app — field notes from 2026-04-11 session

Captured in situ during a farmer-led calibration + ops session. These are
not requirements or a spec — they are observations about what the farmer
actually wanted to do today, what was clunky, and what would have felt
good. Intended as input for product/design when the Farmer app becomes
its own phase.

## Context

Today's session played all of these roles in sequence:

1. **Operator** — "what's the chamber doing right now?"
2. **Calibration engineer** — "narrow the band, watch it bounce, read off numbers"
3. **Reviewer** — "look at 30 minutes of history, tell me the story"
4. **Maintainer** — "change a parameter, deploy, verify"
5. **Observer** — "show me the camera"
6. **Field PM** — "that observation is worth telling the dev team"

Mission Control (OpenMCT) partly covers role 1 and 5 when sitting at a
desktop. Everything else today was done through Claude Code with ad-hoc
SQL, SSH, and git commands. **That's the gap the Farmer app should fill.**

## The single biggest miss of the day

**We spent ~40 minutes calibrating and drawing conclusions before
realizing SHT30 was offline and all the humidity data came from SCD41
(±6% nominal vs SHT30's ±1.5%).** Memory even had it flagged as v1.0
tech debt — neither of us checked.

→ **Design principle #1: sensor health must be so prominent it is
impossible to ignore.** A quiet "SHT30: offline, humidity sourced from
SCD41 (degraded accuracy)" banner at the top of every status view
would have saved the session. Ideally it travels with every derived
number — e.g. "81.3% RH (SCD41, ±6%)" — so operators can't stare at a
figure without knowing its provenance.

## Workflow moments — what the farmer did vs what they wanted

### Moment 1 — "Give me a farm status report"

**What happened:** hand-wrote a SQL aggregate query, SSH'd to fc1 for
service status, cross-referenced with docker ps on elder-plops, and
paraphrased the result into a readable summary.

**What the farmer wanted:** one screen. Current readings, last-6h
trend sparklines, service health (fc1 services + bridge + timescale +
openmct), sensor liveness (including degraded states), humidifier duty
cycle as a running percentage, and "time since last sample per topic".
Nothing clickable needed — just a heads-up display.

**Specific wishes:**
- Numbers with units AND error bars/sensor provenance
- Uptime for each node/service, color-coded
- A "what's unusual" section — anything out of range vs. the last 24h
  mean. Today the 28.4°C spike and the 63% RH crash should have been
  called out automatically, not noticed by the operator reading a table
- Time in local farm tz, not UTC, with UTC on hover

### Moment 2 — "Tell me the story of the last 30 minutes"

**What happened:** SQL query bucketing telemetry into 30s windows,
manual interpretation of the restart-spike-recovery-cycle pattern,
hand-annotation of which bucket contained what event.

**What the farmer wanted:** a **story view**. Not a raw chart — a
narrative timeline where software annotates its own events:

```
20:11  ── fc-core restart (config: humidity_tolerance 0.05 → 0.01)
20:11-12 ─ sensor warm-up spike (ignore, see #999.8)
20:13  ── first humidifier cycle under new band begins
20:15  ── RH crossed 80.5 upper threshold, humidifier OFF
20:17  ── passive decay
20:20  ── RH crossed 79.5 lower threshold, humidifier ON
20:36  ── DWELL-BLOCK: controller wanted OFF, clamped 62s
20:38  ── peak overshoot 82.49% (+2.0% past threshold)
```

Restarts, config changes, DWELL-BLOCK events, safe-state entries,
sensor stalenesses, service flaps — all as first-class events on a
timeline with the telemetry chart underneath. This is the view that
turns calibration from "parse a spreadsheet" into "read a story".

**Killer feature:** pick two timestamps to compare. "This cycle vs
yesterday's cycle — what changed?"

### Moment 3 — "Change a parameter and deploy"

**What happened:** edit YAML → git add → git commit → git push → ssh
to Pi → git pull → colcon build → sudo systemctl restart fc-core →
check it's active → tail journalctl. Five separate steps across two
hosts. Fast if you know the dance, intimidating otherwise.

**What the farmer wanted:** a "change a knob" surface. Target
setpoint, tolerance band, dwell time, camera FPS — all editable with
range sliders and text entry, with these guardrails:

- **Predicted effect banner:** "narrowing tolerance to ±0.5% under
  current control law is predicted to force +2% overshoot past the
  upper threshold (see backlog 999.9)." The app should *know* about
  known pitfalls and surface them at the point of decision.
- **Deploy in one click.** Behind the scenes it can still be git →
  push → Pi pull → restart. Farmer doesn't care.
- **Dry-run / preview mode:** compute "what would this parameter change
  imply" before committing. For control params, show a simulated
  cycle overlaid on live.
- **Auto-revert safety net:** "if this change produces >5min of
  out-of-band RH or triggers >3 safe-state entries, roll back
  automatically and page the operator." For calibration sessions this
  is gold.
- **Change log visible on the same screen:** "you changed
  humidity_tolerance 5 times today, here's when and what each did to
  the chamber."

### Moment 4 — "Capture this observation for the dev team"

**What happened:** manually drafted backlog markdown files, manually
edited ROADMAP.md, manually picked a phase number, manually committed.
Claude helped but this is a lot of friction for what should be a
20-second action.

**What the farmer wanted:** a "flag it" button on every chart, log
line, and event. Clicking it:

1. Snapshots the current view (telemetry, camera frame, active params,
   recent log lines) into an attachment
2. Prompts for a one-sentence description and a category (bug,
   enhancement, observation, question)
3. Files it as a backlog item automatically, pre-filled with the
   attachment
4. Returns the farmer to what they were doing

Today we captured 4 solid observations (999.8, 999.9, 999.10, plus
this doc). With a "flag it" button we would have captured twice as
many — there were probably 3-4 passing thoughts I didn't bother to
commit to memory because capturing them felt expensive.

### Moment 5 — "Show me the camera"

**What happened:** curl probe, grep through bridge source, figure out
ports, paste URLs. Then learned the stream is on 4G and expensive, so
we throttled it.

**What the farmer wanted:** a camera pane inside the same app. Live
toggle, snapshot timeline scrubber, "how much bandwidth has this used
today" counter prominently displayed (so you learn the cost of
watching without having to dig). Ideally the app integrates with
backlog 999.10 so "go live" is an explicit user action that triggers
the subscriber-aware mode to ramp up, and "leave live" drops it back.

### Moment 6 — "Where is it, actually?"

**Nothing handled this today.** The chamber is 40m from main infra
per memory, on weak wifi with Tailscale as the only link. The farmer
might be in the chamber on their phone. Three things the app needs
for this reality:

- **Offline-tolerant:** if the 4G link drops, show cached state with a
  prominent "stale since T" banner. Don't spinner forever.
- **Low-bandwidth first:** requests batched, no constant polling, no
  camera stream unless explicitly asked, no chatty telemetry
  subscriptions. Everything over the 4G link should be deliberate.
- **Mobile-first layout.** OpenMCT is desktop-heavy. The Farmer app
  should feel at home on a phone in a humid chamber with gloves on —
  big targets, high-contrast text, no multi-column layouts.

## Role-aware mode

Per memory, Santi plays both operator and grower but prefers the roles
stay distinct. That maps directly to two app modes:

- **Operator mode:** knobs, telemetry, actuators, logs, sensor health,
  deploys. The stuff we did today. Technical but protective.
- **Grower mode:** crop view, pinning/harvest timeline, camera
  time-lapse, quick "flag a crop issue" button, humidity/CO2
  interpreted as grower-relevant context ("RH trending dry, consider
  misting") rather than as raw numbers. No config knobs in this mode.

Both modes share the same sensor-health banner. A role switch at the
top of the app, remembered per device. A phone probably defaults to
grower mode; a tablet in the office probably defaults to operator.

## Things that almost bit us today — design reminders

- **Forgot SHT30 was offline.** → prominent sensor health
- **Sensor warm-up spike on restart.** → app should mask the first
  minute of post-restart telemetry automatically, or at least badge it
- **4G bandwidth from always-on camera.** → bandwidth cost visible in
  the UI
- **Dwell-forced overshoot under narrow band.** → app should know about
  this pitfall and warn when a farmer is about to tighten beyond ±1%
- **Deploy flow as a sequence of manual steps.** → one-click atomic
  operation with visible progress and rollback
- **Having to paraphrase SQL aggregates as prose.** → stories, not
  tables

## Integration wishes

- **Signal bot** (per memory — farm uses Signal, not Telegram/Slack)
  for alerts, auto-escalation of safe-state entries and long
  out-of-band excursions, and daily morning digest ("last night RH
  held 79.2-80.8, humidifier duty 14%, one DWELL-BLOCK at 03:42").
- **Mission Control (OpenMCT) coexistence.** The Farmer app is not a
  replacement — OpenMCT is the engineer/PM surface, the Farmer app is
  the operator/grower surface. They should share the same Timescale
  backend and ideally the same bridge WebSocket, so there's no "which
  one is right" confusion.
- **Backlog pipeline.** "Flag it" from the app files directly into
  `.planning/phases/999.*/` with session context attached. Ideally
  Claude Code stays the brain for planning and execution, but the
  farmer's capture path is the app.

## Open questions for product/design

1. **Native vs web?** Native is friendlier in gloves and offline, but
   web is deployable without app-store friction. PWA as middle ground?
2. **Single chamber or multi-chamber from day one?** Memory flags FC-2
   and FC-3 as a future backlog item (999.6). Designing for N chambers
   up front is cheap if done now, expensive to retrofit.
3. **Who owns the deploy action?** Should the farmer be able to push
   config changes straight to prod from the app, or does everything
   still go through a PR? (My intuition: farmer can push *safe*
   params — humidity setpoint, tolerance band, lighting schedule —
   directly, but anything touching code or infra requires a dev PR.)
4. **What does the calibration mode look like?** Today we used Claude
   Code as an ad-hoc calibration harness. A native calibration mode
   inside the app — "tighten the band, run N cycles, read off rise
   rate / decay rate / overshoot / undershoot automatically" —
   could be a killer feature, especially once 999.9 (PID) lands and
   system ID becomes a recurring need.
5. **Grower journal.** Grower mode probably needs a notes/journal view
   ("flushing, fan on high", "pinning started on shelf 2", "picked
   200g") linked to the timeline so later you can correlate
   environmental conditions with crop outcomes. Not today's session,
   but worth remembering.

## Prioritization hint

If the dev team can only build three things from this doc, my pick
(farmer's voice):

1. **Sensor health banner** — biggest lesson of today, smallest effort
2. **"Flag it" backlog capture button** — unlocks field product work
3. **One-click config change with pitfall warnings** — turns calibration
   from a developer workflow into a farmer workflow

Everything else can wait for a v2 of the Farmer app.

---

*Captured during 2026-04-11 farmer calibration + ops session.
Session used Claude Code as an ad-hoc farmer app — this doc describes
what a dedicated app would feel like if built from that experience.*
