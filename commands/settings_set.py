#!/usr/bin/python
# -*- coding: utf-8 -*-
# settings_set.py

from __future__ import print_function
import sys
from commands.common import get_db_path, connect_db, exec_write_with_retry

try:
    from db_init import SETTINGS_SCHEMA, validate_setting
except Exception:
    SETTINGS_SCHEMA = {}
    def validate_setting(key, value, schema):
        return True

def main(argv):
    if len(argv) < 3:
        print("Usage: python -m commands.settings_set KEY VALUE [--db /path]")
        return 2

    key = ("%s" % argv[1]).strip()
    val = ("%s" % argv[2]).strip()
    db = get_db_path(argv)

    # validate if we know the schema
    if key in SETTINGS_SCHEMA:
        schema = SETTINGS_SCHEMA[key]
        if not validate_setting(key, val, schema):
            print("ERROR: invalid value for %s (got %r)" % (key, val))
            return 2

    con = connect_db(db)
    try:
        exec_write_with_retry(con, "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, val))
        print("OK %s=%s" % (key, val))
        return 0
    except Exception as e:
        print("ERROR:", e)
        return 2
    finally:
        try: con.close()
        except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))