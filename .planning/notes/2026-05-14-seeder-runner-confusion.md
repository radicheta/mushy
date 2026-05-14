# Coordination note — seeder runner confusion

**Date:** 2026-05-14
**Status:** resolved (farmOS side ran it)

## What happened

Three reply notes traded between mushy-side and farmOS-side Claudes
referenced `scripts/seed-dev-farmos-taxonomies.js` (mushy repo) without
specifying **which side runs it**. Both sides defaulted to "the other
side will run it" because:

- Script lives in the mushy repo -> "mushy will run it"
- Script writes to dev-farmOS via JSON:API -> "farmOS will run it"
- Operator preconditions (vocab + field config via drush) are farmOS-
  side work, and the seeder only makes sense after those land -> reads
  like "farmOS will run it once the preconditions are met"

Net effect: brief stall. Don Santiago caught it; farmOS side ran the
seeder.

## How to avoid this

In any future cross-repo handoff note, include a one-liner like:

```
**Runner:** <which side> executes the script. <which side> verifies.
```

Even if it feels obvious from context. The Claudes can't see each
other's mental model and will silently default-assume in opposite
directions when the script's "home" (which repo) and "target" (which
service) diverge.

## Fixed in this case

farmOS side is running `scripts/seed-dev-farmos-taxonomies.js` against
their dev-farmOS instance. Mushy side will not re-run it.
