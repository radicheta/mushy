#!/usr/bin/env python3
"""Manual SHT30 heater pulse (999.34 hand-run). 3s on, then sample recovery.

Pure I2C, no ROS. Prints CSV to stdout; caller tees it.
"""
import sys, time, datetime
import board, adafruit_sht31d

ADDR = 0x44
PULSE_S = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
TAIL_S = float(sys.argv[2]) if len(sys.argv) > 2 else 240.0

def ts():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

s = adafruit_sht31d.SHT31D(board.I2C(), address=ADDR)
print("iso_utc,phase,temp_c,rh_pct")

def sample(phase):
    print(f"{ts()},{phase},{s.temperature:.3f},{s.relative_humidity:.3f}", flush=True)

for _ in range(6):          # 30s baseline @5s
    sample("baseline"); time.sleep(5)

s.heater = True
print(f"{ts()},HEATER_ON,,", flush=True)
time.sleep(PULSE_S)
s.heater = False
print(f"{ts()},HEATER_OFF,,", flush=True)

t0 = time.monotonic()
while time.monotonic() - t0 < TAIL_S:
    sample("recovery"); time.sleep(5)
print(f"{ts()},DONE,,", flush=True)
