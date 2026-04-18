# mushy-alerter

Signal alert agent for FC-1 fruiting chamber. Runs as a standalone compose service on elder-plops.
Consumes the bridge WebSocket, fires PROBLEM/RECOVERY Signal messages via signal-cli-rest-api,
and supports bidirectional snooze via Signal replies.

## Primary Registration Runbook

One-time manual step. Requires the 4G SIM phone number + SMS access.

```bash
# Step 1: Get captcha token at https://signalcaptchas.org/registration/generate.html
# Right-click the "Open Signal" button, copy the signalcaptcha://... link.

# Step 2: Register (replace +1XXXXXXXXXX with the 4G SIM number)
curl -X POST 'http://localhost:8085/v1/register/+1XXXXXXXXXX' \
  -H 'Content-Type: application/json' \
  -d '{"captcha":"signalcaptcha://PASTE_TOKEN_HERE","use_voice":false}'

# Step 3: Wait for SMS on the 4G SIM, then verify the 6-digit code
curl -X POST 'http://localhost:8085/v1/register/+1XXXXXXXXXX/verify/123456'

# Step 4: Confirm registration succeeded
curl http://localhost:8085/v1/accounts
# Expected: ["+1XXXXXXXXXX"]
```

Notes:
- Registration goes through the REST API only — never `docker exec` into signal-cli container.
- Volume `signal-cli-data` persists at `/home/.local/share/signal-cli` inside the container.
- Primary accounts do not have a 45-day linked-device expiry. Daily heartbeat keeps the session warm.

## Deploy

```bash
# First deploy (builds alerter image, starts signal-cli and alerter)
docker compose up -d --build alerter signal-cli

# After source changes
docker compose up -d --build alerter

# View logs
docker compose logs -f alerter
docker compose logs -f signal-cli
```

## Snooze Grammar

Send a Signal reply to the alert bot (from SIGNAL_RECIPIENT's account):

```
snooze <type> <duration>
```

Types: `rh` | `sensor` | `pi` | `humidifier` | `all`

Durations: `30m` | `1h` | `2h` | `4h` | `8h` | `24h`

Examples:
```
snooze rh 4h
snooze all 8h
snooze pi 30m
```

Snooze suppresses outbound PROBLEM sends but continues internal state tracking.
A RECOVERY message is still sent when the condition clears (even during snooze).

## WARNING: Threshold Changes Require Two Edits

RH target and band live in TWO places and must be updated together:

1. **`fc_config.yaml` on fc1 Pi** — controls the humidity control loop (push via `git push fc1/prod`)
2. **`.env` on elder-plops** — controls when the alerter fires (`ALERT_RH_TARGET`, `ALERT_RH_BAND`)

If you update only the Pi config, the alerter will fire false positives for the new target.
If you update only elder-plops `.env`, the controller and alerter will be out of sync.

The alert band (`ALERT_RH_BAND=3`) is intentionally wider than the controller band (`±1%`).
The alerter fires only when the system fails to stay within ±3% — not for normal control oscillation.

## Networking Topology (Validated)

Probe run 2026-04-18 on elder-plops. Result: **PASS**.

### Topology

- Alerter container joins `mushy_default` compose bridge network
- Bridge runs `network_mode: host` on elder-plops port 8081
- Alerter reaches bridge via `host.docker.internal` resolved to the host gateway IP
- signal-cli reached via internal compose network at `http://signal-cli:8080`

### Probe Command

```bash
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  --network=mushy_default \
  alpine:3.19 sh -c 'apk add --no-cache curl >/dev/null && curl -sf http://host.docker.internal:8081/health | head -c 200'
```

### Probe Output (PASS)

```json
{"status":"ok","db":true,"ros":{"connected":true},"camera":{"lastFrame":...},"humidifier":{"last_msg_ts":...}}
```

### Locked Compose Config (Plans 03/05)

This probe locks the networking strategy for all alerter compose wiring:

```yaml
alerter:
  extra_hosts:
    - "host.docker.internal:host-gateway"
  networks:
    - mushy_default          # reaches bridge via host.docker.internal:8081
    - signal-net             # reaches signal-cli:8080

environment:
  BRIDGE_WS_URL: ws://host.docker.internal:8081
  SIGNAL_API_URL: http://signal-cli:8080
```

The `host-mode fallback` path (Plans 03/05 fallback branch) is **not needed** — do not implement it.

## Env Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `BRIDGE_WS_URL` | `ws://host.docker.internal:8081` | Bridge WebSocket endpoint |
| `SIGNAL_API_URL` | `http://signal-cli:8080` | signal-cli-rest-api base URL |
| `SIGNAL_SENDER` | *required* | Registered Signal number (4G SIM), e.g. `+1XXXXXXXXXX` |
| `SIGNAL_RECIPIENT` | *required* | Farmer's Signal number to send alerts to |
| `ALERT_RH_TARGET` | `90` | RH setpoint (%) — must match fc_config.yaml target |
| `ALERT_RH_BAND` | `3` | Alert band (±%) — wider than controller band by design |
| `ALERT_OOB_N` | `5` | Consecutive OOB samples required before firing |
| `ALERT_OOB_WINDOW_MIN` | `3` | Minimum OOB window (minutes) before firing |
| `ALERT_COOLDOWN_MIN` | `30` | WARN alert repeat interval (minutes) |
| `ALERT_CRITICAL_COOLDOWN_MIN` | `60` | CRITICAL alert repeat interval (minutes) |
| `ALERT_PI_OFFLINE_MIN` | `5` | Minutes before Pi-offline alert fires |
| `ALERT_HUMIDIFIER_STUCK_MIN` | `30` | Minutes humidifier stuck ON with no RH rise |
| `ALERT_HEARTBEAT_HOUR` | `8` | Local hour for daily heartbeat (8 = 8am farm time) |
| `DASHBOARD_URL` | `http://elder-plops-ts:8081/farmer` | Link included in every alert |
| `TZ` | `America/Toronto` | Farm timezone for heartbeat scheduling |
