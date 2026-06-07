# Pinning cycler — runbook

`scripts/pinning_cycler.py` drives **condensation/evaporation cycles** to induce
mushroom pinning. It is the missing *driver* on top of the v1.5 forcing
primitives: `force-condensation` / `force-evaporation` are one-shot and
auto-revert, and the scheduler can't drive them — this script repeats a
wet → dry → rest cycle over a multi-day induction window by calling the
bridge's existing `/control` endpoints.

> **This is an experiment, not a settled recipe.** The default timings are
> starting guesses for an oyster / cold-tolerant block in the cold outdoor
> tent. Tune them by eye as you watch the blocks (see *Tuning* below).

## Where it runs

On **elder-plops** (the host running the bridge), hitting the bridge at
`http://localhost:8081`. It does **not** run on fc1. It talks to fc1 only
indirectly, through the bridge → ROS `start_experiment` service path that was
proven E2E in Phase 31.

## Prerequisites

- Bridge container up (`docker ps | grep bridge`) and fc1 controller live
  (telemetry flowing — check `fc.humidifier_duty` is recent).
- A **fully-colonized block** at the colonizing→fruiting transition. Pinning
  only applies here; running it on un-colonized or already-fruiting substrate
  is pointless or harmful.
- Force endpoint reachable: `curl -s -o /dev/null -w '%{http_code}' \
  -X POST http://localhost:8081/control/experiment -H 'Content-Type: application/json' -d '{}'`
  should return `400` (reachable + validating), not `404`.

## How it works (one cycle)

1. On start it sets the chamber to **`pinning`** mode so every force phase
   reverts *into* pinning between cycles — NOT back into flat-96% `fruiting`,
   which suppresses pinning ("holding flat high RH suppresses pinning",
   SEED-004).
2. **Wet** — `POST /control/experiment {name: force-condensation, duration_minutes: WET}`.
   Ultrasonic mister 100% duty → drives to saturation + aerosol-wets the blocks.
3. **Dry** — `POST /control/experiment {name: force-evaporation, duration_minutes: DRY}`.
   Mister off → surfaces dry toward tacky.
4. **Rest** — sit in `pinning` for REST minutes (defends the 90% RH floor,
   doesn't push up).
5. Repeat until the `--days` window elapses (or `--max-cycles`).

Each force phase **auto-reverts** after its bounded duration. That is the
safety backbone: if this process dies, the network drops, or elder-plops
hiccups mid-wet, the current phase expires back to `pinning` on its own —
**the mister cannot get stuck on.** The cycler adds rhythm, not a new failure
mode.

## Running it — systemd (canonical, survives reboot)

The induction run is managed by a **user-level systemd unit**
(`scripts/pinning-cycler.service`). santi has linger enabled, so the user
manager starts at boot even with no login → the run survives reboots.

```bash
# Install / update the unit (no sudo needed):
cp scripts/pinning-cycler.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pinning-cycler.service

# Manage:
systemctl --user status pinning-cycler
systemctl --user stop pinning-cycler        # SIGTERM -> cancels phase, leaves pinning
systemctl --user restart pinning-cycler
journalctl --user -u pinning-cycler -f

# Re-tune: edit the ExecStart timings in scripts/pinning-cycler.service, then:
cp scripts/pinning-cycler.service ~/.config/systemd/user/ && \
  systemctl --user daemon-reload && systemctl --user restart pinning-cycler
```

Boot race: the bridge is a docker container (restart=always) and may not be up
the instant the unit starts at boot. The script exits 1 if it can't reach the
bridge; `Restart=on-failure` + `RestartSec=30` retries until it is. A clean
completion of the `--days` window exits 0 and does NOT restart (the induction
is intentionally finite).

## Running it — manual (ad-hoc / smoke tests)

```bash
cd /mnt/slime-kingdom/opt/mushy

# 1. Always dry-run first — prints the schedule, fires nothing:
python3 scripts/pinning_cycler.py --dry-run --days 5 --wet-min 10 --dry-min 30 --rest-min 180

# 2. (Recommended before a long run) one real cycle as a smoke test, watching
#    that fc.humidifier_duty flips 1 (wet) then 0 (dry):
python3 scripts/pinning_cycler.py --max-cycles 1 --wet-min 1 --dry-min 1 --rest-min 0 \
  --logfile logs/smoke-pinning.jsonl

# 3. Launch the real run, fully detached so it survives the session:
setsid nohup python3 scripts/pinning_cycler.py \
  --days 5 --wet-min 10 --dry-min 30 --rest-min 180 \
  --logfile logs/pinning-cycler.jsonl > logs/pinning-cycler.out 2>&1 < /dev/null &
```

### Arguments

| Flag | Default | Meaning |
|------|---------|---------|
| `--days` | 5 | Total induction window (days). |
| `--wet-min` | 10 | `force-condensation` minutes per cycle (0 = skip). Range 1–120. |
| `--dry-min` | 30 | `force-evaporation` minutes per cycle (0 = skip). Range 1–120. |
| `--rest-min` | 180 | Rest in `pinning` mode per cycle. |
| `--max-cycles` | 0 | Stop after N cycles (0 = unlimited; use for smoke tests). |
| `--bridge` | `http://localhost:8081` | Bridge base URL. |
| `--logfile` | `logs/pinning-cycler.jsonl` | JSONL action log (gitignored). |
| `--dry-run` | off | Print the schedule and exit; fire nothing. |

Default cycle = 10 + 30 + 180 = **220 min** → ~6–7 cycles/day, ~32 over 5 days.

## Monitoring

```bash
# Live action log:
tail -f logs/pinning-cycler.jsonl

# The cycle made visible — VPD dives to ~0 each wet phase, climbs each dry:
curl -s "http://localhost:8081/history/fc.vpd?start=$(($(date +%s%3N)-7200000))&end=$(date +%s%3N)"

# Or watch it in Mission Control: the VPD panel sawtooth IS the cycle.
```

`fc.humidifier_duty` = 1 during wet, 0 during dry/rest. `fc.vpd` and
`fc.water_vapor` (added 2026-06-07) are the derived readouts of the cycle.

## Tuning (the part you do by eye)

Check the blocks 1–2×/day. Looking for tiny hyphal knots → pinheads.

- Surfaces should **oscillate wet ↔ just-tacky** — never permanently soaked
  (bacterial blotch) nor bone-dry (aborts).
- Staying wet through the rest → **lengthen `--dry-min`** (and/or shorten
  `--rest-min`).
- Drying too hard → **shorten `--dry-min`** (and/or lengthen `--rest-min`).
- To re-tune: **stop, then relaunch** with new args (it's stateless between
  runs; the chamber is left in `pinning`).

Log what you see via the Signal field-notes channel so observations line up
against the VPD trace.

## Stopping

```bash
systemctl --user stop pinning-cycler   # preferred (systemd-managed run)
# or, if running manually:  pkill -f pinning_cycler.py
```

> Do NOT use `pkill -f` with a pattern that also appears in your own shell's
> command line — it will SIGTERM the shell too. Prefer `systemctl --user stop`,
> or kill by PID.

On stop (signal or window-complete) it cancels any in-flight experiment and
sets the chamber back to `pinning`. **Once pins have set, switch to `fruiting`**
to bulk up the fruits:

```bash
curl -s -X POST http://localhost:8081/control/param -H 'Content-Type: application/json' \
  -d '{"node":"fc_controller","param":"active_mode","value":"fruiting"}'
```

## Known gaps / not yet done

- **Reboot recovery restarts the window.** The unit survives reboot (linger),
  but the script tracks elapsed time with a monotonic clock that resets on
  restart — so a reboot starts a fresh `--days` window rather than resuming the
  remaining time. Harmless for the experiment (cycling just continues); only
  matters if you're counting on an exact stop date.
- **FAE is manual.** The fan is temperature-driven only; there is no active
  fresh-air exhaust. Watch CO₂ on the SCD41 and crack the tent if it climbs.
- **Signal trigger path** for force modes was blocked on signal-cli deviceId=2
  (Phase 31); this script uses the proven bridge HTTP path instead.
