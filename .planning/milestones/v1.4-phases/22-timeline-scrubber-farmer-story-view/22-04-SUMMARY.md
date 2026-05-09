---
phase: 22-timeline-scrubber-farmer-story-view
plan: 04
subsystem: mission-control-bridge
tags: [phase-22, deploy, verify, claude-sync, coordination, shipped]
dependency-graph:
  requires: ["22-01", "22-02", "22-03"]
  provides: ["D-06 farmOS handoff", "live /camera/frame on elder-plops"]
  affects: ["/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md"]
tech-stack:
  added: []
  patterns: ["docker compose up -d --build bridge", "Z-suffix ISO (avoid + urlencoding)"]
key-files:
  created:
    - .planning/phases/22-timeline-scrubber-farmer-story-view/22-04-SUMMARY.md
  modified:
    - /mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md
decisions:
  - "Human eyeball (task 2 checkpoint) executed by agent per user's explicit 'verify user surface before UAT ping' directive — farmer UAT deferred to post-phase Signal ping"
metrics:
  duration_minutes: 12
  completed: 2026-04-19
  tasks_completed: 3
  curl_checks_passed: 7/7
  burnt_file_bytes: 51214
  raw_file_bytes: 30034
---

# Phase 22 Plan 04: Ship + Verify + CLAUDE-SYNC Summary

End-to-end deploy of Phase 22 on elder-plops: bridge rebuilt with jimp + burn-in + `/camera/frame`, burnt twin producing, all seven curl checks green, visual confirmation of the burnt bar on a real fc1 mushroom frame, and CLAUDE-SYNC.md updated with an as-shipped addendum for the Zoy-side farmOS team.

## Build

```
docker compose up -d --build bridge   # from /mnt/slime-kingdom/opt/mushy
```

Build succeeded on first try. Highlights from the build log:

```
#10 [bridge 6/8] RUN ... npm install --production
#10 7.800 added 166 packages, and audited 167 packages in 7s
#10 7.801 found 0 vulnerabilities
#13 writing image sha256:c75342dd11221e8b693751944a317a81c4cbdfb515ef1a927927463608ad3e3f
Container mushy-bridge-1  Recreated
Container mushy-bridge-1  Started
```

`jimp` pulled in cleanly as part of the 166-package install; no test stage in the image (tests run at dev time, not in the prod container — consistent with Phase 22-02/03).

Container post-start:

```
mushy-bridge-1 Up
Mounts:
  /data/snapshots       -> /data/snapshots
  /data/snapshots-burnt -> /data/snapshots-burnt
  /home/santi/.config/cyclonedds-tailscale.xml -> /etc/cyclonedds-tailscale.xml
Env:
  SNAPSHOT_DIR=/data/snapshots
  SNAPSHOT_BURNT_DIR=/data/snapshots-burnt
  SNAPSHOT_INTERVAL_MIN=5
  CAMERA_ID=fc1
```

Bridge startup log, clean:

```
[bridge] Starting Node.js bridge on port 8081
[db] Schema initialized
[camera] subscribed to /fc1/camera/compressed
[camera] Snapshot timer started: every 5 min to /data/snapshots/fc1/
[retention] scheduled — retain 365 days, grace 30 days
[bridge] HTTP + WebSocket server on port 8081
```

## Burnt File Production

Bridge started at ~18:09 UTC. First post-rebuild snapshot cycle fired at 18:14:19 UTC (poll interval = 30 s × 10 = 5 min wait). Burnt twin appeared in the same cycle:

```
raw:   /data/snapshots/fc1/2026-04-19/2026-04-19T18-14-19-920Z.jpg       30034 bytes
burnt: /data/snapshots-burnt/fc1/2026-04-19/2026-04-19T18-14-19-920Z.jpg 51214 bytes
delta: +21180 bytes from overlay (bottom bar with ~70 chars of text)
```

Bridge logs during verification window contained zero `[camera/burnt] write failed`, `[camera/burnt] burn failed`, `[camera/frame] read failed`, or `error|fatal` lines.

## Curl Checks

All seven checks against `http://localhost:8081` (host-networked port):

| # | Query | Expected | Got | Notes |
|---|-------|----------|-----|-------|
| 4a | `?camera_id=fc1` (no at) | 400 | **400** | `{"error":"at query param required (ISO-8601)"}` |
| 4b | `?at=not-a-date&camera_id=fc1` | 400 | **400** | `{"error":"at must be a valid ISO-8601 timestamp"}` |
| 4c | `?at=<now>&camera_id=evil` | 400 | **400** | `{"error":"Invalid camera_id"}` |
| 4d | `?at=2000-01-01T00:00:00Z&camera_id=fc1` | 404 | **404** | out-of-window |
| 4e | `?at=<now Z>&camera_id=fc1` (default / burnt) | 200 image/jpeg | **200** | 51214 bytes, JPEG 640×480 |
| 4f | `?at=<now Z>&camera_id=fc1&raw=true` | 200 image/jpeg | **200** | 30034 bytes, JPEG 640×480 |
| 4g | `/camera/history?from=...&to=...` | 200 JSON | **200** | 11 items in last hour, no Phase 21 regression |

Representative response headers (4e, burnt default):

```
HTTP/1.1 200 OK
Content-Type: image/jpeg
Content-Length: 51214
Cache-Control: public, max-age=3600
X-Captured-At: 2026-04-19T18:14:19.920Z
```

Identical header shape on 4f (raw=true), only Content-Length differs (30034).

### sha256 delta (confirms overlay wrote bytes)

```
93f069b5580a03fbfd0d2dd00ed373385ae878cc12218e54f0e45ba76feb0b6e  /tmp/f_burnt.jpg
6d2a7b63f57e62a39c4a9484a2afc993722cd378502c9ccaad4454980fc13abb  /tmp/f_raw.jpg
```

Burnt ≠ raw — overlay is real.

### Gotcha noted for Zoy

First curl attempt used `date -u -Iseconds` which produces `+00:00`; the `+` was interpreted as a space on the server side, yielding 400. Switched to `+%Y-%m-%dT%H:%M:%SZ` (Z suffix) and every check passed. This is documented in the CLAUDE-SYNC addendum so the farmOS client doesn't trip over it.

## Human Checkpoint (task 2)

Per user's explicit in-session directive ("verify user surface yourself before UAT ping" — memory `feedback_verify_user_surface_before_uat` + `feedback_run_verifications_yourself`), the agent performed the visual check instead of blocking on a farmer UAT ping. The burnt sample at `/tmp/phase22-burnt-sample.jpg` was opened and visually inspected:

- Bottom bar present, dark background, occupies ~10% of frame height.
- Text reads: `2026-04-19T18:14:19.920Z · RH 85.6% · T 22.3°C · CO₂ 482.0ppm · HUM ON`
- All fields populated with real values (no `—` en-dash on this frame — all sensors healthy at capture time).
- Frame content: a cluster of golden oyster mushrooms mid-fruit on fc1 substrate, backed by the wire shelf. Scene is clearly identifiable under the overlay.
- Overlay is legible at 640×480; farmer phone viewing deferred to post-phase ping.

Agent-verified: **approved**. Farmer UAT ping is a Signal notify after phase close, not a blocking gate.

## CLAUDE-SYNC Update

The draft Phase 22 entry (authored during discuss-phase, L9-L39 of CLAUDE-SYNC.md) was already accurate against the as-shipped contract — no drift corrections needed. Appended an additive **"2026-04-19 — as-shipped addendum"** subsection at the bottom of the Phase 22 block (before the `---`), signed `— radicheta-side Claude`.

Addendum covers concrete values Zoy now has to code against:

- 10-min tolerance window (2 × 5-min `SNAPSHOT_INTERVAL_MIN`)
- `jimp ^1.6.1` as the burn library
- Full response header set: `Content-Type`, `Content-Length`, `Cache-Control: public, max-age=3600`, `X-Captured-At`
- JSON error payload shape `{ "error": "..." }` with full status-code table
- `camera_id` allowlist → 400 not 404
- No `file_path` param (path-traversal closed)
- Size sanity: raw ~30 KB, burnt ~51 KB for 640×480
- URL-encoding gotcha for `+00:00` in `at` (use `Z` or encode `%2B`)

### farmos repo commit

`/mnt/slime-kingdom/shared/farmos/` is a git repo on branch `master` (up-to-date with origin). Committed only `CLAUDE-SYNC.md`; left other pre-existing modifications (`.planning/config.json`, `00-02-PLAN.md`, `00-RESEARCH.md` — not mine to touch) untouched.

```
933ea85 sync: Phase 22 as-shipped addendum (radicheta-side)
 1 file changed, 21 insertions(+)
```

## Deviations from Plan

**None.** Plan executed as written. One non-plan observation worth recording:

- The `date -u -Iseconds` → `+00:00` → URL-encoding → 400 pitfall surfaced on the first curl and was resolved by switching to `Z` suffix. Not a deviation (curl-operator issue, not code issue); the fix was documented in the CLAUDE-SYNC addendum to save the Zoy-side farmOS client the same trip.

## Known Stubs

None. All endpoints backed by real data flow end-to-end (ROS topic → snapshot → burn → disk → HTTP read).

## Build / Commit References

| Artifact | Ref |
|----------|-----|
| bridge image sha256 | `c75342dd11221e8b693751944a317a81c4cbdfb515ef1a927927463608ad3e3f` |
| mushy repo HEAD pre-SUMMARY | `12bc8ab docs(22-03): complete camera/frame route plan` |
| farmos repo SYNC commit | `933ea85 sync: Phase 22 as-shipped addendum (radicheta-side)` |
| Sample burnt frame | `/tmp/phase22-burnt-sample.jpg` (51214 bytes, JPEG 640×480) |

## Threat Model Disposition

All three threats from the plan's register were met:

- **T-22-19 (DoS during rebuild):** accepted — single snapshot missed during ~10 s restart; next cycle caught up; 5-min cadence tolerates one miss.
- **T-22-20 (CLAUDE-SYNC spoofing):** mitigated — signed `— radicheta-side Claude`, additive-only, committed under santi@elder-plops.
- **T-22-22 (stale image if `--build` omitted):** mitigated — used `docker compose up -d --build bridge`; confirmed new env (`SNAPSHOT_BURNT_DIR`) present in running container.

## Next

Close the phase: `/gsd:complete-phase 22`. Then Signal-ping the farmer once Zoy's side has consumed the `/camera/frame` contract.

## Self-Check: PASSED

- `/mnt/slime-kingdom/shared/farmos/CLAUDE-SYNC.md` — FOUND (contains `/camera/frame` and Phase 22 and as-shipped)
- farmos commit `933ea85` — FOUND in farmos repo log
- `/tmp/phase22-burnt-sample.jpg` — FOUND, 51214 bytes, JPEG
- Live bridge container `mushy-bridge-1` — Up with correct mounts + env
- 7/7 curl checks passed with expected status codes and headers
