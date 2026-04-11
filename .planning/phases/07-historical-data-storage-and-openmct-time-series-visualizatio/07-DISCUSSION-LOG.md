# Phase 7: Historical Data Storage & OpenMCT Time-Series Visualization - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 07-historical-data-storage-and-openmct-time-series-visualizatio
**Areas discussed:** Data ingestion pipeline, OpenMCT history provider, Deployment & infrastructure, Data scope & granularity

---

## Data Ingestion Pipeline

| Option | Description | Selected |
|--------|-------------|----------|
| Bridge service | Node.js bridge already subscribes to ROS topics and sits on frontend-net with TimescaleDB. Add pg client alongside WebSocket broadcast. | ✓ |
| Dedicated writer node | New Python ROS node. Separate concern but adds another service. | |
| fc_telemetry node | Extend existing Python telemetry node. Keeps Python-only but mixes concerns. | |

**User's choice:** Asked "what do you think?" — Claude recommended bridge service for minimal new code and single writer. User accepted.

| Option | Description | Selected |
|--------|-------------|----------|
| pg (node-postgres) | Lightweight, no ORM overhead. Direct INSERT statements. | ✓ |
| Knex.js | Query builder with migration support. Heavier dependency. | |

**User's choice:** pg (node-postgres)

| Option | Description | Selected |
|--------|-------------|----------|
| Immediate insert | One INSERT per message. ~2 writes/sec is trivial for Postgres. | ✓ |
| Batch every N seconds | Buffer and flush. More efficient but adds complexity. | |

**User's choice:** Immediate insert

---

## OpenMCT History Provider

| Option | Description | Selected |
|--------|-------------|----------|
| REST endpoint on bridge | Express routes (GET /history/:topic). Clean separation from WebSocket. | ✓ |
| WebSocket query protocol | Extend rosbridge WebSocket with 'history' op. Mixes live and query. | |
| Separate history service | New microservice. Overkill for current scale. | |

**User's choice:** REST endpoint on bridge

| Option | Description | Selected |
|--------|-------------|----------|
| Last 24 hours | Full day cycle. Useful for humidity patterns across light/dark. | ✓ |
| Last 1 hour | Immediate view. Misses daily patterns. | |
| Last 7 days | Full week. May be slow with 2s data (302k points). | |

**User's choice:** Last 24 hours

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, server-side | Use TimescaleDB time_bucket() for ranges >24h. | ✓ |
| No, return raw data | Always return every 2s point. Charts may choke. | |

**User's choice:** Yes, server-side downsampling

---

## Deployment & Infrastructure

| Option | Description | Selected |
|--------|-------------|----------|
| elder-plops via Docker | Existing docker-compose. Pi stays lightweight. Bridge writes locally. | ✓ |
| On the Pi | Data local to farm but Pi has limited RAM/storage. | |
| Both (replicate) | Survives network loss but significantly more complex. | |

**User's choice:** elder-plops via Docker

| Option | Description | Selected |
|--------|-------------|----------|
| Init script in bridge startup | CREATE TABLE IF NOT EXISTS + hypertable setup. Simple for one table. | ✓ |
| SQL migration files | Versioned .sql files. More formal but adds process overhead. | |

**User's choice:** Init script in bridge startup

| Option | Description | Selected |
|--------|-------------|----------|
| Move to .env file | Standard Docker practice. .env already in .gitignore. | ✓ |
| Leave as-is | Local-only dev setup. Fix when it matters. | |

**User's choice:** Move to .env file

---

## Data Scope & Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| All 4 current topics | Humidity, temperature, CO2, humidifier state. Full picture. | ✓ |
| Sensors only (3) | Skip humidifier state. Loses correlation data. | |
| Humidity only | Minimal but loses context. | |

**User's choice:** All 4 current topics

| Option | Description | Selected |
|--------|-------------|----------|
| Keep everything forever | ~600MB/year. Negligible on elder-plops. | ✓ |
| 90 days raw, indefinite downsampled | Full resolution for 90 days, then 15-min averages. | |
| 30 days, then delete | Simple but loses long-term trends. | |

**User's choice:** Keep everything forever for now. Revisit downsampled retention in a few years.

| Option | Description | Selected |
|--------|-------------|----------|
| Store every reading (~2s) | Full fidelity. Downsample on query only. | ✓ |
| Downsample to 10s before storing | Saves 80% storage but loses spike visibility. | |

**User's choice:** Store every reading

---

## Claude's Discretion

- Table schema design (column types, indexes, hypertable chunk interval)
- Express route structure and query parameter validation
- Downsampling bucket thresholds
- OpenMCT plugin request() implementation details
- Error handling for DB connection loss

## Deferred Ideas

- Downsampled retention policy (revisit in a few years)
- Multi-chamber schema (when FC-2 comes)
- Alerting on historical trends
- Data export/backup
