# Phase 29: Alerter mode awareness + cooldown tuning - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 29-alerter-mode-awareness-cooldown-tuning
**Areas discussed:** (all delegated to Claude's discretion)

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Mode signal plumbing | Bridge WS forward of `current_mode` vs HTTP poll vs flat scalar topics | |
| Behavior during mode-absent / fc1-offline | Last-known vs env-default vs suppress-RH-alerts | |
| Knob sweep scope (ALRT-09) + cooldown tuning (ALRT-10) | Tier classification of env vars + tuning data source | |
| Bundle 999.39 offline-blindness fix | Bundle vs separate phase | |

**User's choice:** "non" — interpreted as "none / Claude decides all". Per session standing instruction ("work without stopping for clarifying questions"), Claude wrote CONTEXT.md with reasoned defaults across all four areas.

**Notes:** All five gray areas captured in CONTEXT.md as Claude's Discretion (D-01..D-09). User invited to redirect any decision before plan-phase.

## Claude's Discretion

All gray areas. Decisions:
- D-01..D-02: WS broadcast plumbing (bridge subscribes to `current_mode`, broadcasts to alerter; on-connect replay)
- D-03: three-state freshness model (fresh / stale-or-disconnected / never-received); env defaults as bootstrap-only backstop
- D-04: bundle 999.39 (same module, same liveness signals)
- D-05: four-tier env var classification (mode-driven / per-mode override / global runtime-tunable / env-only)
- D-06: two new TRANSIENT_LOCAL topics (`alerter_mode_overrides`, `alerter_globals`) instead of broadening Mode.msg
- D-07: cooldown tuning from Timescale `alert_history` (or log parsing fallback); 14-day minimum
- D-08: tuned values land in `fc_config.yaml` `modes.{name}.alerter.*`, not `.env`
- D-09: mode-swap dedup reset within rule, but cooldown keyed on rule alone (not `(rule, mode)`)

## Deferred Ideas

- Alerter writes to Timescale `alert_history` (would simplify D-07 analysis)
- 999.35 alerter self-pathology meta-watchdog
- Per-rule custom freshness thresholds (separate from `sensor_offline_min`)
- Cooldowns keyed by `(alertType, mode)` instead of just `alertType`
