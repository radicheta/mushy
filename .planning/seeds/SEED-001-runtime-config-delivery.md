---
id: SEED-001
status: dormant
planted: 2026-04-13
planted_during: v1.2 (post-milestone, between milestones)
trigger_when: multi-chamber milestone, config management, operational tooling, or Pi fleet management
scope: Medium
---

# SEED-001: Lightweight runtime config delivery (bypass full deploy cycle)

## Why This Matters

Changing a single operational parameter — humidity setpoint, light schedule, tolerance
band — currently requires a full software deploy: edit config, git commit, push to
fc1/prod, run deploy.sh or wait for boot-time pull. That's the same pipeline used for
code changes and new features.

This is overkill. Runtime config changes are frequent, low-risk, and should be
instant. The current path adds friction that discourages tuning, and becomes
untenable with multiple chambers (commit per-chamber config changes?).

## When to Surface

**Trigger:** Next milestone that touches config delivery, multi-chamber support, or operational tooling.

This seed should be presented during `/gsd-new-milestone` when the milestone
scope matches any of these conditions:
- Multi-chamber support (scaling beyond fc1)
- Operational tooling or farmer UX
- Config management or parameter tuning
- Fleet management across multiple Pis

## Scope Estimate

**Medium** — A phase or two. Needs a design decision on the transport mechanism
(MQTT config topic, HTTP endpoint on Pi, scp + reload signal, or similar), plus
changes to how fc_core loads its config at runtime vs. only at launch.

## Breadcrumbs

Related code and decisions found in the current codebase:

- `src/chambers/fc-core/config/fc_config.yaml` — the config file that triggered this idea; all setpoints live here
- `scripts/pi-deploy/fc-core.service` — systemd unit; current deploy restarts the whole service for any change
- `docs/pi-deploy/dev-workflow.md` — documents the current commit→push→deploy flow
- `docs/OPERATIONS.md` — operational runbook references deploy.sh
- Backlog `999.9` (PID humidity control) — will make setpoint tuning even more frequent

## Notes

Prompted by a simple humidity target change (80% → 90%) that required a full
git commit + push to fc1/prod + deploy. The change was 1 line in a YAML file.

Possible approaches to evaluate:
- **MQTT config topic**: Pi subscribes, Mission Control publishes — real-time, fits existing MQTT infra
- **HTTP endpoint on Pi**: Simple REST call to update + hot-reload — no new infra
- **scp + SIGHUP**: Push file, signal process to reload — minimal but manual
- **Config DB in TimescaleDB**: Central config store, Pi polls — fits multi-chamber but adds coupling
