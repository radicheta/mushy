# Condensation Dataset Capture — Runbook

**Tool:** `scripts/cv/capture_condensation_dataset.py` (SEED-005 source #3, Stage A)
**Plan:** `.planning/notes/2026-06-13-cv-condensation-detection-plan.md`

Spike instrumentation. It is a *viewer + writer* only — it does NOT touch the
production snapshot/retention pipeline. Subscribing to the camera ramps
`fc_camera` from idle to ~1 fps (expected + benign, R7).

---

## 0. Prereqs / facts

- **Runs on fc1** (has camera + cv2 + DDS). Output lands on fc1 local disk, then
  rsync to elder-plops for training.
- fc1's `rclpy`/`cv2` live in the ROS env, NOT bare `python3`. You MUST source
  both setup files and export the DDS env (same env the `fc-core` service uses):
  ```
  source /opt/ros/jazzy/setup.bash
  source /home/ubuntu/mushroom_farm_ws/install/setup.bash
  export ROS_DOMAIN_ID=69 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
         RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///etc/cyclonedds.xml
  ```
- **Daylight only** (no flash LED yet). Uruguay is UTC-3; fc1 clock is UTC.
  Winter sunset ~17:50 local (~20:50 UTC). Night frames are pure black and get
  `dark_flag=1` (recorded, not dropped). Capture during the daylight window.

---

## 1. Deploy the script to fc1

From the repo (this worktree), copy the single script to an fc1 scratch dir
(spike — do NOT push through the normal `fc1/prod` deploy pipeline):

```bash
ssh fc1 'mkdir -p /home/ubuntu/condensation-capture'
scp scripts/cv/capture_condensation_dataset.py fc1:/home/ubuntu/condensation-capture/
```

---

## 2. Smoke first (always — `feedback_smoke_before_expensive_batch`)

Short 2-minute run to confirm frames + manifest land and are NOT all dark:

```bash
ssh fc1 'source /opt/ros/jazzy/setup.bash && \
  source /home/ubuntu/mushroom_farm_ws/install/setup.bash && \
  export ROS_DOMAIN_ID=69 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
         RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///etc/cyclonedds.xml && \
  python3 /home/ubuntu/condensation-capture/capture_condensation_dataset.py \
    --out-dir /home/ubuntu/condensation-dataset --run-id smoke-01 \
    --duration-min 2 --interval-sec 15'
```

PASS criteria:
- `frames/` has ~8 JPEGs, `manifest.csv` has matching rows + a header.
- `mean_luma` is well above `--min-luma` (30) in daylight; `dark_flag=0`.
- `rh1`/`rh2` columns populated (sensors flowing), `mode` non-empty (latched
  control topic received — proves the TRANSIENT_LOCAL QoS match works).
- `run-summary.txt` written on exit.

Inspect: `ssh fc1 'tail -3 /home/ubuntu/condensation-dataset/smoke-01/manifest.csv; cat /home/ubuntu/condensation-dataset/smoke-01/run-summary.txt'`

---

## 3. Passive capture run (the dataset)

Passive-first, no forcing. The 93% fruiting limit-cycle already drives the bag
surface dry↔condensed near saturation, so just capture across daylight days.

Detached so it survives the ssh session (bounded to the daylight window):

```bash
ssh fc1 'source /opt/ros/jazzy/setup.bash && \
  source /home/ubuntu/mushroom_farm_ws/install/setup.bash && \
  export ROS_DOMAIN_ID=69 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
         RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///etc/cyclonedds.xml && \
  nohup python3 /home/ubuntu/condensation-capture/capture_condensation_dataset.py \
    --out-dir /home/ubuntu/condensation-dataset --run-id passive-$(date +%Y%m%d) \
    --duration-min 0 --interval-sec 15 \
    > /home/ubuntu/condensation-capture/passive.log 2>&1 &'
```

- `--duration-min 0` = until killed. To bound to remaining daylight, pass e.g.
  `--duration-min 90`.
- Stop cleanly (writes summary): `ssh fc1 'pkill -INT -f capture_condensation_dataset'`
- Re-running with the SAME `--run-id` appends to the manifest (paper trail kept).
- **Repeat daily** across a few daylight days to span the full dry→dripping range.

---

## 4. Pull the dataset to elder-plops (for labeling + training)

```bash
rsync -av fc1:/home/ubuntu/condensation-dataset/ /data/condensation-dataset/
```

---

## 5. Optional: controlled forced-condensation event

ONLY if the passive range never reaches `dripping`/lens-fog. Forcing has real
risk — read these gates first:

- **F8 wet-rot (crop loss):** confirm there are **no fruiting bodies in the
  chamber / in frame** before forcing. Keep pulses short. Crop-owner sign-off.
- The post-event evaporation tail (sensor stuck at 100% while the surface
  visibly clears) is calibration gold (F9) — worth one careful forced run
  *after* the passive baseline, crop permitting.
- Trigger via the alerter `/force-condensation N` command surface
  (`src/agents/alerter/src/experiment_commands.js`); the harness records the
  `experiment` column from `fc1/control/experiment_event` automatically.

---

## 6. Manifest schema

`ts_iso, frame_file, rh1, rh2, temp1, temp2, co2, rh_target, duty, mode,
experiment, mean_luma, dark_flag, label`

`label` is intentionally blank — filled in Stage B (auto-label from telemetry,
then human refine). Taxonomy: `dry/fogged/beaded/dripping` + `lens_fog` flag +
`dark/unusable` flag.
