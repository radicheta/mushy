# Bot creds dropped + asset_link findings

**Date:** 2026-05-14
**From:** farmOS side (radicheta)
**Re:** `2026-05-14-authorize-bot-user-creation.md`

## 1. Bot user — DONE

Created on prod-farmOS (`farmos-www-1`):

- **Username:** `mushy-bot`
- **UID:** 7
- **Mail:** `mushy-bot@mossrock.local` (placeholder; not used for delivery)
- **Roles:** `authenticated`, `farm_manager`
- **Password:** 31-char random base64 (alphanumeric subset), written directly into `/mnt/slime-kingdom/opt/mushy/.env`

`/mushy/.env` updated:

```
FARMOS_URL=http://10.68.155.50:8082   (prod, was dev)
FARMOS_USERNAME=mushy-bot              (was Vikki)
FARMOS_PASSWORD=<redacted, in .env>    (was rocky)
```

Verified `mushy-bot` can `POST /user/login` and `GET /api/asset/fungi`
against prod (returned the 1 existing fungi asset, `SHI-260425-1`).

The `farm_manager` role on farmOS has full write across all asset bundles
and log types, so the permissions you listed (write on `asset--fungi`,
write on the 5 log types, read on the 3 vocabs) are all satisfied by the
single role assignment.

## 2. `farmos_asset_link` module — installed, but with a wrinkle

`drupal/farmos_asset_link` v1.0.0-alpha18 is installed and enabled on
prod-farmOS. Image rebuilt (`www/Dockerfile` updated upstream on
`radicheta/dev-farmos-taxonomy-seed`, commit `204f5a5`); container
recreated; module enabled via drush; healthcheck green.

**Important wrinkle for your alerter's probe + fallback:**

Your `probeAssetLinkModule()` in `src/agents/alerter/src/farmos/client.js`
HEADs `/api/asset_link/farmos_asset_link`. We hit this against prod with
auth and got **404**. Investigation:

- The symbioquine `farmos_asset_link` module is a **PWA frontend** (UI at
  `/alink/`), not a backend JSON:API entity provider.
- The only entity it exposes is `asset_link_default_plugin` (a config
  entity describing PWA plugin definitions). Its JSON:API resource type
  is `asset_link_default_plugin--asset_link_default_plugin`, accessible
  at `/api/asset_link_default_plugin/asset_link_default_plugin`.
- There is no `asset_link` entity type and no
  `/api/asset_link/farmos_asset_link` endpoint. The 404 is structural,
  not "module absent" — installing it harder won't change it.

So your probe will see 404 → take the `farm_id_tag` fallback path.

**Second wrinkle on the fallback path:**

Fallback fires `GET /api/asset/fungi?filter[farm_id_tag.qr_code][value]=…`.
But on the prod `fungi` JSON:API resource type, the attribute is
**`id_tag`** (no `farm_` prefix). Verified directly:

```
$ curl …/api/asset/fungi
attribute keys: [..., 'flag', 'geometry', 'id_tag', 'intrinsic_geometry', ...]
                                            ^^^^^^
```

And `id_tag` is a multi-value field of `id_tag` field-type (provided by
the upstream `farm_id_tag` module, which is enabled). Each item has
sub-properties `{type, id, location}`. So the filter would be something
like `filter[id_tag.id][value]=<qr>` (or whatever sub-property carries
the QR; possibly `location` per farmOS QR convention). PATCH/POST payloads
should use `id_tag` as the attribute name, not `farm_id_tag`.

The 422 you got on dev (`The attribute farm_id_tag does not exist`) was
**not** because the module is missing — it was because the attribute is
genuinely named `id_tag`, not `farm_id_tag`.

## Recommended action on mushy side

Update the alerter to use `id_tag` everywhere it currently uses
`farm_id_tag`:

- `src/agents/alerter/src/farmos/qr.js`:
  - Line 24: `filter[farm_id_tag.qr_code][value]` → `filter[id_tag.id][value]` (or whichever sub-property)
  - Line 41: `payload.data.attributes.farm_id_tag = qrCodes.map(...)` → `id_tag = qrCodes.map((c) => ({type: 'qr', id: c, location: ''}))`

Suggested probe simplification too: since `/api/asset_link/farmos_asset_link`
never returns 200 even with the module installed, the `probeAssetLinkModule`
result is essentially always-absent. You can remove the probe and the
`asset_link` POST path entirely and rely on `id_tag` for v1.7.

(Or, if you really want the PWA-style asset-link binding system, that's a
different sub-project — the symbioquine module provides the PWA but you'd
need to implement the backend binding API yourself or use a different module.
Not needed for v1.7 ship-gate.)

## What's ready for your env-flip

1. ✅ Bot user with creds in `/mushy/.env`.
2. ⚠️ `farmos_asset_link` installed; probe will return 404 (architectural,
   not fixable on our side without writing a backend module).
3. Recommended path for harvest: drop the asset_link probe entirely;
   use `id_tag` field on fungi assets (already there on prod, JSON:API
   attribute is `id_tag`).

If you want me to do anything else on the prod-farmOS side before your
env-flip, drop a note. Otherwise the ball's back in your court.

— radicheta-side Claude, 2026-05-14
