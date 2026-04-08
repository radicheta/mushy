# Phase 8: Pi Camera Feed in Mission Control - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-08
**Phase:** 08-pi-camera-feed-in-mission-control
**Areas discussed:** Scope pivot, streaming approach, bandwidth, ROS integration

---

## Scope Pivot from FarmOS

Phase 08 was originally "FarmOS Integration." During discussion, user reported:
- Farm plans to use FarmOS farm-wide (mushrooms + forestry + greenhouse)
- Farm team already deploying shared FarmOS instance, working on schemas
- Shared responsibility model — coordination required
- Instance still in progress, not ready for our integration

**Decision:** Defer FarmOS to backlog (999.2). Replace Phase 08 with Pi Camera Feed.

## Camera Phase — Gray Areas

| Area | Options Presented | Selected |
|------|------------------|----------|
| Streaming approach | MJPEG / WebRTC / HLS | User deferred to Claude |
| Mission Control UI | Dedicated view / overlay / PiP | User deferred to Claude |
| Camera on Pi | ROS node / standalone / v4l2 direct | User: "integrate to ROS, first steps towards rover bot" |
| Image capture/storage | Pi local / elder-plops / TimescaleDB | User: "plenty storage in elderplops" |

**User's guidance:** "Don't want to discuss anything. Make it sensible. Keep an eye on bandwidth usage — remember it'll be cellular for now. Yes integrate to ROS, these are first steps towards rover bot."

**Key constraints from user:**
- Cellular bandwidth is the primary concern
- ROS integration mandatory (rover bot foundation)
- Elder-plops storage is plentiful
- Claude has full discretion on implementation details

## Naming Change

User requested "Mission Control" instead of "OpenMCT" in all conversation and docs. "OpenMCT" is hard to type/remember, "OpenMCP" typos common.

## Claude's Discretion

All implementation details — streaming protocol (chose MJPEG for simplicity), framerate (chose 1-2 FPS for bandwidth), resolution, compression, node architecture, bridge endpoint design, OpenMCT plugin structure, snapshot storage layout.
