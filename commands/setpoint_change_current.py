#!/usr/bin/python
# -*- coding: utf-8 -*-
# setpoint_change_current.py (Py2.7 compatible)
#
# Legacy-compatible behaviour:
# - If CH boost active -> change BOOST_SETPOINT
# - Else if CH switch == on -> change DEFAULT_ON_SETPOINT
# - Else if a schedule entry is active now -> change that schedule entry's setpoint
# - Else -> change DEFAULT_SETPOINT
#
# If AWAY is active -> CH is forced off; no "in-use" setpoint to change.

from __future__ import print_function

import sys
import time
from datetime import datetime

from commands.common import get_db_path, connect_db, exec_write_with_retry, exec_read_with_retry

def die(msg, code=2):
    print(msg)
    raise SystemExit(code)


def _get_setting(con, key, default=None):
    cur = exec_read_with_retry(con, "SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def _system_in_csv(systems_csv, wanted):
    parts = [p.strip().upper() for p in (systems_csv or "").split(",") if p.strip()]
    return wanted.upper() in parts


def _away_active(con, system, now_epoch):
    cur = exec_read_with_retry(con, """
        SELECT systems
        FROM away_periods
        WHERE enabled=1
          AND start_ts_epoch <= ?
          AND ? < end_ts_epoch
        ORDER BY start_ts_epoch DESC
        LIMIT 1
    """, (now_epoch, now_epoch))
    row = cur.fetchone()
    if not row:
        return False
    return _system_in_csv(row[0], system)


def _get_active_schedule_set(con, system, now_epoch):
    """
    Mirrors engine priority (excluding AWAY which we handle separately):
      - special_periods (if active)
      - NORMAL otherwise
    Returns (set_name, why)
    """
    cur = exec_read_with_retry(con, """
        SELECT systems, schedule_set_name
        FROM special_periods
        WHERE enabled=1
          AND start_ts_epoch <= ?
          AND ? < end_ts_epoch
        ORDER BY start_ts_epoch DESC
        LIMIT 1
    """, (now_epoch, now_epoch))
    row = cur.fetchone()
    if row and _system_in_csv(row[0], system):
        return row[1], "special_periods"
    return "NORMAL", "normal"


def _get_active_ch_entry(con, schedule_set_name, weekday_0_mon, hhmm):
    cur = exec_read_with_retry(con, """
        SELECT id, start_time, end_time, setpoint
        FROM schedule_entries
        WHERE enabled=1
          AND schedule_set_name=?
          AND system='CH'
          AND instr(days, ?) > 0
          AND start_time <= ?
          AND ? < end_time
        ORDER BY start_time ASC
        LIMIT 2
    """, (schedule_set_name, str(weekday_0_mon), hhmm, hhmm))
    rows = cur.fetchall()
    if len(rows) > 1:
        print("WARNING: overlapping schedule entries detected (fix schedules)")
    if not rows:
        return None
    # With overlap validation, should never be >1
    return rows[0]  # (id, start, end, setpoint)


def main(argv):
    if len(argv) < 2:
        print("Usage: python -m commands.setpoint_change_current 20.0 [--db /path]")
        return 2

    # parse setpoint
    try:
        sp = float(("%s" % argv[1]).strip())
    except Exception:
        die("ERROR: invalid setpoint (float)")

    # enforce your schema range (matches db_init SETTINGS_SCHEMA)
    if sp < 5.0 or sp > 24.0:
        die("ERROR: setpoint out of range (5.0..24.0)")

    db = get_db_path(argv)
    con = connect_db(db)
    try:
        now_epoch = time.time()

        # If away is active, CH is forced off -> there is no in-use setpoint.
        if _away_active(con, "CH", now_epoch):
            print("AWAY_ACTIVE: CH is forced OFF; no in-use setpoint to change.")
            return 1

        # Determine boost + switch
        try:
            boost_finish = int(_get_setting(con, "CH_BOOST_FINISH_EPOCH", "0") or "0")
        except Exception:
            boost_finish = 0
        boost_active = (boost_finish > 0 and now_epoch < boost_finish)

        ch_switch = (_get_setting(con, "CH_SYSTEM_SWITCH", "timed") or "timed").strip().lower()

        # 1) Boost active -> BOOST_SETPOINT (legacy BOOST_AND_ON_SETPOINT)
        if boost_active:
            exec_write_with_retry(con,
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                                  ("BOOST_SETPOINT", str(sp))
                                  )
            print("OK: changed BOOST_SETPOINT to %.1f (boost active)" % sp)
            return 0

        # 2) Switch on -> DEFAULT_ON_SETPOINT (continuous)
        if ch_switch == "on":
            exec_write_with_retry(con,
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                                  ("DEFAULT_ON_SETPOINT", str(sp))
                                  )
            print("OK: changed DEFAULT_ON_SETPOINT to %.1f (switch=on)" % sp)
            return 0

        # 3) If a schedule entry is active now -> change that entry's setpoint
        dt = datetime.fromtimestamp(now_epoch)
        weekday = dt.weekday()  # 0=Mon
        hhmm = dt.strftime("%H:%M")

        set_name, why = _get_active_schedule_set(con, "CH", now_epoch)
        active = _get_active_ch_entry(con, set_name, weekday, hhmm)
        if active:
            entry_id, st, en, old_sp = active
            cur = exec_write_with_retry(con,
                "UPDATE schedule_entries SET setpoint=? WHERE id=? AND enabled=1",
                (sp, int(entry_id))
                )
            if getattr(cur, "rowcount", 0) != 1:
                print("ERROR: active entry disappeared/disabled before update (id=%s)" % entry_id)
                return 2
            print("OK: changed active schedule entry id=%s set=%s %s-%s to setpoint=%.1f (%s)" %
                  (entry_id, set_name, st, en, sp, why))
            return 0

        # 4) Otherwise -> DEFAULT_SETPOINT
        exec_write_with_retry(con,
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                              ("DEFAULT_SETPOINT", str(sp))
                              )
        print("OK: changed DEFAULT_SETPOINT to %.1f (no active entry)" % sp)
        return 0

    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))