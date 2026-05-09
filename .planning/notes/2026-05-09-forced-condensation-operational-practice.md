# Forced condensation — operational practice research

**Date:** 2026-05-08 (overnight prep for 2026-05-09 fc1 lab visit)
**Purpose:** sanity-check Phase 31 `force-condensation` defaults (15 min, cap 120) and surface failure modes before the farmer-call discussion item #1.
**Out of scope:** code changes; this drives a conversation, not a commit.

---

## 1. What is "forced condensation," operationally?

Two distinct workflows in the literature get bundled under this label. They have different purposes, different durations, and different failure modes:

### Workflow A — Pinning trigger ("cold-and-wet shock")
- **Goal:** push the chamber from colonization regime (24 °C, ~100% RH, no airflow) into pinning regime (16–20 °C, supersat, increased FAE).
- **Mechanism:** combination of *temperature drop* + *moisture saturation* + *light pulse*. Forced condensation is the "saturation" lever.
- **Species behavior:**
  - **Oyster (P. ostreatus / pulmonarius):** very forgiving; pin reliably under a wide range; condensation pulse mostly accelerates rather than enables.
  - **Shiitake (L. edodes):** *requires* a temperature drop (45–50 °F / 7–10 °C cold shock for 12–24h) for log/block fruiting. Condensation alone won't pin shiitake.
  - **Lion's mane:** between the two — likes high humidity (85–90%) and moderate cold shock.
- **Typical duration:** the *cold shock* is hours-to-a-day. The *condensation event* is minutes — a saturating pulse to ensure no surface drying happened during the cold-shock transition.

### Workflow B — Hydration recovery ("rescue condensation")
- **Goal:** recover from a chamber that has trended dry (RH dropped, surface films lost, primordia at risk of aborting) — typically after a sensor or actuator anomaly, FAE overshoot, or shift change.
- **Mechanism:** drive RH to saturation fast enough to re-establish surface water films before primordia abort. Pure water-mass intervention.
- **Typical duration:** 5–15 min, monitored. Past 15 min, you're not rescuing — you're flooding.
- **This is the workflow Phase 31 is shaped for.** The 15 min default and 120 min cap are sane *for this workflow*. They are pessimistic-but-not-crazy for Workflow A's saturation pulse.

**Discussion item for the farmer:** is the operator's mental model A, B, or both? If A, the *cold shock* is more important than the *condensation pulse*, and Phase 31 alone won't deliver the experiment. If B, Phase 31 nails the use case.

---

## 2. Default duration sanity check — 15 min

Reference points for "how long does saturation actually take":

- **Mass-budget check (from VPD note §2.2):** going from 95% → 100% RH in a 0.5 m³ chamber at 22 °C requires ~0.5 g of additional vapor. At ~1.5 g/min humidifier output, that's **~20 seconds of net injection**. Even with 50% efficiency loss to wall condensation and leakage, you're at saturation in < 1 minute.
- **Past-saturation accumulation:** every additional minute at 100% duty = ~1.5 g of liquid water deposited on chamber surfaces. Over 15 min: ~20–25 g (about a tablespoon spread across the chamber).
- **Realistic standing-water onset:** visible droplet condensation on chamber walls typically appears within 2–5 min of sustained saturation; obvious surface films within 10 min; standing water on the floor by 20–30 min depending on chamber geometry.

**Verdict:** 15 min default is **right for hydration-rescue (Workflow B)**, **right for the saturation pulse part of pinning trigger (A)**, **too short for "I want to see water beading on every surface as a setup for spore release" experiments**, and **way short for any soaking experiment**.

The 120 min hard cap is **conservative** but not crazy. 120 min at 100% duty deposits ~150–200 g of water on surfaces — that's into the "drips off the camera lens, pools on the floor" territory and is approaching unsafe-for-electronics in this chamber design.

**Suggested farmer-call probe:**
- "If 15 min is the median experiment, what's the 90th percentile? Are there real workflows that want 30, 45, 60 min?"
- "Should the default come down (e.g., 10 min) so accidents are smaller?"
- "Is 120 min actually a meaningful cap, or should we make it harder — say 60 min — and require an explicit operator override past that?"

---

## 3. Failure modes (and which Phase 31 already handles)

| # | Failure mode | Severity | Mitigation today | Gap |
|---|---|---|---|---|
| F1 | Operator typo: `/force-condensation 200` (intended 20) | LOW | Hard cap at 120; rejection message | Already handled; UAT-2 covers |
| F2 | Two operators send overlapping experiments | LOW | Single-experiment lockout (`experiment_in_progress`) | Already handled; UAT-3 covers |
| F3 | fc1 reboots mid-experiment | HIGH (safety) | Boot in safe baseline; DB row truncated | Already handled; UAT-5 covers — **DO NOT SKIP** |
| F4 | Bridge restart mid-experiment | MEDIUM | TRANSIENT_LOCAL replay re-subscribes | Already handled; failure-scenario in visit plan |
| F5 | Condensation drips onto sensor body (SHT30/SCD41) | MEDIUM | None | Sensor reports near-100% even after recovery if water-trapped at body; can take hours to clear; **discussion item — physical sensor placement** |
| F6 | Condensation drips onto camera lens | MEDIUM | None | Phase 23 timelapse turns into a fogged window for hours; no auto-recovery; **999.x candidate: lens hood / heater pad** |
| F7 | Standing water on chamber floor → stagnant pool → bacterial bloom | HIGH (crop loss) | None | No drainage detection; visual-only; **operator-visible runbook item — inspect floor after experiments > 15 min** |
| F8 | Bacterial wet-rot on substrate (excess condensation directly on fruiting bodies) | HIGH (crop loss) | None | Mid-fruiting force-condensation should probably be BLOCKED — discussion item #1.3 in visit plan; literature is unambiguous: "any condensation that precipitates directly onto fruiting bodies can cause cosmetic defects and reduce harvest quality"; sustained = mold + pathogenic bacteria |
| F9 | RH sensor stuck-at-100% after experiment ends | LOW–MEDIUM | None today | If no condensation has cleared, controller perceives "still saturated" and won't humidify when it should; degrades silently; **observer in SEED-005 Regime B is the long-term answer** |
| F10 | Power flicker during force-condensation | LOW | systemd Restart=always (post memory `feedback_systemd_restart_ros2_launch` fix); Phase 27.2 SYS-04 partial coverage | Boot-recovery path already validates safe baseline |
| F11 | Force-experiment spans a Phase 30 schedule boundary | LOW | Scheduler suppressed during experiment; re-aligns within 30s on revert | Already handled; UAT-6 covers (D-08) |

**Net assessment of Phase 31 vs failure modes:**
- Software safety (F1–F4, F10–F11): **well covered**.
- Physical/chemical safety (F5–F9): **uncovered, mostly out of scope for the software phase**, but worth surfacing to the farmer so we have a shared mental model. F8 specifically merits a software gate (block during fruiting mode) — this is exactly the operator-input question in visit-plan item #1.3.

---

## 4. State-machine sanity check on Phase 31's contract

Re-reading the visit plan + plan-31-04: the implemented contract is

```
ANY_MODE  --(/force-condensation N)-->  EXPERIMENT(force-condensation, N min, prior_mode=X)
                                                            |
                       (timer expires)  ----- or -----  (/cancel-experiment)  ----- or -----  (boot)
                                                            |
                                                            v
                                                   resume mode X (or safe baseline if boot)
```

This is correct **for hydration rescue (Workflow B)** and **adequate for the saturation pulse of pinning trigger (Workflow A)**, but does not cover **chained experiments** ("force-condensation 5 min → force-evaporation 30 min → fruiting") which would be the canonical pinning experiment shape.

Not a Phase 31 bug — it's a v1.6 question. Worth surfacing to the farmer:
- "Today: one experiment at a time. Tomorrow: should we support recipes / playlists?"

---

## 5. Failure-mode-driven operator runbook (not for code; for the human)

For tomorrow's UAT and for any future operator running force-condensation:

1. **Before starting any experiment > 15 min:**
   - Camera frame should be clear (no pre-existing fog).
   - Visually inspect chamber floor (no standing water).
   - Check substrate not in active fruiting flush.
2. **During the experiment:**
   - Watch first 5 min — should see RH climb to ~100%, condensation visible on far wall by min 3–5.
   - If RH does not climb past 95% by min 3, abort and check humidifier (water level, line clog).
3. **After experiment ends:**
   - Sensor read should drop below 99% within 5 min as condensation evaporates.
   - If sensor pinned at 100% past 30 min after experiment end → suspect sensor body water trap (F5/F9). Wipe gently with lint-free cloth, restart sensor node.
   - Inspect chamber floor for standing water; if present, mop and review experiment duration.
   - Camera lens: if fogged, wait passively (heating recovers within 1–2h naturally).

---

## 6. References

- [Shiitake Mushroom Production: Fruiting, Harvesting, Storage — Ohioline (Ohio State Extension)](https://ohioline.osu.edu/factsheet/f-0042)
- [Mushrooms Production and Harvesting — Penn State Extension](https://extension.psu.edu/forage-and-food-crops/mushrooms/production-and-harvesting)
- [Pinning — ZombieMyco](https://zombiemyco.com/pages/pin)
- [Humidifier for Mushroom Cultivation — Colorado Cultures](https://www.coloradoculturesllc.com/post/humidifier-for-mushroom-cultivation)
- [4 Culture Parameters for Growing Mushrooms — La Mycosphère](https://lamycosphere.com/en-int/blogs/the-future-is-fungi/the-4-culture-parameters-to-master)
- [Cultivating Culinary Mushrooms — 577 Foundation](https://577foundation.org/2023/05/22/cultivating-culinary-mushrooms/)
