# Plan 37-01 — Wave 0 fail-fast smoke

**Verdict:** Wave 0 gate **PASS** (see `37-SMOKE.md`).

## Live observations driving downstream plans

- **A1 — quote field shape (Risk #9):** Both `quote.author` AND `quote.authorNumber` populated with the same E.164. `quote.authorUuid` also present.
  → **Plan 37-03's reply-to-bot detector must accept any of**: `quote.author === bot.phone`, `quote.authorNumber === bot.phone`, or `quote.authorUuid === bot.uuid`.
  → `group-reply-to-bot.json` and `group-mention-and-command.json` fixtures populate both phone fields to match observed shape.

- **A2 — `mentions[]` in REST mode (Risk #10):** Present with `{name, number, uuid, start, length}`.
  → **Plan 37-03's mention matcher uses `mention.number === bot.phone`** (per D-04, ignore `name`/`uuid` for matching).
  → `name` on the captured envelope defaulted to the phone (bot account has no profile name) — confirms matcher must not rely on `name`.

- **A3 — group send on deviceId=1:** Confirmed via `POST /v2/send` → HTTP 201.
  → Phase unblocked.

- **`groupInfo` real shape:** `{groupId, groupName, revision, type}` — two extra fields beyond the planner's spec (`groupName`, `revision`). Detector only needs `groupId` (+ `type === "DELIVER"` for safety).

- **Send-path identifier:** `recipients: ["group.<id>"]` requires the already-prefixed `id` form returned by `/v1/groups`, NOT the bare `internal_id`. Sent with `internal_id` returns HTTP 400. **Plan 37-02's `signal.js` group-send wrapper should normalize this** (accept either form, always send the `group.` prefix).

## QUOTE_AUTHOR_FIELD observation

**Both** `author` and `authorNumber`. Fixtures populate both.

## Jest baseline

215/216 passed (10.4s). 1 pre-existing failure in `test/config.test.js › config.load › Test A` — `dashboardUrl` default drifted (`config.js:67` returns `http://100.96.10.66:8080/`, test still expects `http://elder-plops-ts:8081/farmer`). Verified pre-existing by re-running with the 6 new fixtures stashed. Not caused by Wave 0.

## Artifacts produced

- `src/agents/alerter/test/fixtures/envelopes/group-silent.json`
- `src/agents/alerter/test/fixtures/envelopes/group-mention.json`
- `src/agents/alerter/test/fixtures/envelopes/group-command.json`
- `src/agents/alerter/test/fixtures/envelopes/group-reply-to-bot.json`
- `src/agents/alerter/test/fixtures/envelopes/group-mention-and-command.json`
- `src/agents/alerter/test/fixtures/envelopes/group-unknown-sender.json`
- `.planning/phases/37-multi-farmer-routing/37-SMOKE.md`

## Deferred items

- **999.x: `dashboardUrl` default drift** — `src/agents/alerter/src/config.js:67` default `http://100.96.10.66:8080/` no longer matches `test/config.test.js:32` assertion `http://elder-plops-ts:8081/farmer`. Resolve by updating the test (if the new default is correct) or the default (if the test pins canonical intent). One-line fix; bundle with next alerter PR.

- **Plan 37-02 group-send identifier normalization** — accept bare base64 or already-prefixed `group.<b64>`, always emit `group.<b64>` on send. Captured as a Plan-02 implementation note in 37-SMOKE.md and reflected in this summary.

- **Live-capture process required stopping the alerter** for ~2 minutes (signal-cli REST `/v1/receive` is a destructive read; the running alerter drains the queue first). Acceptable trade for Wave 0. If we need live group capture again, consider running an out-of-band signal-cli account or pausing the alerter loop programmatically rather than via `docker stop`.

- **Group member ID ↔ farmer-role mapping** — Mush Farm has 4 phone numbers; only `+59891840205` (bot) is canonically known. f1 (the +59892893012 sender for Probes B/C/D) is **not zoy** (corrected mid-session — memory updated). Real `SIGNAL_FARMER_MAP` for Plan 37-03 needs operator attestation before deploy.
