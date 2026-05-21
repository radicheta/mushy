# Tech-debt mini-sprint — 2026-05-20

**Trigger:** real 11h fc1 outage today (13:04 → 24:00 UTC). fc_buffer caught the gap end-to-end (huge win), but the alerter never fired, several 999.* items have commits but are still marked OPEN in the roadmap, and the credit-exhaust outage from 2026-05-17 is still untraced. Time to close the long tail.

**Sequencing:** **C → A → B**, flexible window. Each item below has a concrete acceptance line so it can ship or be deferred independently.

---

## Theme C — Housekeeping (do first; clears the deck)

### C1 — ROADMAP closure audit
Reconcile 999.* items that have commits but are still labelled OPEN.
- 999.1 — edge buffering. Closes via Phase 28 + today's validation. Accept: ROADMAP line moves to ✅ with `Closed 2026-05-20 — validated by 11h real outage, see [[project_2026_05_20_fc_buffer_real_outage_validation]]`.
- 999.36 — bridge cursor bug. Accept: ✅ with ref to commit `7660604`.
- 999.40 — bridge QoS extraction. Accept: ✅ with ref to commit `092f43f`.
- 999.32 — `pid_derivative_filter_tau` wiring. Per [[project_2026_05_11_backlog_sweep]] this went live; verify by grep + ros2 param, then ✅.

**Effort:** ~30 min, no code changes (verification + ROADMAP edits only).

### C2 — Memory cleanup
- Consolidate the three 2026-05-13 Phase-40 entries (`a_c_shipped_b_pending`, `backlogB_handoff`, `silent_downtime`) into one rolling "Phase 40 status" memory.
- Archive shipped-milestone notes (`v12_shipped`, `v121_shipped`, `v15_shipped`) — keep one-line index pointers, move bodies to `archive/`.
- Don't delete anything farmer-tagged unless explicitly confirmed.

**Effort:** ~20 min. Bounded.

### C3 — 999.31: `fc_pwm_driver` duty-history deque size mismatch
1-line fix to align the deque maxlen with the 5-min comment.
**Accept:** maxlen value matches the comment; existing pwm tests still pass.

### C4 — 999.50: ROS Jazzy deprecation
Replace `ROS_LOCALHOST_ONLY=0` with `ROS_AUTOMATIC_DISCOVERY_RANGE` + `ROS_STATIC_PEERS` in compose, setup.sh, and any systemd drop-ins.
**Accept:** fc-core comes up clean on fc1 with the new vars; no Jazzy deprecation warnings in journalctl.

### C5 — 999.52: Tier A backup misses `mushy_signal-cli-data` volume
Extend `scripts/backup-tierA/mushy-tierA-backup.sh` to tarball the volume (~99 MB, compress to ~30 MB) into the encrypted bundle.
**Accept:** next nightly Tier A bundle on the VPS includes `payload/elder-plops/signal-cli-data.tar.gz`; manual decrypt + extract reproduces a working volume in a test container.

---

## Theme A — Alerter reliability (do second; today's bug)

### A1 — 999.42: alerter watchdog uses `sht30_fresh` as controller liveness ping
**This is why today's outage didn't page you.** fc1 was dark 10h 47m, `ALERT_PI_OFFLINE_MIN=10` was set, alerter sent zero offline alerts. Watchdog is keying off the wrong signal.
**Scope:** add a real controller-liveness ping (heartbeat topic from fc_controller, or "any `fc.*` topic seen in N seconds"). Replace `sht30_fresh` watchdog with that.
**Accept:** induced fc1 outage (`docker stop` or `tailscale down` in sim) → alerter fires `pi_offline` within `ALERT_PI_OFFLINE_MIN` minutes. Real-outage attestation when next gap occurs.

### A2 — 999.39: alerter "humidifier stuck ON" false-fires during fc1 offline
Pi-offline alert lacks last-known-state; stuck-ON heuristic keeps the last value forever.
**Scope:** when sensor data hasn't arrived in N min, suppress derived-state alerts and only emit the offline alert.
**Accept:** induced offline window does not produce a "humidifier stuck" ghost alert.

### A3 *(optional)* — 999.19 + 999.22: alert link destination + farmer-tunable thresholds
Pair these (both touch alerter config + farmer surface). Defer if A1+A2 eat the budget.

---

## Theme B — PID polish (do third; only one item)

Pick **one** for the sprint. Both are real but neither is on fire.

- **B1 — 999.41**: PID bumpless re-engage hardcodes `last_output=0.15` regardless of in-band restart state. *Directly relevant to today's recovery* — when fc1 came back at 00:00 UTC, the PID re-engaged with this stale guess. Touches `fc_controller.py:973`.
  **Accept:** restart-while-in-band yields `last_output = current humidifier_duty` (not 0.15); regression test added.

- **B2 — 999.49**: in-band integrator never decays. Causes residual I-term over-humidification. Phase 28 D-09 freeze; mitigation today is just "restart fc-core" which is exactly what 999.41 also fixes the recovery for.
  **Accept:** sustained in-band period gradually decays I; new pytest covers it.

Recommendation: **B1**. It composes with today's reboot and is the smaller surface area.

---

## Theme D — Deferred (not in sprint)

- 999.53 (Anthropic token usage) — well-scoped but not blocking the chamber. Slot into next sprint.
- 999.54 (today's 14:00 partial backfill) — investigation only, low pri.

---

## Out of scope (intentional)

- Anything in v1.8 / OSS-Foray. This sprint is *closing* the v1.5–v1.7 tail, not opening new milestones.
- Memory entries for v1.5-and-earlier projects — keep historical context until farmer asks for purge.
