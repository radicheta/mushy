# stack-reconcile

Repairs docker containers that come up **running but attached to zero networks**,
the state elder-plops landed in after its 2026-08-13 cold start.

## The incident this exists for

elder-plops rebooted 2026-08-13 23:56; dockerd started 23:59 and auto-started
every container with a restart policy. Five containers across three compose
projects came up running with **no network attached** -- dockerd raced its own
user-defined network restore.

A container in that state has no DNS and no published ports:

| container | consequence |
|---|---|
| `farmos-www-1` | prod farmOS returned HTTP 500 on every request (`could not translate host name "db"`) for 3 days |
| `farmos-dev-www-1` | dev farmOS same |
| `farmos-flask-1` / `farmos-dev-flask-1` | farmOS proxies unreachable |
| `noodle-mcp` | unreachable |
| *(knock-on)* `mushy-farmos-agent-1` | crash-looped 3 days against a refused `:8082` |

**Nothing alerted, and `docker ps` actively lied.** All five reported `Up 3 days`
and four reported `healthy`, because their healthchecks curl `localhost` *inside*
the container and never cross the network. The only external symptom was the
farmOS agent's restart loop, which nobody was watching.

## Usage

```bash
stack-reconcile.sh          # repair
stack-reconcile.sh --check  # report only; exit 1 if anything is detached
```

Detection: running containers whose `NetworkSettings.Networks` is empty,
excluding `host`/`none`/`container:` network modes -- `mushy-bridge-1`
legitimately runs host-mode for CycloneDDS on wg0, so excluding those is
required, not an optimisation.

Repair: `docker compose up -d --force-recreate --no-deps <svc>` for just the
broken services, grouped per project. `--no-deps` keeps healthy dependencies
untouched -- the db containers stayed attached through the 08-13 boot and there
is no reason to bounce a working database to fix a detached web container.
The script then re-checks and exits non-zero if anything is still detached.

`RECONCILE_MIN_UPTIME_SEC` (default 60, 120 under systemd) skips containers
younger than that, so a container still being wired up by an in-flight
`compose up` is never yanked out from under it.

## Install (needs sudo, run on elder-plops)

```bash
cd /mnt/slime-kingdom/opt/mushy
sudo install -m 0755 scripts/stack-reconcile/stack-reconcile.sh /usr/local/bin/stack-reconcile.sh
sudo install -m 0644 scripts/stack-reconcile/mushy-stack-reconcile.service /etc/systemd/system/
sudo install -m 0644 scripts/stack-reconcile/mushy-stack-reconcile.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mushy-stack-reconcile.service mushy-stack-reconcile.timer
systemctl status mushy-stack-reconcile.service --no-pager
journalctl -u mushy-stack-reconcile.service -n 30 --no-pager
```

The `.service` runs once at boot (`After=docker.service`, plus its own wait loop
for dockerd to actually answer -- "service started" and "daemon accepting API
calls" are not the same instant, and that gap is the bug). The `.timer` re-checks
every 10 min, which is the check that would have caught the 3-day outage.

## Verified

Tested against a throwaway `reconciletest` compose project, not just reasoned about:

- detached canary is **detected** (`--check` exits 1)
- detached canary is **repaired** (force-recreate, re-verified attached)
- a canary younger than `RECONCILE_MIN_UPTIME_SEC` is **skipped**, not yanked
- clean system reports OK and exits 0

One measured surprise worth recording: plain `docker compose up -d` **did**
repair a canary detached via `docker network disconnect` -- compose treated it as
drift and recreated it. So a blanket `up -d` across all projects would likely
have prevented the incident too. This script still does the targeted thing,
because a blanket `up -d` also converges every project to its committed compose
file, silently recreating anything whose file has drifted from what is running.
That is a deploy decision, not a boot repair.

## Scope

Repairs network detachment only. It does **not** start containers that are
stopped (`unless-stopped` deliberately keeps a hand-stopped container stopped --
e.g. `mushy-whisper-transcribe-1`, stopped 2026-07-09 on purpose) and it does not
converge compose files.
