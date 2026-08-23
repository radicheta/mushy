# Credential rotation runbook — MUSHY-35 (2026-07)

Two live credentials are committed to git history and pushed to GitHub
(`radicheta/mushy`). They must be **rotated** (the values are compromised the
moment they touch the remote), then removed from the tree and scrubbed from
history. Deleting the files alone is NOT sufficient — the values remain in every
prior commit and on GitHub.

Ordering matters: **rotate first**, then detrack, then scrub history. Scrubbing
before rotating just hides a still-live secret.

---

## Secret 1 — WiFi PSK (mossrock-lab)

- **Where:** `scripts/pi-deploy/etc/netplan/60-wifi.yaml:15`
- **What:** the `wpa_passphrase` hash (64-hex) for the `mossrock-lab` 4G MiFi AP.
  A PSK hash is password-equivalent — a client can associate with the hash
  directly, so this is a live secret, not an opaque digest.

**Rotate (needs AP access):**
1. On the mossrock-lab 4G MiFi admin page, set a new WPA2 passphrase.
2. Recompute the hash for the netplan file:
   ```bash
   wpa_passphrase "mossrock-lab" "<new-passphrase>" | grep -w psk | cut -d= -f2
   ```
3. Update every client that joins mossrock-lab (fc1 / the Pi, laptops, phones).
   On fc1, put the new hash into the *deployed* netplan (see "Detrack" for how it
   should be supplied out-of-band), then `sudo netplan apply`.

---

## Secret 2 — OpenVPN tls-auth static key

- **Where:** `client.ovpn` (repo root), `<tls-auth>` block (2048-bit static key).
- **What:** the HMAC key protecting the OpenVPN TLS control channel. The `<ca>`
  cert in the same file is public (fine); the tls-auth key is the secret. The
  file uses `auth-user-pass`, so no user password is embedded.

**Rotate (needs VPN-server access):**
1. Generate a fresh key on the server:
   ```bash
   openvpn --genkey secret ta.key    # modern; or: openvpn --genkey --secret ta.key
   ```
2. Install it on the OpenVPN **server** config and reload the server.
3. Redistribute the new `<tls-auth>` block to **every** client profile
   (`key-direction 1` stays). Clients with the old key can no longer complete
   the control-channel HMAC and must be updated.

---

## Detrack from the working tree (after rotation)

Stop tracking the real secrets going forward; supply them out-of-band at deploy time.

```bash
git rm --cached client.ovpn scripts/pi-deploy/etc/netplan/60-wifi.yaml
# commit .example templates + .gitignore entries in their place
```

- `.gitignore` gains: `client.ovpn` and `scripts/pi-deploy/etc/netplan/60-wifi.yaml`.
- Commit `client.ovpn.example` and `60-wifi.yaml.example` with the secret lines
  replaced by `REPLACE_ME` placeholders so deploy still documents the shape.
- The pi-deploy flow must then drop the real `60-wifi.yaml` onto the Pi from a
  secret store, not from git.

## Scrub history (after rotation + detrack; needs force-push approval)

This rewrites shared history and requires a coordinated `git push --force`.
Anyone with a clone must re-clone or hard-reset afterward.

```bash
# preferred: git-filter-repo
git filter-repo --path client.ovpn --path scripts/pi-deploy/etc/netplan/60-wifi.yaml --invert-paths
# re-add origin (filter-repo drops it), then:
git push --force origin --all
git push --force origin --tags
```

Then rotate anything else that assumed the old history, and confirm the GitHub
repo no longer surfaces the values in any commit (check the "History" of both
paths on github.com).

---

## Status

**Re-verified 2026-08-23. Nothing has been rotated. Both secrets remain live and
publicly readable.**

### Escalation: the repo is PUBLIC

`radicheta/mushy` is a **public** GitHub repo (`isPrivate: false`). These are not
merely "in history" -- they are world-readable right now, and have been since
`d3c81c9` (netplan) and `2d13277` (client.ovpn, 2025-05-21). Treat both as
disclosed to the internet, not merely as leaked-to-a-remote.

Scope is narrow and clean: only three commits touch the two paths
(`d3c81c9`, `789a699`, `2d13277`) and neither secret appears in any other blob,
so a `filter-repo` scrub is surgical.

### Secret 2 (OpenVPN tls-auth) -- RESOLVED 2026-08-23 by deleting the server

Identified 2026-08-23. The leaked key is byte-identical to the key configured on
pfSense for the **"Musguito VPN"** server instance:

    payload sha256 = a6a72993c4467f79c1818989db2cc6bb8888c952de9c13462b95ac4f3cb57f3b
    payload size   = 512 hex chars (2048-bit)

    vpnid            = 1
    mode             = server_tls_user      authmode = Local Database
    protocol         = UDP4  dev tun        local_port = 1199
    tunnel_network   = 172.16.10.0/24
    custom_options   = push "route 172.16.10.0 255.255.255.0"
    disable          = SET  (no instance in /var/etc/openvpn/, nothing on :1199)
    local users      = admin, mushy

**Ownership was initially misjudged as third-party and then verified as ours**
(2026-08-23). Three independent signals agree:

1. `tunnel_network` is `172.16.10.0/24` -- the farm's own tunnel range. Live
   `tun_wg0` on pfSense holds `172.16.10.1/24`; `fc1-wg` is `172.16.10.5`; wg
   peers are `.2/.3/.4/.5`.
2. Its only non-admin Local Database user is **`mushy`**.
3. The CA is `CN = Mossrock Private Network CA` (self-signed 2025-05-12 .. 2035-05-10).

Read: this is the farm's **legacy OpenVPN remote-access server**, predating the
kernel-WireGuard migration and disabled once wg0 took over the same
`172.16.10.0/24`. Re-enabling it as-is would collide with live wg0.

**Do not confuse it with the OpenVPN _client_** on the same pfSense box
(`/var/etc/openvpn/client2` -> `vpnforest.ddns.net:9195`, PID 70793). That one is
the VFX studio's outbound tunnel, is unrelated to this leak, and is strictly out
of scope -- it shares only the word "OpenVPN". Confusing the two is what caused
the initial misjudgement; check `tunnel_network` and the user list to tell them
apart.

Because wg0 has already replaced it, the cheaper fix is likely **deletion of the
server instance** rather than key rotation -- rotating a key for a service nobody
runs, on a subnet that now belongs to WireGuard, buys nothing. Operator decision.

### Secret 1 (WiFi PSK) -- no longer load-bearing; rotate at leisure

The `mossrock-lab` PSK is still public and must be treated as compromised. But as
of **2026-08-23 it is no longer on fc1's critical path**, so rotating it is now a
low-risk change rather than a strand risk.

What changed: the operator powered `mossrock-lab` down; fc1 fell back to
`mossrock-west` and resumed telemetry. Verified on fc1 the same day:

    wlan0    10.68.155.56/24        ssid = mossrock-west
                                    key_mgmt = NONE      wpa_state = COMPLETED
                                    bssid = 68:ff:7b:c7:3a:37
    wg0      172.16.10.5/24         handshake 1m30s ago, 5.36 MiB rx
    wg-hub   10.66.0.11/32
    eth0     DOWN
    default route via 10.68.155.1 dev wlan0
    fc-core  active -- 6.9 C, 87.9% RH
    uptime   19h25m (no reboot -- it was up but unreachable, not crashed)

**Two earlier conclusions in this file were wrong and are corrected here:**

1. *"The `fc1` ssh alias points at 10.68.155.56, which is down -- stale alias."*
   **Wrong.** `10.68.155.56` is fc1's correct address; it was simply offline at
   the time. The alias is fine. `fc1-wg` -> `172.16.10.5` also works.
2. *"`10.68.155.53` is a different device that took fc1's IP."* **Wrong.**
   `10.68.155.53` is the **mossrock-west AP** -- its MAC `68:ff:7b:c7:3a:37` is
   the very BSSID fc1 is now associated to. Not a device conflict at all.

Lesson worth keeping: fc1 absent from ARP and from DHCP leases meant "not
currently associated", not "replaced" or "dead". Reach for `wg show` handshake
age and `wpa_cli status` before inferring a topology change from a missing lease.

**Standing risk, separate from this ticket:** `mossrock-west` is an **open**
network (`key_mgmt=NONE`) -- no link-layer encryption. The traffic that matters
(DDS telemetry) rides encrypted inside wg0, so this is not an active breach, but
fc1's uplink is currently unauthenticated. Worth its own ticket.

**Rotation procedure, when the lab AP comes back up:**

1. Set the new passphrase on the mossrock-lab 4G MiFi admin page.
2. `wpa_passphrase "mossrock-lab" "<new>" | grep -w psk | cut -d= -f2`
3. Install the new hash into fc1's **deployed** `/etc/netplan/60-wifi.yaml`
   (it is no longer supplied by git -- see below), then `sudo netplan apply`.
4. Confirm fc1 can still associate to `mossrock-west` before and after, so a
   mistake in the lab stanza never costs the link.

Because fc1 currently holds `mossrock-west` and that stanza needs no secret, step
3 can be done at any time without risking the uplink.

### Supply path after detracking

`scripts/pi-deploy/etc/netplan/60-wifi.yaml` is now **untracked and gitignored**.
`fc-system-sync.service:18-21` is `if [ -f ]`-guarded, so its absence from the
repo means fc1 simply keeps its deployed copy -- verified, and fc1 is serving
telemetry on that copy right now.

Do **not** commit a placeholder at that exact path. fc-system-sync `cmp`s the
repo file against `/etc/netplan/60-wifi.yaml` and installs on difference -- a
`REPLACE_ME` placeholder there would overwrite fc1's working wifi config and
strand the box. The shape reference lives at
`scripts/pi-deploy/etc/netplan/60-wifi.yaml.example` precisely because that
filename is invisible to the sync.

A reflashed fc1 therefore needs the real netplan installed by hand, out of band,
before it can reach the network.

### BLOCKED -- needs the operator to run these (2026-08-23)

Three actions were attempted and refused by the Claude Code auto-mode permission
classifier (router writes, history rewrite, and pushes). Nothing was partially
applied -- each was refused before execution. Verified afterwards: pfSense still
holds the original key, and the repo history is untouched. Commands below are
ready to run as-is.

**Backups taken before any of this (keep until the scrub is confirmed):**

    ~/mushy-prescrub-backup-20260823-162033/mushy-all-refs.bundle   (14M, "complete history")
    ~/mushy-prescrub-backup-20260823-162033/mushy-mirror.git        (full mirror)
    pfSense: /conf/config.xml.pre-mushy35-20260823-161755

**1. Delete the Musguito VPN server on pfSense** -- **DONE 2026-08-23.** Operator ran
the script; output `deleting vpnid=1 desc=Musguito VPN port=1199
tunnel=172.16.10.0/24` then `WROTE`. Verified after: 0 `<openvpn-server>` blocks
remain, the leaked key hash appears 0 times anywhere in `config.xml`, nothing
listens on 1199, the studio client2 (PID 70793) is still running untouched, and
wg0 is up at 172.16.10.1 with fc1 handshaking. Kept for the record:

```bash
ssh admin@10.68.155.1
php -r '
require_once("config.inc"); require_once("util.inc");
global $config; $srv = &$config["openvpn"]["openvpn-server"];
$idx=null; foreach ($srv as $i=>$s) if ((string)($s["vpnid"]??"")==="1") { $idx=$i; break; }
if ($idx===null) { echo "ABORT: vpnid 1 not found\n"; exit(1); }
if (!isset($srv[$idx]["disable"])) { echo "ABORT: server is ENABLED\n"; exit(1); }
if (($srv[$idx]["tunnel_network"]??"") !== "172.16.10.0/24") { echo "ABORT: unexpected tunnel_network\n"; exit(1); }
unset($srv[$idx]); $srv = array_values($srv);
write_config("MUSHY-35: delete disabled legacy Musguito VPN (leaked tls-auth key; superseded by wg0)");
echo "WROTE\n";'
```

The three guards abort unless it is vpnid 1, disabled, and on 172.16.10.0/24.
Leaves `CN = Mossrock Private Network CA` and the server cert orphaned in the
cert manager -- harmless, delete separately if you want the tidy-up. Do not touch
the OpenVPN **client** (`client2`, PID 70793) -- that is the VFX studio's.

**2. Push the detrack commit** (`85fc778`, already committed locally):

```bash
git -C /mnt/slime-kingdom/opt/mushy push origin main
```

**3. Scrub history.** `git-filter-repo` could not be installed (no `ensurepip`,
no network), so this uses native `filter-branch`. Local branches for all 16
remote branches were already created, so a single pass covers everything on
GitHub:

```bash
cd /mnt/slime-kingdom/opt/mushy
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --force \
  --index-filter 'git rm --cached --ignore-unmatch -q client.ovpn scripts/pi-deploy/etc/netplan/60-wifi.yaml' \
  --tag-name-filter cat -- --branches --tags

# verify NOTHING remains, across every rewritten ref:
git log --all --oneline -- client.ovpn scripts/pi-deploy/etc/netplan/60-wifi.yaml   # must be empty

# drop the rewrite backups and repack
rm -rf .git/refs/original && git reflog expire --expire=now --all && git gc --prune=now --aggressive

git push --force origin --all && git push --force origin --tags
```

**After the force-push -- three follow-ups that are easy to forget:**

- **fc1 holds a clone** at `/home/ubuntu/mushroom_farm_ws/mushy-repo` and deploys
  from the `fc1/prod` branch, which is one of the rewritten refs. Its next pull
  will conflict. fc1 is reachable now (`ssh ubuntu@172.16.10.5`); re-point it with
  a fresh clone or `git fetch && git reset --hard origin/fc1/prod`. Do this while
  fc1 is up -- do not leave it for a moment when the chamber is unreachable.
- **The worktree** at `.claude/worktrees/cv-condensation` (branch
  `worktree-cv-condensation`, clean at `20fd3ef`) will point at a pre-rewrite
  commit and needs resetting.
- **GitHub keeps rewritten commits reachable by direct SHA** until it GCs. The
  values are already public, so rotation is what actually fixes this -- but ask
  GitHub Support to purge the stale refs if you want them gone promptly.

**Ordering caveat, stated plainly:** scrubbing the WiFi PSK without rotating it
only removes it from public view; it does not un-disclose it. The PSK is
compromised and stays compromised until the AP passphrase changes. Same for the
tls-auth key -- deleting the server removes the thing it protected, which is why
deletion beats rotation there.

### Checklist

- [ ] Rotate WiFi PSK on mossrock-lab AP + update clients -- **BLOCKED: fc1 unreachable**
- [ ] Establish a non-wifi path to fc1 -- **prerequisite for the above**
- [x] Musguito VPN (OURS): **server instance DELETED 2026-08-23** -- key has no service left to protect
- [x] Remove `client.ovpn` from the tree -- done in `85fc778` (local; push pending)
- [ ] Detrack netplan + `.example` templates + `.gitignore` + out-of-band supply path
- [ ] History scrub + force-push -- **needs explicit approval** (rewrites public history)
