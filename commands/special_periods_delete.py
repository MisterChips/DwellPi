#!/usr/bin/python
# -*- coding: utf-8 -*-
# special_periods_delete.py (Py2.7 compatible)

from __future__ import print_function
import sys
from commands.common import get_db_path, connect_db, exec_write_with_retry

def main(argv):
    if len(argv) < 2:
        print("Usage: python -m commands.special_periods_delete ID [--db /path]")
        return 2

    try:
        pid = int(argv[1])
    except Exception:
        print("ERROR: ID must be integer")
        return 2

    db = get_db_path(argv)
    con = connect_db(db)
    try:
        cur = exec_write_with_retry(con,
                                    "UPDATE special_periods SET enabled=0 WHERE id=?",
                                    (pid,))
        if cur.rowcount == 0:
            print("NOT_FOUND id=%s" % pid)
            return 1

        print("OK disabled special_period id=%s" % pid)
        return 0

    except Exception as e:
        print("ERROR:", e)
        return 2
    finally:
        try: con.close()
        except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))