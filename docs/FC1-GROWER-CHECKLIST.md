# FC-1 Humidity Control — Grower Quick Reference

**Emergency contact: [Developer name/phone — fill in before printing]**

---

## What You See / What To Do

| What you see | What to do |
|---|---|
| Humidifier not running, humidity falling | Check power strip is plugged in and switched on. Check green light on SSR relay box. |
| Humidity display shows no number (blank or --) | Wait 60 seconds. If still blank, call developer. |
| Humidity over 90% for more than 10 minutes | Check humidifier is not stuck ON. If power strip is on, turn off power strip and call developer. |
| Dashboard (computer screen) not loading | On the control computer, open terminal and run: `docker compose up -d openmct bridge` |
| System seems stuck or not responding | Check Pi power (red LED on Pi board). If powered, call developer. |

---

## When to Call the Developer

- Humidity is outside 75–85% for 30 minutes or more
- The Pi board has no red power LED
- The relay light is on but the humidifier is completely silent
- Any issue not listed above

---

## System Info

**Target humidity:** 80% (normal operating range: 75–85%)

**How it works:** The system reads humidity automatically every few seconds and turns the humidifier on or off to keep humidity in range. No manual adjustments are needed during normal operation.

**Sensor location:** Small blue board on a cable inside the chamber.

**Relay location:** Small box with a green LED, mounted near the power strip.

**Pi location:** [Fill in after installation at farm]
