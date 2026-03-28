#!/usr/bin/python
# -*- coding: utf-8 -*-
#schedules_report.py

from __future__ import print_function
import sys
from commands.common import get_db_path, connect_db, exec_read_with_retry, fixed_width_center

def main(argv):
    if len(argv) < 2:
        print("Usage: python -m commands.schedules_report CH|HW [--set NORMAL] [--db /path]")
        return 2

    system = argv[1].upper()
    if system not in ("CH","HW"):
        print("ERROR: system must be CH or HW")
        return 2

    schedule_set = "NORMAL"
    if "--set" in argv:
        try:
            schedule_set = argv[argv.index("--set")+1]
        except Exception:
            pass

    schedule_set = schedule_set.upper()

    db = get_db_path(argv)
    con = connect_db(db)
    try:
        cur = exec_read_with_retry(con, """
            SELECT id, days, start_time, end_time,
                   COALESCE(CAST(setpoint AS TEXT), ''),
                   warmup, enabled,
                   COALESCE(note,'')
            FROM schedule_entries
            WHERE schedule_set_name=? AND system=?
            ORDER BY enabled DESC, days, start_time, end_time, id
        """, (schedule_set, system))
        rows = cur.fetchall()

        print("Schedule Set:", schedule_set, "System:", system)
        if system == "CH":
            print("id |  days   | start |  end  | setpoint | warmup | enabled | note")
        else:
            print("id |  days   | start |  end  | warmup | enabled | note")

        for r in rows:
            if system == "CH":
                (i, days, st, en, sp, warm, enabled, note) = r
                print("%s | %s | %s | %s | %s | %s | %s | %s" %
                      (fixed_width_center( 2, i), fixed_width_center (7, days), st, en, fixed_width_center (8, sp), fixed_width_center (6, warm), fixed_width_center (7, enabled), note))
            else:
                (i, days, st, en, sp, warm, enabled, note) = r
                print("%s | %s | %s | %s | %s | %s | %s" %
                      (fixed_width_center( 2, i), fixed_width_center (7, days), st, en, fixed_width_center (6, warm), fixed_width_center (7, enabled), note))
        return 0
    finally:
        try: con.close()
        except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))