# Phase 36 Runbook — signal-cli Primary Re-Registration

**Purpose:** Flip the mushy-bot Signal account from linked-secondary (deviceId=2, current broken state) to primary (deviceId=1) via SMS verification on the 4G router SIM. This is the load-bearing artifact of Phase 36.

**Estimated wall-time:** 15–30 min if everything works. Up to 2h if captcha/SMS retries needed.

**Pre-reqs in this session:** Plan 36-01 SHIPPED (preflight snapshot + restore recipe in place). See `.planning/phases/36-signal-pre-gate/36-01-preflight-snapshot.md`.

**What this does NOT do:** Send the kickoff message (that's §5 — Plan 36-02 Task 3) or collect farmer round-trip attestation (Plan 36-04). This runbook covers §0–§4 — the actual re-registration.

---

## 0. Pre-Flight Checklist

All boxes MUST be checked before §2.

- [ ] **Plan 36-01 snapshot exists.** See `36-01-preflight-snapshot.md` § "Snapshot Captured". Tarball at `/mnt/slime-kingdom/mushy-backups/signal-cli-data-YYYYMMDD.tar.gz`, ≥1 entry under `./data/`. (`tar -tzf <path> | wc -l` must return ≥1.)
- [ ] **Pre-reg device JSON snapshotted** (`snapshots/devices-YYYYMMDD.json`) — proves the receive-400 root cause; serves as diff baseline post-reg.
- [ ] **Pre-reg identity JSON snapshotted** (`snapshots/identities-YYYYMMDD.json`) — used to confirm farmer trust survived (their fingerprints stay the same; only the bot's own fingerprint rotates).
- [ ] **Phase 35 Tier A verdict reviewed** — currently GAP (filed as 999.52). The local tarball is the ONLY rollback path. Acknowledge before proceeding.
- [ ] **4G router (B310s-518) is powered up + SIM is in slot.** The SIM phone number = the bot E.164 = `$SIGNAL_SENDER` from repo `.env`.
- [ ] **gumbald is reachable** from elder-plops over the WireGuard hub: `ssh gumbald` works (alias resolves to `santi@10.68.155.55`). gumbald is the laptop with WiFi to the 4G router — needed to capture the SMS captcha from a browser session bound to the SIM's network.
- [ ] **gumbald has the 4G router's WiFi credentials** stored so it can join the SIM's network without operator action mid-flow.
- [ ] **`signal-cli-rest-api` is up:** `curl -sS http://127.0.0.1:8085/v1/about | jq .` returns JSON.
- [ ] **farmer #1 and farmer #2 both confirmed reachable for the next 30–60 min** (out-of-band Signal/phone contact before §1 starts). This is the gating coordination — without their reachability, the kickoff message in §5 has no recipient.

---

## 1. Capture Captcha Token

Signal's primary registration is captcha-gated. The captcha token is single-use and has a ~10-minute TTL — acquire it shortly before §2.

1. Open https://signalcaptchas.org/registration/generate.html in a browser. Use gumbald's browser if the captcha provider requires non-VPS network paths; elder-plops Firefox works in practice.
2. Solve the visual challenge. The page will produce a link of the form:
   ```
   signalcaptcha://signal-recaptcha-v2.6Lf-9...some long base64...
   ```
3. Right-click the resulting "Open Signal" button → "Copy link address". Paste it into chat.
4. Strip the `signalcaptcha://` prefix; everything after is the raw `$TOKEN`. (e.g. `signal-recaptcha-v2.6Lf-9...`)

If the page errors out or the token has expired by the time §2 runs, repeat this step. The captcha provider tolerates rapid re-acquisition.

---

## 2. Trigger SMS Registration

The bot's number receives a 6-digit SMS verification code at the 4G router SIM.

```bash
BOT=$(grep -E '^SIGNAL_SENDER=' /mnt/slime-kingdom/opt/mushy/.env | cut -d= -f2)
TOKEN="<paste token from §1 here>"
curl -i -X POST "http://127.0.0.1:8085/v1/register/${BOT}?captcha=${TOKEN}"
```

**Expected:** `HTTP/1.1 201 Created` with empty body (or `200 OK` on some signal-cli-rest-api builds).

**Failure modes:**
- `HTTP 400 Bad Request` with `Invalid captcha given` → captcha expired or already-used. Repeat §1, then retry §2.
- `HTTP 400` with `Rate limit` or `RetryAfterException` → too many recent attempts. Wait 60 min before retrying. After 3 retries, invoke §7 (abort).
- `HTTP 500` with `Need to re-register` quirk → the existing linked-device state is interfering. The fix is `docker compose restart signal-cli` then retry. The volume tarball from Plan 36-01 means this is safe to do.
- `HTTP 429` → rate-limited; wait 60 min.

**Retry budget:** 3 attempts. After 3 hard failures invoke §7.

---

## 3. Receive + Enter SMS Code

The SIM in the 4G router receives a 6-digit code via SMS. Read it from whichever interface the SIM exposes (Huawei B310s-518 web UI on its LAN IP, typically `192.168.1.1` or `192.168.8.1` — gumbald sees this since it's on the 4G WiFi).

```bash
BOT=$(grep -E '^SIGNAL_SENDER=' /mnt/slime-kingdom/opt/mushy/.env | cut -d= -f2)
CODE="<paste 6-digit code from SMS>"
curl -i -X POST "http://127.0.0.1:8085/v1/register/${BOT}/verify/${CODE}"
```

**Expected:** `HTTP/1.1 201 Created` with empty body.

**Failure modes:**
- `HTTP 400` with `Verification code is incorrect` → wrong code; retype carefully (use the latest SMS — older codes invalidate).
- `HTTP 410 Gone` → code expired. Restart from §1 (new captcha + new SMS).
- `HTTP 500` with `Already registered` → §2 was skipped or already succeeded; jump to §4 to confirm.

**Retry budget:** 2 code-entry retries. If code expired, capture a fresh one from §1; that does not count against the §2 retry budget.

---

## 4. Verify Primary Status

All three checks MUST pass before declaring §1–§3 successful.

### 4a. Device list shows primary

```bash
BOT=$(grep -E '^SIGNAL_SENDER=' /mnt/slime-kingdom/opt/mushy/.env | cut -d= -f2)
curl -sS "http://127.0.0.1:8085/v1/devices/${BOT}" | jq '.[] | select(.id==1)'
```

**Expected:** a non-empty object with `.id == 1` and a fresh `creation_timestamp` matching the §2/§3 moment (within seconds of the registration completion). The pre-reg `id=2` entry MAY still appear in the list — that's expected (D-05: do not destroy the old linked-secondary until Plan 36-04 attests round-trip on the new primary).

### 4b. Receive endpoint flipped from 400 → 200

```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:8085/v1/receive/${BOT}"
```

**Expected:** `HTTP 200`. Body is a JSON array (empty is fine — it just means no inbound messages have arrived since registration). The 400→200 flip is the PRE-01 success signal — this is the symptom that broke Phase 25 since deploy.

### 4c. Capture post-reg identity JSON for diffing

```bash
DATE=$(date -u +%Y%m%d)
SNAP=.planning/phases/36-signal-pre-gate/snapshots
mkdir -p $SNAP
curl -sS "http://127.0.0.1:8085/v1/identities/${BOT}" | jq '.' > /tmp/identities-postreg-raw.json
cp /tmp/identities-postreg-raw.json $SNAP/identities-postreg-${DATE}.json
# Redact E.164 + UUIDs before committing
sed -i -E 's/\+[0-9]{8,}/+<REDACTED>/g; s/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/<uuid-redacted>/g' $SNAP/identities-postreg-${DATE}.json
# Sanity check: no E.164 leaks
grep -E '\+[0-9]{8,}' $SNAP/identities-postreg-${DATE}.json && echo "LEAK — re-redact" || echo "OK"
```

**Cross-diff (informational):** the bot's OWN entry should show a NEW fingerprint vs the pre-reg snapshot — that's the safety number change every farmer will see warning about. Farmer entries (other recipients) should have their `fingerprint` and `uuid` UNCHANGED — the farmers themselves didn't re-register.

**This file is the source-of-truth baseline for Plan 36-03 Task 2** (`known-good-identity.json` ingestion).

If any of 4a/4b/4c fails, invoke §7.

---

## 5. Post-Reg Kickoff Message to Farmers

Per D-07: send a friendly heads-up to each farmer immediately after §4 passes. Do NOT auto-trust safety numbers (D-06) — let farmers re-accept manually on their phones.

### Verbatim message text

```
Hey — the mushy bot just got re-registered on a new device. Your Signal app
will show a "Safety number changed" warning the next time we DM. Tap it,
tap "Verify safety number" (you don't have to actually verify — just dismiss
the warning), then reply 'ok' here so I know the round-trip works.

This re-reg also unblocks me being able to read your replies (was broken
since Phase 25). Sorry it took a few weeks.
```

### Send curl (one per farmer, NOT a loop — pause between)

```bash
BOT=$(grep -E '^SIGNAL_SENDER=' /mnt/slime-kingdom/opt/mushy/.env | cut -d= -f2)
FARMER1="<E.164 from operator, NOT committed>"
MSG=$(cat <<'EOF'
Hey — the mushy bot just got re-registered on a new device. Your Signal app
will show a "Safety number changed" warning the next time we DM. Tap it,
tap "Verify safety number" (you don't have to actually verify — just dismiss
the warning), then reply 'ok' here so I know the round-trip works.

This re-reg also unblocks me being able to read your replies (was broken
since Phase 25). Sorry it took a few weeks.
EOF
)
curl -X POST http://127.0.0.1:8085/v2/send \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg n "$BOT" --arg r "$FARMER1" --arg m "$MSG" \
       '{number:$n, recipients:[$r], message:$m}')"
```

**Expected response:** `HTTP 201` with `{"timestamp": <ms-since-epoch>}`. Record the timestamp into `snapshots/kickoff-sends-YYYYMMDD.json` (Plan 36-02 Task 3 writes the file).

Wait 2–3 min, then repeat for farmer #2 (`zoy`). Plan 36-02 Task 3 owns the timestamp-recording bookkeeping.

---

## 6. What to Tell the Farmer (when the safety-number warning appears)

If a farmer pings you out-of-band confused by the Signal warning, this is the short script — paste or read aloud:

> "That warning is expected — I just re-registered the bot on a new SIM. Tap the warning banner, tap 'Verify safety number', and that's it (you don't have to scan anything). Then DM the bot 'ok' so I know it went through. The bot couldn't read your replies before today; now it can."

Do NOT use the auto-trust curl path here (D-06) — initial re-acceptance is farmer-manual. The auto-trust curl is a recovery tool for the *rebuild-corruption* class (D-08), wired up in `scripts/signal/post-rebuild-trust-check.sh` (Plan 36-03).

---

## 7. Abort Path

Trigger conditions:
- §2 returns 400/429 after 3 retries (captcha or rate-limit)
- §3 SMS code expired after 2 retries (counting fresh captchas as separate budget)
- §4 fails: deviceId still 2 after 60s, OR `/v1/receive` still returns 400

**Restore recipe** (verbatim copy of `36-01-preflight-snapshot.md § Restore Recipe`):

```bash
cd /mnt/slime-kingdom/opt/mushy
docker compose stop alerter signal-cli
docker volume rm mushy_signal-cli-data
docker volume create mushy_signal-cli-data
docker run --rm \
  -v mushy_signal-cli-data:/dst \
  -v /mnt/slime-kingdom/mushy-backups:/src \
  alpine tar -xzf /src/signal-cli-data-YYYYMMDD.tar.gz -C /dst
docker compose up -d signal-cli alerter
# Verify
BOT=$(grep -E '^SIGNAL_SENDER=' /mnt/slime-kingdom/opt/mushy/.env | cut -d= -f2)
curl -sS "http://127.0.0.1:8085/v1/devices/${BOT}" | jq '.[] | .id'
# Expected: 1 (server-side primary that we don't own) and 2 (local linked-secondary, restored)
```

After abort: chamber returns to the Phase 25 broken-but-non-destructive state. Receive remains HTTP 400; alerter outbound continues working as before. Per D-05 we kept the old linked-secondary as warm-rollback exactly for this — no farmer-side action is needed.

Diagnose the §1/§2/§3 failure mode before re-attempting. Do NOT loop on the same captcha/SMS approach if a fundamental setting is wrong (e.g. SIM not in slot, 4G router off-net).

---

## 8. Post-Reg Hand-Off to Plan 36-04

After §4 passes and §5 sends are recorded by Plan 36-02 Task 3:

- Plan 36-04 owns the farmer attestation collection (T0 immediate, T+24h re-run, post-rebuild attestation).
- Plan 36-03 Task 2 ingests the §4c `identities-postreg-YYYYMMDD.json` to populate `scripts/signal/known-good-identity.json` — DO NOT skip this; it's how the alerter rebuild healthcheck (D-14) knows what "trusted" looks like going forward.

These two plans run in parallel — Plan 36-04 needs operator+farmer attention; Plan 36-03 Task 2 is autonomous after the post-reg identity JSON lands.

---

## 9. Known Pitfalls

- **Captcha token TTL is short (~10 min).** Acquire it close to §2 execution. If §2 takes more than one debug cycle, recapture.
- **Old `src/agents/alerter/README.md` has a stale password `Shiitake1!`** — IGNORE per memory `project_phase25_pregate_spike_state`. That password caused HTTP 108006 errors in prior attempts; the current re-reg flow uses captcha + SMS only, no password.
- **Bridge ↔ signal-cli vs alerter ↔ signal-cli paths are different.** Bridge talks to `http://127.0.0.1:8085` (host loopback); alerter talks to `http://signal-cli:8080` (compose-net). Do NOT unify. (memory `feedback_bridge_signal_cli_network_path`)
- **If you `docker exec` into signal-cli to inspect state, copy state OUT of `/root` BEFORE any container cleanup** — re-registration may leave transient state in `/root` that gets nuked if signal-cli restarts. (memory `project_signal_cli_link_gotchas`)
- **Both farmers will see the safety-number warning at SAME time** because the bot's identity key rotates on §3-success. Plan ahead: have §6 script ready before §5 sends.
- **The Signal-server-side device list always includes `.id=1` even pre-reg** — that entry is the original-primary-device-somewhere; the local install was `.id=2`. Don't be fooled into thinking re-reg already happened just because `.id=1` exists in the pre-reg list. The verification signal is `creation_timestamp` of the `.id=1` entry matching the §3 moment + `/v1/receive` flipping 400→200.

---

## References

- `36-CONTEXT.md` — all 14 decisions (D-01 through D-14) that shaped this runbook
- `36-01-preflight-snapshot.md` — Plan 36-01 outputs; restore recipe quoted in §7
- `scripts/signal/post-rebuild-trust-check.sh` — Plan 36-03 Task 1 deliverable (operates on §4c post-reg snapshot)
- Memory `project_signal_cli_primary_reregister_path.md` — original spike recipe
- Memory `project_phase25_pregate_spike_state.md` — 2026-04-27 spike PASS; `Shiitake1!` pitfall
- Memory `feedback_bridge_signal_cli_network_path.md` — bridge vs alerter signal-cli endpoint paths
- Memory `project_signal_cli_link_gotchas.md` — `/root` state preservation gotcha
