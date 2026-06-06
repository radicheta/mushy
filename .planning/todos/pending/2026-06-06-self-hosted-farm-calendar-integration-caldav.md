---
created: 2026-06-06T19:51:39.181Z
title: Self-hosted farm calendar integration (CalDAV)
area: general
files: []
---

## Problem

No shared calendar for farm events. Farmers need visibility into scheduled ops (inoculations, harvests, substrate prep) and coordination events (meetings, market days, vendor visits) on their phones.

## Solution

Deploy Radicale or Baikal (CalDAV server) as a Docker service on elder-plops.

**Source of truth split:**
- farmOS = authoritative for ops events (inoculations, harvests, plans) — CalDAV gets a read projection via sync job
- CalDAV = authoritative for coordination events (meetings, market days, vendor visits) — no farmOS equivalent

**Mushy routing:** Signal messages about farm ops → farmOS log; Signal messages about coordination events → CalDAV event directly.

**Bridge:** CalDAV events tagged with `farmos:plan_id=xyz` to close the loop when an ops log comes in for a previously scheduled event.
