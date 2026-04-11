# Phase 09: Connectivity & Boot Stability - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning

<domain>
## Phase Boundary

fc1 Pi is reliably reachable from elder-plops at the farm via a 4G hotspot
path, and `fc-core.service` starts cleanly on every cold boot without
restart loops waiting for `tailscale0`.

Scoped in:
- CONN-01: 4G hotspot provisioning + Pi WAN path + Tailscale reachability
  from remote elder-plops sessions
- TDEBT-03: fc-core.service cold-boot race fix (tailscale0 readiness)
- WAN-blip auto-recovery behavior (success criterion 2)
- Cold-boot verification procedure (success criteria 3 and 4)

Explicitly out of scope:
- Bridge QoS / humidifier last-state replay (Phase 10, TDEBT-01)
- MJPEG stall / phantom CycloneDDS peer cleanup (Phase 10, TDEBT-02)
- Any dashboard/UI work on Mission Control
- Refactor of fc_core, fc_camera, or bridge architecture
</domain>

<decisions>
## Implementation Decisions

### 4G Hotspot Path

- **D-01:** WAN is delivered by a standalone 4G MiFi device living
  **physically next to the Pi** inside the chamber area. No long-range
  WiFi bridge, no 40m Ethernet run.
- **D-02:** Pi connects to the MiFi over its built-in `wlan0`. Short
  (<1m) WiFi hop — 2.4GHz is acceptable, signal loss is a non-issue at
  that distance.
- **D-03:** MiFi hardware is user-supplied (already being sourced —
  see memory `project_4g_hotspot.md`). Plan does NOT procure hardware;
  it assumes a configured MiFi with active 4G plan is available during
  execution. If it isn't, that's a human checkpoint blocker, not a task.
- **D-04:** No failover path. 4G is the sole WAN. If the cellular link
  drops, the system waits for cellular to return — Tailscale + the kernel
  route table handle reconnection naturally.
- **D-05:** No static IP / reservation requirements. Tailscale handles
  addressing end-to-end; the MiFi's LAN DHCP lease to the Pi is
  irrelevant as long as it's stable within a session.

### Boot Race Fix (TDEBT-03)

- **D-06:** Fix combines BOTH systemd ordering AND explicit interface
  readiness:
  - Add `After=tailscaled.service` and `Wants=tailscaled.service` to
    `fc-core.service`
  - Add an `ExecStartPre=` that polls for `tailscale0` (max ~30s with
    a short sleep loop), then exits successfully once the interface is
    present
  - Keep `Restart=on-failure` and `RestartSec=5` as the existing safety
    net, but expected healthy cold boot should produce ZERO automatic
    restarts (per success criterion 3)
- **D-07:** No new `wait-for-tailscale0.service` oneshot unit. Inline
  `ExecStartPre` is fewer moving parts for a one-consumer problem.
  Revisit if Phase 10 needs another service to wait on the same
  condition.
- **D-08:** Fix ships on the `fc1/prod` git branch and deploys via
  `deploy.sh` per project convention (memory:
  `feedback_deploy_method.md`). `fc-update.service` (existing boot-time
  git-pull) will pick it up on the next boot after merge.

### WAN-Blip Recovery Behavior (CONN-01)

- **D-09:** Target behavior: fc-core stays running through a hotspot
  off/on cycle. Tailscale + DDS peers resync automatically once the
  route returns. No fc-core restart on WAN loss, no netlink watchdog,
  no custom reconnect code.
- **D-10:** Acceptance target: after hotspot is toggled back on,
  `ros2 topic echo /fc1/humidity` from elder-plops returns a reading
  within **30 seconds**. This is the concrete bar for success criterion 2.
- **D-11:** Simulated WAN blip procedure: toggle the MiFi's 4G radio
  off (via its control interface) then back on, rather than
  power-cycling the whole MiFi. Avoids re-running DHCP/association on
  the Pi side when the goal is testing WAN recovery, not WiFi recovery.

### Verification Procedure

- **D-12:** User is both operator and grower (memory:
  `user_operator_and_grower.md`). Physical verification at the farm is
  feasible — no Signal handshake with a separate grower needed.
- **D-13:** Success criterion 3 (zero-restart cold boot) is verified by
  pulling the plug (real cold boot, not `sudo reboot`) during an
  on-site visit, then reading `journalctl -u fc-core.service -b` via
  Tailscale SSH once the Pi is back.
- **D-14:** Success criterion 4 (Mission Control reachable within 30s
  of Pi boot) is verified from elder-plops on the same visit, timed
  by hand against the Pi boot moment.
- **D-15:** Success criterion 1 (`/fc1/humidity` reachable from
  elder-plops over 4G) MUST be verified from AT LEAST TWO physical
  locations — farm and at least one remote location (home/office) —
  because elder-plops is expected to roam and CONN-01 is fundamentally
  about remote reachability, not just on-site reachability.

### Claude's Discretion

- Exact ExecStartPre script body (polling interval, max wait duration
  within ~30s budget, error message format)
- Whether the ExecStartPre is a one-liner in the unit or a small script
  checked into `scripts/pi-deploy/`
- Journal log phrasing for boot-race failure cases
- Whether to add any `Conflicts=` or `OnFailure=` directives
- MiFi brand/model guidance (deferred entirely to user)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — CONN-01, TDEBT-03 definitions for v1.1
- `.planning/ROADMAP.md` §Phase 09 — Goal, success criteria, dependencies

### Current Service Unit
- `scripts/pi-deploy/fc-core.service` — Current systemd unit; target of
  the TDEBT-03 fix. Note existing `After=network-online.target
  fc-update.service` — the fix ADDS to this, does not replace it.
- `scripts/pi-deploy/fc-update.service` — Boot-time git pull; already
  an `After=` of fc-core per current unit and must remain so.

### Tailscale / Networking Prior Art
- `.planning/phases/06-wireguard-vpn-routing-for-ros-traffic/` —
  Phase 06 established Tailscale as primary mesh, WireGuard as
  secondary. CycloneDDS uses Tailscale peer unicast (no multicast).
  Relevant for understanding what "tailscale0 ready" means downstream
  for fc-core's DDS discovery.

### v1.0 Milestone Audit
- `.planning/milestones/v1.0-MILESTONE-AUDIT.md` — frontmatter entry
  `cyclonedds-boot-race` documents the exact failure mode that
  TDEBT-03 fixes. Lists the ~4 restart count observed on cold boot.

### Deploy Convention
- No external doc. Convention captured in memory
  `feedback_deploy_method.md`: edit → commit → push to `fc1/prod`
  branch → `deploy.sh` from elder-plops. fc-update.service also
  pulls on boot.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **scripts/pi-deploy/fc-core.service** — existing systemd unit; this
  phase extends the `[Unit]` section with an additional `After=` and
  adds one `ExecStartPre=`. No new unit file needed.
- **scripts/pi-deploy/fc-update.service** — already exists as an
  `After=` dep of fc-core and handles the git-pull-on-boot pattern.
  fc-update itself does NOT have a tailscale0 dep and does not need
  one (it only needs general network).
- **deploy.sh** (assumed at repo root or scripts/) — the sanctioned
  deploy path per memory. The plan should use this, not rsync.

### Established Patterns
- **Systemd unit deploy via git branch** — Pi pulls from `fc1/prod`
  branch. Any unit file change lands in the working tree and is
  activated on next boot or via `systemctl daemon-reload` + restart.
- **Tailscale-first DDS** — `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`
  and `CYCLONEDDS_URI=file:///etc/cyclonedds.xml` already set in
  the unit's Environment. Peers are listed explicitly in the
  CycloneDDS XML (set up in Phase 06).
- **On-failure restart with 5s backoff** — `Restart=on-failure
  RestartSec=5` already in the unit. Keep as safety net; do not
  rely on it for the happy-path cold boot.

### Integration Points
- **Pi's `/etc/cyclonedds.xml`** — the peer list lives on the Pi,
  not in this repo. Out of scope for this phase but relevant for
  Phase 10's phantom-peer cleanup.
- **Tailscale node `fc1-ts`** — existing Tailnet identity for the Pi
  (used in memory `project_network.md` and Phase 06 verification).
- **elder-plops Tailscale client** — existing roaming client; used for
  the roaming verification in D-15.

</code_context>

<specifics>
## Specific Ideas

- "Belt and suspenders" was the chosen framing for the boot race fix:
  systemd ordering AND an explicit interface probe, not one or the other.
- Concrete WAN-recovery bar is **30 seconds**, measured by
  `ros2 topic echo /fc1/humidity` returning from elder-plops after the
  MiFi 4G radio is toggled back on.
- MiFi lives physically beside the Pi, not in a main building. fc1 is
  about 40 meters from main infrastructure and there is no 40m cable or
  long-range WiFi to that main infra — the Pi's WAN path is entirely
  self-contained within the chamber area.
- Remote access must work from multiple locations, not just one "home
  base". elder-plops roams; Tailscale must reach fc1 from wherever it
  lands.
</specifics>

<deferred>
## Deferred Ideas

- **Cellular failover / backup WAN path** — single 4G uplink is fine
  for v1.1. A redundant path (second MiFi, Starlink, wired) is a
  future-milestone concern if cellular reliability disappoints.
- **Alerts on WAN loss** — Phase 999.3 (Signal alerts backlog)
  covers this. Out of scope here.
- **MiFi hardware selection / procurement docs** — user is sourcing
  the device independently; plan treats it as a given.
- **fc_core self-reconnect logic for DDS peer loss** — current
  behavior (stays up, lets Tailscale + DDS discovery handle it) is
  accepted as the target. No code change to fc_core for WAN blips.
- **wait-for-tailscale0.service as a reusable oneshot** — inline
  ExecStartPre is enough today. Revisit if Phase 10 or later phases
  need to share the wait-for-interface behavior.
</deferred>

---

*Phase: 09-connectivity-boot-stability*
*Context gathered: 2026-04-11*
