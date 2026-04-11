# Actuator Wiring Guide — FC-1

One SSR-10A switches a power strip (zapatilla). Humidifier and fans plug into the strip
and trigger together. GPIO 17 = everything on/off.

| What | GPIO | Hardware |
|------|------|----------|
| Power strip (humidifier + fans) | BCM 17 (pin 11) | SSR-10A spliced into strip Live |
| Fan independent (reserved, Phase 3) | BCM 27 (pin 13) | HL-52S CH1 — unused for MVP |

---

## Part 1: Humidifier — SSR-10A (220V AC)

### Why SSR, not MOSFET

The humidifier runs on mains AC power. The SSR provides full galvanic isolation between
the Pi's 3.3V logic and the 220V AC circuit. A MOSFET is not safe for mains switching.

**SSR-10A specs:** Control 3–32V DC in, Output 24–480V AC 10A out.
Pi GPIO 17 at 3.3V is within the control input range — drives directly, no level shifter.

### ⚠ Mains Safety — Read Before Touching

- **ISOLATE MAINS POWER** before any wiring — switch off at the breaker, not just the switch
- Mains AC (220V) is lethal. Double-check the circuit is dead before touching output terminals
- All mains-side wiring must be rated for the load current and insulated for mains voltage
- The SSR output side carries live mains voltage when connected — treat it like a wall outlet
- Keep SSR input wiring (low voltage DC) physically separated from output wiring (mains AC)

### SSR-10A Circuit Diagram

The SSR is spliced into the power strip's supply cable Live wire.
Everything plugged into the strip (humidifier, fans) goes on/off together.

```
    LOW VOLTAGE SIDE (DC)          HIGH VOLTAGE SIDE (AC)
    ─────────────────────          ──────────────────────────────────────────

    Pi GPIO 17 (3.3V) ──── SSR IN+    SSR OUT1 ──── 220V Live (from wall)
    Pi GND ──────────────── SSR IN-    SSR OUT2 ──── Live → zapatilla internal bus
                                                           ├── humidifier outlet
                                                           ├── fan outlet 1
                                                           └── fan outlet 2

                                       220V Neutral ──────── Neutral → zapatilla
                                       (Neutral bypasses SSR — splice direct)
```

Splice point: cut the zapatilla's supply cable, insert SSR into the **Live** wire only.
Neutral wire gets rejoined with a connector — it does not pass through the SSR.

### Pin Assignment

- **GPIO 17** = BCM 17, physical pin 11

```
    3V3  [ 1][ 2]  5V
  GPIO2  [ 3][ 4]  5V
  GPIO3  [ 5][ 6]  GND  ← GND here (pin 6)
  GPIO4  [ 7][ 8]  GPIO14
    GND  [ 9][10]  GPIO15
 GPIO17  [11][12]  GPIO18  ← GPIO 17 here (pin 11)
```

### Wiring Steps

**Step 1: Kill mains power at the breaker. Verify dead with multimeter.**

**Step 2: Prepare the zapatilla supply cable**
1. Cut the supply cable at a convenient point before the strip's body
2. Identify Live and Neutral wires (typically: Live = brown or red, Neutral = blue or black — verify with multimeter before cutting)
3. Cut only the **Live** wire — leave Neutral intact or rejoin with a wire connector

**Step 3: Wire the high-voltage AC side of the SSR**
1. Wall-side Live cut end → SSR **OUT1**
2. Strip-side Live cut end → SSR **OUT2**
3. Neutral wire: rejoin both ends with a wire connector (does not go through SSR)

**Step 4: Wire the low-voltage DC control side**
1. Pi GPIO 17 (physical pin 11) → SSR **IN+**
2. Pi GND (physical pin 6) → SSR **IN-**

**Step 5: Plug humidifier and fans into the zapatilla**

**Step 6: Verify before restoring power** — complete the checklist below.

### Verification Checklist (before restoring mains)

- [ ] Mains supply is OFF and verified dead with multimeter
- [ ] Pi GPIO 17 (pin 11) → SSR IN+
- [ ] Pi GND (pin 6) → SSR IN-
- [ ] Wall-side Live → SSR OUT1
- [ ] SSR OUT2 → zapatilla Live (strip-side)
- [ ] Neutral rejoined directly — does NOT pass through SSR
- [ ] All AC splice points are insulated — no exposed conductors
- [ ] SSR mounted to metal surface or heatsink (gets warm under load)
- [ ] DC control wiring physically separated from AC wiring
- [ ] Humidifier and fans plugged into zapatilla

### Power-On Test Sequence

1. Pi powered on, mains still disconnected from humidifier
2. Run GPIO test:
   ```bash
   scp scripts/pi-deploy/test-gpio-actuator.py fc1:/tmp/
   ssh fc1 "python3 /tmp/test-gpio-actuator.py"
   ```
3. Confirm `=== ALL TESTS PASSED ===`
4. During Test 4 (toggle cycle), the SSR LED indicator should blink — confirms logic signal reaching SSR
5. Restore mains power to humidifier supply
6. Re-run test — humidifier should physically toggle on/off during the 3-cycle test

### Fail-Safe Behavior

When Pi GPIO 17 is LOW (idle, boot, crash, shutdown): SSR input current drops to zero,
SSR output opens, humidifier AC supply is cut. Humidifier defaults **OFF** without any
pull-down resistor — the SSR is current-driven and naturally fails open.

---

## Part 2: Fan — HL-52S MOSFET Module (DC)

Reserved for Phase 3. GPIO 27 assigned to CH1 of the HL-52S.

The HL-52S has an integrated pull-down resistor on each channel — fan defaults OFF
when GPIO is floating or Pi is unpowered.

### Wiring (when needed)

```
    Pi GPIO 27 (physical pin 13) ──── HL-52S CH1 IN
    Pi GND ───────────────────────── HL-52S CH1 GND
    Fan negative wire ─────────────── HL-52S CH1 OUT
    Fan positive wire ─────────────── Fan supply V+
    Fan supply GND ────────────────── HL-52S CH1 GND (shared)
```

**Pi GPIO 27 = physical pin 13:**
```
 GPIO17  [11][12]  GPIO18
 GPIO27  [13][14]  GND  ← GND here (pin 14)
```

---

## Software Notes

- `fc_controller.py` line 49: `humidifier_pin = 17` — no code change needed, GPIO17 is unchanged
- `fc_config.yaml`: set `actuator_simulation_mode: false` after wiring to enable real GPIO output
- Phase 2 (ACTR-02) will move pin assignments to `fc_config.yaml`

## References

- `src/chambers/fc-core/fc_core/fc_controller.py` — humidifier_pin line 49
- `src/chambers/fc-core/config/fc_config.yaml` — actuator_simulation_mode
- `scripts/pi-deploy/test-gpio-actuator.py` — GPIO toggle test (works for both SSR and MOSFET)
