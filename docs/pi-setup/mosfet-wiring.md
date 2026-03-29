# MOSFET Wiring Guide — FC-1 Humidifier

## Safety First

- DISCONNECT humidifier power before wiring
- Pi must be powered OFF during wiring
- Double-check all connections before powering on
- The pull-down resistor is NOT optional — it prevents the humidifier from running
  uncontrolled during Pi boot, crash, or GPIO floating state

## Components

- MOSFET: N-channel logic-level (HL-52S module CH1, or discrete IRLZ44N / IRL540N)
  - Gate threshold must be < 3.3V for Pi GPIO drive compatibility
- 10k ohm resistor (gate pull-down) — already integrated on HL-52S module
- Humidifier power supply (48V DC side)
- Jumper wires (Pi GPIO → MOSFET gate)

## Hardware Context

This wiring uses the **HL-52S MOSFET module** installed on FC-1:
- CH1 → GPIO 17 (BCM) → humidifier control (this guide)
- CH2 → GPIO 27 (BCM) → fan (reserved, not yet active)

The 48V DC bus powers the humidifier through the MOSFET drain.

## Pin Assignment

- GPIO pin: **BCM 17** (physical pin 11)
- Note: pin 17 is currently hardcoded in `fc_controller.py` line 49.
  Phase 2 (ACTR-02) will move this to `fc_config.yaml` as `humidifier_pin`.

## Circuit Diagram (text)

```
    Pi GPIO 17 (physical pin 11) ----[wire]----+---- MOSFET Gate (CH1 IN)
                                               |
                                            [10k R]   <-- pull-down resistor (on HL-52S board)
                                               |
    Pi GND (physical pin 6, 9, 14...)  -------+---- MOSFET Source ---- GND rail
                                                              |
    48V DC+ ----[humidifier+]                                 |
    48V DC- ----[humidifier-] ---- MOSFET Drain              |
                                        |                     |
                                        +---------------------+  (shared GND)

    Note: Humidifier negative leg goes through MOSFET Drain→Source to GND.
    Positive leg connects directly to 48V DC+.
```

### HL-52S Module Pinout (CH1)

```
    HL-52S CH1:
      IN  = signal input (connect to Pi GPIO 17)
      GND = ground (connect to Pi GND)
      OUT = load switch (48V humidifier- wire)
```

The HL-52S has the pull-down resistor built into the board. No external resistor
is needed when using the module. If using a discrete MOSFET, add 10k Gate-to-Source.

## Wiring Steps

### Step 1: Power down everything

1. Power off the Raspberry Pi
2. Disconnect the 48V DC humidifier power supply

### Step 2: Wire Pi GND to MOSFET GND

Connect a jumper wire from any Pi GND pin to the HL-52S CH1 GND terminal.

Pi GND pins (any of): physical pin 6, 9, 14, 20, 25, 30, 34, 39

### Step 3: Wire Pi GPIO 17 to MOSFET IN

Connect a jumper wire from Pi GPIO 17 (physical pin 11) to the HL-52S CH1 IN terminal.

**Pi GPIO 17 is physical pin 11** — counting from the corner near the SD card:
```
    3V3  [ 1][ 2]  5V
  GPIO2  [ 3][ 4]  5V
  GPIO3  [ 5][ 6]  GND  <-- GND here
  GPIO4  [ 7][ 8]  GPIO14
    GND  [ 9][10]  GPIO15
 GPIO17  [11][12]  GPIO18  <-- GPIO 17 here
```

### Step 4: Wire humidifier through MOSFET

1. Connect humidifier positive wire to 48V DC+ (directly, NOT through MOSFET)
2. Connect humidifier negative wire to HL-52S CH1 OUT terminal
3. Connect 48V DC- (GND) to the shared GND rail (same GND as MOSFET Source)

### Step 5: Visual inspection before power-on

Complete the Verification Checklist below before applying power.

## Verification Checklist (before power-on)

- [ ] Pi is powered OFF
- [ ] 48V humidifier supply is disconnected
- [ ] Pi GPIO 17 (physical pin 11) is connected to HL-52S CH1 IN
- [ ] Pi GND is connected to HL-52S CH1 GND
- [ ] Humidifier negative wire is connected to HL-52S CH1 OUT
- [ ] 48V DC- is connected to same GND as MOSFET Source
- [ ] No loose wires or visible shorts
- [ ] Pull-down resistor confirmed present (HL-52S has it on-board; check that solder joints look intact)

## Power-On Test Sequence

1. Power on Pi (leave 48V humidifier supply disconnected)
2. Copy test script to Pi:
   ```bash
   scp scripts/pi-deploy/test-gpio-actuator.py fc1:/tmp/
   ```
3. Run GPIO test (Pi only, no load):
   ```bash
   ssh fc1 "python3 /tmp/test-gpio-actuator.py"
   ```
4. Confirm "ALL TESTS PASSED"
5. Connect 48V humidifier supply
6. Re-run test — humidifier should physically toggle on/off during Test 4 cycle

## Pull-Down Resistor Verification (optional multimeter check)

To confirm the pull-down is functional when Pi is off:

1. Power off Pi completely
2. Set multimeter to DC voltage (20V range)
3. Probe MOSFET Gate pin relative to MOSFET Source GND
4. Reading should be near **0V** (pulled low by 10k resistor)
5. This confirms humidifier stays OFF when Pi is unpowered

## Safety Notes

- This MOSFET circuit controls the 48V DC side only — NOT mains AC
- The HL-52S module provides electrical isolation between Pi GPIO and the 48V rail
- Ensure all 48V wiring is rated for the humidifier's current draw
- If the humidifier uses mains AC power, a Solid State Relay (SSR) must be used instead
  of the MOSFET (SSR decision flagged as pending in STATE.md)

## References

- `src/chambers/fc-core/fc_core/fc_controller.py` — humidifier_pin hardcoded line 49
- `src/chambers/fc-core/config/fc_config.yaml` — actuator_simulation_mode (must be set false after wiring)
- `scripts/pi-deploy/test-gpio-actuator.py` — GPIO test script
- `.planning/STATE.md` — Actuator context: HL-52S, CH1→GPIO17, CH2→GPIO27
