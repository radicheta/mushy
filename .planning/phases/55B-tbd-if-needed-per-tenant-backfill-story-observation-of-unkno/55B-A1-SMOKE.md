---
phase: 55B-fidelity-corpus-unblock
plan: 01
artifact: A1-SMOKE
assumption: A1 (PATCH associates file--file to asset--group)
verdict: BLOCKED
target: dev farmOS :18080
recorded: 2026-06-10
---

# A1 PATCH-associates-files dev smoke probe

Target: http://10.68.155.50:18080 (dev only; prod :8082 refused by script guard)

## Result: BLOCKED (not falsified)

The probe could not reach the PATCH step because authentication to dev :18080 fails.

Diagnostic facts:
- `GET http://10.68.155.50:18080/api` -> HTTP 200 (dev farmOS is up and reachable)
- `POST /user/login?_format=json` -> HTTP 400, body `{"message":"Sorry, unrecognized username or password."}`
- Credentials tried: `FARMOS_USERNAME` (mushy-bot, 9 chars) from `.env` + `FARMOS_PASSWORD`
  (31 chars) from `tenants/mossrock/secrets.env` -- the same pair that authenticates
  against prod :8082.

Conclusion: the prod bot credentials are NOT valid on the dev :18080 instance. The
`mushy-bot` account either does not exist on dev or has a different password there.
A1 (whether a relationships.file PATCH associates a file to an asset--group) is therefore
still UNVERIFIED -- the PATCH was never exercised.

## Unblock options

1. Provide the dev :18080 bot password (and username if it differs), then re-run
   `node src/agents/alerter/scripts/a1-probe.js`.
2. Provide a dev admin account usable for the smoke.
3. Defer live A1: implement Plan 03 image-attach with the direct `patchGroupAssetFiles`
   PATCH (already hermetically unit-tested) and fold the LIVE A1 confirmation into Plan 04's
   5-page re-smoke (which already writes to dev :18080 and asserts "session images attached").
   Risk: if A1 is false, the image-attach approach reworks to the two-step fallback at
   re-smoke time. NOTE: this still requires working dev :18080 creds for the re-smoke.

## Hard prerequisite surfaced

Both of Phase 55B's live operator gates (this A1 probe AND the Plan 04 re-smoke) write to
dev :18080. Working dev credentials are required for either gate to run. Resolving the dev
login is a prerequisite for completing the phase's live validation regardless of the A1
path chosen.
