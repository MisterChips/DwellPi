#!/usr/bin/python
# -*- coding: utf-8 -*-
# schedules_edit.py (Py2.7 compatible) - flag-based editor

from __future__ import print_function
import sys
from datetime import datetime

from commands.common import get_db_path, connect_db, normalize_days, exec_write_with_retry
from commands.schedules_validate import assert_no_overlap

FMT = "%H:%M"

def validate_time_str(t):
    try:
        datetime.strptime(t, FMT)
        return True
    except Exception:
        return False

def parse_boolish(v, default=None):
    if v is None:
        return default
    s = ("%s" % v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return 1
    if s in ("0", "false", "f", "no", "n", "off"):
        return 0
    return default

def main(argv):
    if len(argv) < 2:
        print("Usage: python -m commands.schedules_edit ID [--days 0123] [--start HH:MM] [--end HH:MM] "
              "[--setpoint 20.0] [--warmup 0/1] [--enabled 0/1] [--note text] [--db /path]")
        return 2

    try:
        entry_id = int(argv[1])
    except Exception:
        print("ERROR: ID must be integer")
        return 2

    def get_arg(flag, default=None):
        if flag in argv:
            try:
                return argv[argv.index(flag) + 1]
            except Exception:
                return default
        return default

    db = get_db_path(argv)
    con = connect_db(db)
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT schedule_set_name, system, days, start_time, end_time, setpoint, warmup, enabled, note
            FROM schedule_entries WHERE id=?
        """, (entry_id,))
        row = cur.fetchone()
        if row is None:
            print("ERROR: no such id:", entry_id)
            return 2

        (schedule_set, system, days, st, en, sp, warm, enabled, note) = row

        new_days = get_arg("--days", days)
        if new_days != days:
            new_days = normalize_days(new_days)

        new_st = get_arg("--start", st)
        new_en = get_arg("--end", en)

        if new_st != st and not validate_time_str(new_st):
            print("ERROR: invalid --start (HH:MM)")
            return 2
        if new_en != en and not validate_time_str(new_en):
            print("ERROR: invalid --end (HH:MM)")
            return 2
        if new_en <= new_st:
            print("ERROR: end must be after start (cross-midnight forbidden)")
            return 2

        new_warm = get_arg("--warmup", warm)
        try:
            new_warm = int(new_warm)
        except Exception:
            new_warm = int(parse_boolish(new_warm, 0) or 0)

        new_enabled = get_arg("--enabled", enabled)
        try:
            new_enabled = int(new_enabled)
        except Exception:
            new_enabled = int(parse_boolish(new_enabled, 1) or 1)

        new_warm = 1 if int(new_warm) else 0
        new_enabled = 1 if int(new_enabled) else 0

        new_note = get_arg("--note", note)

        new_sp = sp
        if system == "CH" and "--setpoint" in argv:
            try:
                new_sp = float(get_arg("--setpoint"))
            except Exception:
                print("ERROR: invalid --setpoint")
                return 2

            # ✔ add the range check HERE
            if new_sp < 5.0 or new_sp > 24.0:
                print("ERROR: setpoint out of range (5.0..24.0)")
                return 2

        # HW never uses setpoint or warmup
        if system != "CH":
            new_sp = None
            new_warm = 0

        if system == "CH":
            try:
                sp_check = float(new_sp)
            except Exception:
                print("ERROR: invalid existing setpoint in DB")
                return 2
            if sp_check < 5.0 or sp_check > 24.0:
                print("ERROR: setpoint out of range (5.0..24.0)")
                return 2

        # overlap validation only if enabled
        if int(new_enabled) == 1:
            assert_no_overlap(con, schedule_set, system, new_days, new_st, new_en, exclude_id=entry_id)

        exec_write_with_retry(con, """
                             UPDATE schedule_entries
                             SET days=?,start_time=?,end_time=?,setpoint=?,warmup=?,enabled=?,note=?
                             WHERE id = ?
                             """,
                              (new_days, new_st, new_en, new_sp, int(new_warm), int(new_enabled), new_note, entry_id))

        print("OK edited id=%s" % entry_id)
        return 0

    except Exception as e:
        try:
            con.rollback()
        except Exception:
            pass
        print("ERROR:", e)
        return 2
    finally:
        try:
            con.close()
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))