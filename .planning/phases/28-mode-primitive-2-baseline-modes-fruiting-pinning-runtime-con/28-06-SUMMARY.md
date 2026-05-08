---
phase: 28
plan: 06
subsystem: bridge + fc_buffer
tags: [mode-primitive, runtime-config, persistence, MODE-05, layer-2]
requires: [28-05]
provides:
  - POST /control/persist endpoint on bridge (fc_controller node, allowlisted params only)
  - POST /control/persist + GET /control/overlay routes on fc_buffer (atomic write to /var/lib/fc-core/runtime_overrides.yaml)
  - .bak one-generation retention for one-step manual revert
affects:
  - src/mission-control/bridge/src/control_persist.js (new)
  - src/mission-control/bridge/src/index.js (new mount)
  - src/chambers/fc-core/fc_core/fc_buffer.py (two new HTTP routes + helpers)
tech-stack:
  added: [js-yaml (already in node_modules; verified present)]
  patterns: [atomic-rename overlay write, allowlist defense-in-depth, flat dotted-key yaml]
key-files:
  created:
    - src/mission-control/bridge/src/control_persist.js
  modified:
    - src/mission-control/bridge/src/index.js
    - src/mission-control/bridge/test/control_persist.test.js
    - src/chambers/fc-core/fc_core/fc_buffer.py
    - src/chambers/fc-core/fc_core/test/test_fc_buffer.py
decisions:
  - "Layer 2 transport = fc_buffer HTTP relay (NOT SSH-from-bridge) — locked in 28-01-SPIKE.md D-B1; bridge container has no ssh binary"
  - "Path allowlist enforced on WRITER side (fc_buffer) via realpath() check + .bak/.tmp suffix rejection — defeats traversal AND symlink escape (T-28-20)"
  - "Param allowlist + range bounds duplicated bridge-side AND writer-side — defense in depth"
  - "Overlay yaml uses flat dotted keys under fc_controller.ros__parameters (D-03) — `modes.fruiting.band_low: 0.94`, NOT nested map"
  - "js-yaml emits NaN as `.nan` natively (verified live) — no post-dump normalization needed in practice; defensive replace kept"
metrics:
  duration: ~10min
  completed: 2026-05-08
---

# Phase 28 Plan 06: MODE-05 Layer 2 — Overlay Persistence Summary

**Plan delivered the runtime-config-delivery contract's "stick after reboot" path: a separate POST /control/persist endpoint that writes (param, value) tuples into `/var/lib/fc-core/runtime_overrides.yaml` on fc1, atomically, with `.bak` for one-step revert. Architectural pivot from PLAN.md's SSH-from-bridge to fc_buffer HTTP relay (locked in SPIKE D-B1).**

## What shipped

### Bridge side (`src/mission-control/bridge/`)

- **New module** `src/control_persist.js`:
  - `mergeOverlay(existing, entries)` — preserves existing keys, applies new ones at flat dotted-key level (D-03)
  - `renderOverlay(obj)` — yaml dump with header comment, sortKeys for idempotency, `.nan` normalization (defensive)
  - `makeHandler(transport, opts)` — Express handler; reuses `control_param.validate` (single source of truth for ALLOWLIST)
  - `makeHttpTransport({host, port, fetch})` — Branch B fc_buffer HTTP relay (Node 18+ global fetch)
- **Mount** in `src/index.js` next to plan 05's `/control/param` route. Default transport = `makeHttpTransport({})` resolving to `172.16.10.5:8765`.

### fc1 side (`src/chambers/fc-core/fc_core/fc_buffer.py`)

- **New helpers**:
  - `_is_safe_overlay_path(p)` — restricts to `OVERLAY_DIR` (`/var/lib/fc-core/`), rejects `..` traversal, symlink escape (via `realpath`), `.bak`/`.tmp` suffixes, and prefix lookalikes (`/var/lib/fc-core-evil/`)
  - `_atomic_write_overlay(path, content)` — write `.tmp` → `os.fsync` → rotate prior to `.bak` → `os.replace` `.tmp` → target
  - `_read_overlay(path)` — allowlist-checked read; returns None on missing
- **New HTTP routes** in the existing handler:
  - `GET /control/overlay?path=<urlencoded>` → 200 yaml / 404 missing / 400 unsafe
  - `POST /control/persist` (JSON `{path, content}`) → 200 / 400 unsafe-or-malformed / 413 oversized / 500 OS error

## Endpoint contract

```
Bridge POST /control/persist
  Body: {node:"fc_controller", param:"pid_kp", value:0.4}
        OR
        {node:"fc_controller", params:[{param,value}, ...]}  (max 20)
  ↓
  Allowlist + range validation (control_param.validate — same as Layer 1)
  ↓
  Read existing overlay via fc_buffer GET /control/overlay
  ↓
  yaml.load → mergeOverlay → renderOverlay
  ↓
  POST fc_buffer /control/persist {path, content}
  ↓
  fc_buffer: _is_safe_overlay_path(path) → _atomic_write_overlay(path, content)
  ↓
  Response: 200 {ok:true, persisted:[{param,value}], path:"/var/lib/fc-core/runtime_overrides.yaml"}
```

## Atomic-rename trace (T-28-21)

```
1. write /var/lib/fc-core/runtime_overrides.yaml.tmp  (O_WRONLY|O_CREAT|O_TRUNC, 0644)
2. os.fsync(fd)                                        # durability barrier
3. os.replace(target, target+'.bak')                   # only if target existed
4. os.replace(target+'.tmp', target)                   # atomic by POSIX rename(2)
```

At every instant either the previous version, the new version, or both (one as `.bak`) are on disk. ROS2 launch fails hard on bad yaml so fall-open is impossible by design; `.bak` enables one-step revert: `ssh fc1 sudo mv /var/lib/fc-core/runtime_overrides.yaml{.bak,}`.

## js-yaml NaN behavior observed

Live probe: `node -e "console.log(yaml.dump({a:NaN, b:0.4}))"` → `"a: .nan\nb: 0.4\n"`. js-yaml 4 emits the ROS2-compatible `.nan` literal natively. The defensive `: NaN`/`: nan` → `: .nan` regex in `renderOverlay` is a belt-and-braces guard against future js-yaml regressions; round-trip parse via `yaml.load` confirmed (test: `NaN serializes as .nan literal`).

## Threat register status

| Threat | Disposition | Status |
|--------|-------------|--------|
| T-28-20 path traversal | mitigate | **mitigated** — bridge ALLOWLIST blocks `param: 'modes../../etc/passwd...'`; fc_buffer `_is_safe_overlay_path` blocks raw filesystem traversal AND symlink escape |
| T-28-21 partial-write DoS | mitigate | **mitigated** — `.tmp → fsync → rotate → rename` sequence ensures atomicity |
| T-28-22 SSH key in container | accept-or-mitigate | **eliminated** — Branch B (fc_buffer relay) chosen; no SSH key in bridge container |
| T-28-22b SSH host-key TOFU | mitigate | **n/a** — no SSH path in use |
| T-28-23 `.bak` history disclosure | accept | accepted; no PII risk |
| T-28-24 NaN serialization | mitigate | **mitigated** — js-yaml emits `.nan` natively + defensive normalize + round-trip test |

## Deviations from Plan

### [Rule 1 — SPIKE pivot] Architectural fork from PLAN.md SSH path → fc_buffer HTTP relay

- **Found during:** plan-discuss; pre-locked in 28-01-SPIKE.md §B + §C (D-B1..D-B6) on 2026-05-07
- **Issue:** Original PLAN.md text described two-branch action (SSH-from-bridge OR fc_buffer relay). The SPIKE proved the bridge container has no `ssh` binary (`exec: "ssh": executable file not found in $PATH`), forcing Branch B. Original PLAN.md still listed both branches as live options.
- **Fix:** Implemented Branch B only. Added new task scope: POST /control/persist + GET /control/overlay routes on `fc_buffer.py` (D-B5 plan growth). Atomic write owned by writer side, not bridge.
- **Files modified:** `src/chambers/fc-core/fc_core/fc_buffer.py` (added two HTTP routes + three helpers); `src/mission-control/bridge/src/control_persist.js` (only `makeHttpTransport`, no `makeSshTransport`).
- **Commit:** `3bb0d7a`

### [Rule 2 — Defense in depth] Writer-side path allowlist + symlink-escape check

- **Found during:** Task 1 implementation
- **Issue:** SPIKE noted the fc_buffer relay must validate paths (T-28-20). Original plan text mentioned `realpath` check; implementation also caught `prefix-lookalike` attacks (`/var/lib/fc-core-evil/`) which bare `startswith` would let through.
- **Fix:** `_is_safe_overlay_path` does (a) literal prefix on raw path, (b) `.bak`/`.tmp` suffix reject, (c) `realpath` resolution of parent dir + trailing-slash prefix match against `realpath(OVERLAY_DIR)`.
- **Tests:** `test_is_safe_overlay_path_rejects_prefix_lookalike`, `test_is_safe_overlay_path_rejects_symlink_escape`.
- **Commit:** `3bb0d7a`

### [Rule 2 — Defense in depth] Request body size cap on fc_buffer POST

- **Found during:** Task 1 implementation
- **Issue:** Original plan text didn't specify request size limits; an unbounded JSON body via the wg0 link could pin fc1's tiny memory.
- **Fix:** `PERSIST_REQUEST_MAX_BYTES = 128 KiB` on the request, `OVERLAY_MAX_BYTES = 64 KiB` on the resulting yaml content. 413 returned on oversize.
- **Commit:** `3bb0d7a`

### [Rule 3 — Out of scope, deferred] Pre-existing burn_bar test failures

- **Found during:** Task 2 full-suite regression
- **Issue:** `test/burn_bar.test.js` has 2 failing tests (`Function.fromBuffer` jimp/font rendering issue) unrelated to plan 28-06.
- **Action:** Not fixed (out of scope per SCOPE BOUNDARY). Already logged in `deferred-items.md` from plan 28-05.

## Test coverage

- **Bridge jest:** 23 new tests in `control_persist.test.js`, all GREEN. Full bridge suite: 154/156 pass; 2 failures pre-existing burn_bar (deferred).
- **fc_core pytest:** 12 new tests covering `_is_safe_overlay_path` (6 cases), `_atomic_write_overlay` (5 cases), `_read_overlay` (3 cases). Full `test_fc_buffer.py`: 27/27 pass.

## Integration-soak entry condition for plan 07

- Bridge image rebuild required (`docker compose up -d --build bridge`) for index.js mount + control_persist.js to take effect on elder-plops.
- fc1 deploy required (git push to `fc1/prod` + `deploy.sh`) for fc_buffer.py routes to take effect — plan 07 owns the deploy gate.
- Plan 07's launch edit must add `/var/lib/fc-core/runtime_overrides.yaml` as the SECOND `parameters=[...]` entry after `fc_config.yaml` for last-wins semantics.
- First end-to-end test on plan 07: `curl -X POST elder-plops:8081/control/persist -d '{"node":"fc_controller","param":"pid_kp","value":0.35}'` → file lands on fc1 → `systemctl restart fc-core` → `ros2 param get /fc_controller pid_kp` returns 0.35.

## Commits

- `3bb0d7a` — feat(28-06): MODE-05 Layer 2 — overlay yaml persistence via fc_buffer relay
- `7136ec7` — feat(28-06): mount POST /control/persist on bridge with fc_buffer relay transport

## Self-Check

- [x] `src/mission-control/bridge/src/control_persist.js` exists
- [x] `src/mission-control/bridge/src/index.js` modified (control_persist required + /control/persist mounted)
- [x] `src/chambers/fc-core/fc_core/fc_buffer.py` modified (3 new helpers + 2 new routes)
- [x] 23 jest tests GREEN
- [x] 12 new pytest tests GREEN (27 total in file)
- [x] Commit `3bb0d7a` exists
- [x] Commit `7136ec7` exists

## Self-Check: PASSED
