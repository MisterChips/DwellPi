#!/usr/bin/python
# -*- coding: utf-8 -*-
# relay_status_get.py (Py2.7 compatible)

from __future__ import print_function

import sys
from time import sleep

from commands.common import get_db_path, connect_db, exec_read_with_retry
from llap.commsV2 import LlapHub
from llap.devicesV2 import DualRelayBoard


def get_setting(cur, con, key, default=None):
    cur = exec_read_with_retry(con,"SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        return default
    return row[0]


def main(argv):

    db = get_db_path(argv)
    con = connect_db(db)

    try:
        cur = con.cursor()


        device_id = get_setting(cur, con, "RELAY_BOARD_DEVICE_ID", "RB")
        relay_enable = get_setting(cur, con, "RELAY_ENABLE", "False")
        relay_enable = ("%s" % relay_enable).strip().lower() in ("true", "1", "yes", "on")
        if not relay_enable:
            print("Relay hardware disabled (RELAY_ENABLE=False)")
            return 1

    finally:
        try:
            con.close()
        except Exception:
            pass

    # allow CLI override
    if len(argv) >= 2:
        device_id = argv[1]

    try:
        hub = LlapHub()
        rb = DualRelayBoard(hub, device_id)

        hub.start()
        sleep(0.5)

        print("")
        #print(str(rb))
        print ("HELLO:", rb.hello())
        print("Relay A status:", rb.relay_a.status)
        print("Relay B status:", rb.relay_b.status)
        #print("RelayA:", "ON" if rb.relay_a.status else "OFF")
        #print("RelayB:", "ON" if rb.relay_b.status else "OFF")

        return 0

    except Exception as e:
        print("ERROR: could not communicate with relay board:", e)
        return 2

    finally:
        if hub:
            try: hub.stop()
            except: pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))