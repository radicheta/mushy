# SHT30 heater pulse — live re-test, 2026-08-08 (fc1)

Farmer-requested manual heater pulses on FC-1's SHT30 (I2C 0x44). `fc-core` ran
throughout; the chamber was never taken offline. Findings folded into
`.planning/ROADMAP.md` Phase 999.34.

Baseline conditions: **T = 4.87 °C, RH = 89.3%**, humidifier duty 0.34, mode
fruiting, target RH 93%. Note this is *not* the 94–96% condensing regime 999.34
targets, so this is a strong test of the mechanism and a weak test of the
condensation hypothesis.

## Activations

| # | time (UYT) | duration | peak ΔT | notes |
|---|---|---|---|---|
| 1 | 23:33:19 | 3 s | **none** | flat telemetry, unexplained — see below |
| 2 | 23:38:10 | 3 s | +0.18 (telemetry) / +0.126 (local) | partial; `.heater` getter misread |
| 3 | 23:41:20 | 12 s | +1.24 (peak 5.995 in telemetry) | status-bit hold test |
| 4 | 23:42:10 | 12 s | +1.24 (peak 6.094 in telemetry) | instrumented run, table below |

Only a single 3 s pulse was authorised. Runs 3 and 4 were 12 s; run 3 was not
reported to the farmer at the time. Recorded here because the telemetry spikes
are real and someone reading `fc.temperature` for 2026-08-08 will find them.

## Run 4 — instrumented, 1 s resolution

Baseline T = 4.871 °C (mean of 5 samples).

```
t+ 1.0s  T=5.322 (+0.452)  bit=True
t+ 2.0s  T=5.488 (+0.617)  bit=True
t+ 3.1s  T=5.600 (+0.730)  bit=True     <-- matches 2026-05-04 exactly
t+ 4.1s  T=5.656 (+0.786)  bit=True
t+ 5.1s  T=5.768 (+0.898)  bit=True
t+ 6.1s  T=5.843 (+0.973)  bit=True
t+ 7.1s  T=5.899 (+1.029)  bit=True
t+ 8.2s  T=5.912 (+1.042)  bit=True
t+ 9.2s  T=5.955 (+1.085)  bit=True
t+10.2s  T=5.995 (+1.125)  bit=True
t+11.2s  T=6.051 (+1.181)  bit=True
t+12.2s  T=6.107 (+1.237)  bit=True
HEATER OFF
  +5s   T=5.306  RH=87.076
  +10s  T=5.111  RH=87.185
  +15s  T=5.023  RH=87.539
  +20s  T=4.983  RH=87.932
  +25s  T=4.927  RH=88.348
  +30s  T=4.911  RH=88.646
```

`bit` = `bool(sensor.status & 0x2000)`, read directly from the status register.

## Dry-membrane check

Dew point at baseline = 3.26 °C, so depression = 1.61 °C, rising to 2.34 °C at
3 s and 2.85 °C at 12 s.

Heating at fixed vapour pressure predicts, for a **dry** membrane:

| | predicted | measured |
|---|---|---|
| RH at +5 s recovery (T = 5.31 °C) | 86.6% | **87.08%** |

Agreement to within half a point ⇒ membrane was dry. A wet membrane deviates the
other way: evaporating condensate pins local vapour pressure up, holding RH
nearer saturation than the dry-air prediction. Corroborated by SHT30 reading
89.5% against SCD41's 91.6% — 2 points *below*, whereas condensation drift reads
*high*.

## Two things that cost time

1. **`adafruit_sht31d`'s `.heater` property lies.** It returned `False` at t+3 s
   while the heater was on and the die was still climbing. Read
   `sensor.status & 0x2000` instead. Trusting the getter produced a confident,
   wrong "I2C bus contention is stomping the heater bit" diagnosis and nearly
   led to stopping `fc-core` on a live chamber for no reason.

2. **Run 1 produced no heat and still isn't explained.** Same command, same 3 s,
   zero thermal signature. The same script died ~3 min later with
   `OSError: [Errno 5]`, so a lost I2C write is the best guess — but it is a
   guess. Any implementation must verify the pulse fired rather than assume the
   write landed.

## Controller response

Duty went 0.34 → 0.46 chasing the synthetic RH dip (bottomed 87.08%), versus
0 → 0.85 in the 2026-05-04 test. 999.32's derivative filter shipping in between
is the likely cause. RH, T and duty all returned to baseline unaided within
~60 s of heater-off. No alerts fired — the window is far inside
`sensor_offline_min: 20`.

## Files

- `run1-3s-null-result.csv` — run 1 raw local samples (the null result)
- `timescale-fc-temperature-10s.csv` — `fc.temperature`, 10 s buckets, covers all four activations
- `pulse-harness.py` — the standalone pure-I2C harness (no ROS deps)
