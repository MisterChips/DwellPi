#!/usr/bin/python
# -*- coding: utf-8 -*-
# system_state.py
#
# "Mirror engine" debug command:
# - Shows current switch/boost/away/schedule/entry
# - Computes effective target + hysteresis thresholds
# - Predicts desired CH ON/OFF stateful (see note below)

from __future__ import print_function
import sys
import time
from datetime import datetime

from commands.common import get_db_path, connect_db, exec_read_with_retry


def get_setting(con, key, default=None):
    cur = exec_read_with_retry(con, "SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def system_in_csv(csv, system):
    parts = [p.strip().upper() for p in (csv or "").split(",") if p.strip()]
    return system.upper() in parts


def get_latest_temp(con):
    # Pick the newest temperature_log row (by ts_epoch).
    cur = exec_read_with_retry(con, """
        SELECT ts_epoch, ts, source, value
        FROM temperature_log
        ORDER BY ts_epoch DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        return None, None, None, None
    return row  # (ts_epoch, ts, source, value)


def away_active(con, system, now_epoch):
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
    return bool(row and system_in_csv(row[0], system))


def get_active_schedule_set(con, system, now_epoch):
    """
    Mirrors engine priority (excluding AWAY which is handled separately):
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
    if row and system_in_csv(row[0], system):
        return row[1], "special_periods"
    return "NORMAL", "normal"


def get_active_entry(con, schedule_set_name, system, weekday_0_mon, hhmm):
    cur = exec_read_with_retry(con, """
        SELECT id, start_time, end_time, setpoint, warmup, COALESCE(note,'')
        FROM schedule_entries
        WHERE enabled=1
          AND schedule_set_name=?
          AND system=?
          AND instr(days, ?) > 0
          AND start_time <= ?
          AND ? < end_time
        ORDER BY start_time ASC
        LIMIT 1
    """, (schedule_set_name, system, str(weekday_0_mon), hhmm, hhmm))
    return cur.fetchone()


def clamp_float(s, default=None):
    try:
        return float(s)
    except Exception:
        return default


def predict_desired_stateful(temp_c, target_c, hysteresis_band, last_desired):
    if target_c is None:
        return "OFF", None, None

    band = float(hysteresis_band or 0.0)
    lower = target_c - (band / 2.0)
    upper = target_c + (band / 2.0)

    if temp_c <= lower:
        return "ON", lower, upper
    if temp_c >= upper:
        return "OFF", lower, upper

    # inside the band: hold last desired if known, else OFF (engine boot default)
    if last_desired in ("ON", "OFF"):
        return last_desired, lower, upper
    return "OFF", lower, upper


def main(argv):

    db = get_db_path(argv)
    con = connect_db(db)

    try:
        now_epoch = time.time()
        dt = datetime.fromtimestamp(now_epoch)
        hhmm = dt.strftime("%H:%M")
        weekday = dt.weekday()

        # --- Settings we care about ---
        ch_switch = (get_setting(con, "CH_SYSTEM_SWITCH", "timed") or "timed").strip().lower()
        default_sp = clamp_float(get_setting(con, "DEFAULT_SETPOINT", None), None)
        default_on_sp = clamp_float(get_setting(con, "DEFAULT_ON_SETPOINT", None), None)
        boost_sp = clamp_float(get_setting(con, "BOOST_SETPOINT", None), None)
        hyst = clamp_float(get_setting(con, "HYSTERISIS_BAND", "0"), 0.0)
        last = (get_setting(con, "CH_LAST_DESIRED", None) or "").strip().upper()
        if last not in ("ON", "OFF"):
            last = None

        relay_enable = get_setting(con, "RELAY_ENABLE", "False")

        # --- Latest temperature ---
        trow = get_latest_temp(con)
        if trow and trow[3] is not None:
            temp_c = clamp_float(trow[3], None)
            temp_ts = trow[1]
            temp_src = trow[2]
        else:
            temp_c, temp_ts, temp_src = None, None, None

        # --- Boost ---
        try:
            boost_finish = int(get_setting(con, "CH_BOOST_FINISH_EPOCH", "0") or "0")
        except Exception:
            boost_finish = 0
        boost_active = (boost_finish > 0 and now_epoch < boost_finish)

        # --- Away ---
        away = away_active(con, "CH", now_epoch)

        # --- Schedule set + active entry ---
        set_name, set_why = get_active_schedule_set(con, "CH", now_epoch)
        entry = None
        if not away:
            entry = get_active_entry(con, set_name, "CH", weekday, hhmm)

        # --- Mirror engine target selection ---
        target = None
        reason = ""

        if ch_switch == "off":
            target = None
            reason = "switch=off"

        elif away:
            target = None
            reason = "away(active)"

        elif ch_switch == "on":
            target = default_on_sp
            reason = "switch=on"

        else:
            # timed/once
            if not entry:
                target = None
                reason = "no_entry set=%s (%s)" % (set_name, set_why)
            else:
                entry_id, st, en, entry_sp, warmup, note = entry
                entry_sp_f = clamp_float(entry_sp, default_sp)
                target = entry_sp_f
                reason = "entry_id=%s set=%s %s-%s (%s)" % (entry_id, set_name, st, en, set_why)

        # Boost override (only if not away and not switch=off, and only if there is a target path)
        if boost_active and (not away) and (ch_switch != "off"):
            if boost_sp is not None:
                target = boost_sp
            elif default_on_sp is not None:
                target = default_on_sp
            else:
                target = None
            reason = "boost(until %s)" % time.strftime("%H:%M", time.localtime(boost_finish))

        if temp_c is None:
            desired, lower, upper = (None, None, None)
        else:
            desired, lower, upper = predict_desired_stateful(temp_c, target, hyst, last)

        # --- Output ---
        print("")
        print("=== Heating Engine Mirror ===")
        print("Time:", dt.strftime("%Y-%m-%d %H:%M:%S"))
        print("")

        if temp_c is None:
            print("Temp: (none yet)  (no readable temperature yet)")
        else:
            print("Temp: %.2fC  (from %s, source=%s)" % (temp_c, temp_ts, temp_src))

        print("CH_SYSTEM_SWITCH:", ch_switch)
        print("Away:", "ACTIVE" if away else "inactive")
        print("Boost:", "ACTIVE until %s" % time.strftime("%H:%M", time.localtime(boost_finish)) if boost_active else "inactive")
        print("Schedule set:", set_name, "(%s)" % set_why)

        if entry:
            entry_id, st, en, entry_sp, warmup, note = entry
            print("Active entry: id=%s %s-%s setpoint=%s warmup=%s note=%r" %
                  (entry_id, st, en, entry_sp, warmup, note))
        else:
            print("Active entry: none")

        print("")
        print("Defaults: DEFAULT_SETPOINT=%s DEFAULT_ON_SETPOINT=%s BOOST_SETPOINT=%s" %
              (default_sp, default_on_sp, boost_sp))
        print("Hysteresis band:", hyst)
        print("Relay enabled:", relay_enable)
        print("")

        if target is None:
            print("Target: (none) -> CH OF(no demand) reason=%s" % reason)
            if temp_c is None:
                print("Predicted CH desired: (unknown - no temperature yet)")
            else:
                print("Predicted CH desired: OFF")
        else:
            print("Target: %.2fC   reason=%s" % (target, reason))
            if lower is not None and upper is not None:
                print("Thresholds: [%.2f .. %.2f]" % (lower, upper))
            if desired is None:
                print("Predicted CH desired: (unknown - no temperature yet)")
            else:
                print("Predicted CH desired (stateful):", desired)

        print("")
        print("NOTE: 'stateful' means if temp is between thresholds, we hold CH_LAST_DESIRED.")
        print("      If CH_LAST_DESIRED is missing/invalid, we default to OFF in-band (engine boot default).")
        print("")
        return 0

    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))