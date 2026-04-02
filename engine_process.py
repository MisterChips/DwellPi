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
    def __init__(self, engine_queue, engine_rpc_queue, ui_queue, web_queue,
                 db_queue, ctrl_queue, relay_queue, email_queue, mode, db_path, shutdown_event):
        SettingsClient.__init__(self, ctrl_queue, shutdown_event, name="Engine")

        self.engine_queue = engine_queue
        self.engine_rpc_queue = engine_rpc_queue
        self.ui_queue = ui_queue
        self.web_queue = web_queue
        self.email_queue = email_queue
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

        # actual relay states reported by relay process / board
        self.ch_actual_relay = None   # "ON"/"OFF"/None
        self.hw_actual_relay = None   # "ON"/"OFF"/None
        self.last_actual_relay_update_epoch = 0.0

        # defaults (will be overwritten by snapshot/push)
        self.engine_interval = 2.0
        self.current_temp = None
        self.last_temp_update_epoch = 0.0
        self.temp_stale_timeout = 300.0   # seconds
        self._temp_stale_active = False

        self.ch_system_switch = "timed"   # timed/on/off/once
        self.hw_system_switch = "timed"   # timed/on/off/once
        self.ch_advance = False
        self.hw_advance = False

        self.default_setpoint = 10.0
        self.default_on_setpoint = 20.0
        self.hysteresis_band = 0.0

        # warmup / legacy heat-up settings
        self.fallback_heatup_rate = 0.4
        self.warmup_minimum_lead_time = 30   # minutes
        self.warmup_maximum_lead_time = 120  # minutes
        self.warmup_target_offset = 0.0

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

        # alert thresholds / state
        self.alert_relay_timeout_seconds = 10.0
        self.alert_temp_rise_check_seconds = 900.0
        self.alert_temp_rise_min_delta = 0.3

        self._relay_mismatch_active = False
        self._pending_relay_verification = None

        self._temp_rise_active = False
        self._temp_rise_start_epoch = None
        self._temp_rise_start_temp = None
        self._temp_rise_alert_active = False

        # ---- predictive heating / adaptive heat-up model ----
        self.predictive_heating_enabled = True
        self.predictive_base_rate = 0.7   # °C/hour, derived from legacy data
        self.predictive_min_rate = 0.15   # floor to avoid divide-by-zero / nonsense
        self.predictive_max_rate = 1.50   # clamp for safety
        self.predictive_min_learning_seconds = 600.0

        self.last_heatup_temp = None
        self.last_heatup_ts = 0.0
        self.live_heatup_rate = None      # °C/hour
        self.last_predicted_seconds = None

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
            elif key == "FALLBACK_HEATUP_RATE":
                self.fallback_heatup_rate = float(value)
            elif key == "WARMUP_MINIMUM_LEAD_TIME":
                self.warmup_minimum_lead_time = max(0, int(float(value)))
            elif key == "WARMUP_MAXIMUM_LEAD_TIME":
                self.warmup_maximum_lead_time = max(0, int(float(value)))
            elif key == "WARMUP_TARGET_OFFSET":
                self.warmup_target_offset = float(value)
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
            elif key == "ALERT_SENSOR_STALE_SECONDS":
                self.temp_stale_timeout = max(10.0, float(value))
            elif key == "ALERT_RELAY_TIMEOUT_SECONDS":
                self.alert_relay_timeout_seconds = max(1.0, float(value))
            elif key == "ALERT_TEMP_RISE_CHECK_SECONDS":
                self.alert_temp_rise_check_seconds = max(60.0, float(value))
            elif key == "ALERT_TEMP_RISE_MIN_DELTA":
                self.alert_temp_rise_min_delta = max(0.1, float(value))
            elif key == "PREDICTIVE_HEATING_ENABLED":
                self.predictive_heating_enabled = parse_bool(value)
            elif key == "PREDICTIVE_BASE_RATE":
                try:
                    self.predictive_base_rate = max(0.05, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_MIN_LEARNING_SECONDS":
                try:
                    self.predictive_min_learning_seconds = max(60.0, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_MIN_RATE":
                try:
                    self.predictive_min_rate = max(0.01, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_MAX_RATE":
                try:
                    self.predictive_max_rate = max(0.05, float(value))
                except Exception:
                    pass
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
            self.relay_queue.put(Message(
                "engine",
                "relay_status",
                {},
                request_id=req_id
            ))
        except Exception:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline and not self.shutdown_event.is_set():
            try:
                msg = self.engine_rpc_queue.get(timeout=0.2)
            except Exception:
                continue

            if getattr(msg, "type", None) != "relay_status_result":
                print("[Engine] Startup relay reply ignored: type=%r" % getattr(msg, "type", None))
                continue

            if getattr(msg, "request_id", None) != req_id:
                print("[Engine] Startup relay reply ignored: request_id=%r expected=%r" % (
                    getattr(msg, "request_id", None), req_id
                ))
                continue

            if getattr(msg, "target", None) not in (None, "engine", ""):
                print("[Engine] Startup relay reply ignored: target=%r" % getattr(msg, "target", None))
                continue

            p = msg.payload or {}

            ch_letter = self._get_relay_letter("CH")
            hw_letter = self._get_relay_letter("HW")

            ch_actual_state = self._relay_bool_to_state(p.get(ch_letter))
            hw_actual_state = self._relay_bool_to_state(p.get(hw_letter))

            if ch_actual_state is None or hw_actual_state is None:
                return False

            self.ch_actual_relay = ch_actual_state
            self.hw_actual_relay = hw_actual_state
            self.last_actual_relay_update_epoch = time.time()

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
                    self.last_temp_update_epoch = time.time()
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

    def _get_active_schedule_entry(self, schedule_set_name, system, weekday_0_mon, hhmm, now_epoch):
        cur = self.db_con.cursor()

        if system == "CH":
            cur.execute("""
                SELECT id, start_time, end_time, setpoint, warmup, note, days
                FROM schedule_entries
                WHERE enabled = 1
                  AND schedule_set_name = ?
                  AND system = ?
                ORDER BY start_time ASC
            """, (schedule_set_name, system))
        else:
            cur.execute("""
                SELECT id, start_time, end_time, NULL as setpoint, 0 as warmup, note, days
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

            if self._is_entry_active_now(entry, now_epoch, weekday_0_mon, days_str):
                today_epoch = now_epoch
                yesterday_epoch = now_epoch - 86400.0
                today_wd = weekday_0_mon
                yesterday_wd = (weekday_0_mon - 1) % 7

                overnight = str(entry["end_time"]) <= str(entry["start_time"])

                if str(today_wd) in days_str and self._is_entry_active_now_for_day(entry, now_epoch, today_epoch):
                    start_epoch, end_epoch = self._entry_window_for_day(entry, today_epoch)
                    entry["window_start_epoch"] = start_epoch
                    entry["window_end_epoch"] = end_epoch
                    matches.append(entry)
                    continue

                if overnight and str(yesterday_wd) in days_str and \
                        self._is_entry_active_now_for_day(entry, now_epoch, yesterday_epoch):
                    start_epoch, end_epoch = self._entry_window_for_day(entry, yesterday_epoch)
                    entry["window_start_epoch"] = start_epoch
                    entry["window_end_epoch"] = end_epoch
                    matches.append(entry)

        if not matches:
            return None

        if len(matches) > 1:
            print("[Engine] WARNING: overlapping %s entries detected for %s at %s" %
                  (system, schedule_set_name, hhmm))

        return matches[0]

    def _get_active_entry_with_special_fallback(self, system, weekday_0_mon, hhmm, now_epoch, special_set_name=None):
        if special_set_name:
            entry = self._get_active_schedule_entry(special_set_name, system, weekday_0_mon, hhmm, now_epoch)
            if entry:
                entry["source_set"] = special_set_name
                return entry

        entry = self._get_active_schedule_entry("NORMAL", system, weekday_0_mon, hhmm, now_epoch)
        if entry:
            entry["source_set"] = "NORMAL"
            return entry

        return None

    def _get_active_hw_entry_with_special_fallback(self, weekday_0_mon, hhmm, now_epoch, special_set_name=None):
        return self._get_active_entry_with_special_fallback("HW", weekday_0_mon, hhmm, now_epoch, special_set_name)

    def _get_once_rows_for_set(self, set_name, system, weekday_0_mon, now_epoch):
        cur = self.db_con.cursor()

        if system == "CH":
            cur.execute("""
                        SELECT id, start_time, end_time, setpoint, warmup, note, days
                        FROM schedule_entries
                        WHERE enabled = 1
                          AND schedule_set_name = ?
                          AND system = ?
                        ORDER BY start_time ASC
                        """, (set_name, system))
        else:
            cur.execute("""
                        SELECT id, start_time, end_time, NULL as setpoint, 0 as warmup, note, days
                        FROM schedule_entries
                        WHERE enabled = 1
                          AND schedule_set_name = ?
                          AND system = ?
                        ORDER BY start_time ASC
                        """, (set_name, system))

        rows = cur.fetchall()
        items = []

        today_wd = weekday_0_mon
        yesterday_wd = (weekday_0_mon - 1) % 7

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

            try:
                overnight = str(base_entry["end_time"]) <= str(base_entry["start_time"])
            except Exception:
                overnight = False

            if str(today_wd) in days_str:
                try:
                    start_epoch, end_epoch = self._entry_window_for_day(base_entry, now_epoch)
                    e = dict(base_entry)
                    e["window_start_epoch"] = start_epoch
                    e["window_end_epoch"] = end_epoch
                    items.append(e)
                except Exception:
                    pass

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

    def _get_once_context(self, schedule_set_name, system, weekday_0_mon, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        normal_rows = self._get_once_rows_for_set("NORMAL", system, weekday_0_mon, now_epoch)
        special_rows = self._get_once_rows_for_set(
            special_set_name, system, weekday_0_mon, now_epoch
        ) if special_set_name else []

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

        first_setpoint = None
        if system == "CH":
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

    def _get_ch_once_context(self, schedule_set_name, weekday_0_mon, now_epoch):
        return self._get_once_context(schedule_set_name, "CH", weekday_0_mon, now_epoch)

    def _get_hw_once_context(self, schedule_set_name, weekday_0_mon, now_epoch):
        return self._get_once_context(schedule_set_name, "HW", weekday_0_mon, now_epoch)

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
                    start_epoch = self._time_text_to_epoch_for_day(entry["start_time"], day_epoch)
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

    def _is_temperature_stale(self, now_epoch):
        if self.current_temp is None:
            return True

        try:
            last_update = float(self.last_temp_update_epoch or 0.0)
        except Exception:
            last_update = 0.0

        if last_update <= 0.0:
            return True

        return (now_epoch - last_update) >= float(self.temp_stale_timeout)

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

    def _clamp(self, value, low, high):
        if value < low:
            return low
        if value > high:
            return high
        return value

    def _update_live_heatup_rate(self, ch_calling_for_heat, relay_a_on, current_temp, now_epoch):
        """
        Estimate live heat-up rate while CH is actually heating.
        Stores a smoothed °C/hour value in self.live_heatup_rate.
        """
        try:
            current_temp = float(current_temp)
            now_epoch = float(now_epoch)
        except Exception:
            return

        heating_active = bool(ch_calling_for_heat and actual_ch_on)

        if not heating_active:
            self.last_heatup_temp = current_temp
            self.last_heatup_ts = now_epoch
            return

        if self.last_heatup_temp is None or self.last_heatup_ts <= 0:
            self.last_heatup_temp = current_temp
            self.last_heatup_ts = now_epoch
            return

        dt = now_epoch - self.last_heatup_ts
        if dt < float(self.predictive_min_learning_seconds):
            return

        dtemp = current_temp - self.last_heatup_temp
        raw_rate = (dtemp / dt) * 3600.0
        raw_rate = self._clamp(raw_rate, -0.5, 2.5)

        if self.live_heatup_rate is None:
            smoothed = raw_rate
        else:
            smoothed = (self.live_heatup_rate * 0.7) + (raw_rate * 0.3)

        self.live_heatup_rate = smoothed
        self.last_heatup_temp = current_temp
        self.last_heatup_ts = now_epoch

    def _get_predictive_heatup_rate(self):
        base = float(self.predictive_base_rate or 0.7)

        if self.live_heatup_rate is None:
            return self._clamp(base, self.predictive_min_rate, self.predictive_max_rate)

        blended = (self.live_heatup_rate * 0.7) + (base * 0.3)
        return self._clamp(blended, self.predictive_min_rate, self.predictive_max_rate)

    def _predict_time_to_target_seconds(self, current_temp, target_temp):
        try:
            current_temp = float(current_temp)
            target_temp = float(target_temp)
        except Exception:
            return None

        delta = target_temp - current_temp
        if delta <= 0:
            return 0.0

        rate = self._get_predictive_heatup_rate()
        if rate <= 0:
            return None

        seconds = (delta / rate) * 3600.0
        return max(0.0, seconds)

    def _predictive_warmup_needed(self, current_temp, target_temp):
        seconds = self._predict_time_to_target_seconds(current_temp, target_temp)
        if seconds is None:
            return None

        try:
            min_s = int(float(self.warmup_minimum_lead_time)) * 60
        except Exception:
            min_s = 30 * 60

        try:
            max_s = int(float(self.warmup_maximum_lead_time)) * 60
        except Exception:
            max_s = 120 * 60

        return int(self._clamp(seconds, min_s, max_s))

    def _legacy_warmup_needed(self, current_temp, target_temp):
        try:
            current_temp = float(current_temp)
            target_temp = float(target_temp)
            heatup_rate = float(self.fallback_heatup_rate)
        except Exception:
            return None

        if heatup_rate <= 0:
            return None

        delta_c = max(0.0, target_temp - current_temp)
        seconds = (delta_c / heatup_rate) * 3600.0

        try:
            min_s = int(float(self.warmup_minimum_lead_time)) * 60
        except Exception:
            min_s = 30 * 60

        try:
            max_s = int(float(self.warmup_maximum_lead_time)) * 60
        except Exception:
            max_s = 120 * 60

        return int(self._clamp(seconds, min_s, max_s))

    def _fmt_predictive_minutes(self, seconds_value):
        if seconds_value is None:
            return "--"
        return str(int(round(float(seconds_value) / 60.0)))

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
            "warmup_seconds": None,
            "warmup_mode": None,
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

                    warm_target = entry_setpoint + float(self.warmup_target_offset or 0.0)

                    warmup_seconds = None
                    warmup_mode = "legacy"

                    if self.predictive_heating_enabled:
                        warmup_seconds = self._predictive_warmup_needed(self.current_temp, warm_target)
                        warmup_mode = "predictive"

                    if warmup_seconds is None:
                        warmup_seconds = self._legacy_warmup_needed(self.current_temp, warm_target)
                        warmup_mode = "legacy"

                    if warmup_seconds is not None:
                        warmup_start_epoch = best_start_epoch - float(warmup_seconds)

                        ctx["warmup_entry"] = best_next
                        ctx["warmup_target"] = entry_setpoint
                        ctx["warmup_start_epoch"] = warmup_start_epoch
                        ctx["warmup_seconds"] = warmup_seconds
                        ctx["warmup_mode"] = warmup_mode

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
                    reason = "warmup(id=%s starts=%s set=%s mode=%s eta=%sm)" % (
                        warmup_entry["id"],
                        warmup_entry["start_time"],
                        warmup_entry.get("source_set", active_set_name),
                        ctx.get("warmup_mode") or "legacy",
                        self._fmt_predictive_minutes(ctx.get("warmup_seconds"))
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
                        hw_entry["id"], hw_entry.get("source_set", active_set_name),
                        hw_entry["start_time"], hw_entry["end_time"]
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

    def _relay_bool_to_state(self, value):
        if value is True:
            return "ON"
        if value is False:
            return "OFF"
        return None

    def _relay_state_to_bool(self, state):
        if state == "ON":
            return True
        if state == "OFF":
            return False
        return None

    def _update_actual_relays_from_payload(self, payload):
        if not isinstance(payload, dict):
            return

        ch_letter = self._get_relay_letter("CH")
        hw_letter = self._get_relay_letter("HW")

        ch_actual = self._relay_bool_to_state(payload.get(ch_letter))
        hw_actual = self._relay_bool_to_state(payload.get(hw_letter))

        if ch_actual is not None:
            self.ch_actual_relay = ch_actual
        if hw_actual is not None:
            self.hw_actual_relay = hw_actual

        if ch_actual is not None or hw_actual is not None:
            self.last_actual_relay_update_epoch = time.time()

    def _request_periodic_relay_sync(self):
        import uuid

        if not self._relay_allowed():
            return

        req_id = "sync_" + uuid.uuid4().hex
        self._pending_sync_request_id = req_id

        try:
            self.relay_queue.put(Message(
                "engine",
                "relay_status",
                {},
                request_id=req_id
            ))
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
            self._update_actual_relays_from_payload(p)

            ch_letter = self._get_relay_letter("CH")
            hw_letter = self._get_relay_letter("HW")

            ch_actual = self.ch_actual_relay
            hw_actual = self.hw_actual_relay

            if self._pending_relay_verification:
                verify = self._pending_relay_verification
                actual_state = None
                if verify.get("relay") == ch_letter:
                    actual_state = ch_actual
                elif verify.get("relay") == hw_letter:
                    actual_state = hw_actual

                if actual_state == verify.get("expected"):
                    self._pending_relay_verification = None
                    self._relay_mismatch_active = False

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
            "relay_a": self._relay_state_to_bool(self.ch_actual_relay if self._get_relay_letter("CH") == "A" else self.hw_actual_relay),
            "relay_b": self._relay_state_to_bool(self.ch_actual_relay if self._get_relay_letter("CH") == "B" else self.hw_actual_relay),
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

    def _mark_relay_verification(self, relay_letter, desired_state, label):
        self._pending_relay_verification = {
            "relay": relay_letter,
            "expected": desired_state,
            "label": label,
            "started": time.time()
        }
        self._relay_mismatch_active = False

    def _check_pending_relay_verification(self, now_epoch):
        verify = self._pending_relay_verification
        if not verify:
            return

        age = now_epoch - float(verify.get("started") or now_epoch)
        if age < float(self.alert_relay_timeout_seconds):
            return

        if self._pending_sync_request_id is None:
            self._request_periodic_relay_sync()

        if not self._relay_mismatch_active:
            self._relay_mismatch_active = True
            self._send_email_alert(
                "relay_timeout_" + str(verify.get("label") or "relay").lower(),
                "RELAY_TIMEOUT",
                "%s relay did not confirm expected state in time." % verify.get("label"),
                severity="error",
                extra={
                    "relay": verify.get("relay"),
                    "expected": verify.get("expected"),
                    "timeout_seconds": self.alert_relay_timeout_seconds,
                    "age_seconds": age
                }
            )

    def _start_temp_rise_watch(self, now_epoch):
        if self.current_temp is None:
            self._temp_rise_active = False
            self._temp_rise_start_epoch = None
            self._temp_rise_start_temp = None
            self._temp_rise_alert_active = False
            return

        self._temp_rise_active = True
        self._temp_rise_start_epoch = now_epoch
        self._temp_rise_start_temp = self.current_temp
        self._temp_rise_alert_active = False

    def _stop_temp_rise_watch(self):
        self._temp_rise_active = False
        self._temp_rise_start_epoch = None
        self._temp_rise_start_temp = None
        self._temp_rise_alert_active = False

    def _check_temp_rise_watch(self, now_epoch):
        if not self._temp_rise_active:
            return
        if self.current_temp is None:
            return
        if self._temp_rise_start_epoch is None or self._temp_rise_start_temp is None:
            return
        if self._temp_rise_alert_active:
            return

        elapsed = now_epoch - self._temp_rise_start_epoch
        if elapsed < float(self.alert_temp_rise_check_seconds):
            return

        delta = float(self.current_temp) - float(self._temp_rise_start_temp)
        if delta < float(self.alert_temp_rise_min_delta):
            self._temp_rise_alert_active = True
            self._send_email_alert(
                "temp_not_rising",
                "TEMP_NOT_RISING",
                "Heating has been ON but room temperature has not risen enough.",
                severity="error",
                extra={
                    "start_temp": self._temp_rise_start_temp,
                    "current_temp": self.current_temp,
                    "delta": delta,
                    "required_delta": self.alert_temp_rise_min_delta,
                    "elapsed_seconds": elapsed
                }
            )

    def _send_email_alert(self, alert_key, event, body, severity="error", is_recovery=False, extra=None):
        if self.email_queue is None:
            return

        try:
            self.email_queue.put(Message("engine", "email_alert", {
                "alert_key": alert_key,
                "subsystem": "ENGINE",
                "event": event,
                "severity": severity,
                "is_recovery": is_recovery,
                "body": body,
                "extra": extra or {}
            }))
        except Exception:
            pass

    def run(self):
        from datetime import datetime
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[Engine] Started in mode: %s" % self.mode)

        try:
            self.db_queue.put(Message("engine", "request_settings_snapshot", {}))
        except Exception:
            pass

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

            self._db_connect()

            now_epoch = time.time()
            temp_is_stale = self._is_temperature_stale(now_epoch)

            if temp_is_stale:
                stale_for = 0.0
                try:
                    last_update = float(self.last_temp_update_epoch or 0.0)
                    if last_update > 0.0:
                        stale_for = now_epoch - last_update
                except Exception:
                    stale_for = 0.0

                if not self._temp_stale_active:
                    self._temp_stale_active = True
                    self._send_email_alert(
                        "engine_sensor_stale",
                        "SENSOR_STALE",
                        "Temperature updates have stopped. CH has been forced OFF for safety.",
                        severity="error",
                        extra={
                            "last_temp": self.current_temp,
                            "last_temp_update_epoch": self.last_temp_update_epoch,
                            "stale_timeout_seconds": self.temp_stale_timeout
                        }
                    )
                    try:
                        self.db_queue.put(Message("engine", "state_change", {
                            "system": "CH",
                            "state": "SENSOR_STALE"
                        }))
                    except Exception:
                        pass

                reason = "sensor_stale(%.0fs)" % stale_for
                hw_reason = "sensor_stale_ignored"

                print("[Engine] temperature stale for %.0fs - forcing CH OFF" % stale_for)

                self._publish_state(None, "OFF", reason, (self.hw_desired == "ON"), hw_reason)

                if self.ch_desired != "OFF":
                    self.ch_desired = "OFF"
                    self.ch_last_change_epoch = now_epoch
                    self.ch_last_off_epoch = now_epoch

                    try:
                        self.db_queue.put(Message("engine", "set_setting", {
                            "key": "CH_LAST_DESIRED",
                            "value": "OFF"
                        }))
                    except Exception:
                        pass

                    try:
                        self.db_queue.put(Message("engine", "state_change", {
                            "system": "CH",
                            "state": "DESIRED_OFF_SENSOR_STALE"
                        }))
                    except Exception:
                        pass

                    self._send_relay_desired(self._get_relay_letter("CH"), "OFF", "CH")
                    self._mark_relay_verification(self._get_relay_letter("CH"), "OFF", "CH")

                self._stop_temp_rise_watch()
                time.sleep(self.engine_interval)
                continue
            else:
                if self._temp_stale_active:
                    self._temp_stale_active = False
                    self._send_email_alert(
                        "engine_sensor_stale",
                        "SENSOR_RECOVERED",
                        "Temperature updates have resumed. Engine is operating normally again.",
                        severity="info",
                        is_recovery=True,
                        extra={
                            "current_temp": self.current_temp,
                            "last_temp_update_epoch": self.last_temp_update_epoch
                        }
                    )
                    try:
                        self.db_queue.put(Message("engine", "state_change", {
                            "system": "CH",
                            "state": "SENSOR_OK"
                        }))
                    except Exception:
                        pass

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
                      (self.current_temp, desired_raw, reason, self.hysteresis_band,
                       self.ch_system_switch, self.engine_interval))
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
                self._mark_relay_verification(self._get_relay_letter("CH"), desired, "CH")

                if desired == "ON":
                    self._start_temp_rise_watch(now_epoch)
                else:
                    self._stop_temp_rise_watch()

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
                self._mark_relay_verification(self._get_relay_letter("HW"), hw_desired, "HW")

            now = time.time()

            # use ACTUAL relay state for predictive learning when available
            if self.ch_actual_relay is not None:
                actual_ch_on = (self.ch_actual_relay == "ON")
            else:
                actual_ch_on = (self.ch_desired == "ON")

            try:
                self._update_live_heatup_rate(
                    ch_calling_for_heat=(self.ch_desired == "ON"),
                    relay_a_on=actual_ch_on,
                    current_temp=self.current_temp,
                    now_epoch=now
                )
            except Exception:
                pass

            if self.ch_desired == "ON":
                if not self._temp_rise_active:
                    self._start_temp_rise_watch(now)
            else:
                self._stop_temp_rise_watch()

            self._check_temp_rise_watch(now)
            self._check_pending_relay_verification(now)

            # sync actual relay state more often while heating is active,
            # otherwise keep the lighter periodic cadence
            relay_sync_interval = 60.0 if self.ch_desired == "ON" else 300.0
            if now - self._last_relay_sync > relay_sync_interval:
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