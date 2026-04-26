# Spike Manifest

## Idea

Phase 25 pre-gate: validate that we can send AND receive SMS through the
Huawei 4G router's SIM from fc1, before committing to the signal-cli primary
re-registration path. The Signal verification SMS for `+59891840205` must
land somewhere we can read it programmatically — the router web UI is one
candidate (no SIM swap), a phone holding the SIM is the fallback.

## Spikes

| # | Name | Validates | Verdict | Tags |
|---|------|-----------|---------|------|
| 001 | huawei-router-sms-roundtrip | auth + send + receive via huawei-lte-api lib against 192.168.8.1 from fc1 | PARTIAL — auth blocked on creds, resume on-site | phase-25, signal-cli, 4g-router, sms, huawei |
