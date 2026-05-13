# Note: signal-cli MODE=normal is expensive on CPU

**Observed:** 2026-05-12, from gumbald host (cockfight project).

The `mushy-signal-cli-1` container (`bbernhard/signal-cli-rest-api:0.200-dev`,
`MODE=normal`) forks a fresh JVM for every poll. Each `receive -t 1` cycle
shows the JVM cold-start at ~200–220% CPU before settling to ~85–90% during
the 1-second poll, then exits. This happens continuously while a receive-loop
client is polling — net effect is a near-constant CPU churn that's visible
in `top` even when the host is otherwise idle.

## Why it's `normal` today

`docker-compose.override.yml:39` explains the choice:

> `MODE=normal: /v1/receive is HTTP GET (not WebSocket). Required for receive-loop HTTP polling.`

So `normal` is load-bearing for the current receive-loop architecture.
A naive switch to `native` will break it.

## Options to consider

1. **Keep `normal`, reduce poll frequency** — if the receive-loop is polling
   every N seconds, increasing N proportionally reduces the spawn rate.
   Lowest-effort fix.

2. **Switch to `native` and use WebSocket** — `MODE=native` keeps a single
   long-lived JVM and exposes `/v1/receive` as a WebSocket instead of HTTP
   GET. Eliminates the spawn cost entirely (~300–500 MB constant RAM in
   exchange for near-zero per-poll CPU). Requires updating the receive-loop
   client to consume WebSocket events instead of polling HTTP.

3. **Switch to `json-rpc`** — also persistent JVM, IPC over JSON-RPC socket.
   Similar tradeoffs to `native`. Worth a look if `native`'s WebSocket is
   awkward for the existing client.

For a Signal heartbeat-alert workload that mostly *sends* and only occasionally
*receives*, option 2 is the long-term win. If receive volume is low, option 1
is a one-line change.

## Where this came up

Found while profiling rogue CPU usage on gumbald after a ComfyUI/nightly-batch
incident. The signal-cli churn is a steady ~1 core of background load even
when nothing else is running — not catastrophic, but worth knowing about.

— note left by a passing cockfight session, no action taken
