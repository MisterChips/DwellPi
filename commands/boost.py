#!/usr/bin/python
# -*- coding: utf-8 -*-
# boost.py (Py2.7 compatible)

from __future__ import print_function

import sys
import time

from commands.common import get_db_path, connect_db, exec_write_with_retry


def validate_relaytype(rt):
    return (rt or "").upper() in ("CH", "HW")


def validate_boosthrs(h):
    return ("%s" % h) in ("0", "1", "2", "3")


def main(argv):
    if len(argv) < 3:
        print("Usage: python -m commands.boost CH|HW 0|1|2|3 [--db /path]")
        return 2

    relaytype = (argv[1] or "").upper()
    boosthrs = ("%s" % argv[2]).strip()

    if not (validate_relaytype(relaytype) and validate_boosthrs(boosthrs)):
        print("Not valid arguments, 2 required: HW/CH followed by 0,1,2,or 3")
        return 2

    db = get_db_path(argv)
    con = connect_db(db)

    finish_time_key = "%s_BOOST_FINISH_TIME" % relaytype
    finish_epoch_key = "%s_BOOST_FINISH_EPOCH" % relaytype

    if boosthrs == "0":
        finish_epoch = 0
        finish_time = "00:00"
        msg = "No boost set"
    else:
        finish_epoch = int(time.time() + (int(boosthrs) * 3600))
        finish_time = time.strftime("%H:%M", time.localtime(finish_epoch))
        msg = "%s boosted for %s hours (until %s)." % (relaytype, boosthrs, finish_time)

    try:
        exec_write_with_retry(con, [
            ("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
             (finish_time_key, finish_time)),
            ("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
             (finish_epoch_key, str(finish_epoch))),
        ])
        print(msg)
        return 0

    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))