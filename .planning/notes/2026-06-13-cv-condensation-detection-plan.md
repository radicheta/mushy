# CV Condensation Detection — Plan

**Date:** 2026-06-13
**Status:** Design locked, implementation NOT started (this session was plan-only, no code)
**Activates:** SEED-005 (Chamber water-mass observer + condensation camera macro) — this is **data-source #3** of that seed, pulled forward on its own.
**Trigger that fired:** macro lens arrived + mounted on fc1 camera (2026-06-13). SEED-005's stated dependency "camera macro depends on camera being back online" is now satisfied.

---

## 0. TL;DR

We now have a macro lens on the fc1 camera looking at the **outer (chamber-air-side) surface of a substrate bag**. Plan: capture a labeled dataset of that surface across dry → fogged → beaded → dripping, train a **tiny CNN** to emit a condensation score, run inference **bridge-side on elder-plops**, and use visible condensation as **ground truth to calibrate the RH sensors and humidity targets near 100% RH**, where the SHT30/SCD41 sensors go blind (pin at 100% while real water mass keeps climbing).

**Build order:** (A) capture → (B) label → (C) train CNN → (D) bridge inference + `condensation_score` series → (E) use it to calibrate sensors/targets.

---

## 1. Goal & why now

**Goal:** A visual condensation signal that is trustworthy in exactly the regime where our humidity sensors are not — RH ≥ ~99%. Use it to:
- Anchor sensor calibration: "RH reads 100% AND no visible condensation" ⇒ air is at saturation baseline `m_sat(T)`, not beyond it.
- Confirm saturation is real (first visible droplet) vs sensor drift/stuck-at-100%.
- Set humidity **targets** sensibly near the top of the range (a 93% vs 97% vs "ride saturation" decision is meaningless if the sensor can't tell them apart up there).
- Long arc: feed the SEED-005 water-mass observer as its ground-truth term (source #3).

**Why now:** macro lens mounted; chamber is in fruiting (~93% target) and cycles near saturation routinely, so condensation events are already happening on the bag surface — we can capture without forcing anything.

---

## 2. Decisions locked this session

| Decision | Choice | Rationale |
|---|---|---|
| First step | **Capture a labeled dataset first** | A CNN (or any detector) can't be tuned without real macro frames spanning dry→wet. |
| CV approach | **Tiny CNN** (not classical thresholds) | Operator preference; learned classifier handles lighting/texture variation better than hand-tuned variance/specularity thresholds. Cost: needs labeled data + GPU train. |
| Compute location | **Bridge-side (elder-plops)** | Keeps fc1 Pi CPU free; co-located with derived telemetry + the future water-mass observer (per `project_999_27_bridge_side_derivation`). elder-plops has a 6 GB NVIDIA GPU for training (`project_farmer_language_and_gpu`). |
| Lighting | **Daylight-only for now** | Grow light is NOT wired to the Pi, so no pulse-sync option. Future: small dedicated white-flash LED by the camera (5 V + logic-level MOSFET gated by GPIO — NOT direct 3.3 V drive; white Vf ≈ 3.0–3.4 V leaves no headroom). |
| Detection surface | **OUTER bag surface** (chamber-air side) | Mycelium is in contact with the bag, so the inner surface is a warmer microclimate (deferred). The outer surface tracks chamber air saturation — which is what the sensors measure, so it's the correct calibration reference. |

---

## 3. Physical setup — current state (2026-06-13)

- Macro lens mounted on the fc1 USB webcam (`fc_camera` node, `/dev/video0`, 640×480, JPEG q65).
- Framing: substrate bag, mycelium colonizing, viewed **through** the bag. Circular lens vignette (black corners) — usable image is the central disc only → **crop to the lens circle ROI before training/inference.**
- Specular streaks seen in frames = reflections off the plastic bag (expected).
- **Two RH sensors** (`fc1/humidity`, `fc1/humidity_2`) and **two temp sensors** (`fc1/temperature`, `fc1/temperature_2`) — capture BOTH; their disagreement near saturation is itself a calibration signal.
- Diurnal lighting: night frames are pure black (00:02 sample was fully dark). Daylight window only, until a flash LED exists.
- Snapshot pipeline already persists frames to `/data/snapshots/fc1/YYYY-MM-DD/` on elder-plops, but at ~15 min spacing — too sparse for a condensation transition. Dense capture needs a dedicated tool (see §6).

---

## 4. The hard problem: lens-fog confound (failure mode F6)

**This is the #1 technical risk and must be designed for from the start.** Near 100% RH, condensation forms not only on the bag surface we want to measure but **on the macro lens itself** (F6 in `notes/2026-05-09-forced-condensation-operational-practice.md`). A fogged lens looks superficially like "lots of condensation" — the exact false positive that would wreck a calibration signal.

Discriminators we can lean on:
- **Depth of field:** macro DOF is razor-thin. Bag-surface droplets are *in focus* (sharp edges, specular points); lens-surface fog is a *uniform out-of-focus veil* over the whole disc. These look different and a CNN can learn the difference — **if the training set contains labeled lens-fog episodes.**
- So: the capture must deliberately include lens-fog events, and labeling must have a distinct `lens_fog` class (not lumped into "condensed").

Mitigations to keep on the table (decide later, not now):
- Small lens hood / standoff so the lens sits in slightly drier air.
- The future flash LED dissipates a little heat → mild anti-fog.
- Dedicated tiny heater pad on the lens barrel (F6's suggested 999.x fix).

Do NOT ship a calibration that can't tell bag condensation from lens fog.

---

## 5. Staged plan

### Stage A — Dataset capture
**Recommended: passive-first, no forcing.**
- The chamber at 93% fruiting with the known humidifier limit-cycle already drives the surface through dry↔condensed repeatedly. Capture continuously over a few daylight days and we likely get the full range with **zero crop risk**.
- Run the capture harness (§6) during daylight; auto-pair every saved frame with RH/temp/CO2/target/duty/mode.
- **Escalate to a controlled `/force-condensation N` event ONLY if** the passive range is insufficient (e.g. we never see "dripping"). Forcing has real risk:
  - **F8 — wet-rot:** condensation directly on fruiting bodies causes crop loss; the literature says block mid-fruiting forcing. **Before any forced event, confirm no fruiting bodies in the chamber / in frame, and keep pulses short.**
  - Forcing is also the cleanest way to capture the **post-event evaporation tail** (F9: sensor stuck at 100% after the event) — which is calibration gold (visual clears while sensor still reads 100% ⇒ direct evidence of stuck-sensor blindness). Worth one careful forced run *after* passive baseline, crop permitting.

**Capture-to-disk target:** raw JPEGs + a per-frame manifest CSV (see §6). Land on fc1, rsync to `/data/condensation-dataset/<run-id>/` on elder-plops for training.

### Stage B — Labeling
- **Coarse auto-label** from the manifest: derive a provisional class per frame from telemetry + event timeline (e.g. RH band, humidifier duty integral since last dry, force-event phase). This bootstraps labels for free and orders frames for fast human review.
- **Human refine** the auto-labels (the visual is the ground truth, not the telemetry — that's the whole point). Quick pass in an image grid.
- **Label taxonomy (proposed, ordinal):** `dry` / `fogged` / `beaded` / `dripping` + a separate `lens_fog` flag + `dark`/`unusable` flag. Can collapse to binary later; can also train a 0..1 regression head. Start ordinal — it's more informative and trivially collapses.
- Keep the paper trail: never overwrite raw frames or the auto-label pass (`feedback_keep_paper_trail_of_intermediates`).

### Stage C — Train tiny CNN (elder-plops GPU)
- Input: lens-circle ROI crop, downscaled (e.g. 128×128 or 96×96 grayscale — color adds little for water on plastic, and grayscale is robust to the warm/cool daylight shift).
- Architecture: a *small* net. Two reasonable options to decide at build time:
  1. **From scratch:** 3–4 conv blocks → GAP → small FC. Few hundred K params. Fine if we get ≥ ~1–2k labeled frames with augmentation.
  2. **Transfer learning:** frozen MobileNetV3-small / EfficientNet-lite backbone + tiny head. More robust on a small dataset; heavier inference but bridge-side GPU/CPU can handle 1/min easily.
- Heavy augmentation (brightness/contrast/blur/jitter) — daylight variation is the main domain shift.
- Outputs: ordinal class probabilities → collapse to a `condensation_score` ∈ [0,1] + an explicit `lens_fog` probability (so we can suppress/flag rather than trust a fogged frame).
- Eval: hold out whole *days* (not random frames) to avoid temporal leakage. Need ≥1 real-session-style fixture before trusting it (`feedback_real_data_before_ship_gate_pass`).

### Stage D — Bridge-side inference + `condensation_score` series
- New bridge module, sibling to `snapshot_helpers.js` / `frame_validate.js`. It either subscribes to the camera frames or reads the latest snapshot, runs inference (Python sidecar/service for the model — bridge is Node; a small Python inference service over a local socket/HTTP is the clean seam), and emits:
  - `condensation_score` ∈ [0,1] (low rate, ~1/min per SEED-005)
  - `condensation_class` (dry/fogged/beaded/dripping)
  - `lens_fog` flag
- **Storage decision (deferred):** add a metric to the existing `telemetry` hypertable vs a new `derived_condensation` table. Lean: new derived table keyed like `snapshots` (has `captured_at`, `camera_id`) so it joins cleanly to the frame that produced it.
- Gate on the `dark`/daylight flag — don't emit a score for black night frames (emit a gap, not a wrong value — `feedback_gap_over_noise`).

### Stage E — Use it to calibrate sensors & targets (the payoff)
This is the actual deliverable; everything above is plumbing for it.
- **Saturation anchor:** when both RH sensors read ~100% AND `condensation_score ≈ 0` (no visible condensation) over a stable window ⇒ air is at `m_sat(T)`, not beyond. This anchors where "real 100%" is and exposes per-sensor offset/clip behavior near the top (SCD41 RH is known to clip at 100%; SHT30 may differ).
- **Stuck-sensor detection (F5/F9):** `condensation_score` falling to ~0 while a sensor still reads 100% ⇒ that sensor is water-trapped / blind. Direct, visual confirmation of the failure the ops note flagged — and a candidate alerter signal later.
- **Sensor cross-check:** the two RH sensors vs the visual at the top of the range tells us which to trust / how to correct.
- **Target setting:** lets us choose humidity targets near saturation on a *physical* basis (is the surface wet? how wet?) instead of a sensor number that's saturated and meaningless up there. Feeds the SEED-004 VPD/band work and the SEED-005 water-mass observer.

---

## 6. Capture harness spec (to build next session)

Standalone tool, **surgical — does NOT touch the production snapshot/retention pipeline.**

- **Form:** standalone `rclpy` script (e.g. `scripts/cv/capture_condensation_dataset.py`). Not added to the `fc_core` ROS package — it's spike instrumentation.
- **Runs on:** fc1 (has the camera, cv2, and DDS). Output to fc1 local disk, then `rsync` to `/data/condensation-dataset/<run-id>/` on elder-plops.
  - *Open question:* could run on elder-plops if a host-side `rclpy` + CycloneDDS-over-tailscale reach to fc1 topics is available; fc1 is the safe default.
- **Subscribes (and caches latest of each):**
  - `fc1/camera/compressed` — `sensor_msgs/CompressedImage`. Subscribing makes us a viewer ⇒ `fc_camera` ramps from idle (1/hr) to `camera_active_fps` (1.0 fps). That's our frame source.
  - `fc1/humidity`, `fc1/humidity_2` — `sensor_msgs/RelativeHumidity` (`.relative_humidity`, 0..1)
  - `fc1/temperature`, `fc1/temperature_2` — `sensor_msgs/Temperature` (`.temperature`, °C)
  - `fc1/co2` — `std_msgs/Float32` (`.data`)
  - `fc1/control/humidity_target` — `std_msgs/Float32`
  - `fc1/actuators/humidifier_duty` — `std_msgs/Float32`
  - `fc1/control/current_mode_json` — `std_msgs/String`
  - `fc1/control/experiment_event` — `std_msgs/String`
  - **QoS:** the `fc1/control/*` + `fc1/actuators/*` topics use the controller's `actuator_qos` (latched / TRANSIENT_LOCAL + RELIABLE). The subscriber must match (TRANSIENT_LOCAL + RELIABLE) to receive the latched last value. Sensor + camera topics are default depth-10 volatile → default sub is fine.
- **Per saved frame (throttled to `--interval-sec`, default 15 s — subsample the 1 fps stream):**
  - Save JPEG with ISO-8601-Z filename (matches snapshot convention).
  - Append a manifest CSV row: `ts_iso, frame_file, rh1, rh2, temp1, temp2, co2, rh_target, duty, mode, experiment, mean_luma, dark_flag` (+ a `label` column left blank for Stage B).
  - `mean_luma`: mean grayscale of the lens-circle ROI. `dark_flag = 1` if `mean_luma < --min-luma` (default ~30). **Record dark frames anyway, flagged** — don't silently drop (paper trail / gap-over-noise).
- **Robustness:** never crash on a decode error (log + skip); flush the manifest every row; on SIGINT write a run summary (frame count, RH range, luma range, dark fraction, duration).
- **DDS env when run on fc1:** `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `CYCLONEDDS_URI=...`, `ROS_DOMAIN_ID=69` (ref `feedback_ros2_cli_over_ssh_needs_explicit_dds_env`; or reuse the `ros2-cmd` wrapper env per `project_fc1_ssh_env_wrapper`).
- **Args:** `--out-dir`, `--run-id`, `--duration-min` (0 = until Ctrl-C), `--interval-sec` (default 15), `--min-luma` (default 30).

Deliverables next session: the script above + a short capture runbook (passive run procedure; optional crop-safe forced-event procedure with the F8 pre-checks).

---

## 7. Risks & failure modes

| # | Risk | Severity | Plan |
|---|---|---|---|
| R1 | **Lens fog confound (F6)** — fogged lens mimics heavy condensation | HIGH | §4: separate `lens_fog` class in labels; DOF discriminator; capture fog episodes deliberately; consider hood/heater later. Do not ship without this handled. |
| R2 | **Forcing condensation harms fruiting crop (F8)** | HIGH (crop) | Passive-first (Stage A). If forcing: confirm no fruiting bodies, short pulses, crop owner sign-off. |
| R3 | Daylight-only biases dataset away from night, when condensation is heaviest | MEDIUM | Acknowledge gap; flash LED (5 V + MOSFET) is the fix; until then label/segment by daylight window. |
| R4 | Single fixed camera spot (999.26 coverage gap) | LOW for this goal | Calibration is a *point* measurement against the co-located sensors — one spot is fine. Not crop-wide vision. |
| R5 | Small dataset → CNN overfits | MEDIUM | Hold out whole days; heavy augmentation; transfer-learning option; ≥1 real fixture before trust. |
| R6 | fc1 CPU load from capture | LOW | Capture is subscribe+save (light); inference is bridge-side, off fc1. |
| R7 | Capture tool perturbs production by ramping camera to 1 fps | LOW | Expected + benign; tool is the "viewer". Standalone, doesn't touch snapshot/retention. |

---

## 8. Open questions / decisions deferred

- **Capture host:** fc1 (safe) vs elder-plops (needs rclpy + DDS-to-fc1 reach). Default fc1.
- **`condensation_score` storage:** new metric in `telemetry` hypertable vs new `derived_condensation` table. Lean new table (joins to `snapshots`).
- **Label taxonomy granularity:** ordinal 4-class + flags (proposed) vs binary vs continuous regression. Start ordinal.
- **CNN:** from-scratch tiny net vs transfer-learning backbone. Decide after seeing dataset size/separability.
- **ROI crop:** fixed lens-circle mask — measure the circle center/radius once framing is final.
- **Inference seam:** Python model service ↔ Node bridge (local socket/HTTP) — confirm at Stage D.
- **Lens-fog mitigation:** hood vs heater vs train-around — defer until we see how bad fog is in the data.
- **Flash LED:** which LED Santi has on hand; white ⇒ 5 V + MOSFET route.

---

## 9. Future extensions (out of scope now)

- **Night coverage:** dedicated white-flash LED (5 V rail + logic-level MOSFET gated by GPIO, sync-pulsed per frame in `fc_camera`), so capture/inference run 24/7.
- **Inside-bag microclimate:** once instruments are calibrated, point a lens at the inner bag surface (warmer mycelial microclimate) — explicitly deferred by operator.
- **Full SEED-005 water-mass observer:** psychrometric calc (RH<100%) + humidifier-actuator integral (RH≥100%) fused with this visual ground truth — the bigger arc this feeds.
- **Multi-camera coverage (999.26):** if vision goes crop-wide later.

---

## 10. References

- `.planning/seeds/SEED-005-chamber-water-mass-observer.md` — parent seed; this is source #3.
- `.planning/notes/2026-05-09-forced-condensation-operational-practice.md` — failure modes F5/F6/F8/F9, forcing durations, ops runbook.
- `.planning/seeds/SEED-004-pinning-cycle-and-vpd-mode-schema.md` — VPD/band targeting this feeds.
- `src/chambers/fc-core/fc_core/fc_camera.py` — camera node (subscriber-aware idle/active fps).
- `src/chambers/fc-core/fc_core/fc_sensors.py` — sensor topics/types (dual RH + dual temp).
- `src/chambers/fc-core/fc_core/fc_controller.py` — control topics (target/duty/mode/experiment), `actuator_qos`.
- `src/agents/alerter/src/experiment_commands.js` — `/force-condensation` command surface.
- `src/mission-control/bridge/src/` — `snapshot_helpers.js`, `frame_validate.js`, `retention.js`, `schema_migration.js` (where derived telemetry would live).
- Memory: `project_farmer_language_and_gpu` (elder-plops GPU), `project_999_27_bridge_side_derivation` (derived telemetry is bridge-side), `feedback_gap_over_noise`, `feedback_real_data_before_ship_gate_pass`, `feedback_keep_paper_trail_of_intermediates`, `feedback_ros2_cli_over_ssh_needs_explicit_dds_env`, `project_fc1_ssh_env_wrapper`.

---

*Plan written 2026-06-13 (plan-only session, no code). Next session: build the §6 capture harness + runbook, then run a passive daylight capture.*
