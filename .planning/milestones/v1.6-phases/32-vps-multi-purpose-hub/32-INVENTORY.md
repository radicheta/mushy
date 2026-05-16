# Phase 32 — VPS Inventory (gitignored)

## Box

- **Provider:** Hetzner
- **Plan:** CX22 (~$4.50/mo, 2 vCPU / 3.7G RAM / 38G usable disk / 20 TB bw)
- **Region:** Nuremberg (nbg1)
- **Hostname (Hetzner default):** ubuntu-4gb-nbg1-1
- **OS:** Ubuntu 24.04.3 LTS (noble)
- **Kernel:** 6.8.0-90-generic
- **Public IP:** 178.105.84.13
- **Provisioned:** 2026-05-09 at the fire conversation (DECISION-6)
- **Billing card on file:** farmer #2 (per fire conversation note "had a credit card on hand at the fire")

## SSH access

- **Admin user:** `mushy` (uid 1000, in sudo group, NOPASSWD via `/etc/sudoers.d/90-mushy`)
- **Key auth:** elder-plops `~/.ssh/id_ed25519` (santi@mossrock.space) + gumbald `~/.ssh/id_ed25519` (santi@gumbald) — both in `/home/mushy/.ssh/authorized_keys`
- **Root SSH:** disabled (`PermitRootLogin no` via `/etc/ssh/sshd_config.d/00-mushy-hardening.conf`)
- **Password SSH:** disabled
- **gumbald SSH config:** `~/.ssh/config` aliases `vps`, `mushy-vps`, `178.105.84.13` to `mushy@…` with `IdentitiesOnly yes` (avoids MaxAuthTries overflow from 8+ keys in agent)

## Hardening (T1)

- UFW: deny incoming default; allow 22/tcp + 51820/udp + forwarding within wg-hub
- fail2ban: active (caught 17 SSH probes within minutes of provisioning)
- unattended-upgrades: active (security patches auto-applied)
- locales-all installed (silences es_UY locale warnings)

## Wireguard hub (T2 — LIVE)

- Subnet: `10.66.0.0/24`
- Hub IP: `10.66.0.1`
- Port: `51820/udp`
- Hub keys: `/etc/wireguard/hub.{key,pub}` on VPS
- Hub pubkey: `uk3YC2fiXg/Qgo0MUdv8UkJPo/9XnC7RZgN1JOnXtnc=`
- IP forwarding: `net.ipv4.ip_forward=1` (sysctl drop-in `99-wg-forward.conf`)
- UFW route: `allow in on wg-hub out on wg-hub` (peer-to-peer through hub)
- Latency baseline: ~243ms RTT elder-plops→hub (Uruguay→Nuremberg, matches DECISION-6 estimate)

## Peers

| IP | Peer | Pubkey | Status |
|---|---|---|---|
| 10.66.0.10 | gumbald (operator laptop) | (pending T3) | PENDING |
| 10.66.0.11 | fc1 | (pending T4) | PENDING |
| 10.66.0.12 | elder-plops | hraXwtijugv2HLCP4vBC6dc2WaLUhDEMPNWGiWhmiVU= | ✓ LIVE 2026-05-10 (handshake confirmed; 5ms RTT to fc1 via wg0 unaffected) |
| 10.66.0.20 | farmer #1 (Android phone) | H1Iyu84pnA9MfhhJ3Tkm4+EnDkp8a4gtlxPf+sQ2gE0= | ✓ LIVE 2026-05-10 (handshake confirmed from 200.108.212.210; **MC reachable at http://10.66.0.12:8080/ over tunnel — acceptance criterion HIT**) |

## Bridge CORS

Added `http://10.66.0.12:8080` to `CORS_ORIGIN` env in `/mnt/slime-kingdom/opt/mushy/.env` so MC dashboard JS calls succeed when accessed via wg-hub origin. Bridge restarted; health endpoint clean.

Full env value: `CORS_ORIGIN=http://localhost:8080,http://10.68.155.50:8080,http://elder-plops:8080,http://100.96.10.66:8080,http://10.66.0.12:8080`
