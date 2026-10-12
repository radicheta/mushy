# stack-reconcile

Repairs docker containers that come up **running but attached to zero networks**
(the state elder-plops landed in after its 2026-08-13 cold start) or that
**failed to start and stayed exited** (the 2026-10-12 boot, BONE-20).

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

## The second incident (2026-10-12, BONE-20)

dockerd started before DHCPv4 had delivered `10.68.155.50`: `network-online`
was reached on IPv6 alone at 11:02:06, the IPv4 lease arrived at 11:03:53. Six
containers that publish on that address (`farmos-www-1`, `farmos-flask-1`, their
`-dev` twins, `plane-proxy-1`, `noodle-mcp`) failed with `failed to bind host
port ... cannot assign requested address` and stayed **exited**. dockerd does
not retry a start that fails this way. This script then only enumerated running
containers, so the timer reported OK while prod farmOS was down.

`docker start` alone does not fix such a container: it comes up detached. The
repair is the same force-recreate.

Two layers now cover it: `docker-wait-lan-addr.conf` delays dockerd until the
address exists (prevention), and the script repairs failed starts (cure).

## Usage

```bash
stack-reconcile.sh          # repair
stack-reconcile.sh --check  # report only; exit 1 if anything is detached or failed to start
```

Detection: running containers whose `NetworkSettings.Networks` is empty,
excluding `host`/`none`/`container:` network modes -- `mushy-bridge-1`
legitimately runs host-mode for CycloneDDS on wg0, so excluding those is
required, not an optimisation.

It also picks up **exited** containers whose restart policy is `always` or
`unless-stopped` and whose `State.Error` is non-empty. The error is what
separates a failed start from a container someone stopped by hand, which leaves
`State.Error` empty and is never touched.

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
sudo install -D -m 0644 scripts/stack-reconcile/docker-wait-lan-addr.conf /etc/systemd/system/docker.service.d/wait-lan-addr.conf
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
- an existing container whose restart fails on a port bind (exited, error set)
  is **detected and repaired**; a hand-stopped container and a failed container
  with restart policy `no` are **left alone** (2026-10-12)

The docker drop-in's wait loop was exercised by hand; the unit itself has not
been through a real reboot yet.

One measured surprise worth recording: plain `docker compose up -d` **did**
repair a canary detached via `docker network disconnect` -- compose treated it as
drift and recreated it. So a blanket `up -d` across all projects would likely
have prevented the incident too. This script still does the targeted thing,
because a blanket `up -d` also converges every project to its committed compose
file, silently recreating anything whose file has drifted from what is running.
That is a deploy decision, not a boot repair.

## Scope

Repairs network detachment and failed starts. It does **not** start containers
that someone stopped (`unless-stopped` deliberately keeps a hand-stopped container stopped --
e.g. `mushy-whisper-transcribe-1`, stopped 2026-07-09 on purpose) and it does not
converge compose files.
