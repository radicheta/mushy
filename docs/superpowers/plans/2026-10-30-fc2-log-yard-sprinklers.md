# FC-2 Log-Yard Sprinklers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ROS2 node on a new Pi (FC-2) that pulses a 12 V DC sprinkler valve on a weather-driven schedule, persists its live settings, and shows up in Timescale and Mission Control.

**Architecture:** New package `fc2_core` at `src/outdoor/fc2-core/`. All decisions live in pure modules with no ROS, GPIO or network (`rule`, `scheduler`, `params`, `weather`, `valve`), wrapped by one thin rclpy node `fc2_controller`. The bridge gains an `fc2.js` subscription module; Mission Control gains a `log-yard` plugin with history and live updates. FC-1 is not touched.

**Tech Stack:** Python 3.12, rclpy (ROS2 Jazzy), RPi.GPIO, PyYAML, stdlib `urllib` and `zoneinfo`; Node.js bridge (rclnodejs, jest); OpenMCT plugin.

**Spec:** `docs/superpowers/specs/2026-10-30-fc2-log-yard-sprinklers-design.md` (read it first).

## Global Constraints

- Ticket MUSHY-168. Commit messages end with `🤖 santibot`; no Co-Authored-By trailer.
- Weather: Open-Meteo forecast `current` block, lat `-34.5165641`, lon `-55.0982273`, `timezone=UTC`. Raining uses `precipitation`, never `rain`.
- Ramp interpolates **bursts per hour**, linear on temperature, between `cool_*` and `hot_*`.
- Defaults: `rain_threshold_mm 0`, `cool_bursts_per_hour 1`, `hot_bursts_per_hour 6`, `pulse_sec 60`, `fallback_bursts_per_hour 1`, `weather_poll_sec 900`. Placeholders (comment them as such in config): `cool_temp_c 15`, `hot_temp_c 28`, `max_open_sec 120`, `weather_stale_sec 2700`.
- Night: `night_enabled false` by default; applies only when the clock is synced.
- All timing uses `time.monotonic()`. Wall clock is used only for the night window. The Pi has no RTC.
- Topics under `/fc2/`; Timescale topics under `fc2.`. FC-1 topics, files, units and `/etc/cyclonedds.xml` on FC-1 stay unchanged.
- WG IP `172.16.10.6`. `ROS_DOMAIN_ID=69`. CycloneDDS on `wg0`, unicast, single `<NetworkInterface>`.
- Overlay `FC2_RUNTIME_OVERLAY`, default `/var/lib/fc2-core/runtime_overrides.yaml`, `/**: ros__parameters:` format like `fc_config.yaml`.
- Deploy branch `fc2/prod`. Deploy syncs with `git fetch` + `git reset --hard`, never `git pull` (MUSHY-117).
- Never run ROS tests on fc1 or on domain 69: use `docker/fc-core-test.Dockerfile` with `--network none`.

## Review Focus

1. **Crash loop.** If the node keeps dying, systemd gives up after `StartLimitBurst`. The valve must be off when that happens, not stuck open. Pinned by Task 7 (`ExecStopPost` runs `fc2_valve_off`).
2. **Bad weather payload.** Open-Meteo answers 200 with `null` fields or an `error` body. The node must keep its previous reading and age into fallback, not crash. Pinned by Task 4.
3. **Bad live setting.** `ros2 param set` with `pulse_sec > max_open_sec`, `cool_temp_c >= hot_temp_c`, or a change to the GPIO pin is rejected, and the overlay file is untouched. Pinned by Tasks 3 and 6.
4. **Clock jump at NTP sync.** A jump of the wall clock by years must not trigger, skip or double a burst, and must not make a fresh reading look stale. Pinned by Tasks 1 and 2 (monotonic inputs only).
5. **Power cut while saving settings.** A half-written or corrupt overlay must not stop launch, or the logs get no water. Pinned by Task 3 (`usable_overlay`) and Task 6 (launch uses it).

---

### Task 1: Package skeleton and the rule

**Files:**
- Create: `src/outdoor/fc2-core/package.xml`, `setup.py`, `setup.cfg`, `resource/fc2_core`, `fc2_core/__init__.py`, `fc2_core/test/__init__.py`
- Create: `src/outdoor/fc2-core/fc2_core/rule.py`
- Test: `src/outdoor/fc2-core/fc2_core/test/test_rule.py`

**Interfaces:**
- Produces:
  - `WeatherReading` frozen dataclass: `temperature_c, humidity_pct, wind_kmh, precipitation_mm, et0_mm: float`, `slot_time_utc: str`, `fetched_mono: float`
  - `RuleParams` frozen dataclass with the defaults in Global Constraints, plus `night_enabled: bool = False`, `night_start: str = '20:00'`, `night_end: str = '06:00'`
  - `Decision` frozen dataclass: `mode: str` (one of `'weather' | 'raining' | 'fallback' | 'night'`), `bursts_per_hour: float`
  - `MODE_CODES = {'weather': 0, 'raining': 1, 'fallback': 2, 'night': 3}`
  - `ramp_rate(temp_c: float, p: RuleParams) -> float`
  - `in_night(t: datetime.time, start: str, end: str) -> bool` (window may wrap midnight; start inclusive, end exclusive)
  - `decide(reading: WeatherReading | None, now_mono: float, local_time: datetime.time | None, p: RuleParams) -> Decision`

Precedence in `decide`: night (only if `p.night_enabled` and `local_time is not None` and in window) → rate 0. Then no reading, or `now_mono - reading.fetched_mono > p.weather_stale_sec` → fallback. Then `precipitation_mm > rain_threshold_mm` → raining, 0. Otherwise weather, `ramp_rate`. Keep the ramp's input a single number so ET0 can replace temperature later.

`setup.py` follows `src/chambers/fc-core/setup.py`; `install_requires` = setuptools, rclpy, std_msgs, pyyaml, RPi.GPIO. Entry points: `fc2_controller = fc2_core.fc2_node:main`, `fc2_valve_off = fc2_core.valve:valve_off_main` (both created in later tasks; declare them now).

- [ ] **Step 1: Write the failing tests**

```python
P = RuleParams()
def r(temp=20.0, precip=0.0, fetched=1000.0):
    return WeatherReading(temp, 60.0, 10.0, precip, 0.1, '2026-10-30T15:30', fetched)

def test_ramp_ends_and_middle():
    assert ramp_rate(10.0, P) == 1.0
    assert ramp_rate(15.0, P) == 1.0
    assert ramp_rate(28.0, P) == 6.0
    assert ramp_rate(40.0, P) == 6.0
    assert ramp_rate(21.5, P) == pytest.approx(3.5)

def test_raining_wins_over_heat():
    assert decide(r(temp=35, precip=0.1), 1000.0, None, P) == Decision('raining', 0.0)

def test_rain_field_is_not_used_only_precipitation():
    assert decide(r(precip=0.0), 1000.0, None, P).mode == 'weather'

def test_no_reading_is_fallback():
    assert decide(None, 0.0, None, P) == Decision('fallback', 1.0)

def test_stale_is_fallback_fresh_is_not():
    assert decide(r(fetched=0.0), 2700.0, None, P).mode == 'weather'
    assert decide(r(fetched=0.0), 2700.1, None, P).mode == 'fallback'

def test_staleness_ignores_slot_wall_time():
    old_slot = WeatherReading(20, 60, 10, 0, 0.1, '1970-01-01T00:00', 1000.0)
    assert decide(old_slot, 1001.0, None, P).mode == 'weather'

def test_night_only_when_enabled_and_clock_known():
    n = dataclasses.replace(P, night_enabled=True)
    assert decide(r(), 1000.0, time(23, 0), n) == Decision('night', 0.0)
    assert decide(r(), 1000.0, None, n).mode == 'weather'
    assert decide(r(), 1000.0, time(23, 0), P).mode == 'weather'
    assert decide(None, 0.0, time(23, 0), n).mode == 'night'

def test_in_night_wraps_midnight():
    assert in_night(time(20, 0), '20:00', '06:00')
    assert in_night(time(3, 0), '20:00', '06:00')
    assert not in_night(time(6, 0), '20:00', '06:00')
    assert not in_night(time(12, 0), '20:00', '06:00')
    assert in_night(time(13, 0), '12:00', '14:00')
```

- [ ] **Step 2: Run, expect FAIL (ImportError)**

Run: `PYTHONPATH=src/outdoor/fc2-core .venv/bin/python -m pytest -q src/outdoor/fc2-core/fc2_core/test/test_rule.py`

- [ ] **Step 3: Implement `rule.py` and the package skeleton**

- [ ] **Step 4: Run, expect PASS** (same command)

- [ ] **Step 5: Commit** — `feat(fc2): weather rule for log-yard sprinklers [MUSHY-168]`

---

### Task 2: Burst scheduler and duty

**Files:**
- Create: `src/outdoor/fc2-core/fc2_core/scheduler.py`
- Test: `src/outdoor/fc2-core/fc2_core/test/test_scheduler.py`

**Interfaces:**
- Produces:
  - `class BurstScheduler(start_mono: float)` with `tick(now_mono: float, bursts_per_hour: float, pulse_sec: float) -> bool` (True = valve should be open now) and attribute `last_burst_start: float | None`
  - `duty_pct(intervals: Iterable[tuple[float, float | None]], now_mono: float, window_sec: float = 3600.0) -> float` (an end of `None` means still open; clip to the window; percent 0..100)

`tick` rules:
- During a burst (`now < open_until`) return True, unless the rate is 0, which closes immediately.
- The next burst is due at `(last_burst_start or start_mono) + 3600 / rate`. The first burst therefore comes one full gap after start: a crash-looping node must never water once per restart.
- A rate change re-derives the due time from the same reference, so a jump in rate gives at most one immediate burst.

- [ ] **Step 1: Write the failing tests**

```python
def run(s, t0, t1, rate, pulse=60.0, step=1.0):
    opened = []
    t = t0
    while t < t1:
        if s.tick(t, rate, pulse): opened.append(t)
        t += step
    return opened

def test_first_burst_waits_one_gap():
    s = BurstScheduler(0.0)
    assert not s.tick(0.0, 1.0, 60.0)
    assert not s.tick(3599.0, 1.0, 60.0)
    assert s.tick(3600.0, 1.0, 60.0)

def test_burst_lasts_pulse_sec():
    s = BurstScheduler(0.0)
    opened = run(s, 3600.0, 3800.0, 1.0)
    assert opened[0] == 3600.0 and opened[-1] == 3659.0 and len(opened) == 60

def test_six_per_hour_after_warmup():
    s = BurstScheduler(0.0)
    run(s, 0.0, 600.0, 6.0)
    starts = [t for t in range(600, 4200) if s.tick(float(t), 6.0, 60.0) and s.last_burst_start == t]
    assert len(starts) == 6

def test_rate_jump_gives_one_burst_not_a_storm():
    s = BurstScheduler(0.0)
    run(s, 0.0, 1800.0, 1.0)          # no burst yet, half a gap in
    opened = run(s, 1800.0, 2400.0, 6.0)
    assert opened[0] == 1800.0        # overdue under the new rate: one burst now
    assert len(opened) == 60          # and only that one inside this 10 min

def test_zero_rate_closes_mid_burst():
    s = BurstScheduler(0.0)
    assert s.tick(3600.0, 1.0, 60.0)
    assert not s.tick(3610.0, 0.0, 60.0)

def test_duty_pct_window_and_open_interval():
    assert duty_pct([(0.0, 60.0)], 3600.0) == pytest.approx(60 / 36)
    assert duty_pct([(0.0, 60.0)], 3660.0) == 0.0
    assert duty_pct([(3570.0, None)], 3600.0) == pytest.approx(30 / 36)
```

- [ ] **Step 2: Run, expect FAIL** — `PYTHONPATH=src/outdoor/fc2-core .venv/bin/python -m pytest -q src/outdoor/fc2-core/fc2_core/test/test_scheduler.py`
- [ ] **Step 3: Implement `scheduler.py`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** — `feat(fc2): burst scheduler and rolling duty [MUSHY-168]`

---

### Task 3: Settings: validation, overlay write, overlay read

**Files:**
- Create: `src/outdoor/fc2-core/fc2_core/params.py`
- Test: `src/outdoor/fc2-core/fc2_core/test/test_params.py`

**Interfaces:**
- Consumes: `RuleParams` (Task 1)
- Produces:
  - `RULE_PARAM_NAMES: tuple[str, ...]` — the `RuleParams` field names
  - `STARTUP_ONLY = ('valve_gpio_pin', 'valve_active_low')` — never changed live
  - `params_from_mapping(m: Mapping[str, Any]) -> RuleParams` (ignores unknown keys; missing keys take defaults)
  - `validate(p: RuleParams) -> str | None` (None = OK, else a human-readable reason)
  - `write_overlay(path: str, values: Mapping[str, Any]) -> None` — atomic: temp file in the same dir, `fsync`, `os.replace`; content `{'/**': {'ros__parameters': dict(values)}}`
  - `usable_overlay(path: str) -> bool` — True only if the file exists and parses to that shape

`validate` rejects: `cool_temp_c >= hot_temp_c`; any negative rate; `pulse_sec <= 0`; `pulse_sec > max_open_sec`; `max_open_sec > 600` (hard ceiling); `max(cool, hot, fallback rate) * pulse_sec > 1800` (more than 50 % duty); `weather_stale_sec <= 0`; night times that aren't `HH:MM`.

- [ ] **Step 0: `.venv` lacks PyYAML** — `.venv/bin/pip install pyyaml` (venv, not system).
- [ ] **Step 1: Write the failing tests**

```python
def test_defaults_valid():
    assert validate(RuleParams()) is None

@pytest.mark.parametrize('change', [
    {'cool_temp_c': 28.0}, {'pulse_sec': 121.0}, {'pulse_sec': 0.0},
    {'max_open_sec': 601.0, 'pulse_sec': 60.0}, {'hot_bursts_per_hour': 31.0},
    {'cool_bursts_per_hour': -1.0}, {'weather_stale_sec': 0.0}, {'night_start': '25:00'},
])
def test_rejects(change):
    assert validate(dataclasses.replace(RuleParams(), **change)) is not None

def test_overlay_roundtrip(tmp_path):
    p = tmp_path / 'o.yaml'
    write_overlay(str(p), {'pulse_sec': 45.0})
    assert yaml.safe_load(p.read_text()) == {'/**': {'ros__parameters': {'pulse_sec': 45.0}}}
    assert usable_overlay(str(p))
    assert not list(tmp_path.glob('*.tmp*'))

def test_failed_write_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / 'o.yaml'
    write_overlay(str(p), {'pulse_sec': 45.0})
    monkeypatch.setattr(os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('power cut')))
    with pytest.raises(OSError):
        write_overlay(str(p), {'pulse_sec': 50.0})
    assert yaml.safe_load(p.read_text())['/**']['ros__parameters']['pulse_sec'] == 45.0

@pytest.mark.parametrize('text', ['', '/**: [', 'just a string', '/**: {}'])
def test_unusable_overlay(tmp_path, text):
    p = tmp_path / 'o.yaml'; p.write_text(text)
    assert not usable_overlay(str(p))
    assert not usable_overlay(str(tmp_path / 'missing.yaml'))

def test_params_from_mapping_ignores_unknown():
    assert params_from_mapping({'pulse_sec': 30.0, 'valve_gpio_pin': 17}).pulse_sec == 30.0
```

- [ ] **Step 2: Run, expect FAIL** — `PYTHONPATH=src/outdoor/fc2-core .venv/bin/python -m pytest -q src/outdoor/fc2-core/fc2_core/test/test_params.py`
- [ ] **Step 3: Implement `params.py`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** — `feat(fc2): validated settings with atomic overlay [MUSHY-168]`

---

### Task 4: Weather client

**Files:**
- Create: `src/outdoor/fc2-core/fc2_core/weather.py`
- Create: `src/outdoor/fc2-core/fc2_core/test/data/current_2026-10-30.json` — exactly the payload verified in the spec (`temperature_2m 20.9`, `relative_humidity_2m 55`, `precipitation 0.10`, `rain 0.00`, `wind_speed_10m 14.6`, `et0_fao_evapotranspiration 0.13`, `time 2026-10-30T15:30`, `interval 900`)
- Test: `src/outdoor/fc2-core/fc2_core/test/test_weather.py`

**Interfaces:**
- Consumes: `WeatherReading` (Task 1)
- Produces:
  - `build_url(lat: float, lon: float) -> str` — the spec's URL
  - `parse_current(payload: dict, fetched_mono: float) -> WeatherReading` — raises `ValueError` if `current` is missing, if any of the five used fields is missing or null, or if the payload has `"error": true`
  - `fetch(lat: float, lon: float, timeout_sec: float = 10.0, *, opener=urllib.request.urlopen, now_mono=time.monotonic) -> WeatherReading` — raises on any network, HTTP or parse failure; the caller keeps its previous reading

- [ ] **Step 1: Write the failing tests**

```python
def test_parses_fixture():
    w = parse_current(json.loads(FIXTURE.read_text()), 5.0)
    assert (w.temperature_c, w.precipitation_mm, w.wind_kmh, w.et0_mm) == (20.9, 0.10, 14.6, 0.13)
    assert w.humidity_pct == 55 and w.slot_time_utc == '2026-10-30T15:30' and w.fetched_mono == 5.0

@pytest.mark.parametrize('mutate', [
    lambda d: d['current'].update(precipitation=None),
    lambda d: d['current'].pop('temperature_2m'),
    lambda d: d.pop('current'),
    lambda d: d.update(error=True, reason='Parameter is invalid'),
])
def test_bad_payload_raises(mutate):
    d = json.loads(FIXTURE.read_text()); mutate(d)
    with pytest.raises(ValueError):
        parse_current(d, 0.0)

def test_url_uses_precipitation_and_utc():
    u = build_url(-34.5165641, -55.0982273)
    assert 'precipitation' in u and 'timezone=UTC' in u and 'latitude=-34.5165641' in u

def test_fetch_raises_on_network_error():
    def boom(*a, **k): raise urllib.error.URLError('no route')
    with pytest.raises(Exception):
        fetch(0, 0, opener=boom)
```

- [ ] **Step 2: Run, expect FAIL** — `... -m pytest -q src/outdoor/fc2-core/fc2_core/test/test_weather.py`
- [ ] **Step 3: Implement `weather.py`** (stdlib only; add `package_data` for `test/data/*.json` if the docker suite needs it)
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** — `feat(fc2): Open-Meteo current client [MUSHY-168]`

---

### Task 5: Valve, max-on guard, valve-off command

**Files:**
- Create: `src/outdoor/fc2-core/fc2_core/valve.py`
- Test: `src/outdoor/fc2-core/fc2_core/test/test_valve.py`

**Interfaces:**
- Consumes: `usable_overlay` (Task 3)
- Produces:
  - `class SimValve` with `set_open(open_: bool) -> None` and attribute `is_open: bool`
  - `class GpioValve(pin: int, active_low: bool)` — imports `RPi.GPIO` lazily, sets BCM mode, sets the pin up as an output **already at the off level**, and has `set_open(open_: bool)` and `close()` (drive off and clean up)
  - `class GuardedValve(inner, max_open_sec: float, *, clock=time.monotonic, timer_factory=threading.Timer)` — `set_open(True)` arms a one-shot timer that forces `inner.set_open(False)` and sets `tripped = True`; `set_open(False)` cancels it. The wrapped valve is kept as attribute `inner`. It records `intervals: list[tuple[float, float | None]]` from `clock`, and prunes intervals older than 2 h.
  - `resolve_valve_config(base_path: str, overlay_path: str) -> tuple[int, bool]` — `valve_gpio_pin` / `valve_active_low` with the overlay winning when `usable_overlay`
  - `valve_off_main() -> None` — the `fc2_valve_off` console script. It reads the config paths from env `FC2_CONFIG` (default: the installed share `config/fc2_config.yaml`) and `FC2_RUNTIME_OVERLAY`, drives the pin off, and exits 0. It must never raise past `main` on a missing overlay.

The guard is the spec's "enforced independently of the scheduler": it lives in its own timer thread, so a hung control loop still closes the valve.

- [ ] **Step 1: Write the failing tests**

```python
class FakeTimer:
    made = []
    def __init__(self, sec, fn): self.sec, self.fn, self.cancelled = sec, fn, False; FakeTimer.made.append(self)
    def start(self): pass
    def cancel(self): self.cancelled = True

def test_guard_trips_after_max_open():
    v = SimValve(); g = GuardedValve(v, 120.0, timer_factory=FakeTimer, clock=lambda: 0.0)
    g.set_open(True); assert v.is_open and FakeTimer.made[-1].sec == 120.0
    FakeTimer.made[-1].fn(); assert not v.is_open and g.tripped

def test_close_cancels_guard_and_logs_interval():
    t = [0.0]; v = SimValve(); g = GuardedValve(v, 120.0, timer_factory=FakeTimer, clock=lambda: t[0])
    g.set_open(True); t[0] = 60.0; g.set_open(False)
    assert FakeTimer.made[-1].cancelled and g.intervals[-1] == (0.0, 60.0)

def test_resolve_valve_config_overlay_wins(tmp_path):
    base = tmp_path / 'b.yaml'; base.write_text('/**:\n  ros__parameters:\n    valve_gpio_pin: 17\n    valve_active_low: false\n')
    ov = tmp_path / 'o.yaml'; ov.write_text('/**:\n  ros__parameters:\n    valve_active_low: true\n')
    assert resolve_valve_config(str(base), str(ov)) == (17, True)
    assert resolve_valve_config(str(base), str(tmp_path / 'none.yaml')) == (17, False)

def test_gpio_valve_starts_off_respecting_polarity(monkeypatch):
    calls = install_fake_rpi_gpio(monkeypatch)   # helper in the test file: fake module recording setup/output
    GpioValve(17, active_low=True)
    assert calls['setup'][-1] == (17, 'OUT', 'HIGH')   # active-low: off = HIGH
```

- [ ] **Step 2: Run, expect FAIL** — `... -m pytest -q src/outdoor/fc2-core/fc2_core/test/test_valve.py`
- [ ] **Step 3: Implement `valve.py`**
- [ ] **Step 4: Run, expect PASS**; then run the whole pure suite: `PYTHONPATH=src/outdoor/fc2-core .venv/bin/python -m pytest -q src/outdoor/fc2-core/fc2_core/test/ --ignore=src/outdoor/fc2-core/fc2_core/test/test_node.py`
- [ ] **Step 5: Commit** — `feat(fc2): valve with independent max-on guard [MUSHY-168]`

---

### Task 6: The node, config and launch

**Files:**
- Create: `src/outdoor/fc2-core/fc2_core/fc2_node.py`
- Create: `src/outdoor/fc2-core/config/fc2_config.yaml` — every setting with its default; placeholders commented as such; `valve_gpio_pin: -1` (unset); `valve_active_low: false`; `actuator_simulation_mode: true` until wired; `latitude`, `longitude`, `timezone: America/Montevideo`
- Create: `src/outdoor/fc2-core/launch/fc2.launch.py`
- Test: `src/outdoor/fc2-core/fc2_core/test/test_node.py` (ROS; docker only)

**Interfaces:**
- Consumes: everything from Tasks 1–5
- Produces:
  - Node name `fc2_controller`; class `Fc2Controller(*, fetch_fn=weather.fetch, valve=None, overlay_path=None, clock_synced_fn=None, now_mono=time.monotonic)`. A `valve` of None means: build `GuardedValve(GpioValve(...))`, or `GuardedValve(SimValve())` when `actuator_simulation_mode` is set. A pin of `-1` with simulation off is a startup error.
  - Topics:
    - `/fc2/valve` `std_msgs/Bool`, `TRANSIENT_LOCAL`, published on every change
    - every 60 s: `/fc2/duty_pct_1h`, `/fc2/bursts_per_hour`, `/fc2/weather/{temperature,humidity,wind,precipitation,et0,age_sec}` as `std_msgs/Float32`, and `/fc2/mode` as `std_msgs/Int32` (`MODE_CODES`). Weather topics are published only once a reading exists.
  - Test-facing members: `control_tick() -> None` (one control step, also what the 1 s timer calls), `last_decision: Decision | None`, `valve: GuardedValve`
  - `clock_synced()` default: `os.path.exists('/run/systemd/timesync/synchronized')`

Behaviour:
- **1 s control timer:** `decide` → `scheduler.tick` → `valve.set_open` on change. Then send `WATCHDOG=1` to `$NOTIFY_SOCKET` if it is set (stdlib socket, `AF_UNIX` datagram; `@` prefix = abstract).
- **Weather:** a daemon thread fetches every `weather_poll_sec` (first fetch immediately) and swaps the latest reading in under a lock. On error it logs once per failure streak and keeps the old reading.
- **Parameter callback:** reject any `STARTUP_ONLY` change. Otherwise build the candidate `RuleParams` from current values plus the change; reject if `validate` fails; on success `write_overlay` with all rule params. If the write raises, reject.
- **Shutdown:** `valve.set_open(False)` in a `finally` around spin, and in `destroy_node`.

`fc2.launch.py`: a copy of FC-1's overlay pattern, but it appends the overlay only when `usable_overlay(path)`. One `Node(package='fc2_core', executable='fc2_controller', name='fc2_controller', ...)` with `on_exit=Shutdown()`, so a dead node ends the launch and systemd sees it.

- [ ] **Step 1: Write the failing tests** (rclpy in-process, `SimValve`, fake fetch, `tmp_path` overlay). `node_factory` is a fixture in the test file: `rclpy.init()` once, builds `Fc2Controller(valve=GuardedValve(SimValve(), 120.0), overlay_path=str(overlay), fetch_fn=fetch_fn or a fake returning a fresh reading, clock_synced_fn=lambda: False)`, destroys nodes after the test.

```python
def test_rejects_bad_param_and_leaves_overlay(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    r = n.set_parameters([Parameter('pulse_sec', value=500.0)])[0]
    assert not r.successful and not (tmp_path / 'o.yaml').exists()

def test_rejects_pin_change(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert not n.set_parameters([Parameter('valve_gpio_pin', value=5)])[0].successful

def test_good_param_persists(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert n.set_parameters([Parameter('pulse_sec', value=45.0)])[0].successful
    assert yaml.safe_load((tmp_path / 'o.yaml').read_text())['/**']['ros__parameters']['pulse_sec'] == 45.0

def test_fetch_failure_goes_fallback_valve_closed_at_destroy(node_factory, tmp_path):
    def fail(*a, **k): raise OSError('wifi down')
    n = node_factory(overlay=tmp_path / 'o.yaml', fetch_fn=fail)
    n.control_tick()
    assert n.last_decision.mode == 'fallback'
    n.valve.set_open(True); n.destroy_node()
    assert not n.valve.inner.is_open
```

- [ ] **Step 2: Run in docker, expect FAIL**

```bash
docker build -f docker/fc-core-test.Dockerfile -t fc-core-test .
docker run --rm --network none -v "$PWD/src/outdoor:/src:ro" --entrypoint bash fc-core-test \
  -c 'source /opt/ros/jazzy/setup.bash && cd /src/fc2-core && PYTHONPATH=/src/fc2-core python3 -m pytest -q -p no:cacheprovider fc2_core/test'
```

(PyYAML comes with the ROS image as `python3-yaml`.)

- [ ] **Step 3: Implement `fc2_node.py`, `fc2_config.yaml`, `fc2.launch.py`**
- [ ] **Step 4: Run in docker, expect PASS** — the whole `fc2_core/test` directory, pure tests included
- [ ] **Step 5: Commit** — `feat(fc2): fc2_controller node and launch [MUSHY-168]`

---

### Task 7: Host files and deploy

**Files:**
- Create: `scripts/pi-deploy/fc2/fc2-core.service`
- Create: `scripts/pi-deploy/fc2/cyclonedds.xml` — peers `172.16.10.3`, `172.16.10.6`; `wg0`; single interface
- Create: `scripts/pi-deploy/fc2/bootstrap.sh` — one-time, run with sudo on FC-2: installs that `cyclonedds.xml` to `/etc/cyclonedds.xml`; writes `/etc/systemd/system.conf.d/fc2-watchdog.conf` with `RuntimeWatchdogSec=15`; creates `/var/lib/fc2-core` owned by ubuntu. Idempotent.
- Create: `scripts/pi-deploy/fc2/deploy.sh` — one line: `exec env PI_HOST=172.16.10.6 BRANCH=fc2/prod UNIT_DIR=scripts/pi-deploy/fc2 UNITS=fc2-core.service PACKAGES=fc2_core SERVICE=fc2-core "$(dirname "$0")/../deploy.sh"`
- Modify: `scripts/pi-deploy/deploy.sh` — add env knobs `UNIT_DIR` (default `scripts/pi-deploy`), `UNITS` (default `fc-core.service fc-update.service fc-system-sync.service`), `PACKAGES` (default `fc_msgs fc_core`), `SERVICE` (default `fc-core`); use them in steps 0, 2 and 3. No behaviour change with no env set.
- Modify: `scripts/pi-deploy/wg-setup.sh` — `WG_IP="${1:-172.16.10.5}"`, `PEER_LABEL="${2:-FC-1 Pi}"`, used in the printed pfSense instructions
- Test: `scripts/test_pi_deploy_sync.py` (extend)

`fc2-core.service` = `fc-core.service` with these changes:
- Description: FC-2 log-yard sprinklers.
- Creates `/var/lib/fc2-core`.
- `Environment="FC2_RUNTIME_OVERLAY=/var/lib/fc2-core/runtime_overrides.yaml"`.
- `ExecStart` launches `fc2_core fc2.launch.py`.
- Adds `WatchdogSec=30` and `NotifyAccess=all`.
- Adds `ExecStopPost=` sourcing ROS and the workspace, then running `fc2_valve_off`.
- Keeps `Restart=always`, `RestartSec=10`, `StartLimitIntervalSec=300`, `StartLimitBurst=5` (see the memory note on `ros2 launch` and `Restart=on-failure`).
- Keeps the wg0 wait. `wg-quick` creates wg0 locally from its config, so the wait should pass with WiFi down and FC-2 should still start offline and fall back to the timer. This is expected, not verified: Task 10 Step 7 checks it. If it fails, the wait must become non-fatal for FC-2 (no water is worse than no telemetry).

- [ ] **Step 1: Write the failing tests**

```python
def test_fc2_unit_closes_valve_on_any_stop():
    u = (HERE / 'fc2' / 'fc2-core.service').read_text()
    assert 'ExecStopPost=' in u and 'fc2_valve_off' in u
    assert 'Restart=always' in u and 'WatchdogSec=' in u and 'NotifyAccess=all' in u

def test_fc2_dds_peers_and_fc1_dds_untouched():
    x = (HERE / 'fc2' / 'cyclonedds.xml').read_text()
    assert '172.16.10.3' in x and '172.16.10.6' in x and x.count('<NetworkInterface') == 1
    assert '172.16.10.6' not in (HERE / 'cyclonedds.xml').read_text()

def test_deploy_defaults_unchanged_for_fc1():
    t = code('deploy.sh')
    for d in ['PI_HOST:-172.16.10.5', 'BRANCH:-fc1/prod', 'SERVICE:-fc-core', 'PACKAGES:-fc_msgs fc_core']:
        assert d in t

def test_fc2_deploy_uses_reset_not_pull():
    assert 'git pull' not in code('fc2/deploy.sh')
```

Also add `'fc2/deploy.sh'` handling where `code()` is used.

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/python -m pytest -q scripts/test_pi_deploy_sync.py`
- [ ] **Step 3: Write the files and parameterise `deploy.sh` / `wg-setup.sh`**
- [ ] **Step 4: Run, expect PASS**; also `bash -n` every changed or new shell script
- [ ] **Step 5: Commit** — `feat(fc2): systemd unit, bootstrap and deploy for FC-2 [MUSHY-168]`

---

### Task 8: Bridge: subscribe, store, allow history

**Files:**
- Create: `src/mission-control/bridge/src/fc2.js`
- Modify: `src/mission-control/bridge/src/index.js` — `require('./fc2')`; spread `FC2_DB_TOPICS` into `ALLOWED_TOPICS` (line ~405); call `subscribeFc2(...)` next to the FC-1 subscriptions (~line 845), after `transientLocalQos` exists
- Modify: `src/mission-control/bridge/cyclonedds.xml` — add `<Peer address="172.16.10.6"/>  <!-- FC-2 Pi WG IP -->`
- Test: `src/mission-control/bridge/test/fc2.test.js`

**Interfaces:**
- Produces:
  - `FC2_TOPICS`: array of `{ ros: '/fc2/...', type: 'std_msgs/msg/Float32' | 'std_msgs/msg/Bool' | 'std_msgs/msg/Int32', db: 'fc2.<name>', latched?: true }` covering every topic in Task 6. DB names: `fc2.valve`, `fc2.duty_pct_1h`, `fc2.bursts_per_hour`, `fc2.mode`, `fc2.temperature`, `fc2.humidity`, `fc2.wind`, `fc2.precipitation`, `fc2.et0`, `fc2.weather_age_sec`.
  - `FC2_DB_TOPICS = FC2_TOPICS.map(t => t.db)`
  - `subscribeFc2(node, { insertTelemetry, broadcast, transientLocalQos, now = Date.now })` — one subscription per entry. Bool is stored as 1/0. Timestamps use `now()`: these messages have no header. Each subscription passes `{ qos: transientLocalQos }` when `latched`. Each message is stored **and** sent live as `broadcast({ [db]: value, timestamp })`, keyed by the full `fc2.*` name. Never use bare names like `temperature` or `humidity`: the FC-1 plugin's `onmessage` maps those keys to FC-1 sensors, so FC-2's weather would be drawn on FC-1's chamber plots. It does not touch FC-1 liveness.

- [ ] **Step 1: Write the failing tests**

```js
const { FC2_TOPICS, FC2_DB_TOPICS, subscribeFc2 } = require('../src/fc2');
function fakeNode() { const subs = []; return { subs, createSubscription: (type, topic, a, b) => subs.push({ type, topic, opts: b ? a : undefined, cb: b || a }) }; }

test('every db topic is fc2.-prefixed and unique', () => {
  expect(FC2_DB_TOPICS.every(t => t.startsWith('fc2.'))).toBe(true);
  expect(new Set(FC2_DB_TOPICS).size).toBe(FC2_DB_TOPICS.length);
  expect(FC2_DB_TOPICS).toContain('fc2.duty_pct_1h');
});
test('valve is latched and stored as 1/0', async () => {
  const n = fakeNode(); const ins = jest.fn(); const q = { q: 1 };
  const bc = jest.fn();
  subscribeFc2(n, { insertTelemetry: ins, broadcast: bc, transientLocalQos: q, now: () => 1000 });
  const v = n.subs.find(s => s.topic === '/fc2/valve');
  expect(v.opts).toEqual({ qos: q });
  await v.cb({ data: true });
  expect(ins).toHaveBeenCalledWith('fc2.valve', 1, 1000, 1000 * 1e6);
  expect(bc).toHaveBeenCalledWith({ 'fc2.valve': 1, timestamp: 1000 });
});
test('live broadcast never uses an FC-1 field name', async () => {
  const FC1_FIELDS = ['humidity', 'temperature', 'co2', 'humidifier', 'humidity_2', 'temperature_2',
    'humidifier_duty', 'humidity_target', 'pid_output', 'vpd', 'water_vapor'];
  const n = fakeNode(); const bc = jest.fn();
  subscribeFc2(n, { insertTelemetry: jest.fn(), broadcast: bc, transientLocalQos: {}, now: () => 1 });
  for (const s of n.subs) await s.cb({ data: 1 });
  const keys = bc.mock.calls.flatMap(([m]) => Object.keys(m));
  expect(keys.some(k => FC1_FIELDS.includes(k))).toBe(false);
});
test('float topics store msg.data', async () => {
  const n = fakeNode(); const ins = jest.fn();
  subscribeFc2(n, { insertTelemetry: ins, broadcast: jest.fn(), transientLocalQos: {}, now: () => 5 });
  await n.subs.find(s => s.topic === '/fc2/duty_pct_1h').cb({ data: 1.5 });
  expect(ins).toHaveBeenCalledWith('fc2.duty_pct_1h', 1.5, 5, 5e6);
});
```

- [ ] **Step 2: Run, expect FAIL** — `cd src/mission-control/bridge && npm test -- fc2`
- [ ] **Step 3: Implement `fc2.js`, wire `index.js` (pass the existing `broadcast`), add the DDS peer**
- [ ] **Step 4: Run the full bridge suite, expect PASS** — `npm test`
- [ ] **Step 5: Commit** — `feat(bridge): store FC-2 telemetry [MUSHY-168]`
- [ ] **Step 6: Deploy to elder-plops (this is prod)** — `docker compose up -d --build bridge`. Then verify that FC-1 is unaffected: `curl -s localhost:8081/health` shows `fc1.last_msg_age_sec` under 10, and `curl -s "localhost:8081/history/fc2.mode?start=0&end=1"` returns 200 `[]`, not 400.

---

### Task 9: Mission Control `log-yard` plugin

**Files:**
- Create: `src/mission-control/frontend/plugins/log-yard/plugin.js`
- Modify: `src/mission-control/frontend/index.html` — script tag beside the fruiting-chamber plugin; `tryInstall(function () { return LogYardPlugin(); })`

**Interfaces:**
- Consumes: bridge `GET /history/:topic?start&end` with `FC2_DB_TOPICS`, and the bridge WebSocket broadcasts `{ 'fc2.<name>': value, timestamp }` (Task 8)
- Produces: OpenMCT namespace `log-yard`, a root folder "FC-2 Log Yard", and one telemetry object per `fc2.*` topic. Each has a `utc` time domain and `value` range, and units: % for duty and humidity, °C, km/h, mm, bursts/h, s. Mode gets an enum format: 0 weather, 1 raining, 2 fallback, 3 night.

History and live. `request` goes against `/history`; `subscribe` listens on the bridge WebSocket (same `bridgeUrl` option and default as the FC-1 plugin) and passes each message key that matches an `fc2.*` object to that object's callbacks as `{ value, utc: timestamp }`. Follow `plugins/fruiting-chamber/plugin.js` (~349–505), but keep a separate socket and don't send rosbridge `subscribe` ops: the bridge broadcasts to every client. Reconnect on close like the FC-1 plugin. The chart Santi wants (duty % against temperature, humidity and wind) is an Overlay Plot built from these objects in the UI. No test framework exists for the frontend; verify by hand.

- [ ] **Step 1: Write the plugin and index entry**
- [ ] **Step 2: Rebuild and check the served file** — `docker compose up -d --build openmct`, then `curl -s localhost:8080/plugins/log-yard/plugin.js | head -3` shows the plugin, not a 404 page
- [ ] **Step 3: Check in a browser** — the "FC-2 Log Yard" folder lists the 10 objects, and opening `fc2.mode` shows an empty plot with no console errors (FC-2 isn't publishing yet). FC-1's plots still update live.
- [ ] **Step 4: Commit** — `feat(mission-control): FC-2 log-yard telemetry plugin [MUSHY-168]`

---

### Task 10: Bring-up on the bench Pi (needs Santi on site)

No code. Each step is a check with an expected result. Stop at the first failure.

- [ ] **Step 1: Branch** — `git push origin main:fc2/prod` (needs Santi's go-ahead: it's a push)
- [ ] **Step 2: OS** — Ubuntu 24.04 + ROS2 Jazzy on the Pi, user `ubuntu`, hostname `fc2`, on `mossrock-wifi`. Clone the repo into `/home/ubuntu/mushroom_farm_ws/mushy-repo` with the workspace `src` pointing at it, as on FC-1. If the board turns out to be Zero-class and Jazzy won't run, stop and raise it.
- [ ] **Step 3: WireGuard** — `sudo bash wg-setup.sh 172.16.10.6 "FC-2 Pi"`; Santi adds the pfSense peer; from elder-plops `ping -c3 172.16.10.6` succeeds
- [ ] **Step 4: Bootstrap + deploy** — `sudo bash scripts/pi-deploy/fc2/bootstrap.sh` on the Pi, then `scripts/pi-deploy/fc2/deploy.sh` from elder-plops; `systemctl is-active fc2-core` → `active`
- [ ] **Step 5: Data flows (sim valve)** — within 2 min, Timescale has `fc2.mode` and `fc2.temperature` rows (`select topic, max(time) from telemetry where topic like 'fc2.%' group by 1;`), and the Mission Control folder plots them. With a plot left open in real-time mode, a new point appears within ~60 s without a reload, and FC-1's temperature plot does not pick up FC-2's weather.
- [ ] **Step 6: Live setting persists** — `ros2 param set /fc2_controller pulse_sec 45.0` succeeds; `sudo systemctl restart fc2-core`; `ros2 param get` returns 45.0. Then `ros2 param set ... pulse_sec 500.0` is rejected.
- [ ] **Step 7: Offline start** — with WiFi off (Santi unplugs or disables the AP; never take an interface down over SSH), reboot the Pi. On reconnect, the logs show the node started and `fc2.mode` = 2 (fallback) for the offline period.
- [ ] **Step 8: Real valve on the bench** — Santi wires the switch and picks a pin whose default pull keeps it off during boot. Set `valve_gpio_pin`, `valve_active_low` and `actuator_simulation_mode: false` in `fc2_config.yaml` (commit, deploy). Then check:
  - The valve stays closed through a reboot.
  - Temporarily setting `weather_stale_sec 1`, `fallback_bursts_per_hour 30` and `pulse_sec 10` gives a 10 s click every 2 min. Restore the values afterwards.
  - `sudo kill -9` of the node mid-burst closes the valve within seconds (ExecStopPost).
  - Setting `max_open_sec` below the pulse is rejected.
- [ ] **Step 9: Write it down** — a breadcrumb comment on MUSHY-168: what ran, the commits, what was verified, what's still open (night, thresholds, Signal alerts follow-up, stale netplan example).
