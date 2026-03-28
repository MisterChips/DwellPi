#!/usr/bin/python
# -*- coding: utf-8 -*-
# engine_state_report.py (Py2.7 compatible)

from __future__ import print_function
import sys, time

from commands.common import get_db_path, connect_db

def get_setting(cur, key, default=None):
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    if row is None:
        return default
    return row[0]

def get_last_temperature(cur):
    cur.execute("""
        SELECT temperature_c, recorded_at_text
        FROM temperature_log
        ORDER BY id DESC
        LIMIT 1
    """)
    return cur.fetchone()

def get_active_special(cur, now_epoch, system):
    cur.execute("""
        SELECT id, schedule_set_name, systems
        FROM special_periods
        WHERE enabled=1
          AND start_ts_epoch <= ?
          AND end_ts_epoch > ?
        ORDER BY start_ts_epoch DESC
    """, (now_epoch, now_epoch))

    rows = cur.fetchall()

    for r in rows:
        systems = (r[2] or "").upper()
        parts = [x.strip() for x in systems.split(",") if x.strip()]
        if system in parts:
            return r

    return None

def get_boost_status(cur, system, now_epoch):
    key = "%s_BOOST_FINISH_EPOCH" % system
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        return False, None

    try:
        finish = float(row[0])
    except Exception:
        return False, None

    if finish > now_epoch:
        return True, finish

    return False, finish

def main(argv):

    system = "CH"
    if len(argv) > 1:
        system = argv[1].upper()
        if system not in ("CH","HW"):
            print("ERROR: system must be CH or HW")
            return 2

    db = get_db_path(argv)
    con = connect_db(db)

    try:
        cur = con.cursor()

        now_epoch = time.time()
        now_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_epoch))

        print("=== Engine State Report ===")
        print("System:", system)
        print("Time:", now_text)
        print("")

        # temperature
        t = get_last_temperature(cur)
        if t:
            print("Temperature:", t[0], "C  (recorded", t[1] + ")")
        else:
            print("Temperature: NONE")

        print("")

        # system switch
        switch = get_setting(cur, "%s_SYSTEM_SWITCH" % system, "timed")
        print("System switch:", switch)

        # default setpoints
        default_sp = get_setting(cur, "DEFAULT_SETPOINT", "10")
        default_on_sp = get_setting(cur, "DEFAULT_ON_SETPOINT", "20")

        print("Default setpoint:", default_sp)
        print("Default ON setpoint:", default_on_sp)

        print("")

        # special periods
        sp = get_active_special(cur, now_epoch, system)
        if sp:
            print("Special period active: id=%s set=%s systems=%s" % sp)
        else:
            print("Special period active: none")

        # boost
        boost_active, finish = get_boost_status(cur, system, now_epoch)
        if boost_active:
            print("Boost active: YES until", time.strftime("%H:%M", time.localtime(finish)))
        else:
            print("Boost active: NO")

        print("")

        # schedule sets
        cur.execute("""
            SELECT name, enabled
            FROM schedule_sets
            ORDER BY name
        """)

        print("Schedule sets:")
        for name, enabled in cur.fetchall():
            print(" ", name, "(enabled=%s)" % enabled)

        print("")
        print("Report complete")

        return 0

    finally:
        try: con.close()
        except Exception: pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))