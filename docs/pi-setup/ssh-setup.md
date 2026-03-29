# FC-1 Pi SSH Setup

## Prerequisites
- Raspberry Pi 4 running Ubuntu 24.04 (Noble) — per D-01, D-02
- Pi connected to LAN on 10.68.155.x subnet — per D-06
- Workstation on same LAN subnet

## Current Status (as of 2026-03-29)

**SSH is working.** FC-1 is live and reachable:

- Hostname: `fc1`
- Static IP: `10.68.155.53`
- Subnet: `10.68.155.0/24`
- Gateway: `10.68.155.1`
- User: `ubuntu`
- OS: Ubuntu 24.04.4 LTS (Noble), kernel 6.8.0-1047-raspi
- Static IP config: `/etc/netplan/99-static.yaml` (DHCP disabled on eth0)
- WiFi fallback: `mossrock-west` (works when Ethernet unavailable)

SSH config entry on workstation (`~/.ssh/config`):
```
Host fc1
  HostName 10.68.155.53
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519
```

Verify:
```
ssh fc1 "hostname && uname -a"
```

---

## Setup Steps (for reference / reprovisioning)

### 1. Boot Pi and find its IP
From workstation:
```
nmap -sn 10.68.155.0/24 | grep -B2 "Raspberry"
```
Or check router DHCP lease table.

### 2. Initial SSH (may need password)
```
ssh ubuntu@<PI_IP>
```
Default Ubuntu user is `ubuntu`, default password is `ubuntu` (first boot forces password change).

### 3. Set static IP on Pi
Create `/etc/netplan/99-static.yaml` (do NOT edit cloud-init file):
```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
      addresses: [10.68.155.53/24]
      routes:
        - to: default
          via: 10.68.155.1
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
```
Apply:
```
sudo netplan apply
```

Note: Use a new file like `99-static.yaml` rather than editing `50-cloud-init.yaml` directly —
cloud-init may overwrite it on next boot.

### 4. Copy SSH key from workstation
```
ssh-copy-id -i ~/.ssh/id_ed25519.pub ubuntu@10.68.155.53
```
If no ed25519 key exists:
```
ssh-keygen -t ed25519 -C "mushy-workstation"
```

### 5. Add SSH config entry on workstation
Add to `~/.ssh/config`:
```
Host fc1
  HostName 10.68.155.53
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519
```

### 6. Verify passwordless SSH
```
ssh fc1 "hostname && uname -a"
```
Expected output: Pi hostname and Linux kernel info, no password prompt.

### 7. Disable password auth on Pi (optional hardening)
```
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

## Notes

- Pi static IP: `10.68.155.53` on the `10.68.155.0/24` LAN subnet.
- Static IP is configured in `/etc/netplan/99-static.yaml` on the Pi (DHCP disabled on eth0).
- Per D-06: Pi uses static IP on LAN. The original plan referenced 192.168.88.x but the actual
  network is 10.68.155.x — all references have been updated accordingly.
