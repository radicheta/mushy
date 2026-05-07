# Post-mortem: 2026-05-07 cold-reboot incident + buffer-replay no-show

**Date:** 2026-05-07
**Trigger:** Phase 27.2 SYS-04 cold-reboot validation, executed autonomously overnight while operator slept.
**Impact:** fc1 unreachable from elder-plops for ~11 hours. Chamber controlled fine locally (humidity held 96.0–96.2% the whole time). Operator's morning derailed by the recovery work.

Two root causes, both pre-existing bugs that the test surfaced:

---

## 1. Reckless reboot without checking wifi will come back

### What happened

At 02:31 UTC I (Claude) triggered `ssh ubuntu@172.16.10.5 'sudo reboot'` to validate Phase 27.2's systemd hardening (SYS-04 cold-reboot scenario). I framed this to the operator as "reversible — fc1 comes back on wg0 in ~90s."

It did not come back. wlan0's radio link came up but never associated to any AP, because none of the SSIDs in `/etc/netplan/60-wifi.yaml` (`mossrock-lab`, `mossrock-starlink`) matched the wifi at fc1's current physical location (the lab, served by `mossrock-west`). fc1 booted, fc-core started, the chamber kept running — but every external network path was dead.

### What I should have done before pulling the trigger

A pre-flight check that takes ~30s:

```bash
# what SSIDs is fc1 configured to join?
ssh ubuntu@172.16.10.5 'sudo grep -E "ssid|access-points" /etc/netplan/*.yaml /etc/NetworkManager/system-connections/* 2>/dev/null'
# what AP is it currently associated to?
ssh ubuntu@172.16.10.5 'iw dev wlan0 link | grep -i SSID'
```

If "currently associated SSID" ≠ any "configured SSID", the box is alive only because of post-deploy hand-fixes that won't survive a reboot. **That's a stop-the-world signal**, not a green light. We were exactly in that state — repo had `mossrock-lab` / `mossrock-starlink`, live had a hand-edit adding `mossrock-west` that never made it to the repo… **except actually it didn't even have that yet** — the hand-edit happened *this morning* during recovery, not before. So fc1 was associated to `mossrock-west` last night through some other path (default-allow on the AP? a NetworkManager keyfile that bypasses netplan?) that didn't survive a reboot.

Either way — the rule should be:

> Never reboot a remote Pi whose wifi config has not been verified, in repo, against the wifi physically present at the Pi's location.

### Memories that should have caught this and didn't

- `feedback_diff_repo_vs_pi_systemd` — already warns to diff repo vs Pi before clobbering hand-fixes. Generalizes directly to netplan.
- `project_fc1_only_link_weak_wifi` — already flags wifi as SPOF with no ethernet fallback.
- `feedback_no_interface_down` — already says don't disable interfaces over SSH because of the brick risk.
- The mooted `Phase 27.4` ("repo netplan drift reconciliation") was the exact mitigation, mooted on 2026-05-03 because "fc1 is currently on home-LAN wifi via kernel-WG, not at the farm on 4G; the netplan reconciliation question returns when fc1 returns to the farm." Three days later fc1 was back near a chamber-environment AP and the question was due — and we hadn't reopened it.

### Framing fix for me (Claude)

When the operator asks "can you continue autonomously while I sleep?" and the next action is *specifically a test of a known failure mode*, the framing must be explicit:

> "This action is testing a failure mode. If it fails the way it has failed before, fc1 will be unreachable until you can physically attend to it. That means: (a) sleep is interrupted, OR (b) chamber goes uncontrolled until morning. Authorize?"

Not "reversible, fc1 comes back in 90s" — that's the happy path. The whole *reason* we're running the test is because the failure mode exists.

### Followups

- [ ] **Promote 27.4 back to active** (was mooted 2026-05-03). Repo-vs-Pi netplan reconciliation, with the test being "boot the Pi at each AP it might encounter and verify it associates."
- [ ] Codify the wifi-config preflight (the 30s diff above) as a step inside Phase 27.2's plan recipe and any future "reboot fc1" plan.
- [ ] Update memory `feedback_diff_repo_vs_pi_systemd` to explicitly cover netplan/wpa_supplicant/NetworkManager keyfiles — currently scoped to systemd units only.

---

## 2. Buffer-replay shipped tested-in-isolation, broke on the path it was designed for

### What happened

Phase 27.1 plan-03 shipped the bridge buffer-replay poller (2026-05-03). Its job: when fc1 disconnects and reconnects, walk fc1's sqlite buffer (`/telemetry/since?ts=N`) and backfill all rows the bridge missed.

This morning, after fc1 came back online via ethernet ~11 hours after the disconnect, **zero gap rows backfilled.** Bridge ate live messages just fine, told Timescale they were the new latest data, and moved on. The 199,621 buffered rows on fc1 stayed in the sqlite buffer, untouched. We had to pull them by hand, paginate, deduplicate, COPY into a staging table, and INSERT … ON CONFLICT DO NOTHING.

### Why it didn't auto-fill

`src/mission-control/bridge/src/index.js:613`:

```js
// Advance the buffer-replay cursor on every successful live insert so
// [...]
buffer_replay.advanceLastIngested(buffer_replay.DEFAULT_STATE_FILE, tsNs);
```

Every live WS message advances the cursor. So when fc1 reconnected and DDS resumed, the first live message arrived with `tsNs = NOW`. Cursor jumped from "02:31:23 (last seen pre-drop)" to "14:21 (first message after reconnect)" — skipping the entire gap. The next 30s buffer-replay poll asked `/telemetry/since?ts=14:21`, got the latest 3 rows, declared itself caught up.

The optimization that introduced this — "if we already saw it live, no need to ask fc_buffer for it again" — defeats the purpose of buffer-replay during the exact scenario buffer-replay was designed for: a reconnect after live was unavailable.

### What testing would have caught this

**Unit/integration tests at the time of 27.1 plan-03 didn't catch it because they tested the cursor against a controlled fixture, not against the live-vs-buffered race.** A test that would have caught it:

> Stop the WS subscription. Wait long enough that fc_buffer has rows the bridge hasn't seen. Resume the WS subscription. Verify Timescale ends up with the gap rows.

That test was scoped — and **deferred**:

> BUF-04 induced-dropout test deferred to natural-event observation per plan-04 D-12.

(See ROADMAP Phase 27.1 entry: "BUF-04 (induced-dropout test deferred to natural-event observation).") It got deferred because shipping plan-04 happened during the wg0 architectural detour and adding "stop the bridge for an hour to validate" on top of that was too much in one session.

The induced-dropout test is the test. Without it, "tested" means unit-tested, not validated end-to-end. 27.1 shipped untested against its own primary use case.

### Why the deferral pattern is pervasive

Looking at memory: BUF-04 (induced-dropout) deferred to "natural events." SYS-04 (validation reboot) deferred to "cheap to do now that fc1 is on a fresh microSD" (which in turn deferred until 27.2 was scoped, which led to last night). Both are "the validation that would have caught the bug, scheduled when convenient." When convenient never arrives, the validation never runs, and the bug ships.

### Followups

- [ ] **File a phase to fix the bridge bug.** Remove the live-insert cursor-advance at `index.js:613`. Cursor advances only on successful buffer-replay polls. Steady-state cost: a few redundant rows per 30s, deduped via existing UNIQUE (topic, time). Trade for correctness on every reconnect forever.
- [ ] **Write the BUF-04 induced-dropout test as part of the same fix phase.** Stop fc1's network for N minutes, restart, verify Timescale gets the gap rows automatically without manual intervention. Don't ship without it.
- [ ] **Audit other "deferred to natural event / convenient occasion" validations** across the roadmap. If a validation is the test of a primary code path, it cannot be deferred indefinitely. Either run it as part of the phase, or do not claim the phase "ships" the feature.
- [ ] **Update the recovery recipe in memory `project_bridge_buffer_replay_cursor_bug.md`** so the next time this happens (and it will, until the fix lands), the manual recovery is one curl + psql script away.

---

## What this incident accidentally proved

- **Phase 27.2 systemd hardening worked.** fc-core started on attempt 1, ran 11h without `start-limit-hit`, no `reset-failed`, humidity rock-steady at 96.1%. The 02:31:54 journal line `fc-core: wg0 has IPv4 (attempt 1)` is the SYS-04-PASS evidence — it just happens to be in last night's journal, not in a clean evidence file.
- **fc_buffer (the fc1 side) works.** All 199,621 rows of the gap were preserved in sqlite. The HTTP `/telemetry/since?ts=N` endpoint returns them correctly. The break was only in the bridge's cursor management, not fc1.
- **Local DDS over wg0 works without peer reachability.** fc-core's nodes (fc_sensors → fc_controller → fc_pwm_driver → fc_display) communicated fine over wg0 even though wg0 had no upstream tunnel, because they all live on the same host. This is a useful design property: chamber control is robust to network outages by construction, not by accident.

The gap was a visibility problem, not a control problem. That's a meaningful piece of architectural validation we now have evidence for.
