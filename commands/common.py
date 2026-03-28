#!/usr/bin/python
# -*- coding: utf-8 -*-
#common.py

from __future__ import print_function

import os, sqlite3, time

#===========================
# Single place to flip later:
DEFAULT_DB = "/home/pi/heating.db"
#===========================

def get_db_path(argv=None):
    """
    Priority:
      1) --db /path
      2) env HEATING_DB
      3) DEFAULT_DB
    """
    argv = argv or []
    if "--db" in argv:
        try:
            i = argv.index("--db")
            return argv[i + 1]
        except Exception:
            pass
    env = os.environ.get("HEATING_DB")
    if env:
        return env
    return DEFAULT_DB

def connect_db(db_path):
    con = sqlite3.connect(db_path, timeout=10, isolation_level=None)

    try:
        # WAL mode = concurrent readers + single writer
        con.execute("PRAGMA journal_mode=WAL")

        # faster than FULL but still safe for WAL
        con.execute("PRAGMA synchronous=NORMAL")

        # wait up to 5 seconds if database is locked
        con.execute("PRAGMA busy_timeout=5000")

    except Exception:
        pass

    return con

def now_local_hhmm():
    return time.strftime("%H:%M", time.localtime(time.time()))

def hhmm_to_minutes(hhmm):
    parts = (hhmm or "").split(":")
    if len(parts) != 2:
        raise ValueError("time must be HH:MM")
    h = int(parts[0]); m = int(parts[1])
    if h < 0 or h > 23 or m < 0 or m > 59:
        raise ValueError("time out of range")
    return h*60 + m

def normalize_days(days):
    # accept like "0123456" or "0,1,2" or "0 1 2"
    if days is None:
        raise ValueError("days required")
    # py2/py3 safe stringify (avoids ascii-encode surprises in py2)
    s = ("%s" % days).replace(",", "").replace(" ", "")
    if s == "":
        raise ValueError("days required")
    out = []
    for ch in s:
        if ch < "0" or ch > "6":
            raise ValueError("days must contain only digits 0..6")
        if ch not in out:
            out.append(ch)
    return "".join(out)

def days_intersect(a, b):
    sa = set(list(a or ""))
    sb = set(list(b or ""))
    return len(sa.intersection(sb)) > 0

def parse_bool(v):
    """
    Parse common truthy values used in settings.

    Accepts:
        True, "True", "true", "1", "yes", "on"

    Returns:
        bool
    """
    s = ("%s" % (v or "")).strip().lower()
    return s in ("1", "true", "yes", "on")

def bool_to_str(v):
    return "True" if bool(v) else "False"

#Commands return helpers
def fixed_width_center(width,s):
    # Ensure s is a string (Python 2.7 sometimes hands you None or numbers)
    s = '' if s is None else str(s)
    return s.center(width, ' ')

# SQL
def exec_write_with_retry(con, sql, args=None, retries=15, delay=0.2):
    """
    Execute SQL with retry on SQLITE_BUSY.

    Supports:
        exec_write_with_retry(con, "SQL", args)

    OR batched atomic execution:

        exec_write_with_retry(con, [
            ("SQL1", args1),
            ("SQL2", args2),
        ])
    """

    for attempt in range(retries):

        try:
            cur = con.cursor()
            cur.execute("BEGIN IMMEDIATE")

            # ---- batch mode ----
            if isinstance(sql, list):
                for stmt in sql:
                    if isinstance(stmt, (list, tuple)):
                        q = stmt[0]
                        a = stmt[1] if len(stmt) > 1 else None
                        if a is None:
                            cur.execute(q)
                        else:
                            cur.execute(q, a)
                    else:
                        cur.execute(stmt)

            # ---- single statement ----
            else:
                if args is None:
                    cur.execute(sql)
                else:
                    cur.execute(sql, args)

            con.commit()
            return cur

        except sqlite3.OperationalError as e:
            try: con.rollback()
            except Exception:
                pass

            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue

            raise

        except Exception:
            try: con.rollback()
            except Exception: pass
            raise

def exec_read_with_retry(con, sql, args=None, retries=15, delay=0.2):
    """
    Execute a READ query with retry on SQLITE_BUSY/SQLITE_LOCKED.

    Usage:
        cur = exec_read_with_retry(con, "SELECT ... WHERE x=?", (x,))
        rows = cur.fetchall()

    Notes:
      - We do NOT start a write transaction (no BEGIN IMMEDIATE).
      - On read-only contention, sqlite will raise OperationalError: database is locked/busy.
      - This helper retries those, and re-raises anything else.
    """
    last = None
    for _ in range(retries):
        try:
            cur = con.cursor()
            if args is None:
                cur.execute(sql)
            else:
                cur.execute(sql, args)
            return cur
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if ("locked" not in msg) and ("busy" not in msg):
                raise
            last = e
            time.sleep(delay)
    raise last