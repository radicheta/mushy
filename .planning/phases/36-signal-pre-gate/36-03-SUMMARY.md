---
phase: 36-signal-pre-gate
plan: 03
status: complete
completed_utc: 2026-05-11
---

# Plan 36-03 — post-rebuild-trust-check.sh — SUMMARY

## What shipped

Long-lived enforcement infrastructure for SC#3 ("alerter container rebuild does not break identity trust"). Idempotent bash script + 5-test bats suite + Docker healthcheck wire-up. Live attestation captured during the session.

## Concrete outputs

| Path | Purpose |
|------|---------|
| `scripts/signal/post-rebuild-trust-check.sh` | Trust-DB integrity check; 5 verdicts (ok / recovered / hard_mismatch / signal_cli_unreachable / baseline_missing) |
| `scripts/signal/known-good-identity.json` | Pinned bot fingerprint baseline (current live fingerprint, captured 2026-05-11 18:26 UTC; Phase 36 no-op outcome means this IS the production identity, not a post-reg snapshot) |
| `scripts/signal/test/post-rebuild-trust-check.bats` | 5 bats tests covering all verdicts |
| `scripts/signal/test/fixtures/identities-{clean,stale,mismatch}.json` | Fixture identity lists for the three operational branches |
| `src/agents/alerter/Dockerfile` | Added `apk add --no-cache bash curl jq` so the alpine alerter base can run the bash healthcheck |
| `docker-compose.override.yml` | Mount + env + healthcheck wired into alerter service |

## Four operational verdicts and their hot paths

| Verdict | Exit | When it fires | Hot path? |
|---------|------|---------------|-----------|
| `ok` | 0 | bot fingerprint matches baseline + all recipients in `TRUSTED_VERIFIED`/`TRUSTED_UNVERIFIED` | ✅ Yes — expected on every healthy rebuild and every 5min poll |
| `recovered` | 0 | bot fingerprint matches + ≥1 recipient drifted to `UNTRUSTED` → auto-re-trusted via `?trust_all_known_keys=true` | Occasional — the rebuild-corruption recovery from memory `project_signal_cli_rebuild_breaks_trust` |
| `hard_mismatch` | 1 | bot's own fingerprint != baseline. Container marked **unhealthy**, NO auto-trust per D-06 | Should NEVER fire in normal operation — indicates real key rotation (e.g. a future re-registration) and requires operator review |
| `signal_cli_unreachable` | 2 | REST API down or non-array response | Transient flaps absorbed by `retries: 2` + `interval: 5m`; persistent failures indicate signal-cli is sick |
| `baseline_missing` | 3 | `known-good-identity.json` missing or has empty `bot_fingerprint` | Only fires if the mount or repo state is broken; healthcheck failure surfaces the misconfig |

## Live attestation (this session, SC#3 evidence)

```
2026-05-11T18:29:something  Container mushy-alerter-1 Recreated (new healthcheck active)
2026-05-11T18:30:10Z         Healthcheck exec inside container:
                             {"verdict":"ok","recipients_checked":"3"}
2026-05-11T18:30:10Z         Container marked Status: healthy (FailingStreak: 0)
```

Rebuild → healthcheck → verdict=ok → healthy. SC#3 attested.

## Plan deviation: baseline source

The original Plan 36-03 Task 2 expected to ingest the **post-reg** identity fingerprint (from Plan 36-02 Task 2's `identities-postreg-YYYYMMDD.json`). Since Plan 36-02 became a no-op (PRE-01 already met — see `36-02-SUMMARY.md`), the baseline was instead seeded from the **current live** identity. Outcome is equivalent — what matters is the baseline represents the stable production fingerprint; subsequent rebuilds verify drift against it.

Trade-off: if/when a real re-registration ever happens (SIM swap, etc.), this baseline must be re-captured. Operator task documented in `36-RUNBOOK.md` §4c and surfaced as the `hard_mismatch` verdict's recovery path.

## Bugs caught during live testing (would have shipped silently otherwise)

### Bug A: bbernhard API field name

Plan 36-03 documented the identity trust field as `.trust_level`. Real `bbernhard/signal-cli-rest-api:0.200-dev` returns `.status`. Caught during the first live smoke run (mass `recovery_failed` because all rows looked UNTRUSTED). Fixed in script + fixtures + tests.

### Bug B: `read` collapses leading empty TSV fields

Bash `IFS=$'\t' read -r number status` treats leading TAB as a generic whitespace separator and shifts the next field into `number`. The live identities array contains one entry with empty `.number` (a sync-target row); on that row, `read` set `number="TRUSTED_UNVERIFIED"`, then the script tried to PUT trust to a recipient named `TRUSTED_UNVERIFIED`, which signal-cli rejected with HTTP 400.

Fix: switched separator from TAB to `|`, filtered empty-number rows in jq itself, and never let the bash loop see them. Bats tests cover the path.

## Verification

```
$ bats scripts/signal/test/post-rebuild-trust-check.bats
1..5
ok 1 clean: matching fingerprint + all recipients accepted → verdict=ok, no PUT calls
ok 2 stale: matching fingerprint but one recipient UNTRUSTED → verdict=recovered + PUT issued
ok 3 hard_mismatch: bot fingerprint differs from baseline → exit 1, verdict=hard_mismatch, no PUTs
ok 4 signal_cli_unreachable: fetch returns nothing → exit 2, verdict=signal_cli_unreachable
ok 5 baseline_missing: known-good file unreadable → exit 3, verdict=baseline_missing

$ docker compose config --quiet && echo OK
OK

$ docker inspect mushy-alerter-1 --format '{{.State.Health.Status}}'
healthy
```

## What's next

- Plan 36-04 D-14 already incidentally exercised during the Plan 36-03 Task 2 wire-up (rebuild → healthcheck → ok). Formal Plan 36-04 attestation still TBD; T+24h re-run cycle on the calendar (~2026-05-12 18:00 UTC).
- Memory `project_signal_cli_rebuild_breaks_trust` (the auto-trust curl recovery recipe) is now operationally automated by this script for the per-recipient stale-row class. The memory remains relevant for the BOT-key-changed class which is intentionally NOT auto-handled (hard_mismatch → operator review).
