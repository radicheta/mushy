# farm-watchdog (MUSHY-43)

Asks whether each farm **capability still works**, and pushes failures over a
channel that is not Signal.

## Why not just health checks

Every outage this exists to catch happened to a component that was **still
running and still looked alive**:

| what broke | how long, unnoticed | what "healthy" said |
|---|---|---|
| Signal bot deregistered server-side | **7.8 days** | container up, healthcheck green |
| prod farmOS returning HTTP 500 | **3 days** | 4 of 5 containers reported `healthy` |
| whisper stopped; voice notes stored with NULL transcripts | **5.5 weeks** | nothing to see |
| chamber alerter deaf to all telemetry (MUSHY-97) | **1.5 days** | socket open, health 200 |
| a confirmed 9-block session never written (MUSHY-75) | **17 days** | agent healthy |

The BONE-10 containers are the sharpest case: their healthchecks `curl
localhost` **inside** the container, which succeeds perfectly when the container
has no network at all. `docker ps` showed a clean stack through a full prod
outage. So a check earns its place here only by asking whether a capability
still produces its result -- not whether a process is running.

The second rule follows from the first: a probe that cannot run reports
`UNKNOWN`, never `ok`. Conflating "I could not see" with "it is fine" is the
whole subject of this ticket.

## Checks

| check | question | anchored to |
|---|---|---|
| `signal_registration` | is the bot still registered? | 2026-07-19 SPQR deregistration |
| `farmos_prod` / `farmos_dev` | is farmOS actually serving? | BONE-10 |
| `bridge`, `mission_control` | are they answering a real path? | BONE-10 |
| `whisper` | reachable? (`model_loaded:false` is NORMAL when idle) | MUSHY-33 |
| `telemetry_fresh` | is chamber telemetry landing? | fc1 outages |
| `heartbeat_today` | did today's report reach the farmer? | MUSHY-97 |
| `voice_notes_transcribing` | any capture stored degraded in 24h? | 5.5-week whisper outage |
| `no_parked_records` | confirmed records all written? | MUSHY-75 |
| `no_restart_loops` | anything crash-looping? | 3 days of a dependent shouting |
| `networks_attached` | anything network-detached? | BONE-10 |

## Use

```bash
src/farm-agent/.venv/bin/python scripts/farm-watchdog/farm_watchdog.py
src/farm-agent/.venv/bin/python scripts/farm-watchdog/farm_watchdog.py --json
```

Exit codes: `0` all ok, `1` something BROKEN, `2` something UNKNOWN.

Tests (pure verdict logic, no farm needed):

```bash
src/farm-agent/.venv/bin/python -m pytest scripts/farm-watchdog -q
```

## Install (needs root)

```bash
sudo install -m 0755 scripts/farm-watchdog/farm_watchdog.py /usr/local/bin/farm-watchdog
sudo install -m 0644 scripts/farm-watchdog/checks.py /usr/local/bin/checks.py
sudo install -m 0644 scripts/farm-watchdog/mushy-farm-watchdog.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mushy-farm-watchdog.timer
```

`farm_watchdog.py` imports `checks.py` from its own directory, which is why both
land in `/usr/local/bin`.

## Alert delivery -- ntfy, provisioned 2026-08-19

Delivery goes over [ntfy.sh](https://ntfy.sh), deliberately **not** Signal:
the single most important thing this watches *is* Signal, so alerting through
it would be circular.

The topic is the one the VPS heartbeat receiver already pushes to
(`vps/heartbeat-receiver/index.js`) -- off-box, off-Signal, and it survived
every outage in the table above. It was copied from the receiver's own env file
on the VPS (`/etc/mushy-heartbeat/`, root:mushy 640) straight into
`/etc/mushy-watchdog/env` over ssh, piped through `tee` so the value never
reached a terminal or a transcript. Directory `0700`, file `0600`, root-only.
The topic URL is a shared secret; keep it out of git.

Verified end to end on 2026-08-19 by pointing one check at a dead port so it had
to fail, and confirming the push landed on the phone:

```bash
sudo FARMOS_PROD_URL=http://10.68.155.50:9999/ /usr/local/bin/farm-watchdog --notify
```

The phone is the only acceptable proof here. ntfy creates topics on demand, so
a push to a *mistyped* topic also returns success -- "the POST was accepted"
does not mean "a human was told".

Without `NTFY_URL` the watchdog still runs, still reports, and still exits
non-zero; it just logs `NTFY_URL unset; not notifying` instead of pushing. That
is a deliberate fail-visible default rather than a silent no-op.

## Two layers, and what each covers

- **This timer, on elder-plops** -- catches a capability that has stopped
  working while the host is fine. It probes containers from *outside* them,
  which is what BONE-10 needed.
- **The VPS heartbeat receiver** -- catches elder-plops going away entirely,
  via per-source staleness. This watchdog cannot report its own host's death,
  and that is the layer that does.

Neither covers the other. Both are needed.

## Not covered here

Item 1 of MUSHY-43, **signal-cli currency**, is a recurring human decision
rather than a check: the pin in `docker-compose.override.yml` has to be bumped
deliberately, because a pin that sits still while Signal moves is a scheduled
outage. `signal_registration` detects the *consequence* within 15 minutes
instead of 7.8 days, which is the part that can be automated. The bump cadence
itself is still owed.
