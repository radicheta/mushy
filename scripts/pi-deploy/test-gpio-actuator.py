#!/usr/bin/env python3
"""Test GPIO actuator control for MOSFET-driven humidifier.

Run on Pi: python3 test-gpio-actuator.py

Tests GPIO pin 17 (BCM) — the humidifier MOSFET gate (HL-52S CH1 IN).
This script verifies that the Pi can toggle the MOSFET on and off before
the ROS2 node is configured to drive it.

Prerequisites:
  - RPi.GPIO installed: pip3 install RPi.GPIO
  - ubuntu user in gpio group: sudo usermod -aG gpio ubuntu
  - Script run on the Pi (not the workstation)

Usage:
  # Copy to Pi and run:
  scp scripts/pi-deploy/test-gpio-actuator.py fc1:/tmp/
  ssh fc1 "python3 /tmp/test-gpio-actuator.py"
"""
import sys
import time

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("ERROR: RPi.GPIO not available. Install with: pip3 install RPi.GPIO")
    print("       Also ensure user is in gpio group: sudo usermod -aG gpio $USER")
    sys.exit(1)

HUMIDIFIER_PIN = 17  # BCM pin number — matches fc_controller.py hardcoded value (line 49)


def main():
    print(f"=== GPIO Actuator Test (pin BCM {HUMIDIFIER_PIN}) ===")
    print()

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    try:
        # Setup pin as output, initially LOW (humidifier OFF)
        GPIO.setup(HUMIDIFIER_PIN, GPIO.OUT, initial=GPIO.LOW)
        print(f"Pin {HUMIDIFIER_PIN} configured as OUTPUT, initial state: LOW (OFF)")
        print()

        # Test 1: Confirm initial state is LOW
        state = GPIO.input(HUMIDIFIER_PIN)
        print(f"Test 1 - Initial state: {'HIGH (ON)' if state else 'LOW (OFF)'}")
        assert state == 0, f"Expected LOW, got {state}"
        print("  PASS: Pin starts LOW (humidifier OFF)")
        print()

        # Test 2: Set HIGH (humidifier ON)
        print("Test 2 - Setting pin HIGH (humidifier ON)...")
        GPIO.output(HUMIDIFIER_PIN, GPIO.HIGH)
        time.sleep(0.5)
        state = GPIO.input(HUMIDIFIER_PIN)
        print(f"  Pin state: {'HIGH (ON)' if state else 'LOW (OFF)'}")
        assert state == 1, f"Expected HIGH, got {state}"
        print("  PASS: Pin is HIGH")
        print("  >>> If humidifier is connected, it should be ON now")
        print()

        # Test 3: Set LOW (humidifier OFF)
        print("Test 3 - Setting pin LOW (humidifier OFF)...")
        GPIO.output(HUMIDIFIER_PIN, GPIO.LOW)
        time.sleep(0.5)
        state = GPIO.input(HUMIDIFIER_PIN)
        print(f"  Pin state: {'HIGH (ON)' if state else 'LOW (OFF)'}")
        assert state == 0, f"Expected LOW, got {state}"
        print("  PASS: Pin is LOW")
        print("  >>> Humidifier should be OFF now")
        print()

        # Test 4: Toggle cycle (3 times, 1 second each)
        print("Test 4 - Toggle cycle (3x, 1 second each)...")
        for i in range(3):
            GPIO.output(HUMIDIFIER_PIN, GPIO.HIGH)
            print(f"  Cycle {i+1}: ON", end="", flush=True)
            time.sleep(1)
            GPIO.output(HUMIDIFIER_PIN, GPIO.LOW)
            print(" -> OFF")
            time.sleep(1)
        print("  PASS: Toggle cycle complete")
        print()

        print("=== ALL TESTS PASSED ===")
        print(f"GPIO actuator control verified on pin BCM {HUMIDIFIER_PIN}")

    except AssertionError as e:
        print(f"FAILED: Assertion error — {e}")
        sys.exit(1)
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    finally:
        # Safety: always leave humidifier OFF and release GPIO
        GPIO.output(HUMIDIFIER_PIN, GPIO.LOW)
        GPIO.cleanup()
        print("GPIO cleaned up (pin released, humidifier OFF)")


if __name__ == "__main__":
    main()
