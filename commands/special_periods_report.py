#!/usr/bin/python
# -*- coding: utf-8 -*-
# special_periods_report.py (Py2.7 compatible)

from __future__ import print_function
import sys
from commands.common import get_db_path, connect_db, exec_read_with_retry

def main(argv):
    enabled = None
    system = None
    set_name = None

    if "--enabled" in argv:
        try: enabled = int(argv[argv.index("--enabled")+1])
        except Exception: enabled = None

    if "--system" in argv:
        try: system = argv[argv.index("--system")+1].strip().upper()
        except Exception: system = None
        if system not in (None, "CH", "HW"):
            print("ERROR: --system must be CH or HW")
            return 2

    if "--set" in argv:
        try: set_name = argv[argv.index("--set")+1].strip().upper()
        except Exception: set_name = None

    db = get_db_path(argv)
    con = connect_db(db)
    try:
        where = []
        params = []

        if enabled in (0, 1):
            where.append("enabled=?")
            params.append(enabled)

        if set_name:
            where.append("schedule_set_name=?")
            params.append(set_name)

        if system:
            # systems stored like 'CH' or 'CH,HW'
            where.append("(','||systems||',') LIKE ?")
            params.append("%," + system + ",%")

        sql = """
            SELECT id, start_ts_text, end_ts_text, systems, schedule_set_name, enabled, COALESCE(note,'')
            FROM special_periods
        """
        if where:
            sql += " WHERE " + " AND ".join(where)

        sql += " ORDER BY enabled DESC, start_ts_epoch DESC, id DESC"

        cur = exec_read_with_retry(con, sql, tuple(params))
        rows = cur.fetchall()

        print("special_periods:")
        print("id | start | end | systems | set | enabled | note")
        for r in rows:
            print("%s | %s | %s | %s | %s | %s | %s" % r)
        return 0
    finally:
        try: con.close()
        except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))