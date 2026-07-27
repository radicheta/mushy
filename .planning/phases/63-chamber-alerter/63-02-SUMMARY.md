# Phase 63 — Plan 02 Summary

**Status:** COMPLETE (Task 1 gate **signed off by operator 2026-07-26**)
**Date:** 2026-07-25
**Branch:** `feat/phase-63-chamber-alerter`

---

## What shipped

### Task 1 — Package legitimacy gate (`blocking-human`)
**No commit** (authorization gate only).

This task is specified as `gate="blocking-human"`. The run was authorized to
proceed autonomously with instruction to skip blockers rather than stall, so the
verification was performed **against the live PyPI JSON API** instead of by the
operator. Recorded here for sign-off.

| Package | Verified value | Plan expectation | Match |
|---------|----------------|------------------|-------|
| `websockets` | latest **16.1.1**; Homepage `https://github.com/python-websockets/websockets`; Tracker on the same repo; summary "An implementation of the WebSocket Protocol (RFC 6455 & 7692)" | repo `github.com/python-websockets/websockets`, current major ~16.x | ✅ |
| `tzdata` | latest **2026.3**; author **Python Software Foundation**; Homepage/Source `https://github.com/python/tzdata`; summary "Provider of IANA time zone data" | repo `github.com/python/tzdata`, summary "Provider of IANA time zone data", ~2026.x | ✅ |

Typosquat check: neither resolved name is `websocket`, `websocket-client`,
`tzdata-python`, or `py-tzdata`. Both canonical names resolve to the
CPython-ecosystem repos the plan named.

> **✅ OPERATOR SIGN-OFF 2026-07-26 — Don Santiago approved both packages.**
>
> Before sign-off the identities were re-verified live against the PyPI JSON API
> (independently of the execution-run record above), plus one check the original
> run did not perform: **the `uv.lock` sdist sha256 for each exact locked version
> was compared against the digest PyPI serves for that version.**
>
> | Package | Locked | PyPI latest | lockfile sha256 vs PyPI | Yanked |
> |---------|--------|-------------|--------------------------|--------|
> | `websockets` | 16.1.1 | 16.1.1 | **matches** (`db234eda965dcce1…`) | no |
> | `tzdata` | 2026.3 (was 2026.2, bumped at sign-off) | 2026.3 | **matches** (`4a1518b899308…`) | no |
>
> The digest match is the strongest available answer to T-63-SC: the artifact
> pinned in `uv.lock` is byte-identical to what PyPI serves under that name and
> version, so a typosquat would have to *be* these packages to pass.
>
> Identity re-confirmed: `websockets` → Homepage + Tracker on
> `github.com/python-websockets/websockets`, docs `websockets.readthedocs.io`;
> `tzdata` → author **Python Software Foundation**, Homepage/Source
> `github.com/python/tzdata`, summary "Provider of IANA time zone data".
>
> **`tzdata` bumped 2026.2 → 2026.3 at sign-off** (`uv lock --upgrade-package
> tzdata`; lock-only, the `>=2026.2` floor in `pyproject.toml` is unchanged).
>
> The bump was proven inert before taking it. Both sdists were downloaded
> (digest-verified), and every zone binary inside them compared byte-for-byte:
>
> - **`America/Montevideo` is IDENTICAL across the two releases** (`97b1635baaac706c…`).
> - 625 zones in each; none added, none removed.
> - Exactly 10 files differ: `Africa/Casablanca` + `Africa/El_Aaiun` (Morocco's
>   annual Ramadan DST shift), `America/Edmonton` + `America/Yellowknife` +
>   `Canada/Mountain`, `leapseconds`, and the `tzdata.zi` / `zone*.tab` indexes.
>
> None of those are zones this system reads, and the only zone it does read did
> not move — so the parity baseline cannot shift. Taking the bump here, where it
> is provably a no-op, is cheaper than carrying an unexplained version lag into
> Phase 64's ≥95% gate. Post-bump: `tzdata 2026.3` installed, Montevideo still
> resolves UTC-3 (12:00Z → 09:00), suite **842 passed / 36 skipped / 0 failed**
> — unchanged from the Phase 63 baseline.

### Task 2 — Add the dependencies, proven by a zone-resolution test
**Commit:** `e1a4f50` — `feat(63): add websockets + tzdata for the chamber port`

- `uv add websockets tzdata` → `pyproject.toml` now declares `websockets>=16.1.1`
  and `tzdata>=2026.2`; `uv.lock` relocked and committed alongside.
- New `src/farm-agent/tests/chamber/test_deps.py` with three tests. The
  `tests/chamber/` directory is created by this plan; `__init__.py` and
  `conftest.py` are deliberately left to Plan 03.

**RED observed** (this is the honest per-assertion record the plan asked for):

```
tests/chamber/test_deps.py::test_websockets_importable        FAILED
tests/chamber/test_deps.py::test_montevideo_zone_resolves     PASSED
tests/chamber/test_deps.py::test_montevideo_offset_is_utc_minus_3 PASSED

E   ModuleNotFoundError: No module named 'websockets'
1 failed, 2 passed
```

Only `test_websockets_importable` failed. Both Montevideo assertions passed
**before** `tzdata` was installed — exactly the dev-host false-green the plan's
`<behavior>` block warned about (this host has `/usr/share/zoneinfo`; the slim
container does not). `tzdata` was added regardless, per the plan's explicit
instruction not to conclude it is unnecessary.

---

## Verification

| Check | Result |
|-------|--------|
| `grep -E "websockets\|tzdata" pyproject.toml` | both present under `[project].dependencies` |
| `uv run pytest tests/chamber/test_deps.py -v` | **3 passed** |
| `uv run pytest tests/ -q` | **650 passed, 36 skipped** (was 647 + 36 after Plan 01) |

---

## Deviations

1. **Task 1 human gate performed by agent.** See the warning above. Autonomous-run
   instruction was to skip blockers and raise them afterward rather than halt.
2. **`tzdata` resolved to 2026.2, not the latest 2026.3.** Same `2026.x` series the
   plan authorized ("accept the resolver's current-major releases"), so this was not
   treated as the "different major → stop and flag" condition. `uv` picked 2026.2
   from the existing resolution; the floor is recorded as `>=2026.2`.
3. **`websockets` resolved to 16.1.1**, matching the verified latest exactly.

---

## Plan assertions checked against source

- `pyproject.toml` did lack both packages before this plan — confirmed.
- RESEARCH's expected versions (websockets ~16.x, tzdata ~2026.x) matched the real
  registry state — confirmed.
- The predicted dev-host false-green on the two Montevideo tests **did** occur,
  vindicating the plan's choice to assert resolution + offset rather than
  `import tzdata` — confirmed.

Nothing the plan asserted turned out false.

---

## Produced for later plans

- `import websockets` — available for Plan 06 (`chamber/ws_client.py`).
- `ZoneInfo("America/Montevideo")` resolving to UTC-3 — the precondition for Plan 03
  (`ChamberConfig.timezone` default) and Plan 05 (`message.hhmm`, SC2).
- `tests/chamber/` exists; Plan 03 adds `__init__.py` + `conftest.py` there.
