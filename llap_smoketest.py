#!/usr/bin/python
# -*- coding: utf-8 -*-
# llap_smoketest.py

from __future__ import print_function

import sys
from time import sleep

# Ensure these match your renamed V2 modules
from llap.commsV2 import LlapHub
from llap.devicesV2 import DualRelayBoard

def main():
    device_id = "RB"
    if len(sys.argv) >= 2:
        device_id = sys.argv[1]

    hold_secs = 0.5
    if len(sys.argv) >= 3:
        hold_secs = float(sys.argv[2])

    hub = LlapHub()
    rb = DualRelayBoard(hub, device_id)
    hub.start()

    # Give threads a moment to spin up
    sleep(0.2)
    try:

        print("=== LLAP Smoke Test ===")
        print("Device ID:", device_id)

        # Optional info calls (comment out if you just want relay control fast)
        try:
            print("HELLO:", rb.hello())
        except Exception as e:
            print("HELLO failed:", e)

        # Status read
        try:
            a0 = rb.relay_a.status
            b0 = rb.relay_b.status
            print("Initial: RelayA=%s RelayB=%s" % ("ON" if a0 else "OFF", "ON" if b0 else "OFF"))
        except Exception as e:
            print("Initial status failed:", e)
            return 2

        # Switch Relay A ON, confirm
        try:
            print("Setting Relay A ON")
            rb.relay_a.on()
            sleep(0.2)
            a1 = rb.relay_a.status
            print("After ON: RelayA=%s" % ("ON" if a1 else "OFF"))
        except Exception as e:
            print("Relay A ON failed:", e)
            return 2

        sleep(hold_secs)

        # Switch Relay A OFF, confirm
        try:
            print("Setting Relay A OFF")
            rb.relay_a.off()
            sleep(0.2)
            a2 = rb.relay_a.status
            print("After OFF: RelayA=%s" % ("ON" if a2 else "OFF"))
        except Exception as e:
            print("Relay A OFF failed:", e)
            return 2

        print("OK")
    finally:
        try:
            hub.stop()
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main())