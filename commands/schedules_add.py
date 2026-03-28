#!/usr/bin/python
# -*- coding: utf-8 -*-
# schedules_add.py (Py2.7 compatible)

from __future__ import print_function

import sys
from datetime import datetime

from commands.common import get_db_path, connect_db, exec_write_with_retry, normalize_days
from commands.schedules_validate import assert_no_overlap

FMT = "%H:%M"

def die(msg, code=2):
    print(msg)
    raise SystemExit(code)

def validate_time_str(t):
    try:
        datetime.strptime(t, FMT)
        return True
    except Exception:
        return False

def parse_boolish(v, default=False):
    if v is None:
        return default
    s = ("%s" % v).strip().lower()   # Py2-safe
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default

def ensure_schedule_set_exists(conn, set_name):
    # Race-safe create if missing
    exec_write_with_retry(
        conn,
        "INSERT OR IGNORE INTO schedule_sets (name, enabled, note) VALUES (?, 1, ?)",
        (set_name, "Created by schedules_add.py")
    )

def usage():
    print("Usage:")
    print("  python -m commands.schedules_add CH|HW START END DAYS [--set NORMAL] [--db /path/heating.db]")
    print("CH only:")
    print("  add --setpoint 20.0 [--warmup 0|1] [--enabled 0|1] [--note text]")
    raise SystemExit(2)

def main(argv):
    if len(argv) < 5:
        usage()

    system = argv[1].upper()
    start_time = argv[2]
    end_time = argv[3]
    days_in = argv[4]

    # defaults
    schedule_set = "NORMAL"
    db_path = get_db_path(argv)
    setpoint = None
    warmup = 0
    enabled = 1
    note = ""

    start_time = ("%s" % start_time).strip()
    end_time = ("%s" % end_time).strip()

    # parse flags
    i = 5
    while i < len(argv):
        a = argv[i]
        if a == "--set" and i + 1 < len(argv):
            schedule_set = argv[i + 1]
            i += 2
        elif a == "--db" and i + 1 < len(argv):
            db_path = argv[i + 1]
            i += 2
        elif a == "--setpoint" and i + 1 < len(argv):
            setpoint = argv[i + 1]
            i += 2
        elif a == "--warmup" and i + 1 < len(argv):
            warmup = 1 if parse_boolish(argv[i + 1], False) else 0
            i += 2
        elif a == "--enabled" and i + 1 < len(argv):
            enabled = 1 if parse_boolish(argv[i + 1], True) else 0
            i += 2
        elif a == "--note" and i + 1 < len(argv):
            note = argv[i + 1]
            i += 2
        else:
            die("Unknown arg: %r" % a)

    # clamp to 0/1 no matter what user passed
    warmup = 1 if int(warmup) else 0
    enabled = 1 if int(enabled) else 0
    note = ("%s" % note)

    if system not in ("CH", "HW"):
        die("system must be CH or HW")

    schedule_set = (("%s" % schedule_set).strip().upper() or "NORMAL")  # Py2-safe

    if not validate_time_str(start_time):
        die("Invalid START time, expected HH:MM")
    if not validate_time_str(end_time):
        die("Invalid END time, expected HH:MM")

    # Forbid cross-midnight / same-day only
    if end_time <= start_time:
        die("END must be after START (same-day entries only; cross-midnight forbidden)")

    try:
        days = normalize_days(days_in)
    except Exception as e:
        die("Invalid DAYS: %s" % e)

    if system == "CH":
        if setpoint is None:
            die("CH requires --setpoint")
        try:
            setpoint = float(setpoint)
        except Exception:
            die("Invalid setpoint (float)")
        if setpoint < 5.0 or setpoint > 24.0:
            die("Setpoint out of range (5.0..24.0)")
    else:
        setpoint = None
        warmup = 0

    conn = connect_db(db_path)
    try:
        ensure_schedule_set_exists(conn, schedule_set)

        # Overlap validation only matters if the entry is enabled
        if int(enabled) == 1:
            assert_no_overlap(conn, schedule_set, system, days, start_time, end_time, exclude_id=None)

        sql = """
            INSERT INTO schedule_entries
            (schedule_set_name, system, days, start_time, end_time, setpoint, warmup, enabled, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        args = (schedule_set, system, days, start_time, end_time, setpoint, int(warmup), int(enabled), note)

        exec_write_with_retry(conn, sql, args)

        print("[OK] Added schedule entry: set=%s system=%s days=%s %s-%s setpoint=%s warmup=%s enabled=%s" %
              (schedule_set, system, days, start_time, end_time, setpoint, warmup, enabled))
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))