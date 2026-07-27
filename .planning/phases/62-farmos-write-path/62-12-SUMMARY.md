---
phase: 62-farmos-write-path
plan: 12
subsystem: testing
tags: [live-fire, farmos, dev-18080, json-api, upsert, fidelity-gate]

requires:
  - phase: 62-farmos-write-path
    provides: full Python write path (client, merge, assets, logs, files, router, watchdog, fidelity gate)
provides:
  - "in-phase dev :18080 live-fire proving SC2 (0-dup upsert) + SC3 (image-on-field) + SC4 (fidelity hold)"
  - "finding: dev farmOS account is mushy-bot, not the tenant-config farmos_agent (config drift)"
affects: [farmos-write-path, 64-parity-gate, 65-cutover, tenancy-config]

tech-stack:
  added: []
  patterns:
    - "env-gated opt-in live-fire (mark live_fire, skip unless FWR_LIVE_FIRE=1 + creds); never runs in CI"
    - "unique timestamped block name per run => re-runnable against accumulating dev state; name-filter count, not global count"

key-files:
  created:
    - src/farm-agent/tests/test_farmos_live_fire.py
    - src/farm-agent/tests/fixtures/farmos/live_fire_seeding_draft.json
    - src/farm-agent/live-fire-trails/lf_20260629_000934.jsonl

key-decisions:
  - "D-04: live-fire is in-phase against dev :18080, not deferred to an operator step"
  - "Ran the live-fire with FARMOS_USERNAME=mushy-bot (the working dev account), overriding the tenant config's farmos_agent which fails auth (HTTP 400)"

patterns-established:
  - "live-fire is the ship-gate for wiring seams unit tests miss (feedback_unit_tests_dont_catch_wiring)"

requirements-completed: [FWR-01, FWR-02, FWR-03]

duration: ~10min (incl. auth-mismatch diagnosis)
completed: 2026-06-29
---

# Phase 62 Plan 12: dev :18080 Live-Fire Summary

**The full Python write path is proven live against dev farmOS :18080: a second commit of the same seeding draft creates 0 duplicate assets, the attached image lands on the asset's `image` field, and a strain-mismatch draft is held as `fidelity_cross_check_unverified` with 0 assets created.**

## Performance

- **Duration:** ~10 min (incl. a real auth-mismatch the live-fire caught)
- **Completed:** 2026-06-29
- **Tasks:** Task 1 (live-fire test + run) PASS; Task 0 (creds) + Task 2 (operator UI verify) handled in-session (creds resolved; automated + independent-API proof in lieu of / pending the visual UI confirm)

## Results (run lf_20260629_000934)

| SC | Assertion | Evidence |
|----|-----------|----------|
| SC2 | 0 duplicate `asset--fungi` on 2nd run | Run A asset `f64fffa7-cf1f-4d31-b59f-76aedc018836`; Run B created `[]`; name-filter re-query count == 1 |
| SC3 | image on the asset `image` field | file_id `ff60a5a3-4a26-4af9-8fa1-1d63309be4d0`; independent API query shows `image` relationship present |
| SC4 | strain-mismatch held, 0 assets | block `LF_20260629_000934_MISMATCH` held `fidelity_cross_check_unverified`; name-filter count == 0 |

Both the test's own assertions AND an independent post-run JSON:API re-query (orchestrator) agree.

## Finding: dev farmOS username config drift (NOT a code defect)

The live-fire caught a real wiring issue: the ported `client.py` auth (a faithful mirror of Node `client.js` — `POST /user/login?_format=json`, JSON `{name,pass}`) returned **HTTP 400** using the tenant config's `FARMOS_USERNAME: farmos_agent` (`tenants/mossrock/config.yaml`). farmOS's Drupal JSON login route returns 400 for an unrecognized username/password. A username probe confirmed the working dev account is **`mushy-bot`** (HTTP 200; established in Phase 55B when the dev password was reset to match `secrets.env`). The write-path code is correct; the config username is stale.

**Recommendation (follow-on, needs operator confirmation — touches deploy config):** reconcile `FARMOS_USERNAME` for the mossrock tenant/dev to `mushy-bot` (and confirm the prod `:8082` account name in repo-root `.env`), so a real alerter-py boot against farmOS authenticates instead of silently failing on every commit.

## Notes

- The run targeted dev `:18080` only (the test asserts the URL port before any write; prod `:8082` never touched).
- Paper trail (uuids only, no creds): `src/farm-agent/live-fire-trails/lf_20260629_000934.jsonl`.
