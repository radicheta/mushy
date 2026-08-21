# Dev farmOS username drift: config `farmos_agent` vs working `mushy-bot`

**Found:** 2026-06-29 (Phase 62 live-fire, 62-12)
**Severity:** latent auth failure (not a code defect)
**Ticket:** MUSHY-2 (Phase 62 follow-on)

## What

`tenants/mossrock/config.yaml` sets `FARMOS_USERNAME: "farmos_agent"`, but the working
dev farmOS `:18080` account is **`mushy-bot`**. The Phase 62 live-fire's ported
`client.py` auth (faithful mirror of Node `client.js`: `POST /user/login?_format=json`,
JSON `{name,pass}`) returned **HTTP 400** with `farmos_agent`; a username probe confirmed
`mushy-bot` → HTTP 200. farmOS's Drupal JSON login route returns 400 for an unrecognized
username/password. The dev account + password were reconciled in Phase 55B (dev `mushy-bot`
password reset to match `tenants/mossrock/secrets.env`), but the config username was never
updated to match.

The live-fire was run with `FARMOS_USERNAME=mushy-bot` overriding the config, so Phase 62's
SC2/SC3/SC4 are proven. This todo is only about the config.

## Why it matters

If `alerter-py` (the v1.12 Python port) ever boots against farmOS using the tenant config,
every commit silently fails auth (400) — the never-throws client returns an error envelope,
the commit watchdog requeues, nothing reaches farmOS. A classic silent-wiring failure.

## How to apply

1. Reconcile `FARMOS_USERNAME` for the mossrock tenant/dev to `mushy-bot` in
   `tenants/mossrock/config.yaml` (and any dev override).
2. Confirm the **prod** `:8082` farmOS account name (repo-root `.env` `FARMOS_USERNAME`,
   consumed by `docker-compose.yml`) is correct and distinct if prod uses a different account.
3. Decide the source of truth: tenant `config.yaml` vs repo-root `.env` vs compose env —
   today they can disagree. Pin one.
4. Re-run the live-fire (`FWR_LIVE_FIRE=1 uv run pytest tests/test_farmos_live_fire.py -m live_fire`)
   using the config value (no override) to prove the reconciled config authenticates.

Related: `project_dev_farmos_18080_rejects_prod_bot_creds` (the original creds resolution),
`feedback_unit_tests_dont_catch_wiring` (the live-fire caught this).
