# Admin Onboarding Checklist

Steps to onboard a new farmer or dev. Do these before sending them the farmer guide.

---

## 1. Tailscale

- [ ] Open the Tailscale app on your device → the new person taps "Log in" → QR code appears → you scan it (or they share the link, you approve in the admin console at login.tailscale.com)
- [ ] Confirm they appear in `tailscale status` on elder-plops

## 2. Verify farmOS is up

Any device on the tailnet (`100.x.x.x`) is trusted automatically — no per-device config needed.

```bash
curl -o /dev/null -w "%{http_code}" http://100.96.10.66:8082
# expect 403 (login page) — that's good
```

## 3. Create a farmOS account for them

Log in to farmOS → People → Add user. Set their role (farmer vs admin).

## 4. Send them the farmer guide

Share `docs/onboarding/FARMER-GUIDE.md` or paste the links directly into Signal.

---

## Ports reference

| Service | Port | Notes |
|---|---|---|
| Mission Control | 8080 | OpenMCT, no auth |
| farmOS | 8082 | Drupal login required |
| Logger | 8765 | Flask app, QR-based |

All services on elder-plops (`100.96.10.66`).
