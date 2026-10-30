# FC-2: weather-driven sprinkler control for the outdoor logs

Ticket: MUSHY-168. Status: design, 2026-10-30.

## Intent

The outdoor mushroom logs are watered by hand today. FC-2 takes that job: a
Raspberry Pi in the lab (next to FC-1) driving a solenoid valve at the logs
over a 15 m cable, opening the sprinklers in short bursts on a schedule that
follows the weather.

There is no moisture sensor. FC-2 never measures how wet the logs are; it acts
on weather data alone. The rules start rough and get tuned by hand over weeks,
from what the farmer reports, through Claude Code sessions. So the most
important property after safety is that every number in the rule is a setting
you can change live, and that the record of what it did, next to the weather
it saw, is good enough to tune against.

## Goals

- Water the logs automatically, with zero daily effort from the farmer.
- Skip watering while it is raining.
- Water more on hot days than on cool days, smoothly in between.
- Keep watering on a plain timer when the weather feed is unavailable.
- Make every rule number a live setting that survives a restart.
- Record valve activity and the weather inputs so Mission Control can show
  sprinkler duty % per hour against temperature, humidity and wind.

## Non-goals (v1)

- Moisture sensing of any kind.
- Using wind, humidity or ET0 to drive the schedule. They are recorded from day
  one; switching the schedule onto them is a later change.
- Litres. Duty % is the unit. A bucket-and-stopwatch test can convert later.
- Signal alerts for FC-2 (builder's note: worth a follow-up ticket).
- Offline telemetry buffering like FC-1's `fc_buffer`. Readings during a WiFi
  drop are lost; the valve keeps working (see Fallback).
- Multiple zones or valves.

## Anti-goals

These would make it a failure even if it technically works:

- **The water stays on.** A crash, hang, reboot or bad setting must never leave
  the valve open. This outranks every other requirement.
- **Silent no-watering.** A dead weather feed must not quietly stop all
  watering for days. It falls back to the timer.
- **Settings that need a redeploy.** If tuning means editing code and shipping,
  the farmer-feedback loop dies.
- **Settings that reset on reboot.** A tuned value lost at the next power cut
  is worse than no setting.

## Constraints and facts

- **Hardware.** Raspberry Pi (currently on the bench) driving a switch (relay
  or logic-level MOSFET module, not chosen yet) that powers a **12 V DC**
  solenoid valve (coil current to be read off its label, typically 0.3-0.5 A).
  The valve is normally closed: no power means no water. GPIO pin not yet
  chosen. FC-2 is its own Pi, separate from FC-1, so a sprinkler bug cannot take
  the chamber down (decided).
- **Placement (decided).** The Pi, the switch and a 12 V supply (at least 1 A)
  sit indoors in the lab, next to FC-1. Only the cable runs out, about 15 m, to
  the valve at the logs. No waterproof enclosure for electronics.
- **Valve wiring (decided; for whoever wires it, no code impact).**
  - Cable: outdoor or direct-burial Cat5e (or indoor cable in conduit), one
    pair each way, so ~0.6 V drop at 0.5 A. 18 AWG outdoor two-core also works.
    A single conductor each way (~1.3 V drop) is marginal.
  - Flyback diode (e.g. 1N4007) across the valve coil, stripe to +.
  - TVS diode (e.g. P6KE15A) across the pair at the lab end: an outdoor cable
    enters the lab next to FC-1.
  - Splice at the valve with gel-filled direct-burial connectors.
- **Network.** The lab is on `mossrock-wifi`, the WiFi FC-1 uses (FC-1 is
  `10.68.155.56` on it; FC-1's `eth0` is unused). Verified on FC-1's live
  `/etc/netplan/` 2026-10-30. FC-2 joins the same WiFi, or a wired port if one
  is handy (builder's call at install). The repo's
  `scripts/pi-deploy/etc/netplan/60-wifi.yaml.example` still says
  `mossrock-west`: that file is stale, not the live config.
- **Network to elder-plops.** Kernel WireGuard to pfSense, subnet
  `172.16.10.0/24`. elder-plops is `.3`, FC-1 is `.5`. FC-2 takes `.6`.
  `scripts/pi-deploy/wg-setup.sh` sets up a Pi; it currently hardcodes
  `WG_IP="172.16.10.5"`. The pfSense peer is added by hand
  (`docs/pi-setup/wireguard-setup.md`).
- **DDS.** CycloneDDS over `wg0`, unicast, with explicit peer lists in
  `scripts/pi-deploy/cyclonedds.xml` and `src/mission-control/bridge/cyclonedds.xml`.
  Only the bridge's list needs `172.16.10.6` (see Deploy). Note the comment in the Pi file: only one
  `<NetworkInterface>` entry. `ROS_DOMAIN_ID=69`.
- **No RTC.** FC-1's Pi has no real-time clock (it boots with a wrong clock
  until NTP syncs). Assume the same for FC-2. Burst timing must use a
  monotonic clock; anything that needs wall-clock time (night rule, stamps on
  data) must cope with an unsynced clock.
- **Weather source.** Open-Meteo, already used by FC-1's sim
  (`fc_core/sim/ambient.py`, `scripts/fetch-ambient-weather.py`) at the farm's
  location, lat `-34.5165641`, lon `-55.0982273`. Those use the `archive`
  endpoint; live control uses the forecast endpoint's `current` block:

  ```
  https://api.open-meteo.com/v1/forecast?latitude=-34.5165641&longitude=-55.0982273
    &current=temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m,et0_fao_evapotranspiration
    &timezone=UTC
  ```

  Verified live 2026-10-30: returns all six fields for the current 15-minute
  slot (`"interval": 900`). `precipitation` includes showers; `rain` does not
  (that call returned `rain: 0.00`, `precipitation: 0.10`). It is a model
  estimate, not a gauge at the yard: it can miss a local shower or report one
  that never reaches the logs.

## The rule (decided)

Inputs each cycle: the latest weather reading and its age.

1. **Raining:** if `precipitation > rain_threshold_mm` (default `0`), the rate is
   0 bursts/hour. No watering.
2. **Otherwise, temperature ramp.** Interpolate *bursts per hour* (not the gap
   between bursts) linearly on temperature:
   - at or below `cool_temp_c`: `cool_bursts_per_hour` (default 1)
   - at or above `hot_temp_c`: `hot_bursts_per_hour` (default 6)
   - in between: linear. Halfway is 3.5/h, a burst about every 17 min.

   Bursts per hour was chosen so each degree warmer adds the same water, which
   is easier to tune from feedback. The gap between bursts is `3600 / rate`
   seconds.
3. **Each burst** opens the valve for `pulse_sec` (default 60).
4. **Fallback:** if there is no weather reading, or it is older than
   `weather_stale_sec`, ignore the rule and use `fallback_bursts_per_hour`
   (default 1) of `pulse_sec`. This covers WiFi drops, Open-Meteo outages and
   boot without network. Return to the rule when fresh data arrives.

Default thresholds for "cool" and "hot" were not given. Builder's call for the
starting values (something like 15 °C and 28 °C), clearly marked as
placeholders to be tuned.

**Later, not v1:** replace temperature with ET0 as the ramp input, so wind and
humidity count with the right sign (more wind, more water; more humidity, less
water). The rule should be structured so this is a contained change.

## Safety (decided)

- The valve is closed at boot, at node start, at node shutdown, and on any
  exception path.
- Every burst has a hard maximum on-time, `max_open_sec` (default: builder's
  call, comfortably above `pulse_sec`, e.g. 120). It is enforced independently
  of the scheduling logic, so a bug in the scheduler cannot hold the valve open.
  A setting change that makes `pulse_sec > max_open_sec` is rejected.
- If the node dies, the valve must close. The normally-closed valve covers loss
  of power but not a process that dies with the GPIO driven on. **Software only
  for v1** (decided): no extra hardware. Use the Pi's hardware watchdog plus a
  supervisor; the exact design is the builder's (see Left to the builder).
- **Board unknown** (decided: design without it). The Pi model and the switch
  (relay or MOSFET module) are not chosen yet, so polarity (active-high or
  active-low) and the pin's state during boot are unknown. Make polarity a setting
  (`valve_active_low`), keep the GPIO layer behind a small interface, and do
  not rely on any particular boot-time pin state. Picking a pin whose default
  pull keeps the switch off through boot is a wiring-time task (Open questions).
  Plan the hardware-free parts (rule, scheduler, settings, bridge, Mission
  Control) first.
- **Network coverage** in the lab is good enough (FC-1 runs there). The timer
  fallback is for drops and outages, not the normal mode.

## Settings (decided)

Every rule number is a ROS parameter on the FC-2 node, settable live
(`ros2 param set`) and persisted across restart. Settings are changed from
Claude Code sessions; editing them from Mission Control is not required in v1.

Launch follows FC-1's pattern: `fc.launch.py` layers a runtime overlay YAML
(`FC_RUNTIME_OVERLAY`, default `/var/lib/fc-core/runtime_overrides.yaml`) over
the base config, last-wins, and a missing overlay must not fail launch. FC-2
gets the same layering at its own path.

Writing the overlay differs from FC-1 (my call). On FC-1 a bare
`ros2 param set` does *not* persist: the overlay is written separately, by the
bridge's `POST /control/persist` through `fc_buffer`. FC-2 has no `fc_buffer`,
so the FC-2 node writes its own overlay whenever it accepts a parameter change,
atomically (write to a temp file, fsync, rename), since the Pi can lose power
at any moment. A rejected change is not written.

Settings: `rain_threshold_mm`, `cool_temp_c`, `hot_temp_c`,
`cool_bursts_per_hour`, `hot_bursts_per_hour`, `pulse_sec`, `max_open_sec`,
`fallback_bursts_per_hour`, `weather_stale_sec`, `weather_poll_sec`
(default 900, matching the model's 15-minute slots), `valve_gpio_pin`, `valve_active_low`,
latitude/longitude, and the night setting below.

**Night (my call, pending the farmer):** a setting, off by default, that when
on suppresses watering between two local times. Off means day and night follow
the same rule. When the clock is not synced the night rule does not apply.

## Data and Mission Control (decided)

FC-2 publishes under `fc2/`:

- valve state (open/closed), on every change, latched like FC-1's humidifier
  topic (`TRANSIENT_LOCAL`) so a bridge restart sees the current state;
- the weather it used: temperature, humidity, wind, precipitation, ET0, plus
  the reading's own timestamp/age;
- the chosen rate in bursts/hour and the mode (`weather`, `raining`,
  `fallback`, `night`).

The bridge (`src/mission-control/bridge/src/index.js`) gets subscriptions for
these and adds them to `ALLOWED_TOPICS` (currently FC-1 only, `fc.*`), storing
them in Timescale under an `fc2.` prefix. FC-1 topics and names stay as they
are.

Mission Control gets an FC-2 view whose main chart is **sprinkler duty % per
hour** (valve-open seconds in the hour / 3600) against temperature, humidity
and wind, with the mode shown so rain and fallback hours are explainable.

## Deploy (decided)

- FC-2 deploys like FC-1: a git branch (`fc2/prod`, mirroring FC-1's
  `fc1/prod` gate), a systemd unit, `deploy.sh`.
- `scripts/pi-deploy/deploy.sh` hardcodes FC-1's host (`172.16.10.5`), branch
  (`fc1/prod`) and unit list. Parameterise it so the same script deploys either
  Pi. FC-1 deploys must behave exactly as today with no new arguments.
- `wg-setup.sh` takes the WG IP instead of hardcoding it.
- **FC-1 is not touched (my call).** With unicast discovery FC-1 never needs to
  find FC-2; only the bridge talks to both. So:
  - FC-2 gets its own CycloneDDS config, peers `172.16.10.3` (elder-plops) and
    `172.16.10.6` (itself).
  - The bridge config (`src/mission-control/bridge/cyclonedds.xml`) adds
    `172.16.10.6`, then `docker compose up -d --build bridge`.
  - FC-1's `scripts/pi-deploy/cyclonedds.xml` stays as it is. Changing it would
    only land through `fc-system-sync.service` at an FC-1 reboot, which also
    reruns netplan and `wpa_cli reconfigure` on a production box whose only
    link is WiFi.
- **Per-host files (my call).** `fc-system-sync.service` installs netplan,
  `fc-core.service` and `cyclonedds.xml` from one hardcoded folder,
  `scripts/pi-deploy/`. FC-2 must not run that unit as it is, or it would
  install FC-1's chamber service. FC-2's host files (its unit, DDS config,
  netplan if any) live in their own folder, e.g. `scripts/pi-deploy/fc2/`, with
  their own sync step if one is needed. FC-1's files and units stay where
  they are.

## Package layout (decided)

A new ROS2 Python package beside `fc_core` (e.g. under `src/chambers/` or a new
`src/outdoor/`; builder's call), not code inside `fc_core`. `fc_core` is
chamber-specific. Copy the patterns (launch with overlay, config YAML, systemd
unit), not the chamber logic.

## Left to the builder

- Package name, node structure, file layout.
- How the "valve closes if the process dies" guarantee is built (e.g. a
  separate watchdog, a hardware watchdog, a switch that needs a heartbeat).
  Say what was chosen.
- How bursts are scheduled when the rate changes mid-gap (e.g. next burst at
  last burst + new gap). Avoid both a burst storm and a long stall.
- Starting values for `cool_temp_c`, `hot_temp_c`, `max_open_sec`,
  `weather_stale_sec`.
- Whether duty % per hour is computed in the node, the bridge or the chart query.
- Testing approach. The rule and the scheduler must be testable without ROS,
  GPIO or network (FC-1 keeps its kernel pure for the same reason).

## Open questions

- Night behaviour: ask the farmer.
- Real values for the cool and hot thresholds: tune from farmer feedback.
- Which GPIO pin drives the switch, and its polarity: set when it's
  wired. Choose a pin whose default pull keeps the valve closed during boot.
- Pi model and OS. FC-1 runs Ubuntu 24.04 with ROS2 Jazzy, and FC-2 assumes the
  same; a Pi Zero-class board would put Jazzy in question.
