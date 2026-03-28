#!/usr/bin/python
# -*- coding: utf-8 -*-
# shutdown_guard.py (Py2.7 compatible)

from __future__ import print_function

import subprocess
import threading
import time

import RPi.GPIO as GPIO

HAVE_LCD = True
try:
    import lcd.lcd_library as lcd_library
except Exception:
    HAVE_LCD = False


SHUTDOWN_PIN = 17
HOLD_SECONDS = 5.0
POLL_INTERVAL = 0.1


def init_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SHUTDOWN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def button_is_pressed():
    # pull-up input: pressed = LOW
    return GPIO.input(SHUTDOWN_PIN) == 0


def wait_for_press():
    GPIO.wait_for_edge(SHUTDOWN_PIN, GPIO.FALLING)


def confirm_long_press(hold_seconds):
    """
    Return True only if button remains held for hold_seconds.
    Return False if released early.
    """
    deadline = time.time() + float(hold_seconds)

    while time.time() < deadline:
        if not button_is_pressed():
            return False
        time.sleep(POLL_INTERVAL)

    return True


def show_shutdown_message():
    """
    Best effort LCD message. Returns lcd object or None.
    """
    if not HAVE_LCD:
        return None

    try:
        lcd = lcd_library.lcd(58, 1)
        lcd.lcd_clear()
        lcd.lcd_puts_left_justified("Shutting Down..", 1)
        lcd.lcd_puts_left_justified("Please wait...", 2)
        lcd.lcd_puts_left_justified("Safe to unplug", 3)
        lcd.lcd_puts_left_justified("when lcd stops", 4)
        return lcd
    except Exception as e:
        print("WARNING: LCD shutdown message failed: %s" % e)
        return None


def _shutdown_call():
    try:
        subprocess.call(
            ["/sbin/shutdown", "-h", "now"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except Exception as e:
        print("ERROR: shutdown command failed: %s" % e)


def perform_shutdown_with_indicator(lcd):
    """
    Start OS shutdown in a background thread, then keep animating
    the LCD until the OS kills this process.
    """
    t = threading.Thread(target=_shutdown_call)
    t.daemon = True
    t.start()

    spinner = ["/", "-", "\\", "|"]
    i = 0

    while True:
        if lcd is not None:
            try:
                lcd.lcd_puts_right_justified(spinner[i % len(spinner)], 1)
            except Exception:
                pass
        i += 1
        time.sleep(0.4)


def main():
    init_gpio()
    print("shutdown_guard: waiting for shutdown button on GPIO %s" % SHUTDOWN_PIN)

    try:
        while True:
            wait_for_press()

            # debounce settle
            time.sleep(0.05)

            if not button_is_pressed():
                continue

            print("shutdown_guard: button pressed, checking hold...")

            if confirm_long_press(HOLD_SECONDS):
                print("shutdown_guard: long press confirmed, shutting down")
                lcd = show_shutdown_message()

                try:
                    GPIO.cleanup()
                except Exception:
                    pass

                perform_shutdown_with_indicator(lcd)
            else:
                print("shutdown_guard: press too short, cancelled")

    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()