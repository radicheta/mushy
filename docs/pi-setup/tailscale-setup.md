# FC-1 Pi Tailscale VPN Setup

Tailscale provides NAT-traversal VPN for accessing the Pi when direct WireGuard
port forwarding isn't available (e.g., behind carrier NAT on a 4G hotspot).

## Current State

| Setting | Value |
|---------|-------|
| fc1 Tailscale IP | `100.96.239.75` |
| elder-plops Tailscale IP | `100.96.10.66` |
| SSH alias | `ssh fc1-ts` |
| Tailscale account | `radicheta@github` |
| Interface | `tailscale0` |

## How It Fits In

- **WireGuard (wg0)** is the permanent VPN through pfSense — requires ISP port forward
- **Tailscale (tailscale0)** is the fallback when port forwarding isn't available
- Both can coexist; switch between them by changing which CycloneDDS config is active

## CycloneDDS Configs

| File | Interface | When to use |
|------|-----------|-------------|
| `cyclonedds.xml` | `wg0` | LAN or pfSense WireGuard tunnel |
| `cyclonedds-tailscale.xml` | `tailscale0` | 4G hotspot / remote access |

Both are in `scripts/pi-deploy/` and deployed to `/etc/` on the Pi.

## Switching fc-core Between Configs

On the Pi:

```bash
# Switch to Tailscale
sudo sed -i 's|cyclonedds.xml|cyclonedds-tailscale.xml|' /etc/systemd/system/fc-core.service
sudo systemctl daemon-reload && sudo systemctl restart fc-core

# Switch back to WireGuard
sudo sed -i 's|cyclonedds-tailscale.xml|cyclonedds.xml|' /etc/systemd/system/fc-core.service
sudo systemctl daemon-reload && sudo systemctl restart fc-core
```

## Switching the Bridge (elder-plops)

The bridge container picks up CycloneDDS config via `docker-compose.override.yml`.
Edit the `CYCLONEDDS_URI` environment variable and volume mount:

```yaml
# For Tailscale
- CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml
volumes:
  - /home/santi/.config/cyclonedds-tailscale.xml:/etc/cyclonedds-tailscale.xml:ro

# For WireGuard
- CYCLONEDDS_URI=file:///etc/cyclonedds.xml
volumes:
  - /home/santi/.config/cyclonedds.xml:/etc/cyclonedds.xml:ro
```

Then: `docker-compose rm -sf bridge && docker-compose up -d bridge`

## Connecting Pi to 4G Hotspot

The Pi uses `wpa_cli` (no NetworkManager):

```bash
# Scan for networks
ssh fc1 "sudo wpa_cli -i wlan0 scan && sleep 3 && sudo wpa_cli -i wlan0 scan_results"

# Connect (network 1 = Galaxy A13 B849, already configured)
ssh fc1 "sudo wpa_cli -i wlan0 select_network 1"

# Switch back to LAN (network 0 = mossrock-west)
ssh fc1 "sudo wpa_cli -i wlan0 select_network 0"

# Verify current network
ssh fc1-ts "sudo wpa_cli -i wlan0 status | grep ssid"
```

> After switching to hotspot, use `ssh fc1-ts` (Tailscale IP) since the LAN IP is gone.

## Verify

```bash
# Ping over Tailscale
ping 100.96.239.75

# SSH over Tailscale
ssh fc1-ts "hostname"

# Check ROS topics through bridge
docker exec mushy_bridge_1 bash -c "\
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && \
  export CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml && \
  source /opt/ros/jazzy/setup.bash && \
  ros2 topic echo /fc/humidity --once"
```

## Tested 2026-04-05

- Pi on Galaxy A13 B849 (4G hotspot, carrier NAT at 10.114.157.x)
- All 4 ROS topics verified over Tailscale: humidity, temperature, CO2, humidifier state
- SSH via `fc1-ts` alias confirmed working
- Latency: ~1-2ms (Tailscale direct connection, both devices on same ISP)
