# Phase 32 — VPS multi-purpose hub (WireGuard MVP) — CONTEXT

**Status:** scaffolded 2026-05-10 mid-session for an IT all-nighter execution.
**Source:** DECISION-6 in `.planning/notes/2026-05-09-fire-conversation.md` (Hetzner CX22 Nuremberg provisioned 2026-05-09 at the fire).

**Scope cut for tonight (operator-locked 2026-05-10):**
- Workloads: WireGuard hub ONLY tonight
- Peers tonight: fc1 + elder-plops + gumbald (operator laptop) + zoy (beta-tester #1)
- Heartbeat receiver, uptime-kuma, borgbackup → DEFERRED to Phase 33+ (separate session)

## Decisions (locked from DECISION-6 unless noted)

| ID | Decision | Source |
|----|----------|--------|
| D-01 | **Provider:** Hetzner CX22 (~$4.50/mo, 2 vCPU / 4 GB RAM / 40 GB SSD / 20 TB bw) | DECISION-6 (locked after Vultr/DO comparison) |
| D-02 | **Region:** Nuremberg | DECISION-6 (operator chose 2026-05-09 over Ashburn — cheaper in practice; ~200ms latency to Uruguay is non-issue for WG/backup workloads) |
| D-03 | **OS:** Hetzner-default Ubuntu 24.04 LTS (assumed; verify on first SSH) | Standard Hetzner image |
| D-04 | **SSH bootstrap path:** root password from Hetzner console → push operator's SSH key → disable password auth | Operator-confirmed 2026-05-10 (key not yet pushed) |
| D-05 | **Hardening baseline:** UFW (allow 22/tcp + WG port; deny everything else), key-only SSH (no password, no root password login after key push), fail2ban for SSH, unattended-upgrades for security patches | DECISION-6 risk-acknowledgement section |
| D-06 | **WireGuard subnet:** `10.66.0.0/24` (avoids conflict with existing fc1↔elder-plops `wg0` on `172.16.10.0/24`); hub = `10.66.0.1`; peers numbered down from `.10` | NEW — locked tonight |
| D-07 | **WG port:** `51820/udp` (default) | NEW — keep default unless reason to randomize |
| D-08 | **WG interface name on peers:** `wg-hub` (not `wg0` — fc1 and elder-plops already have a `wg0` for their direct LAN tunnel; they need both to coexist) | NEW — coexistence-driven |
| D-09 | **Peer topology:** hub-and-spoke; only hub has a public endpoint; spokes connect outbound; AllowedIPs scoped per-peer (NOT full mesh tonight) | DECISION-6 + simplicity |
| D-10 | **Beta-tester scope:** zoy (or first named contact) gets a peer config that can reach the hub + can route to mushy services via the hub. Full-mesh access to fc1 deferred to a later phase decision (security/blast-radius review). | DECISION-6 open-question 2 — answered "scope down for tonight" |
| D-11 | **DNS:** use bare IP for tonight; A-record/subdomain pointing at the VPS = follow-up | DECISION-6 silent on this; tonight-only deferral |
| D-12 | **Existing wg0 (fc1↔elder-plops over LAN) stays primary** for chamber-control DDS traffic. The VPS hub is additive, NOT a replacement. fc1 and elder-plops join the hub as outside-in observability peers; they do NOT route DDS through the hub. | NEW — must preserve memory `feedback_stopping_tailscaled_kills_pid` lesson (don't break the existing transport) |
| D-13 | **Connection info capture:** all secrets (private keys, hub endpoint, peer configs) get committed to a NEW location, NOT to the public repo. Use `~/.config/mushy-vps/` on operator's laptop + git-encrypt for repo storage IF anything needs to ship in repo. | NEW — security |

## Open questions (answer as we go)

- VPS public IP (capture on first SSH; commit to memory + Phase 32 docs)
- Operator's SSH key path on gumbald (default `~/.ssh/id_ed25519.pub`?)
- zoy's contact for sending the .conf file (Signal? farmOS people directory?)
- IP forwarding: hub-and-spoke peers need to talk to each other? For tonight: zoy → hub → fc1 NOT enabled (D-10); fc1 ↔ elder-plops via VPS hub if direct LAN is down — needs sysctl `net.ipv4.ip_forward=1` + UFW forward rules + WG AllowedIPs that include all peer subnets. Decision-on-the-fly when we get there.

## What's NOT in scope tonight

- Heartbeat receiver / outage-alert relay (Phase 33 candidate)
- uptime-kuma outside-in monitoring (Phase 33 candidate)
- borgbackup / restic offsite backups (Phase 34 candidate)
- Public status page
- Multiple beta-testers (only zoy tonight; runbook for adding more = Task 8)
- Removing the existing `wg0` LAN tunnel (it stays; D-12)
- DNS / TLS / web frontend on the VPS
- Any service exposed on the VPS beyond SSH + WG

## Composition with existing memories

- `project_fc1_link_architecture_options` — VPS path now CHOSEN, no longer fallback (per DECISION-6)
- `project_fc1_cgnat_confirmed` — VPS hub is the workaround we're committing to
- `project_2026_05_07_fc1_reboot_unrecoverable` — outside-in monitoring (Phase 33) directly addresses this; tonight's WG hub is the prerequisite
- `project_2026_05_03_ssd_failure` — backups (Phase 34) directly mitigate; not tonight
- `feedback_stopping_tailscaled_kills_pid` — applies; D-12 enforces the don't-break-existing-transport rule

## Acceptance for Phase 32 (tonight)

1. VPS reachable via SSH key (no password) from gumbald
2. UFW + fail2ban + unattended-upgrades active and verified
3. WireGuard hub running; `wg show` reports interface up with at least 4 configured peers (fc1, elder-plops, gumbald, zoy)
4. From gumbald: `ping 10.66.0.1` succeeds via wg-hub
5. From fc1: `ping 10.66.0.1` succeeds via wg-hub (does NOT break existing wg0 to elder-plops — verify `ssh ubuntu@172.16.10.5` still works after wg-hub up)
6. From elder-plops: `ping 10.66.0.1` succeeds via wg-hub
7. zoy receives a tested .conf file (peer config validated by us before send)
8. Runbook in `32-RUNBOOK.md` for adding a new beta-tester peer (so future ones don't need this same all-nighter)
