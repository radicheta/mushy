# 2026-05-09 — Farmer #1 verbatim quotes (lab visit)

Capture-only file. Verbatim quotes + minimal context. Parse / promote / file later.

---

## Q1 — CO2 sensor 1-second offline-recovery alert noise

**Trigger event (mushy-bot Signal message):**
> [RECOVERY] FC-1 · CO2 Sensor offline back
> Was OOB for 0m 01s
> Open: http://100.96.10.66:8080/

**Farmer #1, verbatim:**
> "I don't want to hear about events lasting 1 second. do not bother me with tiny deviations. warn me of real problems, not minor hiccups"

**Context / interpretation (radicheta-side, not farmer's words):**
- Implies a minimum-duration threshold before sensor-OOB → alert fires (maybe ≥30s? ≥60s?)
- "Minor hiccups" framing — farmer wants alerter to debounce / hysteresis
- Likely systemic across all sensor-offline alerts (CO2, temp, humidity, etc.), not just CO2

---

## Q2 — Chamber state today: ideal force-evaporation test conditions

**Farmer #1 + radicheta observation (paraphrased, not direct quote):**
> Lots of condensation on the fruiting chamber today after several rainy days and a big drop in temp. There's even some water pooling on the floor. Great time to test an evaporation cycle today.

**Context:**
- Phase 31 force-evaporation UAT — exceptional natural test conditions today (saturated chamber, post-rain + cold snap)
- Pre-existing sensor reading: 8.8°C / 95.5% RH (cold-room mode confirmed)
- Suggests prioritizing **force-evaporation** over **force-condensation** in today's UAT-1 happy-path scenario, given the natural setup

---

## Q3 — Another short power blackout during visit (~13:53 local)

**Farmer #1, paraphrased:**
> Another short blackout just now.

**System impact (radicheta-checked, CORRECTED after closer look):**
- Initial read was wrong: PID continuity is not proof of process survival. fc1 uptime check showed **fc1 actually rebooted** — uptime was 3 min after the blackout. The colcon build was killed mid-flight ("Starting >>> fc_msgs" was the last logged step before the crash).
- elder-plops-side ssh PID 2142365 was a TCP zombie waiting for keepalive timeout, not a live process — gave a false "still running" signal.
- Recovery: re-ran deploy.sh after kill, second build completed in 28.5s (incremental cache).

**Calibration (added 2026-05-09 ~14:05 after farmer note):**
- Today is **stormy — not typical**. The blackout frequency observed today is NOT representative of normal operating conditions. SEED-007 trigger criteria should weight non-stormy-day blackouts separately from storm-day blackouts when assessing "is this incident frequent enough to act?"
- Storm-day blackouts may also affect upstream: 4G router, switch, even pfSense. UPS scope decision (Pi-only vs whole-rack) is more nuanced under storm conditions because everything tends to drop together.

**Implication:**
- Live data point for SEED-007 — but flagged as non-typical-weather. Do not extrapolate today's frequency to baseline.
- Worth tracking blackout count for the rest of the visit, tagged as storm-day.

---

## Q4 — Farmer UI feedback: camera feed + snapshot chip colors are ambiguous

**Farmer #1, paraphrased (radicheta-summary):**
> "Camera feed and snapshot chip colour are super ambiguous"

**Screenshots referenced:** `~/Screenshots/snip_20260509-133427.jpg`, `~/Screenshots/snip_20260509-133437.jpg`

**Specific ambiguities observed (radicheta + Claude):**

Two contradictory uses of RED in the same UI:
- `🔴 FEED LIVE` — red dot inside the chip; intended as "recording" convention (the broadcast/streaming metaphor) → reads as POSITIVE
- `🔴 SNAPSHOTS` — red fills the chip; intended as "no snapshots in 24h" alarm → reads as NEGATIVE

Two contradictory uses of "OFF / dim":
- `⚫ CAMERA FEED` — gray/off → no information about *why* (no frames? not subscribed? camera physically dead? feed paused?). Today's case: camera was unplugged from blue USB until ~16:27, but the chip didn't differentiate "camera offline" from "subscribed but no frames" from "snapshot interval not yet elapsed".
- `⚫ HUMIDIFIER` — gray/off → similarly opaque. Is the humidifier OFF because it's not commanded, or because something is broken?

Cyan as "good" with no contrast against the bad states is also flat — `🟢 BRIDGE`, `🟢 PI REACHABLE`, `🟢 GRACE`, `🟢 SENSORS` all look identical even though they represent very different things.

**Design implications (not for farmer to solve — for us):**
- **Red must mean one thing.** Either drop the broadcast-style "live red dot" or move it to a different visual treatment (e.g., a small animated pulse indicator separate from chip color).
- **Gray needs a reason.** "OFF" should always carry a one-word qualifier (e.g., `CAMERA · NO FRAMES`, `CAMERA · UNPLUGGED`, `HUMIDIFIER · IDLE`, `HUMIDIFIER · COMMANDED OFF`).
- Consider explicit semantic palette: green=ok, yellow=degraded, red=broken, gray=unknown, blue=informational. The current cyan-is-OK / red-is-mixed scheme isn't legible.
- Memory `feedback_gap_over_noise` ("prefer visible data gaps over wrong-looking values") + `feedback_no_sparklines` (annotated event timeline preferred over sparkline) — both align: the chip row is the same problem class. Farmer wants self-evident state, not a code to decode.

---

## Q5 — HUMIDIFIER chip is permanently gray (BUG, not just UI)

**Farmer #1, paraphrased:**
> "Chip for humidifier is grey too"

**Root cause (radicheta + Claude):**
- HUMIDIFIER chip's data source is the **legacy `/fc1/actuators/humidifier` Bool topic**, which `fc_controller` STOPPED PUBLISHING in Phase 27 (~2026-05-02, ≈8 days ago) when slow-PWM duty cycling replaced binary on/off control.
- Live data has been on `/fc1/actuators/humidifier_duty` (Float32, 0.0–1.0) since Phase 27 ship, publishing at 1 Hz. Verified just now: 291 rows in Timescale in the last 5 min.
- Same root cause as bridge `/health` exposing `humidifier.last_msg_ts: null` — both the chip and the health field read the dead legacy field.
- Bridge `src/index.js` line 799-815: still subscribes to legacy `/fc1/actuators/humidifier` and uses it to set `humidifierLastMsgTs` (which feeds the chip). Then line 816+ subscribes to `humidifier_duty` separately but doesn't update the same `humidifierLastMsgTs` field.

**Bug class:**
- Real bug — not a "color is ambiguous" UX nit. Chip is **wrong** (says unknown/off when humidifier is actually controlling actively). This has been silently false for ~8 days, presumably misleading the farmer this whole time.
- Goes into the same Phase-27-leftover bucket as the alerter watchdog quiet-topic bug (memory `project_alerter_watchdog_quiet_topic_bug`). Both stem from the same legacy-topic retirement not being followed through across the stack.

**Fix shape:**
- Bridge: switch chip-data feed to `humidifier_duty`. Chip semantics:
  - duty == 0 (no demand) → IDLE (gray with "IDLE" label, OR yellow if "we want it on but PID says no")
  - 0 < duty < 1 → MODULATING (cyan with "X%" label)
  - duty == 1 → FULL (cyan/blue with "100%" label)
  - no msg in N seconds → UNKNOWN (gray with "STALE" or "OFFLINE" label)
- Optional richer view: differentiate "PID-controlled idle" vs "force-mode commanded off" vs "no controller" so farmer can see WHY duty is 0.
- Same fix needed for `/health` `humidifier.last_msg_ts` — should source from `humidifier_duty` last-message-time, not legacy.

**Severity:** High-priority follow-up. Pre-existing bug surfaced by today's UI feedback. Should be a quick file-it-and-fix, not a milestone.

---

## Q6 — Outside weather data alongside chamber sensors

**Farmer #1, paraphrased:**
> "It'd be nice to have weather data (temp humidity) along our sensors. To compare to the 'outside'."

**Why it's a useful ask (radicheta-side analysis):**
- Diagnostic: when chamber RH spikes / drifts, the first question is always "is this a chamber problem or an ambient problem?" Outside data answers that immediately. Today's stormy-day saturation is a perfect example — chamber RH at 95% with humidifier off is not anomalous if outside is also at 90%+.
- Planning: farmer can decide "don't open the chamber today, ambient is too dry" or "force-evaporation will work today, ambient is dry" without guessing.
- Story: when explaining a yield outcome to themselves or to customers, "we had 4 stormy days in a row" is a real explanatory variable.
- Aligns with `feedback_gap_over_noise` — weather context turns ambiguous chamber readings into self-explanatory ones.

**Implementation shapes (small → medium scope, not a milestone):**

1. **API-based (smallest)** — pull from a free weather API (OpenWeatherMap, weather.gov, Uruguayan SMN if it has an API). Poll every 5-10 min. Add as Timescale topics `weather.outside.temperature`, `weather.outside.humidity`, optionally precipitation/wind. Plot alongside chamber series in OpenMCT and farmer-app. ~1 phase of work, mostly bridge + farmos-proxy plumbing.
   - Pros: zero hardware, immediate
   - Cons: location accuracy is regional (nearest station may be 5-20km away); doesn't capture micro-climate at the lab building itself

2. **Local outdoor sensor (medium)** — mount a weatherproof SHT30 (or BME280 for pressure too) outside the lab building, wire to fc1 via long I2C cable or via a small Pi Zero W bridge over wifi. Local truth.
   - Pros: actual lab-building micro-climate; same sensor stack as inside (apples to apples)
   - Cons: extra hardware install, needs weather shield, cable run

3. **Both (best)** — API as the always-on regional baseline, local sensor as the ground-truth overlay. Detect divergence and flag it (could indicate a localized weather event the API missed, or sensor failure).

**Recommendation:** start with API-based (Option 1) as a small follow-up phase. Adds the diagnostic value with minimal risk. If farmer finds it useful and the regional API is too coarse, add Option 2 later. This composes well with the existing v1.4 CV milestone, the dynamic-RH-target groundwork (memory `project_dynamic_rh_target_groundwork`), and SEED-005 (water-mass observer would benefit from ambient input).

**Captures into:** worth a SEED-008 or a 999.x backlog item. Memory worth keeping is "farmer wants ambient context for chamber readings" — composes with future scheduling/automation work.

