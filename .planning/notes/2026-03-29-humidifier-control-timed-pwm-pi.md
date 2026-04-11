---
date: "2026-03-29 00:00"
promoted: false
---

Humidifier control: replace bang-bang with timed PWM duty-cycle + PID loop. PID output (0-100%) maps to on-time within a fixed window. Window size should match control loop period (e.g. 2-min samples → 2-min window; 10s samples → 10s window). SSR needed for true high-freq PWM; current relay setup can use slow duty-cycle.

D term: only useful at faster sampling rates (≤10s). D amplifies sensor noise — must apply a low-pass filter to the derivative term, differentiating the filtered trend not raw readings. With filtering at 10s sampling, D meaningfully detects humidification rate and decay rate, enabling predictive braking before setpoint overshoot. At slow sample rates (2-min), D adds nothing — skip it and use PI only.

## Actuator wiring — session 2026-03-29

**Sensor confirmed:** SHT30 I2C at 0x44 (GPIO2/GPIO3, i2c-1). Live readings flowing to /fc/humidity and /fc/temperature. Sensor wired: SDA→pin3, SCL→pin5, VCC→pin4 (5V), GND→pin6.

**Actuator plan:** HL-52S dual MOSFET module.
- CH1 → humidifier (GPIO17, hardcoded in fc_controller.py)
- CH2 → ventilation fan (GPIO27, reserve for later)
- Humidifier is 48V DC (from 220V AC→48V DC PSU)
- Switching 48V DC side with MOSFET is the right approach

**Isolation concern:** Pi powered via USB, 48V PSU separate supply. Common ground required for HL-52S (no built-in optoisolation). Options:
1. Add PC817 optocoupler between GPIO and MOSFET IN — full isolation
2. Use DC SSR (has built-in optoisolation, better for frequent switching)
3. Direct common ground if 48V PSU is quality/isolated

**Status:** User checking for SSR. Actuator wiring pending. `actuator_simulation_mode: true` in config until wired.

**Pi setup state:** gpio group + udev rule for /dev/gpiomem, ubuntu in i2c+gpio groups. Libs installed: adafruit-blinka, adafruit-circuitpython-sht31d, RPi.GPIO 0.7.1.
