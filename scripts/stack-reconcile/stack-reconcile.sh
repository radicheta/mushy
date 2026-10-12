#!/usr/bin/env bash
# stack-reconcile — repair docker containers that came up detached from their
# networks, or failed to start at all, typically after a host cold start.
#
# THE FAILURE THIS FIXES (observed 2026-08-13 boot, found 2026-08-17):
# elder-plops rebooted at 23:56; dockerd started at 23:59 and auto-started every
# container with a restart policy. Five containers across three compose projects
# came up RUNNING but attached to ZERO networks -- dockerd raced its own
# user-defined network restore. A container in that state has no DNS and no
# published ports, so:
#   - farmos-www-1 / farmos-dev-www-1 returned HTTP 500 on every request
#     ("could not translate host name 'db' to address"), i.e. prod farmOS was
#     down for 3 days
#   - mushy-farmos-agent-1 crash-looped for 3 days against a refused :8082
#   - farmos-flask-1 / farmos-dev-flask-1 (the farmOS proxies) were unreachable
#   - noodle-mcp was unreachable
# Every one of them reported "Up 3 days" and four of them reported "healthy",
# because their healthchecks probe localhost inside the container and never
# touch the network. Nothing alerted.
#
# WHY --force-recreate RATHER THAN PLAIN `docker compose up -d`:
# Measured, not assumed. On a canary container detached with `docker network
# disconnect`, plain `up -d` DID notice and recreate it -- so a blanket
# `up -d` across every project would probably have prevented the 08-13
# incident too. Two reasons this script does the targeted thing anyway:
#   1. Blanket `up -d` converges every project to its committed compose file,
#      which at boot would silently recreate any container whose file drifted
#      from what is running. That is a much bigger blast radius than "repair
#      the broken ones", and it is a deploy decision, not a boot repair.
#   2. Whether plain `up -d` repairs a detached container depends on compose's
#      drift detection agreeing that runtime network state is drift. That held
#      for `network disconnect`; it is not guaranteed to hold for whatever
#      dockerd does to a container during a boot race. --force-recreate does
#      not depend on that judgement.
# The verify pass at the end exists because of exactly this uncertainty: it
# re-checks and fails loudly rather than trusting the repair worked.
#
# THE SECOND FAILURE THIS FIXES (2026-10-12 boot, BONE-20):
# dockerd started before DHCPv4 had delivered 10.68.155.50 (network-online was
# satisfied by IPv6 alone). Six containers that publish on that address failed
# with "failed to bind host port ... cannot assign requested address" and
# stayed EXITED -- dockerd does not retry a start that fails this way. This
# script only looked at running containers, so it reported OK. `docker start`
# on such a container brings it up detached, so the repair is the same
# force-recreate as above.
#
# Usage:
#   stack-reconcile.sh            repair any detached or failed-start containers
#   stack-reconcile.sh --check    report only, exit 1 if any are broken
#
# Env:
#   RECONCILE_MIN_UPTIME_SEC  skip containers younger than this (default 60) so
#                             a container still being wired up by an in-flight
#                             `compose up` is never yanked out from under it
#   RECONCILE_DOCKER_WAIT_SEC how long to wait for dockerd at boot (default 180)

set -uo pipefail

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

MIN_UPTIME_SEC="${RECONCILE_MIN_UPTIME_SEC:-60}"
DOCKER_WAIT_SEC="${RECONCILE_DOCKER_WAIT_SEC:-180}"

log() { echo "$(date -Is) [stack-reconcile] $*"; }

# ---------------------------------------------------------------------------
# Wait for dockerd. At boot this unit can start before the daemon accepts
# connections; without this the whole run would no-op and the race would win.
# ---------------------------------------------------------------------------
waited=0
until docker info >/dev/null 2>&1; do
    if [ "$waited" -ge "$DOCKER_WAIT_SEC" ]; then
        log "ERROR: dockerd not responding after ${DOCKER_WAIT_SEC}s; giving up"
        exit 1
    fi
    sleep 3
    waited=$((waited + 3))
done
[ "$waited" -gt 0 ] && log "dockerd ready after ${waited}s"

# ---------------------------------------------------------------------------
# Classify one container. Prints "detached" or "failed-start" if it is broken,
# nothing otherwise.
#
# detached: running with zero networks. host/none network modes are
# legitimately network-less -- mushy-bridge-1 runs host-mode on purpose (it
# needs the host's wg0 for CycloneDDS). Excluding them is required, not an
# optimisation.
#
# failed-start: exited, restart policy says it should be up, and dockerd
# recorded a start error. The error is what separates this from a container
# someone stopped by hand (`docker stop` leaves State.Error empty), which must
# stay stopped.
# ---------------------------------------------------------------------------
broken_kind() {
    local status mode nets policy err
    read -r status mode nets policy err <<<"$(docker inspect "$1" --format \
        '{{.State.Status}} {{.HostConfig.NetworkMode}} {{len .NetworkSettings.Networks}} {{.HostConfig.RestartPolicy.Name}} {{if .State.Error}}1{{else}}0{{end}}' 2>/dev/null)"
    if [ "$status" = "running" ]; then
        [ "$nets" != "0" ] && return
        case "$mode" in host|none|container:*) return ;; esac
        echo detached
    elif [ "$status" = "exited" ] && [ "$err" = "1" ]; then
        case "$policy" in always|unless-stopped) echo failed-start ;; esac
    fi
}

broken=""
now_epoch=$(date +%s)

while read -r name; do
    [ -z "$name" ] && continue
    kind=$(broken_kind "$name")
    [ -z "$kind" ] && continue

    if [ "$kind" = "detached" ]; then
        started=$(docker inspect "$name" --format '{{.State.StartedAt}}')
        started_epoch=$(date -d "$started" +%s 2>/dev/null || echo 0)
        age=$((now_epoch - started_epoch))
        if [ "$age" -lt "$MIN_UPTIME_SEC" ]; then
            log "SKIP $name -- detached but only ${age}s old, may still be starting"
            continue
        fi
    fi

    proj=$(docker inspect "$name" --format '{{index .Config.Labels "com.docker.compose.project"}}')
    svc=$(docker inspect "$name" --format '{{index .Config.Labels "com.docker.compose.service"}}')
    dir=$(docker inspect "$name" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')
    files=$(docker inspect "$name" --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}')

    if [ -z "$proj" ] || [ -z "$svc" ]; then
        log "WARN $name is $kind but carries no compose labels; repair it by hand"
        continue
    fi
    if [ "$kind" = "detached" ]; then
        log "DETACHED $name (project=$proj service=$svc age=${age}s)"
    else
        log "FAILED-START $name (project=$proj service=$svc): $(docker inspect "$name" --format '{{.State.Error}}')"
    fi
    broken="${broken}${proj}|${svc}|${dir}|${files}"$'\n'
done < <(docker ps -a --format '{{.Names}}')

if [ -z "$broken" ]; then
    log "OK -- every container is attached to its network and none failed to start"
    exit 0
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
    log "CHECK: broken containers present (see above)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Repair, grouped per project so one compose invocation fixes all of that
# project's broken services at once.
#
# --no-deps: never restart a healthy dependency (the db containers stayed
# attached through the 08-13 boot; there is no reason to bounce a working
# database to fix a detached web container).
# ---------------------------------------------------------------------------
rc=0
while IFS='|' read -r proj dir files; do
    [ -z "$proj" ] && continue
    svcs=$(printf '%s' "$broken" | awk -F'|' -v p="$proj" '$1==p {print $2}' | sort -u | tr '\n' ' ')
    [ -z "$svcs" ] && continue

    fargs=()
    IFS=',' read -ra flist <<<"$files"
    for f in "${flist[@]}"; do [ -n "$f" ] && fargs+=(-f "$f"); done

    log "REPAIR project=$proj services=[$svcs]"
    # shellcheck disable=SC2086
    if docker compose -p "$proj" --project-directory "$dir" "${fargs[@]}" \
         up -d --force-recreate --no-deps $svcs 2>&1 | sed "s/^/    /"; then
        log "REPAIRED project=$proj"
    else
        log "ERROR repair failed for project=$proj"
        rc=1
    fi
done < <(printf '%s' "$broken" | awk -F'|' '!seen[$1]++ {print $1"|"$3"|"$4}')

# ---------------------------------------------------------------------------
# Verify. A repair that silently did not take is worse than none, because the
# log would then claim success while farmOS still 500s.
# ---------------------------------------------------------------------------
sleep 5
still=0
while read -r name; do
    [ -z "$name" ] && continue
    kind=$(broken_kind "$name")
    [ -z "$kind" ] && continue
    log "STILL BROKEN after repair: $name ($kind)"
    still=1
done < <(docker ps -a --format '{{.Names}}')

if [ "$still" -eq 1 ]; then
    log "FAILED -- some containers are still broken"
    exit 1
fi

log "DONE -- all containers attached and started"
exit "$rc"
