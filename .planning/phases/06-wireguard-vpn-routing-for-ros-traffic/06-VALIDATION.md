---
phase: 6
slug: wireguard-vpn-routing-for-ros-traffic
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-29
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Manual shell verification (networking/infra phase — no unit test framework) |
| **Config file** | none |
| **Quick run command** | `sudo wg show && ping -c 1 172.16.10.1` |
| **Full suite command** | `sudo wg show && ping -c 1 172.16.10.3 && ros2 topic echo /fc/humidity --once` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick check (`sudo wg show`)
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | WG-Pi | manual | `ssh fc1 sudo wg show` | ✅ | ⬜ pending |
| 06-01-02 | 01 | 1 | WG-Pi autostart | manual | `ssh fc1 systemctl is-active wg-quick@wg0` | ✅ | ⬜ pending |
| 06-02-01 | 02 | 1 | WG-elder-plops | manual | `sudo wg show` | ✅ | ⬜ pending |
| 06-02-02 | 02 | 1 | WG-elder-plops autoconnect | manual | `nmcli connection show wg0 \| grep autoconnect` | ✅ | ⬜ pending |
| 06-03-01 | 03 | 2 | ROS2 on elder-plops | manual | `ros2 --version` | ❌ W0 | ⬜ pending |
| 06-03-02 | 03 | 2 | CycloneDDS install | manual | `dpkg -l ros-jazzy-rmw-cyclonedds-cpp` | ❌ W0 | ⬜ pending |
| 06-04-01 | 04 | 3 | DDS unicast Pi | manual | `ssh fc1 echo \$CYCLONEDDS_URI` | ✅ | ⬜ pending |
| 06-04-02 | 04 | 3 | DDS unicast elder-plops | manual | `echo \$CYCLONEDDS_URI` | ✅ | ⬜ pending |
| 06-05-01 | 05 | 4 | E2E ROS over VPN | manual | `ros2 topic echo /fc/humidity --once` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- None — no new test files needed. All verification is CLI/shell commands on existing infrastructure.

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| WireGuard tunnel established (Pi ↔ pfSense) | D-06 | Network handshake — cannot automate without live hardware | `ssh fc1 sudo wg show` — expect peer with last-handshake timestamp |
| WireGuard tunnel established (elder-plops ↔ pfSense) | D-07 | Network state — requires live VPN | `sudo wg show` on elder-plops — expect active peer |
| Ping across mesh | D-03 | ICMP over VPN tunnel | `ping -c 3 172.16.10.5` from elder-plops; `ping -c 3 172.16.10.3` from Pi |
| ROS2 topic visible across VPN | D-09 | Requires both machines live with VPN up | From elder-plops: `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ros2 topic echo /fc/humidity --once` |
| pfSense peer registration | D-08 | pfSense WebGUI — not scriptable | pfSense WebGUI: VPN > WireGuard > Peers — FC-1 public key listed |

---

## Validation Sign-Off

- [ ] All tasks have manual verify steps documented
- [ ] Sampling continuity: check after each major task
- [ ] Wave 0: no new test files needed
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
