#!/usr/bin/python
# -*- coding: utf-8 -*-
# settings_get.py

from __future__ import print_function
import sys
from commands.common import get_db_path, connect_db, exec_read_with_retry

def main(argv):
    db = get_db_path(argv)

    key = None
    if len(argv) >= 3 and argv[1] == "--key":
        key = argv[2]
    elif len(argv) >= 2 and not argv[1].startswith("--"):
        key = argv[1]

    if not key:
        print("Usage: python -m commands.settings_get KEY [--db /path]")
        print("   or: python -m commands.settings_get --key KEY [--db /path]")
        return 2

    con = connect_db(db)
    try:
        cur = exec_read_with_retry(con, "SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        if row is None:
            print("NOT_SET")
            return 1
        print(row[0])
        return 0
    finally:
        try:
            con.close()
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))