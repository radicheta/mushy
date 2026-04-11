#!/usr/bin/env python3
"""Test SHT30 sensor directly on Pi via I2C — no ROS dependency.

Run on Pi: python3 test-sht30-raw.py

Tests SHT30 at I2C address 0x44 — the sensor used by fc_sensors.py
(adafruit_sht31d library, board.I2C()).

NOTE: The original plan called for DHT22 (GPIO4 / adafruit_dht), but the
actual implementation in fc_sensors.py uses an SHT30 over I2C with
adafruit-circuitpython-sht31d. This script tests the real hardware.
"""
import sys
import time

try:
    import board
    import adafruit_sht31d
except ImportError:
    print("ERROR: Adafruit SHT31D library not available.")
    print("Install with:")
    print("  pip3 install adafruit-blinka adafruit-circuitpython-sht31d")
    sys.exit(1)

SHT30_I2C_ADDRESS = 0x44  # matches fc_config.yaml sht30_i2c_address: 0x44


def main():
    print("=== SHT30 Raw Sensor Test (I2C 0x44) ===")
    print()

    try:
        i2c = board.I2C()
        sensor = adafruit_sht31d.SHT31D(i2c, address=SHT30_I2C_ADDRESS)
        print(f"SHT30 initialized at I2C address 0x{SHT30_I2C_ADDRESS:02x}")
    except Exception as e:
        print(f"ERROR: Failed to initialize SHT30: {e}")
        print("Troubleshooting:")
        print("  1. Check I2C wiring: SDA=pin3, SCL=pin5, VCC=pin4, GND=pin6")
        print("  2. Check I2C enabled: sudo raspi-config -> Interfacing -> I2C")
        print("  3. Scan for device: i2cdetect -y 1 (should show 0x44)")
        print("  4. Check user is in i2c group: groups | grep i2c")
        sys.exit(1)

    readings = []
    errors = 0
    max_attempts = 10

    print(f"Taking {max_attempts} readings (2s interval)...")
    print()

    for i in range(max_attempts):
        try:
            temperature = sensor.temperature
            humidity = sensor.relative_humidity

            if humidity is not None and temperature is not None:
                readings.append((temperature, humidity))
                print(f"  Reading {i+1}: temp={temperature:.1f}C  humidity={humidity:.1f}%")
            else:
                errors += 1
                print(f"  Reading {i+1}: None returned (sensor not ready)")

        except Exception as e:
            errors += 1
            print(f"  Reading {i+1}: Error — {e}")

        time.sleep(2.0)

    print()
    print("=== Results ===")
    print(f"Successful readings: {len(readings)}/{max_attempts}")
    print(f"Errors: {errors}/{max_attempts}")

    if len(readings) == 0:
        print()
        print("FAILED: No valid readings obtained.")
        print("Troubleshooting:")
        print("  1. Check I2C wiring: SDA=pin3, SCL=pin5, VCC=pin4, GND=pin6")
        print("  2. Run: i2cdetect -y 1  (expect 0x44 to appear)")
        print("  3. Check user group: id | grep i2c")
        sys.exit(1)

    temps = [r[0] for r in readings]
    humids = [r[1] for r in readings]

    print(f"Temperature range: {min(temps):.1f}C — {max(temps):.1f}C")
    print(f"Humidity range: {min(humids):.1f}% — {max(humids):.1f}%")

    # Sanity checks
    sane = True
    for t, h in readings:
        if t < 0 or t > 60:
            print(f"WARNING: Temperature {t}C outside reasonable range (0-60)")
            sane = False
        if h < 0 or h > 100:
            print(f"WARNING: Humidity {h}% outside valid range (0-100)")
            sane = False

    if sane and len(readings) >= 3:
        print()
        print("=== SHT30 RAW TEST PASSED ===")
        print(f"Sensor is working. Got {len(readings)} valid readings.")
    elif sane:
        print()
        print("=== SHT30 RAW TEST MARGINAL ===")
        print(f"Only {len(readings)} valid readings — sensor may have intermittent issues.")
    else:
        print()
        print("=== SHT30 RAW TEST WARNING ===")
        print("Values outside expected range — check sensor and wiring.")
        sys.exit(1)


if __name__ == "__main__":
    main()
