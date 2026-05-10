---
phase: 32-vps-multi-purpose-hub
plan: 01
subsystem: infra
tags: [vps, wireguard, hardening, beta-tester, all-nighter]
autonomous: false
requires: []
provides:
  - "Hetzner CX22 Nuremberg hardened (UFW, fail2ban, key-only SSH, unattended-upgrades, locales)"
  - "WireGuard hub on 10.66.0.0/24, port 51820/udp"
  - "5 peers connected: fc1, elder-plops, farmer1 (Android, ACTIVE), farmer2 (Android, configured), farmer3 (iOS, configured)"
  - "Bridge CORS_ORIGIN extended to allow http://10.66.0.12:8080"
  - "32-RUNBOOK.md (peer add/revoke/debug)"
affects: [fc1, elder-plops, farmers#1/#2/#3]

duration: ~3hrs (one session, IT all-nighter style)
completed: 2026-05-10
---

# Plan 32-01 Summary — VPS WireGuard hub MVP

**Status:** SHIPPED 2026-05-10. Farmer #1 (Android, off-network) **reaching Mission Control via brand-new VPS** — acceptance criterion HIT live in-session.

## Performance

- **Duration:** ~3 hours wall-clock (one continuous session)
- **Peers configured tonight:** 5 (farmer1, fc1, elder-plops, farmer2, farmer3)
- **Acceptance criteria from CONTEXT:** 7/8 hit live (T3 gumbald skipped by operator decision)

## Accomplishments

### T0 — SSH bootstrap
- Pushed elder-plops SSH key to root@VPS via initial password
- Created `mushy` admin user (uid 1000, sudo, NOPASSWD)
- Both elder-plops and gumbald keys in `/home/mushy/.ssh/authorized_keys`
- Fixed key comment metadata (santi@boat.media → santi@mossrock.space) on both elder-plops `.pub` source and VPS authorized_keys
- gumbald SSH config: added `Host vps mushy-vps 178.105.84.13` stanza with `IdentitiesOnly yes` (workaround for MaxAuthTries overflow caused by 8+ keys in agent)

### T1 — Hardening
- `apt update + upgrade` clean
- Installed: `ufw fail2ban unattended-upgrades wireguard wireguard-tools qrencode locales-all`
- UFW: deny-incoming, allow `22/tcp` + `51820/udp` + forwarding within `wg-hub` interface
- fail2ban active (caught 17 SSH probes within minutes of provisioning — public IPs get scanned fast)
- unattended-upgrades enabled
- SSH locked down: `PermitRootLogin no`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no` via `/etc/ssh/sshd_config.d/00-mushy-hardening.conf` (filename prefix `00-` ensures it loads BEFORE cloud-init's `50-cloud-init.conf` which sets `PasswordAuthentication yes`; sshd uses first-wins semantics)

### T2 — WireGuard hub
- IP forwarding sysctl drop-in `99-wg-forward.conf` (`net.ipv4.ip_forward=1`)
- Hub keypair generated on VPS (`/etc/wireguard/hub.{key,pub}`)
- `wg-hub.conf` with `[Interface]` at `10.66.0.1/24`, `ListenPort = 51820`
- `wg-quick@wg-hub` enabled + started; interface up
- Latency baseline: ~243ms RTT from Uruguay to Nuremberg (matches DECISION-6 ~200ms estimate)

### T4 — fc1 peer (10.66.0.11)
- Generated fc1's keypair on fc1 (`/etc/wireguard/fc1-hub.{key,pub}`)
- wg-hub.conf on fc1 with **no ListenPort** (ephemeral, avoids conflict with existing wg0 on 51820)
- Both tunnels coexist: wg0 (LAN to elder-plops at 172.16.10.0/24) for chamber DDS + wg-hub (to VPS at 10.66.0.0/24) for outside-in
- **D-12 verified:** fc1's existing wg0 + fc-core + DDS all unaffected post wg-hub bring-up

### T5 — elder-plops peer (10.66.0.12)
- Keypair generated locally on elder-plops
- wg-hub.conf with hub as the only peer
- Bridge `CORS_ORIGIN` env extended to include `http://10.66.0.12:8080` (so MC dashboard JS calls succeed when accessed via wg-hub origin)
- Bridge restarted; health endpoint clean post-restart

### T6 — Farmer peers (10.66.0.20 / .21 / .22)
- **Farmer #1 (Android, 10.66.0.20):** ANSI QR generated in terminal, operator scanned in-person, tunnel UP, **MC reachable at `http://10.66.0.12:8080/` over hub — acceptance HIT**
- **Farmer #2 (Android, 10.66.0.21):** PNG QR + `.conf` written to `/tmp/farmer2-mushy-vps.{png,conf}` on elder-plops for Signal delivery
- **Farmer #3 (iOS, 10.66.0.22):** PNG QR + `.conf` written to `/tmp/farmer3-mushy-vps.{png,conf}` on elder-plops for Signal delivery
- **10.66.0.23 reserved** for the 4th shared iOS device (not configured tonight)

### T8 — Runbook
- `32-RUNBOOK.md` written: peer add/revoke recipe, ssh debug tripwires, hardening notes, architecture commentary
- `32-INVENTORY.md` (gitignored) updated with all peer pubkeys, IPs, status

## Mid-session findings (non-obvious; surfaced for future memory)

1. **Ubuntu 24 sshd_config first-wins ordering**: cloud-init's `50-cloud-init.conf` sets `PasswordAuthentication yes`; a lexically-later override (e.g. `99-mushy-hardening.conf`) is silently shadowed. Fix: name the override `00-*` or earlier than cloud-init's prefix.
2. **`sshd -t` outside systemd**: needs `/run/sshd` to exist. Either `mkdir -p /run/sshd` first or skip the precheck (`systemctl reload ssh` validates).
3. **ssh-agent MaxAuthTries overflow**: gumbald had 8+ keys loaded; ssh tried them all in order, hit server-side `MaxAuthTries=6`, fell back to password. Fix on peer side: `~/.ssh/config` host stanza with `IdentitiesOnly yes`.
4. **fail2ban activity within minutes**: 17 SSH probes hit the public IP before T1 completed. Public IPs get scanner-targeted within minutes of going live.
5. **UFW + WireGuard requires `ufw route allow in on wg-hub out on wg-hub`** for peer-to-peer through hub. Default UFW blocks forwarded traffic silently.
6. **fc1 wg-hub conflict avoidance**: existing wg0 on fc1 listens on 51820; new wg-hub must omit `ListenPort` (use ephemeral) to avoid kernel rejection. Outbound-only peers don't need a listen port anyway.
7. **CORS_ORIGIN must list every origin that loads MC**: when farmer browses via wg-hub IP, the Origin header is `http://10.66.0.12:8080`; bridge enforces CORS via env-supplied allowlist. Add new origins as needed.
8. **Ed25519 key comment is just metadata**: changing the comment field of a pubkey (the `user@host` at the end) has no auth impact; sha256 of the line changes but the key bytes don't. Cosmetic only.

## Deferred (Phase 33+ candidates)

- **Heartbeat receiver + outage-alert relay on VPS** — biggest pending value (mitigates 2026-05-07 11h-offline incident). DECISION-6 workload #3.
- **Outside-in monitoring (uptime-kuma / healthchecks.io)** — DECISION-6 workload #2. Pings fc1/elder-plops/openmct/signal-cli from outside.
- **Offsite backups (borgbackup / restic)** — DECISION-6 workload #4. Encrypted incrementals from elder-plops.
- **fc1 CycloneDDS prep for farm-4G return** — update `/etc/cyclonedds.xml` to bind to BOTH `wg0` AND `wg-hub`; when fc1 physically moves to the farm, wg0 dies but DDS auto-falls-back to wg-hub. ~30 min, blocker for fc1-at-farm return.
- **4th shared iOS device peer** (`10.66.0.23` reserved) — config when device is in hand.
- **gumbald (operator laptop) peer** (`10.66.0.10` reserved) — operator convenience; ssh into fc1/elder-plops via hub when home LAN dies.
- **DNS / TLS termination** — currently bare IP; subdomain like `vps.mossrock.space` + Let's Encrypt would be nice but not blocking anything.

## Acceptance criteria status (mirrors 32-CONTEXT)

- [x] 1. VPS SSH key-only from elder-plops + gumbald ✓
- [x] 2. UFW + fail2ban + unattended-upgrades active ✓
- [x] 3. wg-hub up, ≥4 peers configured (actually 5) ✓
- [ ] 4. gumbald → 10.66.0.1 — **SKIPPED by operator decision**, deferred
- [x] 5. fc1 → 10.66.0.1 ping ✓ AND existing wg0 still works ✓
- [x] 6. elder-plops → 10.66.0.1 ping ✓ AND existing wg0 still works ✓
- [x] 7. farmer #1 reaching MC via hub (**critical path**) ✓
- [x] 8. 32-RUNBOOK.md written ✓

7 of 8 hit; only one was an operator-skipped non-critical item.

## Self-check: SHIPPED

The all-nighter delivered the MVP from DECISION-6: a public-facing WireGuard hub on a hardened Hetzner VPS, with the chamber-side infrastructure (fc1, elder-plops) and the critical-path beta-tester (farmer #1) all connected. Farmer #1 demonstrably reaching MC via the brand-new VPS during the session is the proof-of-life acceptance.

Architecturally, the VPS hub is now ready to support fc1's eventual return to farm 4G (memory `project_fc1_cgnat_confirmed` documents that this was the only viable path; tonight made it real).
