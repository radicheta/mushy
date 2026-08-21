# mushy

Control and record-keeping for a mushroom farm in Uruguay. Two halves:

**The chamber.** A ROS2 Jazzy workspace running on a Raspberry Pi (`fc1`) that
holds fruiting-chamber humidity, temperature and CO2 on a closed loop, and
streams telemetry to a Mission Control dashboard backed by TimescaleDB.

**The farm agent.** A Python asyncio daemon that reads the farmer's Signal
messages -- voice notes, photos of notebook pages, plain text -- extracts what
happened on the farm, asks the farmer to confirm it, and writes the result to
farmOS. The point is that logging a day's work costs the farmer a message, not
an afternoon of data entry.

## Layout

| Path | What |
|------|------|
| `src/chambers/fc-core/` | ROS2 package: sensors, controller, display. Runs on fc1. |
| `src/chambers/fc-msgs/` | ROS2 message definitions. |
| `src/farm-agent/` | The Python farm agent. Live since the 2026-08-18 cutover. |
| `src/agents/alerter/` | The Node stack the agent replaced. Retired, not yet removed (MUSHY-101). |
| `src/mission-control/` | OpenMCT frontend + the bridge that feeds it. |
| `src/whisper-transcribe/` | GPU transcription worker for voice notes. |
| `src/farmos-agent/` | farmOS-side helpers. |
| `src/simulation/` | Gazebo sim for development without hardware. |
| `scripts/farm-watchdog/` | Checks that farm capabilities still work; pushes to ntfy on change. |

## Running it

See `CLAUDE.md` for build, test and deploy commands -- it is the working
reference and is kept current. In short: `colcon build` for the ROS2 side,
`docker compose up -d` from the repo root for the Mission Control and agent
stack, and `--build` whenever you change agent or bridge source.

## Where the truth lives

- **Status and open work:** Plane, project `MUSHY`. This is the tracker.
- **Narrative history:** `.planning/MILESTONES.md` (what shipped) and
  `.planning/notes/` (what was found while shipping it).
- **Roadmap:** `.planning/ROADMAP.md`.

`.planning/STATE.md` and the ROADMAP tables are a summary layer over the phase
paper trail; when they disagree with a phase SUMMARY or with Plane, they are the
ones that are wrong.
