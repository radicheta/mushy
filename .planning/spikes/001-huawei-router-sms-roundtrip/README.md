---
spike: 001
name: huawei-router-sms-roundtrip
validates: "Given fc1 + Huawei 4G router credentials, when a Python script using huawei-lte-api runs against 192.168.8.1, then it can (a) authenticate, (b) read the SMS inbox, (c) send an SMS, (d) observe an SMS sent to the SIM"
verdict: PENDING
related: []
tags: [phase-25, signal-cli, 4g-router, sms, huawei]
---

# Spike 001: Huawei Router SMS Roundtrip

## What This Validates

The Phase 25 plan (`/v1/receive/+59891840205` returning HTTP 400 → re-register
signal-cli as primary using SMS verification through the SIM in the 4G router)
depends on a single unproven capability: **can fc1 read SMS messages
delivered to the SIM, programmatically?**

This spike answers that with one Python script.

Given:
- fc1 (Raspberry Pi at 192.168.8.100) is on the LAN of a Huawei HiLink router (192.168.8.1)
- Router admin credentials (`admin / Shiitake1!`)
- A target phone (+59892893012, the farmer) for the round-trip

When:
- `huawei-lte-api` (Python, MIT) connects with those credentials
- We exercise auth → device info → inbox list → send → poll-for-new

Then:
- All four operations succeed within ~2 minutes per side
- Phase 25 pre-gate is unblocked

## How to Run

On fc1 (preferred — direct LAN to the router) **OR** any host that can reach
`192.168.8.1` (e.g. via VPN/tunnel through fc1):

```bash
pip install --user huawei-lte-api

export ROUTER_PASS='Shiitake1!'      # in /tmp/huawei on elder-plops
# (ROUTER_URL/USER default to http://192.168.8.1/ and admin)

# Step 1 — auth only (no farmer-visible side effect)
python3 roundtrip.py auth

# Step 2 — device + signal + sms count (still no side effects)
python3 roundtrip.py info

# Step 3 — read inbox (still no side effects)
python3 roundtrip.py inbox 10

# Step 4 — send a test SMS to the farmer (visible side effect!)
python3 roundtrip.py send '+59892893012' 'TEST from mushy spike — please ignore'

# Step 5 — receive: ask farmer to reply, then poll inbox for the reply
python3 roundtrip.py wait-for-from '+59892893012' 180
```

Steps 1–3 prove auth + read.
Step 4 proves outbound SMS.
Step 5 proves inbound SMS.

## What to Expect

- **Step 1:** prints `AUTH OK` plus device name and serial.
- **Step 2:** prints model, firmware, signal RSRP/RSRQ, sms_count totals.
  Likely model: B315 / B525 / B535 / B618 / B628 / B818 (any of these are
  fully supported by huawei-lte-api).
- **Step 3:** prints up to 10 inbox entries. Will include any old SMS from
  carrier or previous Signal verification.
- **Step 4:** prints `SEND rc=OK` (or `200000`). Farmer receives "TEST from
  mushy spike — please ignore" within seconds.
- **Step 5:** within ~30s of farmer replying, prints `HIT` with the reply
  body. Times out after 180s if nothing arrives.

## Failure modes worth distinguishing

| Symptom | What it means | Implication |
|---------|---------------|-------------|
| Auth raises ResponseErrorLoginCsrfException | Firmware uses SCRAM auth (newer B-series) — already handled by the lib but lib version may be old. Try `pip install -U huawei-lte-api`. | Library compat fix, not a dead end. |
| Auth raises 108003 (Already login) | Web UI is logged in elsewhere. Log out from browser or wait 5 min. | Trivial. |
| `info` works but `sms.sms_count` raises 100002 | Carrier-locked firmware disables programmatic SMS. | **Dead end** — must use phone-with-SIM fallback. |
| Send returns rc != 'OK'/200000 | Either bad number format or carrier rejected | Try with leading `+`, with leading `00598`, or without `+`. |
| Step 5 times out but inbox shows the message later | Polling cadence / API caching | Likely fine — Signal verification SMS will still be readable, just slower. |

## Results

**VERDICT: PARTIAL — blocked on credentials (2026-04-25)**

Verified:
- Router is Huawei HiLink at `192.168.8.1` on fc1's wlan0 (default gateway).
  Confirmed by signature `/api/webserver/SesTokInfo` response and 307 →
  `/html/index.html` redirect.
- `huawei-lte-api` 1.11.0 installs cleanly on fc1 (Ubuntu, Python 3.12,
  needs `--break-system-packages`). Pulls in `pycryptodomex` and
  `xmltodict`.
- Password `Shiitake1!` from `elder-plops:/tmp/huawei` reaches the script
  intact: `len=10, first=S, last=!`. Not a shell-quoting bug.
- Auth path returns `108006: Username and Password wrong` from the
  router. Three failed attempts; one or two more before Huawei's typical
  5-attempt lockout (5 min).

Next action (in person at the farm):
1. Open `http://192.168.8.1` in a browser on the same SSID and try
   `admin` / `Shiitake1!`.
2. Outcomes:
   - **Browser login works** → lib version / firmware quirk; check
     `c.user.state_login()['password_type']` and re-test, or upgrade
     `huawei-lte-api`.
   - **Browser says wrong password** → recover/reset, update `/tmp/huawei`,
     re-run.
   - **Account locked** → wait 5 min, single retry.
3. Once auth passes, run steps 2–5 from "How to Run" in order.

## Open question

While running this spike, fc1's Tailscale link kept dropping (DERP-relay only
because the 4G SIM is behind CGNAT). Worth an independent backlog item:
mosh + tmux, or reverse autossh, to make fc1 SSH reliable enough for
non-trivial work. Not part of this spike.
