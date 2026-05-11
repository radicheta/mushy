# Phase 37 Runbook — Multi-farmer Routing

**Purpose:** Plumb `SIGNAL_GROUP_ID` + `SIGNAL_FARMER_MAP` into the live alerter container, redeploy, and confirm via four live attestations that (a) f2 DMs no longer leak to f1 (999.20 retired), (b) alerter-originated sends default to the "Mush Farm" group, (c) unmapped whitelisted senders are captured with the `(unassigned)` sentinel and still get a reply, and (d) envelopes with multiple group triggers fire exactly one reply (D-09 dedupe).

**Estimated wall-time:** 15–30 min if attestations pass on first try. Add ~10 min per farmer if Signal-side scheduling delays occur.

**Pre-reqs:** Plans 37-01..37-03 merged to `main`; commit `7b7256c` (Plan 37-04 Task 1) staged the compose env + index.js wire-up. `37-SMOKE.md` verdict line = PASS.

---

## 1. Prerequisites

- [ ] Phase 36 shipped — `signal-cli` runs as primary on `deviceId=1`. Verify: `curl -sS http://127.0.0.1:8085/v1/about | jq -r '.capabilities."v2/send"'` returns an array containing `"mentions"`.
- [ ] Plans 37-01 / 37-02 / 37-03 all have `SUMMARY.md` in this phase directory.
- [ ] `37-SMOKE.md` reviewed; note the **send-path identifier shape** caveat (§2 below).
- [ ] Farmers f1, f2, f3 reachable for the next ~30 min for attestations A and D.
- [ ] Operator has shell on `elder-plops` (host running the alerter container).
- [ ] Repo-root `.env` is writeable by the operator account. (`.env` is gitignored.)

---

## 2. Obtain SIGNAL_GROUP_ID

**Decision — which identifier form to paste:**

The signal-cli REST endpoint returns two fields per group: `internal_id` (bare base64) and `id` (already-prefixed `group.<base64>` form). Per 37-SMOKE.md Probe A, the `/v2/send` endpoint accepts only the `id` form when passed via `recipients[]`. The alerter wraps the env value as `group.${SIGNAL_GROUP_ID}` internally (see `src/agents/alerter/src/signal.js` line 49–50), so `SIGNAL_GROUP_ID` MUST be the bare `internal_id`, NOT the prefixed `id`.

**Source-of-truth value (verified via Probe A 2026-05-11):**

```
SIGNAL_GROUP_ID=hKw0KX1gte8Mnjw7fMlMCsPc7s/g3drpkpVsBwPcxwE=
```

**To re-derive (or for future groups):**

```bash
BOT=$(grep -E '^SIGNAL_SENDER=' /mnt/slime-kingdom/opt/mushy/.env | cut -d= -f2)
curl -sS "http://127.0.0.1:8085/v1/groups/$BOT" | jq '.[] | {name, internal_id, id}'
```

Pick the row where `name == "Mush Farm"`. Copy the `internal_id` value (bare base64; no `group.` prefix; trailing `=` padding is part of the value).

**Common pitfalls:**

- Do NOT paste the `id` field (already-prefixed `group.<...>=`). Alerter will then send to `group.group.<...>=` which signal-cli rejects with HTTP 400.
- Format spot-check: `^[A-Za-z0-9+/=]{20,}$` after stripping whitespace.
- If `curl` to `127.0.0.1:8085` fails, signal-cli isn't on host loopback — re-check `docker-compose.override.yml` port binding (`127.0.0.1:8085:8080`).

---

## 3. Author SIGNAL_FARMER_MAP

**Format:** `+phone:slug,+phone:slug,+phone:slug`

- Phones MUST be E.164 (`+` prefix, country code, no spaces, no dashes).
- Slugs MUST match a farmOS person directory slug exactly (case-sensitive). Pull from `/mnt/slime-kingdom/shared/farmos/.planning/notes/` (FarmOS schema lock commit `d4e5a30`, 2026-05-11). When in doubt, use the lowercase short-name the farmer is referred to by in the group thread (`f1`, `zoy`, `f3`).
- Whitespace around `:` and `,` is tolerated (the parser trims).
- Parser splits on the FIRST `:` only — slugs containing `:` (none today) are forward-compatible.
- Malformed entries are silently dropped — the `[boot] farmer-map entries = N` log line is the only operator-visible signal of a typo. If `N` is lower than expected, re-check punctuation in `.env`.

**For v1.7 — three entries needed (operator fills real phones):**

```
SIGNAL_FARMER_MAP=+5XXXXXX3012:f1,+<zoy-phone>:zoy,+<f3-phone>:f3
```

- f1 phone is the value already in repo-root `.env` as `SIGNAL_RECIPIENT`. Confirmed: `+5XXXXXX3012`.
- zoy's phone — NOT the same as f1. Pull from farmOS people directory or out-of-band. Phase 36 added zoy to `SIGNAL_ADDITIONAL_SENDERS`; that env line is the source of zoy's number.
- f3's phone — pull from farmOS people directory or out-of-band.

**Unmapped-but-whitelisted senders** (a phone in `SIGNAL_ADDITIONAL_SENDERS` that is NOT in `SIGNAL_FARMER_MAP`) are captured with `farmos_person = '(unassigned)'` per D-12, and the reply still fires. Operator updates `.env` + restarts to map them later.

---

## 4. Update repo-root `.env`

Append (or update if already present) these two lines:

```bash
SIGNAL_GROUP_ID=hKw0KX1gte8Mnjw7fMlMCsPc7s/g3drpkpVsBwPcxwE=
SIGNAL_FARMER_MAP=+5XXXXXX3012:f1,+<zoy-phone>:zoy,+<f3-phone>:f3
```

Phones MUST be unmasked in `.env` (the `X`s above are documentation placeholders only). `.env` is gitignored.

Sanity-check the file parses by sourcing in a sub-shell:

```bash
( set -a; . /mnt/slime-kingdom/opt/mushy/.env; set +a; \
  echo "GROUP=${SIGNAL_GROUP_ID:0:12}…"; \
  echo "MAP=${SIGNAL_FARMER_MAP}" )
```

Both lines should print with values (no `unbound variable`).

---

## 5. Deploy alerter

From repo root on `elder-plops`:

```bash
docker compose up -d --build alerter
sleep 5
docker compose logs --tail=80 alerter | grep -E '\[boot\]'
```

**Expected `[boot]` lines (verify presence in order):**

```
[boot] alerter starting — sender=+5XXXXXX0205 recipient=+5XXXXXX3012
[boot] bridge=ws://… signal=http://signal-cli:8080 tz=America/Toronto
[boot] signal_capture schema initialized (db=…)
[boot] signal defaultTarget = group:hKw0KX1g…
[boot] farmer-map entries = 3
```

**Failure-mode triage:**

- If `defaultTarget = DM:+5XXXXXX3012` appears → `SIGNAL_GROUP_ID` didn't reach the runtime. Re-check `.env` line punctuation, then re-check `docker-compose.override.yml` has the `- SIGNAL_GROUP_ID=${SIGNAL_GROUP_ID}` line (commit `7b7256c`).
- If `farmer-map entries = 0` (or fewer than expected) → `SIGNAL_FARMER_MAP` is malformed. Most common: missing `+` prefix on phone, or trailing comma, or typo in the colon separator.
- If the container fails to start → `docker compose logs alerter | grep -iE 'error|fatal'` — most likely a `mustEnv` throw for an unrelated missing var.

Do NOT proceed to attestations until BOTH new `[boot]` lines are visible.

---

## 6. Live verification — four attestations

Mark each attestation outcome in `37-04-SUMMARY.md` with timestamp + exact strings/values observed.

### Attestation A — 999.20 proof-of-fix (ROUTE-01)

**Goal:** Confirm that an f2 (zoy) DM to the bot triggers a reply to f2 only, never to f1.

1. zoy sends a Signal DM to the bot (NOT the group): `ping P37-<3-digit rand>`. Operator coordinates the exact ping string over a separate channel.
2. Wait up to 60s for the bot reply.
3. zoy confirms a reply arrived on her phone (paste the exact reply body into `37-04-SUMMARY.md`).
4. Operator (f1 phone) confirms NO Signal message arrived during the same window.
5. (Sanity check, optional) On `elder-plops`: query the most recent capture row:

   ```bash
   docker compose exec timescale psql -U postgres -d postgres -c \
     "SELECT sender, farmos_person, reply_target_kind, captured_at
      FROM signal_capture ORDER BY captured_at DESC LIMIT 1;"
   ```

   Expected: `sender = <zoy phone>`, `farmos_person = 'zoy'`, `reply_target_kind = 'dm'`.

**Pass criterion:** reply visible on zoy's phone AND absent from f1's phone AND (if checked) capture row attributes correctly.

### Attestation B — Group default visibility (D-04, ROUTE-02)

**Goal:** Confirm that alerter-originated non-reply sends now land in the "Mush Farm" group thread, not as a DM to f1.

There are two paths:

- **Path 1 (preferred, deterministic):** trigger a Tier B/C alert by briefly pushing RH out-of-band. Out of scope for this runbook — defer to operator judgement.
- **Path 2 (no-side-effect):** wait for the next scheduled heartbeat. The heartbeat cadence is configured by `ALERT_HEARTBEAT_HOUR` (default `8` America/Toronto). Verify the next heartbeat tick is < 60 min away; otherwise lower the hour temporarily.

  ```bash
  docker compose logs alerter | grep -i heartbeat | tail -5
  ```

**Pass criterion:** the heartbeat message appears in the "Mush Farm" group thread; the f1-DM thread does NOT receive it during the same window.

### Attestation C — Unknown-sender capture (ROUTE-03)

**Goal:** Confirm an unmapped-but-whitelisted sender is captured with `farmos_person = '(unassigned)'` AND still receives a reply (D-12).

1. Identify a whitelisted phone NOT mapped in `SIGNAL_FARMER_MAP`. If none exists in the current whitelist, temporarily add a test phone to `SIGNAL_ADDITIONAL_SENDERS` (without adding to `SIGNAL_FARMER_MAP`) and redeploy.
2. From that phone, DM the bot: `hello P37-unmapped`.
3. Confirm a Signal reply arrives back on the test phone.
4. Verify the capture row:

   ```bash
   docker compose exec timescale psql -U postgres -d postgres -c \
     "SELECT sender, farmos_person, reply_target_kind, captured_at
      FROM signal_capture ORDER BY captured_at DESC LIMIT 1;"
   ```

**Pass criterion:** `sender` matches the test phone, `farmos_person = '(unassigned)'` (literal — quoted parens are part of the sentinel), `reply_target_kind = 'dm'`, AND the reply was received.

If you added a test phone, remove it from `SIGNAL_ADDITIONAL_SENDERS` and redeploy when done.

### Attestation D — Group dedupe + mention-by-phone (D-09, D-06)

**Goal:** Confirm an envelope with BOTH an @mention AND a command keyword fires EXACTLY ONE bot reply (not two), and that mention matching keys off the bot's phone (D-06) rather than display name.

**About @-mentions in Signal:** Signal's mobile UI lets you @-mention a contact by typing `@` and selecting from a contact list. The UI renders mentions by display name, but the wire envelope encodes them in `dataMessage.mentions[].number` as the E.164 phone of the mentioned account. Per D-06 + 37-SMOKE.md A2, the bot's matcher compares `mention.number` against `config.signalSender` (the bot's E.164). Display name is irrelevant — works even if the bot's Signal profile has no display name set (as it currently doesn't).

1. From zoy's phone, send a single message to the "Mush Farm" group containing BOTH:
   - An @-mention of the bot account (open the contact picker, select the bot — Signal renders it as the bot's display name or phone, doesn't matter)
   - The command keyword `mute` (or `snooze 1h`, `status`, `quiet`)
   - Example composed message text (post-mention): `@Bot mute` — the literal text Signal sends will be `￼ mute` (object-replacement char for the mention) with the mention encoded structurally.
2. Within 60s, observe the bot's reply in the group thread.
3. Confirm: EXACTLY ONE bot reply message is visible. Count the bot's messages in the group from the timestamp just before zoy's send to ~60s after.
4. Verify the capture row:

   ```bash
   docker compose exec timescale psql -U postgres -d postgres -c \
     "SELECT id, sender, group_id IS NOT NULL AS in_group, reply_target_kind, captured_at
      FROM signal_capture ORDER BY captured_at DESC LIMIT 1;"
   ```

**Pass criterion:** exactly one bot reply in the group; `in_group = t`, `reply_target_kind = 'group'`, exactly one row.

If TWO bot replies appear, the D-09 dedupe regressed — file a follow-up plan; do not block this phase indefinitely (the operator can always temporarily unset `SIGNAL_GROUP_ID` to revert to DM-only).

---

## 7. Rollback

If any attestation fails and a hot-fix is not in reach:

1. Comment out (or delete) the `SIGNAL_GROUP_ID=` line in `.env`. Leave `SIGNAL_FARMER_MAP=` as-is (it's inert without the group).
2. Redeploy: `docker compose up -d --build alerter`.
3. Confirm the boot log now shows `defaultTarget = DM:+5XXXXXX3012`.
4. File a deferred item under `.planning/phases/37-multi-farmer-routing/deferred-items.md` with the failure mode. Do not block downstream phases (38+) — they only depend on the schema columns, which are already migrated and back-compat (NULL on legacy rows).

---

## 8. Phase 33 invariant check (non-regression)

After all four attestations pass, do one final non-regression check against the Phase 33 VPS outage-alert path. The Phase 33 path bypasses the alerter entirely (`bridge` service POSTs directly to `signal-cli` on host loopback per `project_phase33_shipped` memory), so structurally it cannot inherit the new `defaultTarget` — but verify anyway.

1. Simulate a VPS-side outage trigger per `33-RUNBOOK.md` § "VPS Outage Detection". The simplest path: stop the alerter container on `elder-plops` for >3 min and let the VPS heartbeat receiver fire.

   ```bash
   docker compose stop alerter
   # wait 4+ min; VPS detects silence
   docker compose start alerter
   ```

2. Confirm: the outage alert lands on f1's phone as a DM, NOT in the "Mush Farm" group thread.

**Pass criterion:** Phase 33 outage alert is operator-only, direct DM, no group leakage.

Record the outcome in `37-04-SUMMARY.md` under "Attestation E (Phase 33 invariant)".

---

## Appendix — Quick reference

| Variable | Source | Format | Required |
|---|---|---|---|
| `SIGNAL_GROUP_ID` | signal-cli `/v1/groups/$BOT` `.internal_id` | bare base64 | for D-04 default-to-group |
| `SIGNAL_FARMER_MAP` | farmOS people directory + farmer phones | `+phone:slug,...` | for D-11 attribution |

**Boot log lines that prove envs reached the runtime:**

```
[boot] signal defaultTarget = group:<first-8-chars>…
[boot] farmer-map entries = <N>
```

**One-line health probe (post-deploy):**

```bash
docker compose logs --tail=10 alerter | grep -E '\[boot\] (signal defaultTarget|farmer-map)'
```
