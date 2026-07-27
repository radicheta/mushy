# NOTE: port 8080 clash with studio webserver (mushy-openmct)

**Date:** 2026-06-16
**From:** webserver-sombrero deploy on elder-plops (mossrock)
**Severity:** low (worked around for now, but please remap when convenient)

## What

`mushy-openmct-1` runs on the **host network** and binds **TCP 8080**
(`*:8080`, confirmed via `ss`/`curl` and the `CORS_ORIGIN`/`DASHBOARD_URL`
defaults in `docker-compose.yml` / `docker-compose.override.yml`).

The studio webserver stack (`webserver-sombrero`, `docker-compose-dev.yml`)
defaults its `webserver` service to host **8080** as well. On elder-plops this
collides with mushy-openmct.

## Workaround applied (on the webserver-sombrero side)

We publish `webserver` on host **28080** instead of 8080 (container port stays
8080, reached normally through the nginx `server` on :80). No change needed on
mushy to keep things working today.

## Ask

If/when convenient, please move `mushy-openmct` off host **8080** (e.g. publish
on a dedicated/high port, or take it off host networking) so 8080 is free for
the studio webserver's default config. That would let us drop the elder-plops
port override.

Ping the pipeline/webserver-sombrero side before/after any change so we can flip
`webserver` back to the 8080 default.
