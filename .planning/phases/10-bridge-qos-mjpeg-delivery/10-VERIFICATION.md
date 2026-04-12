---
phase: 10-bridge-qos-mjpeg-delivery
verified: 2026-04-12T15:45:00Z
status: human_needed
score: 2/5 must-haves verified (all 3 observable truths require live system)
overrides_applied: 0
human_verification:
  - test: "Bridge restart replays humidifier last-known state"
    expected: "After `docker compose restart bridge` on elder-plops, the Mission Control humidifier-state chart immediately shows the correct last-known state — no blank gap"
    why_human: "Requires live bridge container + Pi publishing on fc1/actuators/humidifier; TRANSIENT_LOCAL replay can only be observed end-to-end"
  - test: "MJPEG delivers continuous frames for 60+ seconds"
    expected: "`curl -s http://10.68.155.50:8081/camera/mjpeg --max-time 65 -o /dev/null -w 'Downloaded %{size_download} bytes in %{time_total}s'` returns >100KB OR Mission Control camera feed shows continuous updates without freezing"
    why_human: "Requires live Pi with fc_camera running and DDS bridged through to elder-plops; cannot verify without active camera stream"
  - test: "No 192.168.1.193 phantom peer errors in fc-core logs"
    expected: "`ssh ubuntu@100.96.239.75 'journalctl -u fc-core.service --since 5min | grep 192.168.1.193'` returns zero lines"
    why_human: "Requires SSH access to Pi; runtime DDS peer state cannot be verified from repo inspection alone"
---

# Phase 10: Bridge QoS & MJPEG Delivery Verification Report

**Phase Goal:** Mission Control accurately replays the last humidifier state on bridge restart, and the live camera feed delivers continuous frames without phantom-peer stalls
**Verified:** 2026-04-12T15:45:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Restarting the bridge container causes the Mission Control humidifier-state chart to immediately show the correct last-known state — no blank gap or stale pre-restart value | ? HUMAN NEEDED | Code change is correct and wired; end-to-end replay requires live Pi + bridge container running |
| 2 | The `/camera/mjpeg` endpoint delivers a continuous stream (visible frame updates every ~1 second) for at least 60 seconds without stalling during normal operation | ? HUMAN NEEDED | Cannot verify without live fc_camera publishing and Pi reachable |
| 3 | `journalctl -u fc-core.service` on the Pi shows no repeated write-retry or peer-unreachable log lines referencing `192.168.1.193` after the CycloneDDS peer cleanup is deployed | ? HUMAN NEEDED | Requires SSH to Pi; runtime DDS state not inspectable from repo |

**Score:** 0/3 truths independently verifiable (all require live system); code correctness confirmed for T1 and T3 setup — see artifact section for what is verified programmatically.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/mission-control/bridge/src/index.js` | Humidifier subscription with TRANSIENT_LOCAL QoS | VERIFIED | `humidifierQos` object at lines 312-318: `KEEP_LAST`, depth 1, `RELIABLE`, `TRANSIENT_LOCAL`. Passed as `{ qos: humidifierQos }` 3rd arg at line 324. Startup log at line 331. All 4 other subscriptions (humidity, temperature, co2, camera) remain 3-arg form — unchanged. |
| `scripts/pi-deploy/cyclonedds.xml` | Pi-side CycloneDDS config with tailscale0, no phantom IP | VERIFIED | Uses `tailscale0`, `AllowMulticast=false`, `LeaseDuration 5s`, peers `100.96.10.66`/`100.96.239.75`. No `192.168.1.193`. Updated from WireGuard (`wg0`/`172.16.10.x`) to Tailscale in commit `c9ea753`. |
| `scripts/pi-deploy/cyclonedds-tailscale.xml` | Production Tailscale config, no stale "Temporary" comment | VERIFIED | Uses `tailscale0`, `AllowMulticast=false`, explicit Tailscale peers. Comment updated to "Production config — Tailscale replaced WireGuard in Phase 09". No `192.168.1.193`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `index.js` humidifier subscription | `fc_controller.py` actuator_qos | `TRANSIENT_LOCAL` QoS profile (`KEEP_LAST`, depth=1, `RELIABLE`, `TRANSIENT_LOCAL`) | VERIFIED | QoS parameters in `index.js` exactly match `fc_controller.py` lines 91-96. Both use depth=1, KEEP_LAST, RELIABLE, TRANSIENT_LOCAL. |
| `scripts/pi-deploy/cyclonedds.xml` | `/etc/cyclonedds-tailscale.xml` on Pi | `fc-update.service` pulls `fc1/prod` branch; `fc-system-sync.service` stages configs | PARTIAL | `fc-system-sync.service` only copies netplan and `fc-core.service` — it does NOT copy `cyclonedds*.xml` to `/etc/`. `deploy.sh` also does not copy CycloneDDS XMLs. The live `/etc/cyclonedds-tailscale.xml` was confirmed clean by Phase 09's work, and `fc-core.service` points to it via `CYCLONEDDS_URI`. The repo config update is a documentation sync — no automated mechanism deploys it. |

**Note on PARTIAL key link:** The plan claimed deployment via `deploy.sh`, but `deploy.sh` only does `git pull + colcon build + systemctl restart fc-core` — it does not copy any XML files to `/etc/`. The CycloneDDS config on the live Pi was confirmed correct during Plan 02 execution (Phase 09 had already deployed it). The repo sync is valuable for preventing future drift, but the deployment link is not mechanically automated. This is not a blocker — the live Pi state is confirmed correct per the SUMMARY — but future deploys that change `cyclonedds.xml` will require a manual `sudo cp` or an update to `fc-system-sync.service`.

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `index.js` humidifier subscription | `msg.data` (Bool from ROS topic) | `/fc1/actuators/humidifier` DDS topic (fc_controller.py TRANSIENT_LOCAL publisher) | Depends on live Pi publishing — code path is correct | FLOWING when Pi online |
| `index.js` MJPEG pushFrame | `jpegBuffer` (CompressedImage from ROS) | `/fc1/camera/compressed` DDS topic (fc_camera.py) | Depends on live camera running at ~1 frame/min | FLOWING when Pi camera online |

### Behavioral Spot-Checks

Step 7b: SKIPPED — behavioral verification requires live bridge container and Pi; all relevant checks are in the human verification section.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TDEBT-01 | 10-01-PLAN.md | Bridge subscribes humidifier with TRANSIENT_LOCAL QoS so last state replays on restart | SATISFIED (code) / ? (runtime) | `index.js` contains correct QoS implementation; runtime replay requires human verification |
| TDEBT-02 | 10-02-PLAN.md | MJPEG delivers continuous frames; no 192.168.1.193 phantom peer errors | SATISFIED (config) / ? (runtime) | Repo configs confirmed clean; no phantom IP; LeaseDuration 5s added; runtime verification requires Pi SSH + live stream |

**Orphaned requirements check:** TDEBT-03 and CONN-01 are mapped to Phase 09 in REQUIREMENTS.md — not orphaned for Phase 10. No Phase 10 orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| No anti-patterns found | — | — | — | — |

Scanned: `src/mission-control/bridge/src/index.js`, `scripts/pi-deploy/cyclonedds.xml`, `scripts/pi-deploy/cyclonedds-tailscale.xml`. No TODOs, FIXMEs, placeholders, stale comments, or stub patterns. QoS implementation is complete and substantive.

### Human Verification Required

#### 1. Bridge Restart — Humidifier State Replay (TDEBT-01 / SC1)

**Test:** On elder-plops:
```
cd /mnt/slime-kingdom/opt/mushy
docker compose up -d --build bridge   # if not already rebuilt after commit 5e8b8e4
docker compose logs --tail=10 bridge | grep -i "transient_local\|humidifier"
docker compose restart bridge
```
Then immediately open Mission Control at `http://10.68.155.50:8080` and check the humidifier-state chart.

**Expected:** 
- Log line: `[bridge] Humidifier subscription: TRANSIENT_LOCAL QoS (replays last state on restart)`
- Humidifier chart shows the correct last-known state immediately after restart — no blank gap, no waiting for the next state change

**Why human:** Requires live Pi with fc_controller publishing on the humidifier topic. TRANSIENT_LOCAL late-joiner replay only works end-to-end with an active DDS participant holding the cached message.

---

#### 2. MJPEG Continuous Frame Delivery (TDEBT-02 / SC2)

**Test:** From elder-plops, run for 65 seconds:
```
curl -s http://10.68.155.50:8081/camera/mjpeg --max-time 65 -o /dev/null -w "Downloaded %{size_download} bytes in %{time_total}s\n"
```
Or watch Mission Control camera feed for 60+ seconds.

**Expected:** Download size >100KB (confirming frames delivered). No freeze or stall visible in Mission Control.

**Why human:** Requires live Pi with fc_camera running and DDS bridged to elder-plops. At current 1 frame/min rate (configured per 4G thrift), download size will be modest (~24KB per frame). If testing, consider temporarily bumping `camera_fps` for the duration.

---

#### 3. No Phantom Peer Errors in fc-core Logs (TDEBT-02 / SC3)

**Test:** SSH to Pi and check recent logs:
```
ssh ubuntu@100.96.239.75 "journalctl -u fc-core.service --since '5 minutes ago' | grep 192.168.1.193"
```

**Expected:** Zero output (no matches).

**Why human:** Requires SSH access to Pi; DDS runtime peer state cannot be read from the repo.

---

### Gaps Summary

No hard gaps found. All code changes are correct, substantive, and wired. Both commits (`5e8b8e4`, `c9ea753`) exist in git history.

The three human verification items are the only remaining open items — they represent runtime confirmation of behaviors that are correct in code but depend on the live Pi + bridge stack being active.

**One structural note** (not a gap, but worth logging): The `scripts/pi-deploy/cyclonedds.xml` update has no automated deployment path to `/etc/` on the Pi. `fc-system-sync.service` handles `fc-core.service` and netplan but not CycloneDDS XMLs. If a future change to `cyclonedds.xml` needs to land on the Pi, a manual `sudo cp` is required or `fc-system-sync.service` must be extended. The current live state is correct; this is a future drift risk only.

---

_Verified: 2026-04-12T15:45:00Z_
_Verifier: Claude (gsd-verifier)_
