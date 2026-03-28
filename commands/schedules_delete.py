#!/usr/bin/python
# -*- coding: utf-8 -*-
# schedules_delete.py (Py2.7 compatible)

from __future__ import print_function
import sys
from commands.common import get_db_path, connect_db, exec_write_with_retry

def main(argv):
    if len(argv) < 2:
        print("Usage: python -m commands.schedules_delete ID [--db /path]")
        return 2
    entry_id = int(argv[1])
    db = get_db_path(argv)
    con = connect_db(db)
    try:
        cur = exec_write_with_retry(con, "UPDATE schedule_entries SET enabled=0 WHERE id=?", (entry_id,))
        if cur.rowcount == 0:
            print("NOT_FOUND id=%s" % entry_id)
            return 1
        print("OK disabled id=%s" % entry_id)
        return 0
    except Exception as e:
        try: con.rollback()
        except Exception: pass
        print("ERROR:", e)
        return 2
    finally:
        try: con.close()
        except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))