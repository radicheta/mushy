---
filed: 2026-06-27
source: devops network/infra review (elder-plops). Re-surfacing the Phase 35 SPOF acknowledged 2026-05-11.
severity: HIGH — single key loss makes ALL Tier-A backups unrecoverable ciphertext (defeats the backup)
priority: near-term, needs ~10 min operator action (age-keygen + paste secret to 1Password)
disposition: RESOLVED 2026-06-28 — 2nd age recipient (paper escrow, 2 off-site cards) deployed; verified
relates_phase: 35
---

> **✅ RESOLVED 2026-06-28** (tracked as Plane BONE-2). Added a 2nd age recipient escrowed on PAPER
> (chosen over a vault — no bootstrap dependency; two off-site cards). `/etc/mushy/tierA-recipients.txt`
> = ssh-ed25519 key + `age10tr5…zlejt`; deployed **and** repo backup scripts patched (line 19 → recipients
> file). Backup `20260628-2218.tar.age` ran clean with the 2-recipient file and decrypts via the ssh key.
> SPOF closed: backups recoverable with the on-host ssh key OR an off-site paper card. Runbook updated.

# Tier-A backup decrypt-key SPOF — add an offline 2nd recipient

## What

The nightly Tier-A backup (`/usr/local/bin/mushy-tierA-backup.sh`, 03:30 →
`mushy@178.105.84.13:/var/backups/mushy-tierA/`) encrypts to a **single** age recipient:
`~/.ssh/id_ed25519.pub` on elder-plops. The matching private key on elder-plops is the **only**
thing that can decrypt. If that disk dies AND the key is lost, every backup on the VPS is dead
ciphertext. This is the SPOF the operator acknowledged + deferred when Phase 35 shipped
(see `35-SUMMARY.md` "KNOWN SPOF" + `memory/project_phase35_tierA_backup.md`).

## Recommended fix (multi-recipient, offline 2nd key)

1. `age-keygen` a dedicated backup keypair on elder-plops.
2. Store the secret line (`AGE-SECRET-KEY-1…`) in 1Password (and/or paper/USB offsite); `shred`
   it off disk. Keep only the public `age1…` recipient. (Better than escrowing `id_ed25519`
   itself — never copies the SSH auth identity.)
3. `/etc/mushy/tierA-recipients.txt` = both pubkeys, one per line.
4. Script edit (deployed **and** repo copy), line 19 only:
   `RECIPIENT_PUB` default `…/id_ed25519.pub` → `/etc/mushy/tierA-recipients.txt`.
   `age -R <file>` already takes multiple recipients — line 82 unchanged.
5. Verify: decrypt a fresh bundle with BOTH the old SSH key and the new offline age key.
6. Mark `35-SUMMARY.md` SPOF section RESOLVED.

## Full runbook

`/home/shared/opt/devops/runbooks/tierA-backup-key-spof-fix.md` — exact commands, the diff,
verify steps, and the lower-effort alternative (escrow `id_ed25519` to 1Password — not preferred).

## Notes

- Steps 1–2 require the operator (offline secret storage can't be automated).
- Repo vs deployed script already drift (repo 113 LOC stages a signal-cli volume; deployed 98) —
  reconcile separately; the line-19 edit is identical in both.
