# Phase 8: FarmOS Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 08-farmos-integration
**Areas discussed:** Scope & data flow direction, FarmOS deployment, Integration method, Asset & log modeling

---

## Vision (Pre-discussion)

| Option | Description | Selected |
|--------|-------------|----------|
| Push telemetry to FarmOS | Send sensor readings into FarmOS as sensor data logs | |
| Pull grow recipes from FarmOS | Define setpoints in FarmOS, Pi pulls them | |
| Bidirectional sync | Push telemetry AND pull recipes | |
| Something else | Different vision | ✓ |

**User's choice:** Managing production — logging manual events (inoculation, harvest, etc.). Referenced farm_fungi Drupal module.

---

## Scope & Data Flow Direction

| Option | Description | Selected |
|--------|-------------|----------|
| Manual events only | FarmOS for production, telemetry stays in TimescaleDB/OpenMCT | ✓ |
| Both telemetry and events | Push sensor readings as observation logs too | |
| Telemetry only | Use FarmOS as telemetry store instead of TimescaleDB | |

**User's choice:** Manual events only

| Option | Description | Selected |
|--------|-------------|----------|
| One-way: farm → FarmOS only | FarmOS is record-keeping, Pi runs independently | ✓ |
| Pull grow recipes | FarmOS becomes control plane | |
| Bidirectional | Push events AND pull config | |

**User's choice:** One-way

---

## FarmOS Deployment

| Option | Description | Selected |
|--------|-------------|----------|
| Self-hosted Docker on elder-plops | Add to docker-compose, control the data | ✓ |
| Farmier (hosted) | Managed hosting, data lives externally | |
| Cloud VPS | Self-hosted on VPS | |
| On the Pi | Pi 4 tight for Drupal + PostgreSQL | |

**User's choice:** Self-hosted Docker on elder-plops

| Option | Description | Selected |
|--------|-------------|----------|
| Separate PostgreSQL container | Isolation from TimescaleDB | ✓ |
| Share TimescaleDB instance | Saves resources, couples lifecycle | |

**User's choice:** Separate PostgreSQL

---

## Integration Method

| Option | Description | Selected |
|--------|-------------|----------|
| FarmOS UI directly | Mobile-friendly forms, no custom code | ✓ |
| Custom CLI tool | farmOS.py command-line tool | |
| ROS node bridge | Over-engineered for manual events | |
| Mix of UI and automation | Manual + some automated entries | |

**User's choice:** FarmOS UI directly. Start manual, defer automation.

**User's note:** Future automation vision includes roving robots logging observations and Pi camera pushing hourly images as observations.

| Option | Description | Selected |
|--------|-------------|----------|
| LAN only via elder-plops IP | Port 8082, same pattern as OpenMCT | ✓ |
| Local DNS / hostname | Nicer URL, requires DNS config | |

**User's choice:** LAN only

---

## Asset & Log Modeling

| Option | Description | Selected |
|--------|-------------|----------|
| One asset per batch | All bags inoculated together = one asset | |
| One asset per bag/block | Individual container tracking | ✓ |
| Not sure yet | Start with batches, adjust later | |

**User's choice:** One asset per bag/block

Lifecycle events selected (all four):
- ✓ Inoculation (species, substrate, date, source culture)
- ✓ Colonization check (progress, contamination)
- ✓ Fruiting initiated (enters chamber, location reference)
- ✓ Harvest (weight, flush number, quality)

| Option | Description | Selected |
|--------|-------------|----------|
| FC-1 as location asset | Structure asset, enables location queries | ✓ |
| Just use notes | Mention FC-1 in log text | |

**User's choice:** FC-1 as location asset

---

## Claude's Discretion

- FarmOS Docker image version and Drupal configuration
- Specific module set beyond farm_fungi
- Taxonomy term seeding
- Docker networking
- Reverse proxy setup

## Deferred Ideas

- Automated sensor telemetry to FarmOS
- Pi camera image observations
- Roving robot observations
- Grow recipe pull from FarmOS
- Multi-chamber location hierarchy
- Harvest analytics
