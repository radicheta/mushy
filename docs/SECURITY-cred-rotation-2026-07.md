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

- [ ] Rotate WiFi PSK on mossrock-lab AP + update clients — **infra (Santi)**
- [ ] Rotate OpenVPN tls-auth key on server + redistribute to clients — **infra (Santi)**
- [ ] Detrack + `.example` templates + `.gitignore` — repo change, ready on request
- [ ] History scrub + force-push — **needs explicit approval** (rewrites GitHub history)
