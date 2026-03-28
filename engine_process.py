#!/usr/bin/python
# -*- coding: utf-8 -*-
# engine_process.py

from __future__ import print_function

import time
import sqlite3

from message_schema import Message
from commands.common import parse_bool
from settings_client import SettingsClient


class EngineProcess(SettingsClient):
    def __init__(self, engine_queue, engine_rpc_queue, ui_queue, web_queue, db_queue, ctrl_queue, relay_queue, mode, db_path, shutdown_event):
        SettingsClient.__init__(self, ctrl_queue, shutdown_event, name="Engine")

        self.engine_queue = engine_queue
        self.engine_rpc_queue = engine_rpc_queue
        self.ui_queue = ui_queue
        self.web_queue = web_queue
        self.db_queue = db_queue
        self.ctrl_queue = ctrl_queue
        self.mode = mode
        self.shutdown_event = shutdown_event

        self.relay_queue = relay_queue

        self.db_path = db_path
        self.db_con = None

        # relay safety / mapping
        self.relay_enable = False
        self.ch_relay_letter = "A"
        self.hw_relay_letter = "B"

        # defaults (will be overwritten by snapshot/push)
        self.engine_interval = 2.0
        self.current_temp = None

        self.ch_system_switch = "timed"  # timed/on/off/once
        self.hw_system_switch = "timed"  # timed/on/off/once
        self.ch_advance = False
        self.hw_advance = False

        self.default_setpoint = 10.0
        self.default_on_setpoint = 20.0
        self.hysteresis_band = 0.0

        # relay reply checking
        self._last_relay_sync = 0.0
        self._pending_sync_request_id = None

        # short cycling protection
        self.ch_last_change_epoch = None
        self.ch_last_on_epoch = None
        self.ch_last_off_epoch = None
        self.ch_min_on_seconds = 120
        self.ch_min_off_seconds = 120

        # CH/HW decision state
        self.ch_desired = None  # "ON"/"OFF"
        self.hw_desired = None  # "ON"/"OFF"

    def _apply_setting_changed(self, key, value):
        try:
            if key == "ENGINE_INTERVAL":
                self.engine_interval = float(value)
            elif key == "CH_SYSTEM_SWITCH":
                self.ch_system_switch = str(value)
            elif key == "HW_SYSTEM_SWITCH":
                self.hw_system_switch = str(value)
            elif key == "CH_ADVANCE":
                self.ch_advance = parse_bool(value)
            elif key == "HW_ADVANCE":
                self.hw_advance = parse_bool(value)
            elif key == "DEFAULT_SETPOINT":
                self.default_setpoint = float(value)
            elif key == "DEFAULT_ON_SETPOINT":
                self.default_on_setpoint = float(value)
            elif key == "HYSTERESIS_BAND":
                self.hysteresis_band = float(value)
            elif key == "RELAY_ENABLE":
                self.relay_enable = parse_bool(value)
            elif key == "CH_RELAY_LETTER":
                self.ch_relay_letter = str(value).upper()
            elif key == "HW_RELAY_LETTER":
                self.hw_relay_letter = str(value).upper()
            elif key == "CH_LAST_DESIRED":
                v = (str(value) or "").strip().upper()
                if v in ("ON", "OFF"):
                    self.ch_desired = v
            elif key == "HW_LAST_DESIRED":
                v = (str(value) or "").strip().upper()
                if v in ("ON", "OFF"):
                    self.hw_desired = v
            elif key == "CH_MIN_ON_SECONDS":
                self.ch_min_on_seconds = max(0, int(float(value)))
            elif key == "CH_MIN_OFF_SECONDS":
                self.ch_min_off_seconds = max(0, int(float(value)))
        except Exception:
            pass

    def _request_relay_status_startup(self, timeout=2.0):
        """
        One-shot actual relay read on startup.
        Seeds CH/HW desired state from real relay state if available.
        Also seeds CH last on/off timestamps for short-cycle protection.
        """
        import uuid

        while True:
            try:
                self.engine_rpc_queue.get_nowait()
            except Exception:
                break

        req_id = uuid.uuid4().hex

        try:
            self.relay_queue.put(Message("engine", "relay_status", {"request_id": req_id}))
        except Exception:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline and not self.shutdown_event.is_set():
            try:
                msg = self.engine_rpc_queue.get(timeout=0.2)
            except Exception:
                continue

            if getattr(msg, "type", None) != "relay_status_result":
                continue
            if getattr(msg, "request_id", None) != req_id:
                continue
            if getattr(msg, "target", None) not in (None, "engine"):
                continue

            p = msg.payload or {}

            ch_letter = self._get_relay_letter("CH")
            hw_letter = self._get_relay_letter("HW")

            ch_actual_state = self._relay_bool_to_state(p.get(ch_letter))
            hw_actual_state = self._relay_bool_to_state(p.get(hw_letter))

            if ch_actual_state is None or hw_actual_state is None:
                return False

            now_epoch = time.time()

            self.ch_desired = ch_actual_state
            self.hw_desired = hw_actual_state
            self.ch_last_change_epoch = now_epoch

            if ch_actual_state == "ON":
                self.ch_last_on_epoch = now_epoch
            else:
                self.ch_last_off_epoch = now_epoch

            print("[Engine] Startup relay status: RELAY%s=%s RELAY%s=%s -> CH/HW seeded from actual relay state" %
                  (ch_letter, ch_actual_state, hw_letter, hw_actual_state))

            try:
                self.db_queue.put(Message("engine", "set_setting", {
                    "key": "CH_LAST_DESIRED",
                    "value": ch_actual_state
                }))
            except Exception:
                pass

            try:
                self.db_queue.put(Message("engine", "set_setting", {
                    "key": "HW_LAST_DESIRED",
                    "value": hw_actual_state
                }))
            except Exception:
                pass

            return True

        return False

    def _drain_engine_queue(self):
        while True:
            try:
                m = self.engine_queue.get_nowait()
            except Exception:
                break
            if m.type == "TEMP_UPDATE":
                try:
                    self.current_temp = float((m.payload or {}).get("temperature"))
                except Exception:
                    pass

    def _db_connect(self):
        if self.db_con:
            return
        self.db_con = sqlite3.connect(self.db_path, timeout=2)
        self.db_con.execute("PRAGMA journal_mode=WAL")
        self.db_con.execute("PRAGMA synchronous=NORMAL")
        self.db_con.execute("PRAGMA foreign_keys=ON")

    def _get_setting_cached(self, key, default=None):
        v = self.settings.get(key)
        return v if v is not None else default

    def _get_relay_letter(self, system_name):
        system_name = str(system_name or "").strip().upper()

        if system_name == "CH":
            return str(self.settings.get("CH_RELAY_LETTER", "A") or "A").strip().upper()

        if system_name == "HW":
            return str(self.settings.get("HW_RELAY_LETTER", "B") or "B").strip().upper()

        return ""

    def _is_boost_active(self, system, now_epoch):
        key_epoch = "%s_BOOST_FINISH_EPOCH" % system
        key_time = "%s_BOOST_FINISH_TIME" % system

        try:
            finish_epoch = int(self._get_setting_cached(key_epoch, "0") or "0")
        except Exception:
            finish_epoch = 0

        if finish_epoch and now_epoch < finish_epoch:
            return True, finish_epoch

        if finish_epoch and now_epoch >= finish_epoch:
            try:
                self.db_queue.put(Message("engine", "set_setting", {"key": key_epoch, "value": "0"}))
                self.db_queue.put(Message("engine", "set_setting", {"key": key_time, "value": "00:00"}))
            except Exception:
                pass

        return False, finish_epoch

    def _request_cleanup_overrides(self):
        now = time.time()
        last = getattr(self, "_last_cleanup_req", 0.0)
        if now - last < 60.0:
            return
        self._last_cleanup_req = now
        try:
            self.db_queue.put(Message("engine", "cleanup_expired_overrides", {"now_epoch": now}))
        except Exception:
            pass

    def _system_in_csv(self, systems_csv, wanted):
        parts = [p.strip().upper() for p in (systems_csv or "").split(",") if p.strip()]
        return wanted.upper() in parts

    def _time_text_to_today_epoch(self, hhmm_text, now_epoch):
        from datetime import datetime

        dt_now = datetime.fromtimestamp(now_epoch)

        hh = int(str(hhmm_text).split(":")[0])
        mm = int(str(hhmm_text).split(":")[1])

        dt_value = dt_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return time.mktime(dt_value.timetuple())

    def _time_text_to_epoch_for_day(self, hhmm_text, day_epoch):
        from datetime import datetime

        dt_day = datetime.fromtimestamp(day_epoch)

        hh = int(str(hhmm_text).split(":")[0])
        mm = int(str(hhmm_text).split(":")[1])

        dt_value = dt_day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return time.mktime(dt_value.timetuple())

    def _entry_window_for_day(self, entry, day_epoch):
        start_epoch = self._time_text_to_epoch_for_day(entry["start_time"], day_epoch)
        end_epoch = self._time_text_to_epoch_for_day(entry["end_time"], day_epoch)

        if end_epoch <= start_epoch:
            end_epoch += 86400.0

        return start_epoch, end_epoch

    def _is_entry_active_now_for_day(self, entry, now_epoch, day_epoch):
        try:
            start_epoch, end_epoch = self._entry_window_for_day(entry, day_epoch)
            return start_epoch <= now_epoch < end_epoch
        except Exception:
            return False

    def _entry_window_for_today(self, entry, now_epoch):
        start_epoch = self._time_text_to_today_epoch(entry["start_time"], now_epoch)
        end_epoch = self._time_text_to_today_epoch(entry["end_time"], now_epoch)

        if end_epoch <= start_epoch:
            end_epoch += 86400.0

        return start_epoch, end_epoch

    def _is_entry_active_now(self, entry, now_epoch, weekday_0_mon, days_str):
        today_epoch = now_epoch
        yesterday_epoch = now_epoch - 86400.0

        today_wd = weekday_0_mon
        yesterday_wd = (weekday_0_mon - 1) % 7

        try:
            start_text = str(entry["start_time"])
            end_text = str(entry["end_time"])
            overnight = (end_text <= start_text)
        except Exception:
            overnight = False

        if str(today_wd) in days_str:
            if self._is_entry_active_now_for_day(entry, now_epoch, today_epoch):
                return True

        if overnight and str(yesterday_wd) in days_str:
            if self._is_entry_active_now_for_day(entry, now_epoch, yesterday_epoch):
                return True

        return False

    def _is_holiday_active(self, system, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT systems
                    FROM away_periods
                    WHERE enabled = 1
                      AND start_ts_epoch <= ?
                      AND ? < end_ts_epoch
                    ORDER BY start_ts_epoch DESC LIMIT 1
                    """, (now_epoch, now_epoch))
        row = cur.fetchone()
        if row and self._system_in_csv(row[0], system):
            return True
        return False

    def _get_active_special_set(self, system, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT systems, schedule_set_name
                    FROM special_periods
                    WHERE enabled = 1
                      AND start_ts_epoch <= ?
                      AND ? < end_ts_epoch
                    ORDER BY start_ts_epoch DESC LIMIT 1
                    """, (now_epoch, now_epoch))
        row = cur.fetchone()
        if row and self._system_in_csv(row[0], system):
            return row[1]
        return None

    def _get_active_entry(self, schedule_set_name, system, weekday_0_mon, hhmm, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT id, start_time, end_time, setpoint, warmup, note, days
                    FROM schedule_entries
                    WHERE enabled = 1
                      AND schedule_set_name = ?
                      AND system = ?
                    ORDER BY start_time ASC
                    """, (schedule_set_name, system))
        rows = cur.fetchall()

        matches = []

        for r in rows:
            entry = {
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "setpoint": r[3],
                "warmup": r[4],
                "note": r[5],
                "days": r[6],
            }

            days_str = str(entry["days"] or "")

            today_epoch = now_epoch
            yesterday_epoch = now_epoch - 86400.0
            today_wd = weekday_0_mon
            yesterday_wd = (weekday_0_mon - 1) % 7

            try:
                overnight = str(entry["end_time"]) <= str(entry["start_time"])
            except Exception:
                overnight = False

            matched = False

            if str(today_wd) in days_str:
                try:
                    start_epoch, end_epoch = self._entry_window_for_day(entry, today_epoch)
                    if start_epoch <= now_epoch < end_epoch:
                        entry["window_start_epoch"] = start_epoch
                        entry["window_end_epoch"] = end_epoch
                        matches.append(entry)
                        matched = True
                except Exception:
                    pass

            if (not matched) and overnight and str(yesterday_wd) in days_str:
                try:
                    start_epoch, end_epoch = self._entry_window_for_day(entry, yesterday_epoch)
                    if start_epoch <= now_epoch < end_epoch:
                        entry["window_start_epoch"] = start_epoch
                        entry["window_end_epoch"] = end_epoch
                        matches.append(entry)
                except Exception:
                    pass
        if not matches:
            return None

        if len(matches) > 1:
            print("[Engine] WARNING: overlapping entries detected for %s/%s at %s" %
                  (schedule_set_name, system, hhmm))

        return matches[0]

    def _get_active_entry_with_special_fallback(self, system, weekday_0_mon, hhmm, now_epoch, special_set_name=None):
        if special_set_name:
            entry = self._get_active_entry(special_set_name, system, weekday_0_mon, hhmm, now_epoch)
            if entry:
                entry["source_set"] = special_set_name
                return entry

        entry = self._get_active_entry("NORMAL", system, weekday_0_mon, hhmm, now_epoch)
        if entry:
            entry["source_set"] = "NORMAL"
            return entry

        return None

    def _get_active_hw_entry_with_special_fallback(self, weekday_0_mon, hhmm, now_epoch, special_set_name=None):
        if special_set_name:
            entry = self._get_active_hw_entry(special_set_name, weekday_0_mon, hhmm, now_epoch)
            if entry:
                entry["source_set"] = special_set_name
                return entry

        entry = self._get_active_hw_entry("NORMAL", weekday_0_mon, hhmm, now_epoch)
        if entry:
            entry["source_set"] = "NORMAL"
            return entry

        return None

    def _get_active_hw_entry(self, schedule_set_name, weekday_0_mon, hhmm, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT id, start_time, end_time, note, days
                    FROM schedule_entries
                    WHERE enabled = 1
                      AND schedule_set_name = ?
                      AND system = 'HW'
                    ORDER BY start_time ASC
                    """, (schedule_set_name,))
        rows = cur.fetchall()

        matches = []

        for r in rows:
            entry = {
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "note": r[3],
                "days": r[4],
            }

            days_str = str(entry["days"] or "")

            today_epoch = now_epoch
            yesterday_epoch = now_epoch - 86400.0
            today_wd = weekday_0_mon
            yesterday_wd = (weekday_0_mon - 1) % 7

            try:
                overnight = str(entry["end_time"]) <= str(entry["start_time"])
            except Exception:
                overnight = False

            matched = False

            if str(today_wd) in days_str:
                try:
                    start_epoch, end_epoch = self._entry_window_for_day(entry, today_epoch)
                    if start_epoch <= now_epoch < end_epoch:
                        entry["window_start_epoch"] = start_epoch
                        entry["window_end_epoch"] = end_epoch
                        matches.append(entry)
                        matched = True
                except Exception:
                    pass

            if (not matched) and overnight and str(yesterday_wd) in days_str:
                try:
                    start_epoch, end_epoch = self._entry_window_for_day(entry, yesterday_epoch)
                    if start_epoch <= now_epoch < end_epoch:
                        entry["window_start_epoch"] = start_epoch
                        entry["window_end_epoch"] = end_epoch
                        matches.append(entry)
                except Exception:
                    pass

        if not matches:
            return None

        if len(matches) > 1:
            print("[Engine] WARNING: overlapping HW entries detected for %s at %s" %
                  (schedule_set_name, hhmm))

        return matches[0]

    def _get_next_entry_for_set(self, schedule_set_name, system, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT id, start_time, end_time, setpoint, warmup, note, days
                    FROM schedule_entries
                    WHERE enabled = 1
                      AND schedule_set_name = ?
                      AND system = ?
                    ORDER BY start_time ASC
                    """, (schedule_set_name, system))
        rows = cur.fetchall()

        from datetime import datetime, timedelta

        dt_now = datetime.fromtimestamp(now_epoch)
        best_entry = None
        best_start_epoch = None

        for r in rows:
            entry = {
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "setpoint": r[3],
                "warmup": r[4],
                "note": r[5],
                "days": r[6],
                "source_set": schedule_set_name,
            }

            days_str = str(entry["days"] or "")

            for day_offset in range(0, 8):
                dt_day = dt_now + timedelta(days=day_offset)
                wd = dt_day.weekday()

                if str(wd) not in days_str:
                    continue

                try:
                    day_epoch = time.mktime(dt_day.timetuple())

                    start_epoch = self._time_text_to_epoch_for_day(
                        entry["start_time"],
                        day_epoch
                    )
                except Exception:
                    continue

                if start_epoch <= now_epoch:
                    continue

                if best_start_epoch is None or start_epoch < best_start_epoch:
                    best_start_epoch = start_epoch
                    best_entry = dict(entry)

        return best_entry, best_start_epoch

    def _choose_earlier_entry(self, a_entry, a_epoch, b_entry, b_epoch):
        if a_entry is None:
            return b_entry, b_epoch
        if b_entry is None:
            return a_entry, a_epoch

        if a_epoch < b_epoch:
            return a_entry, a_epoch
        if b_epoch < a_epoch:
            return b_entry, b_epoch

        # same start time: prefer special over NORMAL
        a_is_special = (a_entry.get("source_set") != "NORMAL")
        b_is_special = (b_entry.get("source_set") != "NORMAL")

        if a_is_special and not b_is_special:
            return a_entry, a_epoch
        if b_is_special and not a_is_special:
            return b_entry, b_epoch

        return a_entry, a_epoch

    def _relay_allowed(self):
        if self.mode == "TEST":
            return True
        return bool(self.relay_enable)

    def _compute_ch_target(self, weekday, hhmm, now_epoch):
        sw = (self.ch_system_switch or "").lower()

        holiday_active = False
        special_set_name = None

        if sw != "off":
            holiday_active = self._is_holiday_active("CH", now_epoch)
            if not holiday_active:
                special_set_name = self._get_active_special_set("CH", now_epoch)

        if sw == "off":
            target = None
            reason = "switch=off"

        elif holiday_active:
            target = float(self.default_setpoint)
            reason = "holiday(fallback_default_setpoint)"

        elif sw == "on":
            target = float(self.default_on_setpoint)
            reason = "switch=on"


        elif sw == "once":
            active_set_name = special_set_name or "NORMAL"
            once_ctx = self._get_ch_once_context(active_set_name, weekday, now_epoch)

            has_once_entries = bool(once_ctx.get("first_entry")) and bool(once_ctx.get("last_entry"))

            if self.ch_advance:
                advance_until = None

                if not has_once_entries:
                    target = float(self.default_setpoint)
                    reason = "advance(no_once_entries fallback_default_setpoint)"
                    advance_until = None

                elif once_ctx["in_window"]:
                    target = float(self.default_on_setpoint)
                    advance_until = once_ctx["last_end_epoch"]
                    reason = "advance(skip_once_until %s set=%s)" % (
                        once_ctx["last_entry"]["end_time"],
                        once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                else:
                    target = float(once_ctx["first_setpoint"])
                    advance_until = once_ctx["first_start_epoch"]
                    reason = "advance(start_once_now %s-%s first_set=%s last_set=%s)" % (
                        once_ctx["first_entry"]["start_time"],
                        once_ctx["last_entry"]["end_time"],
                        once_ctx["first_entry"].get("source_set", active_set_name),
                        once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                if advance_until is None or now_epoch >= advance_until:
                    self._clear_advance("CH")
                    once_ctx = self._get_ch_once_context(active_set_name, weekday, now_epoch)
                    has_once_entries = bool(once_ctx.get("first_entry")) and bool(once_ctx.get("last_entry"))

                    if has_once_entries and once_ctx["in_window"]:
                        target = float(once_ctx["first_setpoint"])
                        reason = "once(set=%s %s-%s first_sp=%.1f)" % (
                            once_ctx["first_entry"].get("source_set", active_set_name),
                            once_ctx["first_entry"]["start_time"],
                            once_ctx["last_entry"]["end_time"],
                            once_ctx["first_setpoint"]
                        )
                    else:
                        target = float(self.default_setpoint)
                        reason = "once(outside_window fallback_default_setpoint)"

            else:
                if has_once_entries and once_ctx["in_window"]:
                    target = float(once_ctx["first_setpoint"])
                    reason = "once(set=%s %s-%s first_sp=%.1f)" % (
                        once_ctx["first_entry"].get("source_set", active_set_name),
                        once_ctx["first_entry"]["start_time"],
                        once_ctx["last_entry"]["end_time"],
                        once_ctx["first_setpoint"]
                    )
                else:
                    target = float(self.default_setpoint)
                    reason = "once(outside_window fallback_default_setpoint)"

        elif sw == "timed":
            active_set_name = special_set_name or "NORMAL"
            ctx = self._get_ch_timed_context(active_set_name, weekday, hhmm, now_epoch)
            entry = ctx["current_entry"]

            if self.ch_advance:
                advance_until = ctx["advance_until_epoch"]

                if advance_until is None or now_epoch >= advance_until:
                    self._clear_advance("CH")
                    ctx = self._get_ch_timed_context(active_set_name, weekday, hhmm, now_epoch)
                    entry = ctx["current_entry"]
                else:
                    target = ctx["advanced_target"]
                    if entry:
                        reason = "advance(skip_current_until %s set=%s)" % (
                            entry["end_time"],
                            entry.get("source_set", active_set_name)
                        )
                    else:
                        next_entry = ctx["next_entry"]
                        if next_entry:
                            reason = "advance(until_next_start %s then %s-%s set=%s active_now)" % (
                                next_entry["start_time"],
                                next_entry["start_time"],
                                next_entry["end_time"],
                                next_entry.get("source_set", active_set_name)
                            )
                        else:
                            reason = "advance(no_next_entry)"
                    entry = "__ADVANCE_APPLIED__"

            if entry != "__ADVANCE_APPLIED__":
                if entry:
                    target = float(entry["setpoint"] or self.default_setpoint)
                    reason = "id=%s set=%s %s-%s" % (
                        entry["id"], entry.get("source_set", active_set_name), entry["start_time"], entry["end_time"]
                    )
                elif ctx.get("warmup_active"):
                    warmup_entry = ctx.get("warmup_entry")
                    target = float(ctx.get("warmup_target") or self.default_setpoint)
                    reason = "warmup(id=%s starts=%s set=%s)" % (
                        warmup_entry["id"],
                        warmup_entry["start_time"],
                        warmup_entry.get("source_set", active_set_name)
                    )
                else:
                    target = float(self.default_setpoint)
                    reason = "default_setpoint set=%s" % active_set_name

        else:
            target = None
            reason = "unsupported_switch=%s" % sw

        boost_active, boost_finish = self._is_boost_active("CH", now_epoch)
        if boost_active and not holiday_active and sw != "off":
            if self.ch_advance:
                self._clear_advance("CH")

            try:
                target = float(self.settings.get("BOOST_SETPOINT", self.default_on_setpoint))
            except Exception:
                target = float(self.default_on_setpoint)

            reason = "boost(until %s)" % time.strftime("%H:%M", time.localtime(boost_finish))

        return {
            "target": target,
            "reason": reason,
            "switch": sw,
            "holiday_active": holiday_active,
            "special_set_name": special_set_name,
        }

    def _compute_hw_target(self, weekday, hhmm, now_epoch):
        hw_sw = (self.hw_system_switch or "").lower()

        holiday_active = False
        special_set_name = None

        if hw_sw != "off":
            holiday_active = self._is_holiday_active("HW", now_epoch)
            if not holiday_active:
                special_set_name = self._get_active_special_set("HW", now_epoch)

        if hw_sw == "off":
            hw_target_on = False
            hw_reason = "switch=off"

        elif holiday_active:
            hw_target_on = False
            hw_reason = "holiday(active)"

        elif hw_sw == "on":
            hw_target_on = True
            hw_reason = "switch=on"


        elif hw_sw == "once":
            active_set_name = special_set_name or "NORMAL"
            hw_once_ctx = self._get_hw_once_context(active_set_name, weekday, now_epoch)

            has_once_entries = bool(hw_once_ctx.get("first_entry")) and bool(hw_once_ctx.get("last_entry"))

            if self.hw_advance:
                hw_advance_until = None
                if not has_once_entries:
                    hw_target_on = False
                    hw_reason = "advance(no_once_entries)"
                    hw_advance_until = None

                elif hw_once_ctx["in_window"]:
                    hw_target_on = False
                    hw_advance_until = hw_once_ctx["last_end_epoch"]
                    hw_reason = "advance(skip_once_until %s set=%s)" % (
                        hw_once_ctx["last_entry"]["end_time"],
                        hw_once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                else:
                    hw_target_on = True
                    hw_advance_until = hw_once_ctx["first_start_epoch"]
                    hw_reason = "advance(start_once_now %s-%s first_set=%s last_set=%s)" % (
                        hw_once_ctx["first_entry"]["start_time"],
                        hw_once_ctx["last_entry"]["end_time"],
                        hw_once_ctx["first_entry"].get("source_set", active_set_name),
                        hw_once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                if hw_advance_until is None or now_epoch >= hw_advance_until:
                    self._clear_advance("HW")
                    hw_once_ctx = self._get_hw_once_context(active_set_name, weekday, now_epoch)
                    has_once_entries = bool(hw_once_ctx.get("first_entry")) and bool(hw_once_ctx.get("last_entry"))

                    if has_once_entries and hw_once_ctx["in_window"]:
                        hw_target_on = True
                        hw_reason = "once(set=%s %s-%s)" % (
                            hw_once_ctx["first_entry"].get("source_set", active_set_name),
                            hw_once_ctx["first_entry"]["start_time"],
                            hw_once_ctx["last_entry"]["end_time"]
                        )
                    else:
                        hw_target_on = False
                        hw_reason = "once(outside_window)"

            else:
                if has_once_entries and hw_once_ctx["in_window"]:
                    hw_target_on = True
                    hw_reason = "once(set=%s %s-%s)" % (
                        hw_once_ctx["first_entry"].get("source_set", active_set_name),
                        hw_once_ctx["first_entry"]["start_time"],
                        hw_once_ctx["last_entry"]["end_time"]
                    )
                else:
                    hw_target_on = False
                    hw_reason = "once(outside_window)"

        elif hw_sw == "timed":
            active_set_name = special_set_name or "NORMAL"
            hw_ctx = self._get_hw_timed_context(active_set_name, weekday, hhmm, now_epoch)
            hw_entry = hw_ctx["current_entry"]

            if self.hw_advance:
                hw_advance_until = hw_ctx["advance_until_epoch"]

                if hw_advance_until is None or now_epoch >= hw_advance_until:
                    self._clear_advance("HW")
                    hw_ctx = self._get_hw_timed_context(active_set_name, weekday, hhmm, now_epoch)
                    hw_entry = hw_ctx["current_entry"]
                else:
                    hw_target_on = hw_ctx["advanced_on"]
                    if hw_entry:
                        hw_reason = "advance(skip_current_until %s set=%s)" % (
                            hw_entry["end_time"],
                            hw_entry.get("source_set", active_set_name)
                        )
                    else:
                        hw_next_entry = hw_ctx["next_entry"]
                        if hw_next_entry:
                            hw_reason = "advance(until_next_start %s then %s-%s set=%s active_now)" % (
                                hw_next_entry["start_time"],
                                hw_next_entry["start_time"],
                                hw_next_entry["end_time"],
                                hw_next_entry.get("source_set", active_set_name)
                            )
                        else:
                            hw_reason = "advance(no_next_entry)"
                    hw_entry = "__ADVANCE_APPLIED__"

            if hw_entry != "__ADVANCE_APPLIED__":
                if not hw_entry:
                    hw_target_on = False
                    hw_reason = "no_entry set=%s" % active_set_name
                else:
                    hw_target_on = True
                    hw_reason = "id=%s set=%s %s-%s" % (
                        hw_entry["id"], hw_entry.get("source_set", active_set_name), hw_entry["start_time"],
                        hw_entry["end_time"]
                    )

        else:
            hw_target_on = False
            hw_reason = "unsupported_switch=%s" % hw_sw

        hw_boost_active, hw_boost_finish = self._is_boost_active("HW", now_epoch)
        if hw_boost_active and not holiday_active and hw_sw != "off":
            if self.hw_advance:
                self._clear_advance("HW")
            hw_target_on = True
            hw_reason = "boost(until %s)" % time.strftime("%H:%M", time.localtime(hw_boost_finish))

        return {
            "target_on": hw_target_on,
            "reason": hw_reason,
            "switch": hw_sw,
            "holiday_active": holiday_active,
            "special_set_name": special_set_name,
        }

    def _decide_ch(self, temp_c, target_c):
        if target_c is None:
            return "OFF", None, None

        band = float(self.hysteresis_band or 0.0)
        lower = target_c - band
        upper = target_c

        if self.ch_desired is None:
            if temp_c <= lower:
                return "ON", lower, upper
            elif temp_c >= upper:
                return "OFF", lower, upper
            return "OFF", lower, upper

        if self.ch_desired == "ON":
            if temp_c >= upper:
                return "OFF", lower, upper
            return "ON", lower, upper

        if temp_c <= lower:
            return "ON", lower, upper
        return "OFF", lower, upper

    def _clear_advance(self, system):
        key = "%s_ADVANCE" % system
        try:
            self.settings[key] = "False"
            if system == "CH":
                self.ch_advance = False
            elif system == "HW":
                self.hw_advance = False

            self.db_queue.put(Message("engine", "set_setting", {
                "key": key,
                "value": "False"
            }))
            print("[Engine] %s advance auto-cleared" % system)
        except Exception:
            pass

    def _get_ch_timed_context(self, schedule_set_name, weekday_0_mon, hhmm, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        current_entry = self._get_active_entry_with_special_fallback(
            "CH", weekday_0_mon, hhmm, now_epoch, special_set_name
        )

        normal_next, normal_next_epoch = self._get_next_entry_for_set("NORMAL", "CH", now_epoch)

        if special_set_name:
            special_next, special_next_epoch = self._get_next_entry_for_set(special_set_name, "CH", now_epoch)
        else:
            special_next, special_next_epoch = None, None

        best_next, best_start_epoch = self._choose_earlier_entry(
            special_next, special_next_epoch,
            normal_next, normal_next_epoch
        )

        ctx = {
            "current_entry": current_entry,
            "next_entry": best_next,
            "current_target": None,
            "advanced_target": None,
            "advance_until_epoch": None,
            "warmup_active": False,
            "warmup_entry": None,
            "warmup_target": None,
            "warmup_start_epoch": None,
        }

        if current_entry:
            ctx["current_target"] = float(current_entry["setpoint"] or self.default_setpoint)

            try:
                end_epoch = current_entry.get("window_end_epoch")
            except Exception:
                end_epoch = None

            ctx["advanced_target"] = None
            ctx["advance_until_epoch"] = end_epoch

        else:
            if best_next:
                ctx["advanced_target"] = float(best_next["setpoint"] or self.default_setpoint)
                ctx["advance_until_epoch"] = best_start_epoch

                try:
                    warmup_enabled = parse_bool(best_next.get("warmup"))
                except Exception:
                    warmup_enabled = False

                if warmup_enabled and self.current_temp is not None:
                    try:
                        entry_setpoint = float(best_next.get("setpoint") or self.default_setpoint)
                    except Exception:
                        entry_setpoint = float(self.default_setpoint)

                    try:
                        heatup_rate = float(self.settings.get("HEATUP_RATE", "0.4"))
                    except Exception:
                        heatup_rate = 0.4

                    try:
                        min_startup = int(float(self.settings.get("MINIMUM_HEATING_STARTUP_TIME", "30")))
                    except Exception:
                        min_startup = 30

                    try:
                        max_startup = int(float(self.settings.get("MAXIMUM_HEATING_STARTUP_TIME", "120")))
                    except Exception:
                        max_startup = 120

                    try:
                        target_offset = float(self.settings.get("TARGET_SETPOINT_OFFSET", "0.0"))
                    except Exception:
                        target_offset = 0.0

                    if heatup_rate > 0:
                        warm_target = entry_setpoint + target_offset
                        delta_c = max(0.0, warm_target - float(self.current_temp))
                        mins_needed = int(round((delta_c / heatup_rate) * 60.0))

                        mins_needed = max(min_startup, mins_needed)
                        mins_needed = min(max_startup, mins_needed)

                        warmup_start_epoch = best_start_epoch - (mins_needed * 60.0)

                        ctx["warmup_entry"] = best_next
                        ctx["warmup_target"] = entry_setpoint
                        ctx["warmup_start_epoch"] = warmup_start_epoch

                        if warmup_start_epoch <= now_epoch < best_start_epoch:
                            ctx["warmup_active"] = True

        return ctx

    def _get_hw_timed_context(self, schedule_set_name, weekday_0_mon, hhmm, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        current_entry = self._get_active_hw_entry_with_special_fallback(
            weekday_0_mon, hhmm, now_epoch, special_set_name
        )

        normal_next, normal_next_epoch = self._get_next_entry_for_set("NORMAL", "HW", now_epoch)

        if special_set_name:
            special_next, special_next_epoch = self._get_next_entry_for_set(special_set_name, "HW", now_epoch)
        else:
            special_next, special_next_epoch = None, None

        best_next, best_start_epoch = self._choose_earlier_entry(
            special_next, special_next_epoch,
            normal_next, normal_next_epoch
        )

        ctx = {
            "current_entry": current_entry,
            "next_entry": best_next,
            "current_on": bool(current_entry is not None),
            "advanced_on": False,
            "advance_until_epoch": None,
        }

        if current_entry:
            try:
                end_epoch = current_entry.get("window_end_epoch")
            except Exception:
                end_epoch = None

            ctx["advanced_on"] = False
            ctx["advance_until_epoch"] = end_epoch

        else:
            if best_next:
                ctx["advanced_on"] = True
                ctx["advance_until_epoch"] = best_start_epoch

        return ctx

    def _get_ch_once_context(self, schedule_set_name, weekday_0_mon, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        def _get_once_rows(set_name):
            cur = self.db_con.cursor()
            cur.execute("""
                        SELECT id, start_time, end_time, setpoint, warmup, note, days
                        FROM schedule_entries
                        WHERE enabled = 1
                          AND schedule_set_name = ?
                          AND system = 'CH'
                        ORDER BY start_time ASC
                        """, (set_name,))
            rows = cur.fetchall()

            items = []
            for row in rows:
                base_entry = {
                    "id": row[0],
                    "start_time": row[1],
                    "end_time": row[2],
                    "setpoint": row[3],
                    "warmup": row[4],
                    "note": row[5],
                    "days": row[6],
                    "source_set": set_name,
                }

                days_str = str(base_entry["days"] or "")
                today_wd = weekday_0_mon
                yesterday_wd = (weekday_0_mon - 1) % 7

                try:
                    overnight = str(base_entry["end_time"]) <= str(base_entry["start_time"])
                except Exception:
                    overnight = False

                # Candidate anchored to today
                if str(today_wd) in days_str:
                    try:
                        start_epoch, end_epoch = self._entry_window_for_day(base_entry, now_epoch)
                        e = dict(base_entry)
                        e["window_start_epoch"] = start_epoch
                        e["window_end_epoch"] = end_epoch
                        items.append(e)
                    except Exception:
                        pass

                # Candidate anchored to yesterday for overnight carry-over
                if overnight and str(yesterday_wd) in days_str:
                    try:
                        yesterday_epoch = now_epoch - 86400.0
                        start_epoch, end_epoch = self._entry_window_for_day(base_entry, yesterday_epoch)
                        e = dict(base_entry)
                        e["window_start_epoch"] = start_epoch
                        e["window_end_epoch"] = end_epoch
                        items.append(e)
                    except Exception:
                        pass

            return items

        normal_rows = _get_once_rows("NORMAL")
        special_rows = _get_once_rows(special_set_name) if special_set_name else []

        all_rows = normal_rows + special_rows

        if not all_rows:
            return {
                "first_entry": None,
                "last_entry": None,
                "first_start_epoch": None,
                "last_end_epoch": None,
                "first_setpoint": None,
                "in_window": False,
            }

        first_entry = None
        first_start_epoch = None

        for entry in all_rows:
            start_epoch = entry.get("window_start_epoch")
            if start_epoch is None:
                continue

            if first_start_epoch is None or start_epoch < first_start_epoch:
                first_entry = entry
                first_start_epoch = start_epoch
            elif start_epoch == first_start_epoch:
                if entry.get("source_set") != "NORMAL" and first_entry.get("source_set") == "NORMAL":
                    first_entry = entry
                    first_start_epoch = start_epoch

        last_entry = None
        last_end_epoch = None

        for entry in all_rows:
            end_epoch = entry.get("window_end_epoch")
            if end_epoch is None:
                continue

            if last_end_epoch is None or end_epoch > last_end_epoch:
                last_entry = entry
                last_end_epoch = end_epoch
            elif end_epoch == last_end_epoch:
                if entry.get("source_set") != "NORMAL" and last_entry.get("source_set") == "NORMAL":
                    last_entry = entry
                    last_end_epoch = end_epoch

        if first_entry is None or last_entry is None:
            return {
                "first_entry": None,
                "last_entry": None,
                "first_start_epoch": None,
                "last_end_epoch": None,
                "first_setpoint": None,
                "in_window": False,
            }

        in_window = (first_start_epoch <= now_epoch < last_end_epoch)

        try:
            first_setpoint = float(first_entry["setpoint"] or self.default_setpoint)
        except Exception:
            first_setpoint = float(self.default_setpoint)

        return {
            "first_entry": first_entry,
            "last_entry": last_entry,
            "first_start_epoch": first_start_epoch,
            "last_end_epoch": last_end_epoch,
            "first_setpoint": first_setpoint,
            "in_window": in_window,
        }

    def _get_hw_once_context(self, schedule_set_name, weekday_0_mon, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        def _get_once_rows(set_name):
            cur = self.db_con.cursor()
            cur.execute("""
                        SELECT id, start_time, end_time, note, days
                        FROM schedule_entries
                        WHERE enabled = 1
                          AND schedule_set_name = ?
                          AND system = 'HW'
                        ORDER BY start_time ASC
                        """, (set_name,))
            rows = cur.fetchall()

            items = []
            for row in rows:
                base_entry = {
                    "id": row[0],
                    "start_time": row[1],
                    "end_time": row[2],
                    "note": row[3],
                    "days": row[4],
                    "source_set": set_name,
                }

                days_str = str(base_entry["days"] or "")
                today_wd = weekday_0_mon
                yesterday_wd = (weekday_0_mon - 1) % 7

                try:
                    overnight = str(base_entry["end_time"]) <= str(base_entry["start_time"])
                except Exception:
                    overnight = False

                # Candidate anchored to today
                if str(today_wd) in days_str:
                    try:
                        start_epoch, end_epoch = self._entry_window_for_day(base_entry, now_epoch)
                        e = dict(base_entry)
                        e["window_start_epoch"] = start_epoch
                        e["window_end_epoch"] = end_epoch
                        items.append(e)
                    except Exception:
                        pass

                # Candidate anchored to yesterday for overnight carry-over
                if overnight and str(yesterday_wd) in days_str:
                    try:
                        yesterday_epoch = now_epoch - 86400.0
                        start_epoch, end_epoch = self._entry_window_for_day(base_entry, yesterday_epoch)
                        e = dict(base_entry)
                        e["window_start_epoch"] = start_epoch
                        e["window_end_epoch"] = end_epoch
                        items.append(e)
                    except Exception:
                        pass

            return items

        normal_rows = _get_once_rows("NORMAL")
        special_rows = _get_once_rows(special_set_name) if special_set_name else []

        all_rows = normal_rows + special_rows

        if not all_rows:
            return {
                "first_entry": None,
                "last_entry": None,
                "first_start_epoch": None,
                "last_end_epoch": None,
                "in_window": False,
            }

        first_entry = None
        first_start_epoch = None

        for entry in all_rows:
            start_epoch = entry.get("window_start_epoch")
            if start_epoch is None:
                continue

            if first_start_epoch is None or start_epoch < first_start_epoch:
                first_entry = entry
                first_start_epoch = start_epoch
            elif start_epoch == first_start_epoch:
                if entry.get("source_set") != "NORMAL" and first_entry.get("source_set") == "NORMAL":
                    first_entry = entry
                    first_start_epoch = start_epoch

        last_entry = None
        last_end_epoch = None

        for entry in all_rows:
            end_epoch = entry.get("window_end_epoch")
            if end_epoch is None:
                continue

            if last_end_epoch is None or end_epoch > last_end_epoch:
                last_entry = entry
                last_end_epoch = end_epoch
            elif end_epoch == last_end_epoch:
                if entry.get("source_set") != "NORMAL" and last_entry.get("source_set") == "NORMAL":
                    last_entry = entry
                    last_end_epoch = end_epoch

        if first_entry is None or last_entry is None:
            return {
                "first_entry": None,
                "last_entry": None,
                "first_start_epoch": None,
                "last_end_epoch": None,
                "in_window": False,
            }

        in_window = (first_start_epoch <= now_epoch < last_end_epoch)

        return {
            "first_entry": first_entry,
            "last_entry": last_entry,
            "first_start_epoch": first_start_epoch,
            "last_end_epoch": last_end_epoch,
            "in_window": in_window,
        }

    def _relay_bool_to_state(self, value):
        if value is True:
            return "ON"
        if value is False:
            return "OFF"
        return None

    def _request_periodic_relay_sync(self):
        import uuid

        if not self._relay_allowed():
            return

        req_id = "sync_" + uuid.uuid4().hex
        self._pending_sync_request_id = req_id

        try:
            self.relay_queue.put(Message("engine", "relay_status", {
                "request_id": req_id
            }))
        except Exception:
            pass

    def _handle_periodic_relay_sync_reply(self):
        while True:
            try:
                msg = self.engine_rpc_queue.get_nowait()
            except Exception:
                break

            if getattr(msg, "type", None) != "relay_status_result":
                continue

            if getattr(msg, "request_id", None) != self._pending_sync_request_id:
                continue

            p = msg.payload or {}

            ch_letter = self._get_relay_letter("CH")
            hw_letter = self._get_relay_letter("HW")

            ch_actual = self._relay_bool_to_state(p.get(ch_letter))
            hw_actual = self._relay_bool_to_state(p.get(hw_letter))

            if ch_actual is not None and ch_actual != self.ch_desired:
                print("[Engine] SYNC MISMATCH: CH is %s but should be %s. Fixing..." %
                      (ch_actual, self.ch_desired))
                try:
                    self.relay_queue.put(Message("engine", "relay_set", {
                        "relay": ch_letter,
                        "state": self.ch_desired,
                        "reason": "Sync Correction"
                    }))
                except Exception:
                    pass

            if hw_actual is not None and hw_actual != self.hw_desired:
                print("[Engine] SYNC MISMATCH: HW is %s but should be %s. Fixing..." %
                      (hw_actual, self.hw_desired))
                try:
                    self.relay_queue.put(Message("engine", "relay_set", {
                        "relay": hw_letter,
                        "state": self.hw_desired,
                        "reason": "Sync Correction"
                    }))
                except Exception:
                    pass

            self._pending_sync_request_id = None
            break

    def _publish_state(self, target, ch_desired, reason, hw_target_on, hw_reason):
        payload = {
            "target": target,
            "ch_desired": ch_desired,
            "reason": reason,
            "ch_switch": self.ch_system_switch,
            "hw_reason": hw_reason,
            "hw_switch": self.hw_system_switch,
            "hw_desired": "ON" if hw_target_on else "OFF",
        }

        try:
            self.ui_queue.put(Message("engine", "ui_state", payload))
        except Exception:
            pass

        try:
            self.web_queue.put(Message("engine", "web_state", payload))
        except Exception:
            pass

    def _send_relay_desired(self, relay_letter, desired_state, label):
        if self._relay_allowed():
            try:
                self.relay_queue.put(Message("engine", "relay_set", {
                    "relay": relay_letter,
                    "state": desired_state,
                    "reason": "%s desired state" % label
                }))
                print("[Engine] relay_set sent: RELAY%s=%s" % (relay_letter, desired_state))
            except Exception as e:
                print("[Engine] %s relay_set failed: %s" % (label, e))
        else:
            print("[Engine] %s relay_set blocked (RELAY_ENABLE=False or mode not allowed)" % label)

    def run(self):
        from datetime import datetime
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[Engine] Started in mode: %s" % self.mode)

        ok = self.wait_for_initial_snapshot(timeout=3.0)
        if not ok:
            print("[Engine] No settings snapshot received yet; using defaults")

        print("[Engine] ENGINE_INTERVAL initial: %.2f" % self.engine_interval)

        seeded_from_relay = self._request_relay_status_startup(timeout=2.0)

        if not seeded_from_relay:
            now_epoch = time.time()
            if self.ch_desired == "ON" and self.ch_last_on_epoch is None:
                self.ch_last_on_epoch = now_epoch
                self.ch_last_change_epoch = now_epoch
            elif self.ch_desired == "OFF" and self.ch_last_off_epoch is None:
                self.ch_last_off_epoch = now_epoch
                self.ch_last_change_epoch = now_epoch

            if self.hw_desired is None:
                self.hw_desired = "OFF"

            print("[Engine] Startup relay status unavailable; seeded CH_LAST_DESIRED=%s HW=%s" %
                  (self.ch_desired, self.hw_desired))

        print("[Engine] CH_SYSTEM_SWITCH=%s DEFAULT_SETPOINT=%.1f DEFAULT_ON_SETPOINT=%.1f HYSTERESIS_BAND=%.1f" %
              (self.ch_system_switch, self.default_setpoint, self.default_on_setpoint, self.hysteresis_band))

        while not self.shutdown_event.is_set():
            self.drain_ctrl_queue()
            self._drain_engine_queue()

            self.db_queue.put(Message("engine", "heartbeat", {"status": "ok"}))

            if self.current_temp is None:
                print("[Engine] waiting for temperature... interval=%.2f" % self.engine_interval)
                time.sleep(self.engine_interval)
                continue

            self._db_connect()

            now_epoch = time.time()
            dt = datetime.fromtimestamp(now_epoch)
            weekday = dt.weekday()
            hhmm = dt.strftime("%H:%M")

            self._request_cleanup_overrides()

            ch_ctx = self._compute_ch_target(weekday, hhmm, now_epoch)
            target = ch_ctx["target"]
            reason = ch_ctx["reason"]

            hw_ctx = self._compute_hw_target(weekday, hhmm, now_epoch)
            hw_target_on = hw_ctx["target_on"]
            hw_reason = hw_ctx["reason"]

            desired_raw, lower, upper = self._decide_ch(self.current_temp, target)
            desired = desired_raw

            now_epoch = time.time()
            prev = self.ch_desired

            try:
                min_on = float(self.ch_min_on_seconds or 0)
            except Exception:
                min_on = 0.0

            try:
                min_off = float(self.ch_min_off_seconds or 0)
            except Exception:
                min_off = 0.0

            if prev == "ON" and desired == "OFF" and min_on > 0:
                if self.ch_last_on_epoch is not None:
                    since_on = now_epoch - self.ch_last_on_epoch
                    if since_on < min_on:
                        desired = "ON"
                        reason = reason + " + min_on_block(%.0fs<%ss)" % (since_on, int(min_on))

            elif prev == "OFF" and desired == "ON" and min_off > 0:
                if self.ch_last_off_epoch is not None:
                    since_off = now_epoch - self.ch_last_off_epoch
                    if since_off < min_off:
                        desired = "OFF"
                        reason = reason + " + min_off_block(%.0fs<%ss)" % (since_off, int(min_off))

            if target is None:
                print("[Engine] temp=%.1fC CH=FORCED_OFF raw=%s (%s) band=%.1f switch=%s interval=%.2f" %
                      (self.current_temp, desired_raw, reason, self.hysteresis_band, self.ch_system_switch,
                       self.engine_interval))
            else:
                print("[Engine] temp=%.1fC target=%.1fC band=%.1f thr=[%.1f..%.1f] CH=%s raw=%s (%s) switch=%s interval=%.2f" %
                      (self.current_temp, target, self.hysteresis_band, lower, upper,
                       desired, desired_raw, reason, self.ch_system_switch, self.engine_interval))

            print("[Engine] HW=%s (%s) switch=%s" %
                  ("ON" if hw_target_on else "OFF", hw_reason, self.hw_system_switch))

            self._publish_state(target, desired, reason, hw_target_on, hw_reason)

            if desired != self.ch_desired:
                self.ch_desired = desired

                now_epoch = time.time()
                self.ch_last_change_epoch = now_epoch

                if desired == "ON":
                    self.ch_last_on_epoch = now_epoch
                else:
                    self.ch_last_off_epoch = now_epoch

                try:
                    self.db_queue.put(Message("engine", "set_setting", {
                        "key": "CH_LAST_DESIRED",
                        "value": desired
                    }))
                except Exception:
                    pass

                self.db_queue.put(Message("engine", "state_change", {
                    "system": "CH",
                    "state": "DESIRED_%s" % desired
                }))

                self._send_relay_desired(self._get_relay_letter("CH"), desired, "CH")

            hw_desired = "ON" if hw_target_on else "OFF"

            if hw_desired != self.hw_desired:
                self.hw_desired = hw_desired

                try:
                    self.db_queue.put(Message("engine", "set_setting", {
                        "key": "HW_LAST_DESIRED",
                        "value": hw_desired
                    }))
                except Exception:
                    pass

                self.db_queue.put(Message("engine", "state_change", {
                    "system": "HW",
                    "state": "DESIRED_%s" % hw_desired
                }))

                self._send_relay_desired(self._get_relay_letter("HW"), hw_desired, "HW")

            now = time.time()

            if now - self._last_relay_sync > 300.0:
                self._last_relay_sync = now
                self._request_periodic_relay_sync()

            self._handle_periodic_relay_sync_reply()

            time.sleep(self.engine_interval)

        try:
            if self.db_con:
                self.db_con.close()
        except Exception:
            pass
        print("[Engine] Shutting down cleanly")