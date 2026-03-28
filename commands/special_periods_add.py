#!/usr/bin/python
# -*- coding: utf-8 -*-
# special_periods_add.py (Py2.7 compatible)

from __future__ import print_function
import sys, time

from commands.common import get_db_path, connect_db, exec_write_with_retry

def parse_epoch(s):
    # accept epoch seconds or "YYYY-MM-DD HH:MM"
    s = (s or "").strip()
    if s.isdigit():
        return float(int(s))
    try:
        t = time.strptime(s, "%Y-%m-%d %H:%M")
        return float(time.mktime(t))
    except Exception:
        raise ValueError("time must be epoch seconds or 'YYYY-MM-DD HH:MM'")

def ts_text(epoch):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))

def normalize_set_name(s):
    s = ("%s" % (s or "")).strip().upper()
    if not s:
        raise ValueError("SET_NAME required")
    return s

def normalize_systems(s):
    # allow CH, HW, or CH,HW (any order), no duplicates
    raw = ("%s" % (s or "")).strip().upper()
    if not raw:
        raise ValueError("SYSTEMS required")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out = []
    for p in parts:
        if p not in ("CH", "HW"):
            raise ValueError("SYSTEMS must be CH, HW, or CH,HW")
        if p not in out:
            out.append(p)
    if not out:
        raise ValueError("SYSTEMS must be CH, HW, or CH,HW")
    return ",".join(out)

def systems_intersect(a, b):
    sa = set([x.strip().upper() for x in (a or "").split(",") if x.strip()])
    sb = set([x.strip().upper() for x in (b or "").split(",") if x.strip()])
    return len(sa.intersection(sb)) > 0

def assert_no_special_overlap(con, start_epoch, end_epoch, systems, exclude_id=None):
    """
    Disallow overlaps against enabled special_periods that share any system.
    Overlap test is [start,end) intersects [row_start,row_end).
    """
    cur = con.cursor()
    cur.execute("""
        SELECT id, start_ts_epoch, end_ts_epoch, systems, schedule_set_name
        FROM special_periods
        WHERE enabled=1
    """)
    rows = cur.fetchall()

    for (rid, rstart, rend, rsystems, rset) in rows:
        if exclude_id is not None and int(rid) == int(exclude_id):
            continue

        if not systems_intersect(systems, rsystems):
            continue

        if not (end_epoch <= float(rstart) or float(rend) <= start_epoch):
            raise ValueError("overlap with special_period id=%s set=%s systems=%s" % (rid, rset, rsystems))

def main(argv):
    if len(argv) < 5:
        print("Usage: python -m commands.special_periods_add START END SET_NAME SYSTEMS [--note text] [--db /path]")
        print("  START/END: epoch or 'YYYY-MM-DD HH:MM'")
        print("  SET_NAME: e.g. CHRISTMAS")
        print("  SYSTEMS: CH | HW | CH,HW")
        return 2

    try:
        start = parse_epoch(argv[1])
        end = parse_epoch(argv[2])
        set_name = normalize_set_name(argv[3])
        systems = normalize_systems(argv[4])
    except Exception as e:
        print("ERROR:", e)
        return 2

    note = ""
    if "--note" in argv:
        try:
            note = argv[argv.index("--note") + 1]
        except Exception:
            note = ""
    note = ("%s" % note)  # Py2-safe

    if end <= start:
        print("ERROR: END must be after START")
        return 2

    db = get_db_path(argv)
    con = connect_db(db)
    try:
        assert_no_special_overlap(con, start, end, systems, exclude_id=None)

        exec_write_with_retry(
            con,
            "INSERT OR IGNORE INTO schedule_sets (name, enabled, note) VALUES (?,?,?)",
            (set_name, 1, "")
        )

        exec_write_with_retry(con, """
            INSERT INTO special_periods
            (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, schedule_set_name, enabled, note)
            VALUES (?,?,?,?,?,?,?,?)
        """, (start, ts_text(start), end, ts_text(end), systems, set_name, 1, note))

        print("OK added special period")
        return 0

    except Exception as e:
        print("ERROR:", e)
        return 2
    finally:
        try: con.close()
        except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))