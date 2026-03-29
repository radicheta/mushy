---
date: "2026-03-29 00:00"
promoted: false
---

Humidifier control: replace bang-bang with timed PWM duty-cycle + PI loop. PID output (0-100%) maps to on-time within a fixed window (start with 30s). Use PI not PID — humidity lag makes derivative noisy. SSR needed for true high-freq PWM; current relay setup can use slow duty-cycle. Window size trades responsiveness vs relay wear.
