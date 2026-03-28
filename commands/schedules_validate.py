#!/usr/bin/python
# -*- coding: utf-8 -*-
# schedules_validate.py

from __future__ import print_function

import sys
from datetime import datetime

from commands.common import get_db_path, connect_db, normalize_days, hhmm_to_minutes, days_intersect

FMT = "%H:%M"

def validate_time_str(t):
    try:
        datetime.strptime(t, FMT)
        return True
    except Exception:
        return False

def assert_no_overlap(con, schedule_set, system, days, start_time, end_time, exclude_id=None):
    """
    Raises ValueError if the proposed entry overlaps any enabled entry
    in the same schedule_set+system that shares at least one day.

    Assumes cross-midnight is forbidden (end > start).
    """
    schedule_set = (("%s" % schedule_set).strip().upper() or "NORMAL")
    system = (("%s" % system).strip().upper())
    start_time = ("%s" % start_time).strip()
    end_time = ("%s" % end_time).strip()

    days = normalize_days(days)

    if system not in ("CH", "HW"):
        raise ValueError("system must be CH or HW")

    if not validate_time_str(start_time) or not validate_time_str(end_time):
        raise ValueError("time must be HH:MM")

    # Forbid cross-midnight / same-day only
    if end_time <= start_time:
        raise ValueError("end must be after start (cross-midnight forbidden)")

    if exclude_id is not None:
        try:
            exclude_id = int(exclude_id)
        except Exception:
            raise ValueError("exclude_id must be an integer")

    s_new = hhmm_to_minutes(start_time)
    e_new = hhmm_to_minutes(end_time)

    cur = con.cursor()
    cur.execute("""
        SELECT id, days, start_time, end_time
        FROM schedule_entries
        WHERE enabled=1
          AND schedule_set_name=?
          AND system=?
        ORDER BY id
    """, (schedule_set, system))
    rows = cur.fetchall()

    for (eid, edays, estart, eend) in rows:

        estart = ("%s" % estart).strip()
        eend = ("%s" % eend).strip()

        if exclude_id is not None and int(eid) == exclude_id:
            continue

        try:
            edays_norm = normalize_days(edays)
        except Exception:
            raise ValueError("existing entry id=%s has invalid days=%r; fix DB" % (eid, edays))

        if not days_intersect(days, edays_norm):
            continue

        # Existing entries *should* also be same-day; if not, treat as unsafe overlap
        if not validate_time_str(estart) or not validate_time_str(eend) or eend <= estart:
            raise ValueError("existing entry id=%s has invalid/cross-midnight times; fix DB before adding more" % eid)

        s_old = hhmm_to_minutes(estart)
        e_old = hhmm_to_minutes(eend)

        # overlap test: [s_new,e_new) intersects [s_old,e_old)
        if not (e_new <= s_old or e_old <= s_new):
            raise ValueError("overlap with id=%s (%s %s-%s) on intersecting days" % (eid, edays_norm, estart, eend))

def main(argv):
    """
    Optional CLI: validate a proposed entry without inserting it.
    """
    if len(argv) < 2:
        print("Usage: python -m commands.schedules_validate CH|HW --set NORMAL --days 01234 --start 07:00 --end 08:30 [--exclude ID] [--db /path]")
        return 2

    system = argv[1].upper()
    if system not in ("CH", "HW"):
        print("ERROR: system must be CH or HW")
        return 2

    def get_arg(flag, default=None):
        if flag in argv:
            try:
                return argv[argv.index(flag) + 1]
            except Exception:
                return default
        return default

    schedule_set = get_arg("--set", "NORMAL")
    days = get_arg("--days")
    start_time = get_arg("--start")
    end_time = get_arg("--end")
    exclude_id = get_arg("--exclude", None)

    if not days or not start_time or not end_time:
        print("ERROR: --days, --start, --end required")
        return 2

    db = get_db_path(argv)
    con = connect_db(db)
    try:
        try:
            assert_no_overlap(con, schedule_set, system, days, start_time, end_time, exclude_id=exclude_id)
        except Exception as e:
            print("NOT_OK:", e)
            return 1
        print("OK: no overlaps")
        return 0
    finally:
        try:
            con.close()
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))