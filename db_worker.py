#!/usr/bin/python
# -*- coding: utf-8 -*-
# db_worker.py

from __future__ import print_function
try:
    from Queue import Empty as QueueEmpty  # Py2
except ImportError:
    from queue import Empty as QueueEmpty  # Py3

import sqlite3, time, traceback
from message_schema import Message
import datetime

try:
    # reuse your validation + schema
    from db_init import SETTINGS_SCHEMA, validate_setting
except Exception:
    SETTINGS_SCHEMA = {}
    def validate_setting(key, value, schema):
        return True


class DBWorker(object):
    PROGRAM_COLUMNS = (
        "id", "schedule_set_name", "system", "start_time", "end_time",
        "days", "setpoint", "warmup", "note", "enabled"
    )

    HOLIDAY_COLUMNS = (
        "id", "start_ts_epoch", "start_ts_text", "end_ts_epoch",
        "end_ts_text", "systems", "enabled", "note"
    )

    SPECIAL_PERIOD_COLUMNS = (
        "id", "start_ts_epoch", "start_ts_text", "end_ts_epoch",
        "end_ts_text", "systems", "schedule_set_name", "enabled", "note"
    )

    SCHEDULE_SET_COLUMNS = (
        "name", "enabled", "note"
    )

    STATE_LOG_COLUMNS = (
        "ts_epoch", "ts", "system", "state"
    )

    TEMPERATURE_LOG_COLUMNS = (
        "ts_epoch", "ts", "source", "value"
    )

    def __init__(self, db_path, mode):
        self.db_path = db_path
        self.mode = mode
        self.conn = None
        self.last_prune_ts = 0.0

        # ---- settings cache ----
        self.settings = {}   # key -> value (strings)
        self.dirty = set()   # keys needing flush (usually tiny)

        # ---- log buffers ----
        self.temp_buf = []       # list of tuples for temperature_log
        self.state_buf = []      # list of tuples for state_log
        #HEARTBEAT to DB
        #self.heartbeat_buf = []  # list of tuples for heartbeat_log
        self.last_log_flush = 0.0

    def connect(self):
        self.conn = sqlite3.connect(self.db_path, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

        # Ensure core runtime tables exist.
        # Full schema is expected to be created by db_init before this worker starts.
        self.conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS temperature_log (ts_epoch REAL, ts TEXT, source TEXT, value REAL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS state_log (ts_epoch REAL, ts TEXT, system TEXT, state TEXT)")

        # HEARTBEAT to DB
        # optional heartbeat log table
        #self.conn.execute("CREATE TABLE IF NOT EXISTS heartbeat_log (ts_epoch REAL, ts TEXT, source TEXT)")
        self.conn.commit()

    def load_settings_cache(self):
        cur = self.conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        rows = cur.fetchall()
        self.settings = {}
        for k, v in rows:
            self.settings[k] = v

        # make sure LOGGING_INTERVAL exists in cache (fallback)
        if "LOGGING_INTERVAL" not in self.settings:
            self.settings["LOGGING_INTERVAL"] = "600"

        print("[DB] Settings cached: %d keys" % (len(self.settings),))

    def get_logging_interval_seconds(self):
        try:
            return int(self.settings.get("LOGGING_INTERVAL", "600"))
        except Exception:
            return 600

    def _ok_id_response(self, msg, msg_type, item_id, extra=None):
        payload = {"ok": True, "id": item_id}
        if extra:
            payload.update(extra)
        return self._make_response(msg, msg_type, payload)

    def _error_response(self, msg, msg_type, error_text, extra=None):
        payload = {"ok": False, "error": error_text}
        if extra:
            payload.update(extra)
        return self._make_response(msg, msg_type, payload)

    def _fetch_one(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()

    def _fetch_all(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    def _fetch_one_dict(self, columns, sql, params=()):
        row = self._fetch_one(sql, params)
        if row is None:
            return None
        return self._row_to_dict(columns, row)

    def _fetch_all_dicts(self, columns, sql, params=()):
        rows = self._fetch_all(sql, params)
        return self._rows_to_dicts(columns, rows)

    def _find_overlapping_period(self, table_name, start_ts_epoch, end_ts_epoch, systems, exclude_id=None):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT id, start_ts_epoch, end_ts_epoch, systems
            FROM %s
            WHERE enabled = 1
        """ % table_name)
        rows = cur.fetchall()

        for row in rows:
            row_id = row[0]
            row_start = float(row[1])
            row_end = float(row[2])
            row_systems = row[3]

            if exclude_id is not None and row_id == exclude_id:
                continue

            if not self._systems_overlap(systems, row_systems):
                continue

            if start_ts_epoch < row_end and end_ts_epoch > row_start:
                return row_id

        return None

    def _find_overlapping_holiday(self, start_ts_epoch, end_ts_epoch, systems, exclude_id=None):
        return self._find_overlapping_period(
            "away_periods", start_ts_epoch, end_ts_epoch, systems, exclude_id
        )

    def _find_overlapping_special(self, start_ts_epoch, end_ts_epoch, systems, exclude_id=None):
        return self._find_overlapping_period(
            "special_periods", start_ts_epoch, end_ts_epoch, systems, exclude_id
        )

    def _parse_program_payload(self, payload, require_id=False):
        p = payload or {}

        if require_id:
            try:
                program_id = int(p.get("id"))
            except Exception:
                raise ValueError("Invalid program id")
        else:
            program_id = None

        start_time = str(p.get("start_time") or "").strip()
        end_time = str(p.get("end_time") or "").strip()
        days = str(p.get("days") or "").strip()
        note = str(p.get("note") or "").strip()
        schedule_set_name = str(p.get("schedule_set_name") or "NORMAL").strip().upper()
        system = str(p.get("system") or "CH").strip().upper()
        enabled = 1 if p.get("enabled") else 0

        if system not in ("CH", "HW"):
            raise ValueError("Invalid system")

        if not start_time or not end_time or not days:
            raise ValueError("Missing required fields")

        if system == "CH":
            try:
                setpoint = float(p.get("setpoint"))
            except Exception:
                raise ValueError("Invalid setpoint")
            warmup = 1 if p.get("warmup") else 0
        else:
            setpoint = None
            warmup = 0

        return {
            "id": program_id,
            "start_time": start_time,
            "end_time": end_time,
            "days": days,
            "note": note,
            "schedule_set_name": schedule_set_name,
            "system": system,
            "enabled": enabled,
            "setpoint": setpoint,
            "warmup": warmup,
        }


    def _get_log_items_for_day(self, table_name, columns, date_text):
        start_epoch, end_epoch, day_used = self._get_day_range_epoch(date_text)

        items = self._fetch_all_dicts(
            columns,
            """
            SELECT %s
            FROM %s
            WHERE ts_epoch >= ? AND ts_epoch < ?
            ORDER BY ts_epoch DESC
            """ % (", ".join(columns), table_name),
            (start_epoch, end_epoch)
        )

        return day_used, items

    def _ensure_schedule_set_exists(self, schedule_set_name):
        cur = self.conn.cursor()
        cur.execute("SELECT name FROM schedule_sets WHERE name = ?", (schedule_set_name,))
        if cur.fetchone() is not None:
            return

        try:
            self._begin()
            cur.execute(
                "INSERT INTO schedule_sets (name, enabled, note) VALUES (?, ?, ?)",
                (schedule_set_name, 1, "")
            )
            self._commit()
        except Exception:
            self._rollback_quiet()
            raise

    def _insert_row(self, table, columns, values):
        cur = self.conn.cursor()
        self._begin()
        placeholders = ",".join(["?"] * len(values))
        cur.execute(
            "INSERT INTO %s (%s) VALUES (%s)" % (table, columns, placeholders),
            values
        )
        new_id = cur.lastrowid
        self._commit()
        return new_id

    def _update_row_by_id(self, table, set_clause, values, item_id):
        cur = self.conn.cursor()
        self._begin()
        cur.execute(
            "UPDATE %s SET %s WHERE id = ?" % (table, set_clause),
            tuple(values) + (item_id,)
        )
        changed = cur.rowcount
        self._commit()
        return changed

    def _delete_by_id(self, table, item_id):
        cur = self.conn.cursor()
        self._begin()
        cur.execute("DELETE FROM %s WHERE id = ?" % table, (item_id,))
        changed = cur.rowcount
        self._commit()
        return changed

    def prune_old_data(self, days_to_keep=30):
        now = time.time()
        # 86400 seconds in a day
        cutoff_epoch = now - (days_to_keep * 86400)

        cur = self.conn.cursor()
        try:
            self._begin()

            # Delete old temperatures
            cur.execute("DELETE FROM temperature_log WHERE ts_epoch < ?", (cutoff_epoch,))
            temp_deleted = cur.rowcount

            # Delete old state changes
            cur.execute("DELETE FROM state_log WHERE ts_epoch < ?", (cutoff_epoch,))
            state_deleted = cur.rowcount

            self._commit()

            if temp_deleted > 0 or state_deleted > 0:
                print("[DB] Pruning Complete: Removed %d temp rows and %d state rows." %
                      (temp_deleted, state_deleted))

                # Optional: If you deleted a HUGE amount of data (e.g. first prune)
                # you can run VACUUM, but it's slow. Usually not needed daily.
                # self.conn.execute("VACUUM")

        except Exception:
            self._rollback_quiet()
            print("[DB] ERROR during pruning")
            traceback.print_exc()

    def _get_day_range_epoch(self, day_text):
        now = datetime.datetime.now()

        if day_text:
            dt = datetime.datetime.strptime(day_text, "%Y-%m-%d")
        else:
            dt = now.replace(hour=0, minute=0, second=0, microsecond=0)

        start_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + datetime.timedelta(days=1)

        start_epoch = time.mktime(start_dt.timetuple())
        end_epoch = time.mktime(end_dt.timetuple())

        # if today, only return up to "now"
        if start_dt.date() == now.date():
            end_epoch = time.time()

        return start_epoch, end_epoch, start_dt.strftime("%Y-%m-%d")

    # -------------------------
    # atomic settings flush
    # -------------------------
    def flush_settings(self):
        if not self.dirty:
            return

        keys = list(self.dirty)
        cur = self.conn.cursor()

        try:
            # atomic batch update
            self._begin()
            for key in keys:
                val = self.settings.get(key)
                cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val))
            self._commit()
            self.dirty.clear()
            print("[DB] Flushed settings:", keys)
        except Exception:
            self._rollback_quiet()
            print("[DB] ERROR flushing settings")
            traceback.print_exc()

    # -------------------------
    # batched log flush
    # -------------------------
    def flush_logs_if_due(self, force=False):
        interval = self.get_logging_interval_seconds()
        now = time.time()

        if not force and (now - self.last_log_flush) < interval:
            return

        cur = self.conn.cursor()
        try:
            self._begin()

            if self.temp_buf:
                cur.executemany(
                    "INSERT INTO temperature_log (ts_epoch, ts, source, value) VALUES (?, ?, ?, ?)",
                    self.temp_buf
                )
                self.temp_buf = []

            if self.state_buf:
                cur.executemany(
                    "INSERT INTO state_log (ts_epoch, ts, system, state) VALUES (?, ?, ?, ?)",
                    self.state_buf
                )
                self.state_buf = []

            # HEARTBEAT to DB
            #if self.heartbeat_buf:
            #    cur.executemany(
            #        "INSERT INTO heartbeat_log (ts_epoch, ts, source) VALUES (?, ?, ?)",
            #        self.heartbeat_buf
            #    )
            #    self.heartbeat_buf = []

            self._commit()
            self.last_log_flush = now
            # print("[DB] Log flush OK")
        except Exception:
            self._rollback_quiet()
            print("[DB] ERROR flushing logs")
            traceback.print_exc()

    # -------------------------
    # setting validation
    # -------------------------
    def _validate_or_default(self, key, value):
        if key not in SETTINGS_SCHEMA:
            # unknown keys allowed? choose policy:
            # return False to reject OR True to allow.
            # For now: allow unknown keys.
            return True, value

        schema = SETTINGS_SCHEMA[key]
        if validate_setting(key, value, schema):
            return True, value

        # invalid -> default
        default_val = schema.get("default")
        return False, default_val

    # -------------------------
    # message handlers
    # -------------------------

    def send_settings_snapshot(self, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        snap = dict(self.settings)
        msg = Message("db", "settings_snapshot", {"values": snap})
        for q in (engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
            try:
                q.put(msg)
            except Exception:
                pass

    def _begin(self):
        self.conn.cursor().execute("BEGIN IMMEDIATE")

    def _commit(self):
        self.conn.commit()

    def _rollback_quiet(self):
        try:
            self.conn.rollback()
        except Exception:
            pass

    def _row_to_dict(self, columns, row):
        return dict(zip(columns, row))

    def _rows_to_dicts(self, columns, rows):
        return [self._row_to_dict(columns, row) for row in rows]

    def _reply_queue_for_source(self, source, engine_ctrl_queue, sensor_ctrl_queue,
                                relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        return {
            "engine": engine_ctrl_queue,
            "sensor": sensor_ctrl_queue,
            "relay": relay_ctrl_queue,
            "ui": ui_ctrl_queue,
            "web": web_ctrl_queue,
        }.get(source)

    def _make_response(self, msg, msg_type, payload):
        return Message(
            "db",
            msg_type,
            payload,
            target=msg.source,
            request_id=msg.request_id
        )

    def _reply_to_source(self, msg, resp, engine_ctrl_queue, sensor_ctrl_queue,
                         relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        q = self._reply_queue_for_source(
            msg.source,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

        if q is None:
            print("[DB] WARNING: unknown reply target source=%r" % (msg.source,))
            return

        try:
            q.put(resp)
        except Exception as e:
            print("[DB] WARNING: failed reply to %r: %s" % (msg.source, e))

    def handle_get_setting(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                           ui_ctrl_queue, web_ctrl_queue):
        key = (msg.payload or {}).get("key")
        val = self.settings.get(key)

        resp = self._make_response(msg, "setting_value", {
            "key": key,
            "value": val
        })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_programs(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                            ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}
        system = str(p.get("system") or "").upper()
        schedule_set_name = str(p.get("schedule_set_name") or "NORMAL").strip().upper()

        if system not in ("CH", "HW"):
            resp = self._make_response(msg, "programs_result", {
                "ok": False,
                "error": "invalid system",
                "system": system,
                "schedule_set_name": schedule_set_name,
                "items": []
            })
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            items = self._fetch_all_dicts(
                self.PROGRAM_COLUMNS,
                """
                SELECT id, schedule_set_name, system, start_time, end_time,
                       days, setpoint, warmup, note, enabled
                FROM schedule_entries
                WHERE schedule_set_name = ?
                  AND system = ?
                ORDER BY start_time ASC, id ASC
                """,
                (schedule_set_name, system)
            )

            resp = self._make_response(msg, "programs_result", {
                "ok": True,
                "system": system,
                "schedule_set_name": schedule_set_name,
                "items": items
            })

        except Exception as e:
            resp = self._make_response(msg, "programs_result", {
                "ok": False,
                "error": str(e),
                "system": system,
                "schedule_set_name": schedule_set_name,
                "items": []
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                           ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}
        try:
            program_id = int(p.get("id"))
        except Exception:
            program_id = None

        if program_id is None:
            resp = self._make_response(msg, "program_result", {
                "ok": False,
                "error": "Invalid program id"
            })
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            item = self._fetch_one_dict(
                self.PROGRAM_COLUMNS,
                """
                SELECT id, schedule_set_name, system, start_time, end_time,
                       days, setpoint, warmup, note, enabled
                FROM schedule_entries
                WHERE id = ?
                LIMIT 1
                """,
                (program_id,)
            )

            if item is None:
                resp = self._make_response(msg, "program_result", {
                    "ok": False,
                    "error": "Program not found",
                    "id": program_id
                })
            else:
                resp = self._make_response(msg, "program_result", {
                    "ok": True,
                    "item": item
                })

        except Exception as e:
            resp = self._make_response(msg, "program_result", {
                "ok": False,
                "error": str(e),
                "id": program_id
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_create_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                              ui_ctrl_queue, web_ctrl_queue):
        try:
            data = self._parse_program_payload(msg.payload, require_id=False)

            if data["schedule_set_name"] != "NORMAL":
                self._ensure_schedule_set_exists(data["schedule_set_name"])

            new_id = self._insert_row(
                "schedule_entries",
                "schedule_set_name, system, start_time, end_time, days, setpoint, warmup, note, enabled",
                (
                    data["schedule_set_name"],
                    data["system"],
                    data["start_time"],
                    data["end_time"],
                    data["days"],
                    data["setpoint"],
                    data["warmup"],
                    data["note"],
                    data["enabled"],
                )
            )

            resp = self._ok_id_response(msg, "create_program_result", new_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "create_program_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                              ui_ctrl_queue, web_ctrl_queue):
        try:
            data = self._parse_program_payload(msg.payload, require_id=True)

            if data["schedule_set_name"] != "NORMAL":
                self._ensure_schedule_set_exists(data["schedule_set_name"])

            cur = self.conn.cursor()
            self._begin()
            cur.execute("""
                UPDATE schedule_entries
                SET schedule_set_name = ?,
                    start_time        = ?,
                    end_time          = ?,
                    days              = ?,
                    setpoint          = ?,
                    warmup            = ?,
                    note              = ?,
                    enabled           = ?
                WHERE id = ?
                  AND system = ?
            """, (
                data["schedule_set_name"],
                data["start_time"],
                data["end_time"],
                data["days"],
                data["setpoint"],
                data["warmup"],
                data["note"],
                data["enabled"],
                data["id"],
                data["system"],
            ))
            changed = cur.rowcount
            self._commit()

            if changed < 1:
                resp = self._error_response(msg, "update_program_result", "Program not found")
            else:
                resp = self._ok_id_response(msg, "update_program_result", data["id"])

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "update_program_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_delete_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                              ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            program_id = int(p.get("id"))
            system = str(p.get("system") or "").strip().upper()

            if system not in ("CH", "HW"):
                raise ValueError("Invalid system")

            cur = self.conn.cursor()
            self._begin()
            cur.execute(
                "DELETE FROM schedule_entries WHERE id = ? AND system = ?",
                (program_id, system)
            )
            changed = cur.rowcount
            self._commit()

            if changed < 1:
                resp = self._error_response(msg, "delete_program_result", "Program not found")
            else:
                resp = self._ok_id_response(msg, "delete_program_result", program_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "delete_program_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_copy_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                            ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            program_id = int(p.get("id"))
            system = str(p.get("system") or "").strip().upper()

            if system not in ("CH", "HW"):
                raise ValueError("Invalid system")

            row = self._fetch_one(
                """
                SELECT schedule_set_name, system, start_time, end_time, days, setpoint, warmup, note, enabled
                FROM schedule_entries
                WHERE id = ? AND system = ?
                LIMIT 1
                """,
                (program_id, system)
            )

            if not row:
                resp = self._error_response(msg, "copy_program_result", "Program not found")
            else:
                new_id = self._insert_row(
                    "schedule_entries",
                    "schedule_set_name, system, start_time, end_time, days, setpoint, warmup, note, enabled",
                    row
                )
                resp = self._ok_id_response(msg, "copy_program_result", new_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "copy_program_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_active_ch_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue,
                                     relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            now_epoch = float((msg.payload or {}).get("now_epoch", time.time()))
        except Exception:
            now_epoch = time.time()

        try:
            dt_now = datetime.datetime.fromtimestamp(now_epoch)
            weekday = dt_now.weekday()  # 0 = Mon
            yesterday = (weekday - 1) % 7
            hhmm = dt_now.strftime("%H:%M")

            cur = self.conn.cursor()
            cur.execute("""
                SELECT id,
                       schedule_set_name,
                       system,
                       start_time,
                       end_time,
                       days,
                       setpoint,
                       warmup,
                       note,
                       enabled
                FROM schedule_entries
                WHERE enabled = 1
                  AND system = 'CH'
                  AND (
                        (
                            instr(days, ?) > 0
                            AND start_time < end_time
                            AND start_time <= ?
                            AND ? < end_time
                        )
                        OR
                        (
                            instr(days, ?) > 0
                            AND start_time >= end_time
                            AND ? >= start_time
                        )
                        OR
                        (
                            instr(days, ?) > 0
                            AND start_time >= end_time
                            AND ? < end_time
                        )
                      )
                ORDER BY start_time ASC, id ASC
                LIMIT 1
            """, (
                str(weekday), hhmm, hhmm,
                str(weekday), hhmm,
                str(yesterday), hhmm
            ))

            row = cur.fetchone()

            if not row:
                resp = self._make_response(msg, "active_ch_program_result", {
                    "ok": True,
                    "item": None
                })
            else:
                resp = self._make_response(msg, "active_ch_program_result", {
                    "ok": True,
                    "item": self._row_to_dict(self.PROGRAM_COLUMNS, row)
                })

        except Exception as e:
            resp = self._make_response(msg, "active_ch_program_result", {
                "ok": False,
                "error": str(e),
                "item": None
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_program_setpoint(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                       ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            program_id = int(p.get("id"))
        except Exception:
            program_id = None

        if program_id is None:
            resp = self._error_response(msg, "update_program_setpoint_result", "Invalid program id")
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            setpoint = float(p.get("setpoint"))
        except Exception:
            resp = self._error_response(msg, "update_program_setpoint_result", "Invalid setpoint")
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            cur = self.conn.cursor()
            self._begin()
            cur.execute("""
                UPDATE schedule_entries
                SET setpoint = ?
                WHERE id = ?
            """, (setpoint, program_id))

            changed = cur.rowcount
            self._commit()

            if changed < 1:
                resp = self._error_response(
                    msg,
                    "update_program_setpoint_result",
                    "Program not found",
                    {"id": program_id}
                )
            else:
                ts_epoch = time.time()
                ts_text = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts_epoch))
                self.state_buf.append(
                    (ts_epoch, ts_text, "PROGRAM", "Program %s setpoint=%.1f" % (program_id, setpoint))
                )

                resp = self._ok_id_response(
                    msg,
                    "update_program_setpoint_result",
                    program_id,
                    {"setpoint": setpoint}
                )

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "update_program_setpoint_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def _push_setting_changed(self, key, value, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        msg = Message("db", "setting_changed", {"key": key, "value": value})
        for q in (engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
            try:
                q.put(msg)
            except Exception:
                pass

    def handle_set_setting(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                           web_ctrl_queue):
        p = msg.payload or {}
        key = p.get("key")
        value = p.get("value")

        if not key:
            print("[DB] WARNING: set_setting missing key")
            return

        ok, final_val = self._validate_or_default(key, value)
        self.settings[key] = final_val
        self.dirty.add(key)

        self.flush_settings()

        self._push_setting_changed(
            key, final_val,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

        ts_epoch = time.time()
        ts_text = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts_epoch))
        state_msg = "Setting %s=%s" % (key, final_val)
        if not ok:
            state_msg = "Invalid %s=%s -> default %s" % (key, value, final_val)
        self.state_buf.append((ts_epoch, ts_text, "SETTINGS", state_msg))

    def handle_temperature_log(self, msg):
        data = msg.payload or {}
        ts_epoch = data.get("timestamp", time.time())
        ts_text = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts_epoch))
        source = msg.source
        value = data.get("value")
        try:
            value = float(value)
        except Exception:
            return
        self.temp_buf.append((ts_epoch, ts_text, source, value))

    def handle_state_change(self, msg):
        data = msg.payload or {}
        ts_epoch = data.get("timestamp", time.time())
        ts_text = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts_epoch))
        system = data.get("system", "SYSTEM")
        state = data.get("state", "")
        self.state_buf.append((ts_epoch, ts_text, system, state))

    def handle_heartbeat(self, msg, supervisor_queue):
        #HEARTBEAT to DB
        #ts_epoch = getattr(msg, "timestamp", time.time())
        #ts_text = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts_epoch))
        #self.heartbeat_buf.append((ts_epoch, ts_text, msg.source))

        # Forward to supervisor (watchdog)
        try:
            supervisor_queue.put(Message("db", "heartbeat_notice", {"source": msg.source}))
        except Exception:
            pass

    def handle_cleanup_expired_overrides(self, msg):
        now_epoch = None
        try:
            now_epoch = float((msg.payload or {}).get("now_epoch", time.time()))
        except Exception:
            now_epoch = time.time()

        cur = self.conn.cursor()
        try:
            self._begin()
            cur.execute("DELETE FROM away_periods WHERE enabled=1 AND end_ts_epoch < ?", (now_epoch,))
            cur.execute("DELETE FROM special_periods WHERE enabled=1 AND end_ts_epoch < ?", (now_epoch,))
            self._commit()
        except Exception:
            self._rollback_quiet()
            # keep quiet-ish; or log if you prefer

    def handle_get_state_log(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                             ui_ctrl_queue, web_ctrl_queue):
        try:
            req_date = (msg.payload or {}).get("date")
            day_used, items = self._get_log_items_for_day(
                "state_log",
                self.STATE_LOG_COLUMNS,
                req_date
            )

            resp = self._make_response(msg, "state_log_result", {
                "ok": True,
                "date": day_used,
                "items": items
            })
        except Exception as e:
            resp = self._make_response(msg, "state_log_result", {
                "ok": False,
                "error": str(e),
                "items": []
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_temperature_log(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                   ui_ctrl_queue, web_ctrl_queue):
        try:
            req_date = (msg.payload or {}).get("date")
            day_used, items = self._get_log_items_for_day(
                "temperature_log",
                self.TEMPERATURE_LOG_COLUMNS,
                req_date
            )

            resp = self._make_response(msg, "temperature_log_result", {
                "ok": True,
                "date": day_used,
                "items": items
            })
        except Exception as e:
            resp = self._make_response(msg, "temperature_log_result", {
                "ok": False,
                "error": str(e),
                "items": []
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def _parse_systems_csv(self, systems):
        return set([x.strip().upper() for x in str(systems or "").split(",") if x.strip()])

    def _systems_overlap(self, a, b):
        return len(self._parse_systems_csv(a).intersection(self._parse_systems_csv(b))) > 0

    def _normalise_systems(self, systems):
        vals = []
        for x in str(systems or "").split(","):
            x = x.strip().upper()
            if x in ("CH", "HW") and x not in vals:
                vals.append(x)
        return ",".join(vals)

    def _parse_epoch(self, value):
        if value is None or value == "":
            raise ValueError("Missing date/time")
        return float(value)

    def _validate_period(self, start_ts_epoch, end_ts_epoch):
        if end_ts_epoch <= start_ts_epoch:
            raise ValueError("End must be after start")

    def handle_get_schedule_sets(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                 ui_ctrl_queue, web_ctrl_queue):
        try:
            items = self._fetch_all_dicts(
                self.SCHEDULE_SET_COLUMNS,
                """
                SELECT name, enabled, note
                FROM schedule_sets
                ORDER BY name ASC
                """
            )

            resp = self._make_response(msg, "schedule_sets_result", {
                "ok": True,
                "items": items
            })
        except Exception as e:
            resp = self._make_response(msg, "schedule_sets_result", {
                "ok": False,
                "error": str(e),
                "items": []
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_holidays(self, msg, engine_ctrl_queue, sensor_ctrl_queue,
                            relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            items = self._fetch_all_dicts(
                self.HOLIDAY_COLUMNS,
                """
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch,
                       end_ts_text, systems, enabled, note
                FROM away_periods
                ORDER BY start_ts_epoch DESC, id DESC
                """
            )

            resp = self._make_response(msg, "holidays_result", {
                "ok": True,
                "items": items
            })
        except Exception as e:
            resp = self._make_response(msg, "holidays_result", {
                "ok": False,
                "error": str(e),
                "items": []
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                           ui_ctrl_queue, web_ctrl_queue):
        try:
            holiday_id = int((msg.payload or {}).get("id"))
            item = self._fetch_one_dict(
                self.HOLIDAY_COLUMNS,
                """
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch,
                       end_ts_text, systems, enabled, note
                FROM away_periods
                WHERE id = ?
                LIMIT 1
                """,
                (holiday_id,)
            )

            if item is None:
                resp = self._make_response(msg, "holiday_result", {
                    "ok": False,
                    "error": "Holiday not found"
                })
            else:
                resp = self._make_response(msg, "holiday_result", {
                    "ok": True,
                    "item": item
                })
        except Exception as e:
            resp = self._make_response(msg, "holiday_result", {
                "ok": False,
                "error": str(e)
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_create_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                              ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            start_ts_epoch = self._parse_epoch(p.get("start_ts_epoch"))
            end_ts_epoch = self._parse_epoch(p.get("end_ts_epoch"))
            start_ts_text = str(p.get("start_ts_text") or "").strip()
            end_ts_text = str(p.get("end_ts_text") or "").strip()
            systems = self._normalise_systems(p.get("systems"))
            enabled = 1 if p.get("enabled") else 0
            note = str(p.get("note") or "").strip()

            self._validate_period(start_ts_epoch, end_ts_epoch)

            if not systems:
                raise ValueError("Systems required")

            if enabled:
                overlap_id = self._find_overlapping_holiday(
                    start_ts_epoch, end_ts_epoch, systems
                )
                if overlap_id is not None:
                    raise ValueError("Overlaps existing holiday #%s" % overlap_id)

            new_id = self._insert_row(
                "away_periods",
                "start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note",
                (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note)
            )

            resp = self._ok_id_response(msg, "create_holiday_result", new_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "create_holiday_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                              ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            holiday_id = int(p.get("id"))
            start_ts_epoch = self._parse_epoch(p.get("start_ts_epoch"))
            end_ts_epoch = self._parse_epoch(p.get("end_ts_epoch"))
            start_ts_text = str(p.get("start_ts_text") or "").strip()
            end_ts_text = str(p.get("end_ts_text") or "").strip()
            systems = self._normalise_systems(p.get("systems"))
            enabled = 1 if p.get("enabled") else 0
            note = str(p.get("note") or "").strip()

            self._validate_period(start_ts_epoch, end_ts_epoch)

            if not systems:
                raise ValueError("Systems required")

            if enabled:
                overlap_id = self._find_overlapping_holiday(
                    start_ts_epoch, end_ts_epoch, systems, exclude_id=holiday_id
                )
                if overlap_id is not None:
                    raise ValueError("Overlaps existing holiday #%s" % overlap_id)

            changed = self._update_row_by_id(
                "away_periods",
                "start_ts_epoch=?, start_ts_text=?, end_ts_epoch=?, end_ts_text=?, systems=?, enabled=?, note=?",
                (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note),
                holiday_id
            )

            if changed < 1:
                resp = self._error_response(msg, "update_holiday_result", "Holiday not found")
            else:
                resp = self._ok_id_response(msg, "update_holiday_result", holiday_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "update_holiday_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_delete_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                              ui_ctrl_queue, web_ctrl_queue):
        try:
            holiday_id = int((msg.payload or {}).get("id"))

            changed = self._delete_by_id("away_periods", holiday_id)

            if changed < 1:
                resp = self._error_response(msg, "delete_holiday_result", "Holiday not found")
            else:
                resp = self._ok_id_response(msg, "delete_holiday_result", holiday_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "delete_holiday_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_copy_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                            ui_ctrl_queue, web_ctrl_queue):
        try:
            holiday_id = int((msg.payload or {}).get("id"))

            row = self._fetch_one(
                """
                SELECT start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, note
                FROM away_periods
                WHERE id = ?
                LIMIT 1
                """,
                (holiday_id,)
            )

            if not row:
                resp = self._error_response(msg, "copy_holiday_result", "Holiday not found")
            else:
                new_id = self._insert_row(
                    "away_periods",
                    "start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note",
                    (row[0], row[1], row[2], row[3], row[4], 0, row[5])
                )
                resp = self._ok_id_response(msg, "copy_holiday_result", new_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "copy_holiday_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_special_periods(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                   ui_ctrl_queue, web_ctrl_queue):
        try:
            items = self._fetch_all_dicts(
                self.SPECIAL_PERIOD_COLUMNS,
                """
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch,
                       end_ts_text, systems, schedule_set_name, enabled, note
                FROM special_periods
                ORDER BY start_ts_epoch DESC, id DESC
                """
            )

            resp = self._make_response(msg, "special_periods_result", {
                "ok": True,
                "items": items
            })
        except Exception as e:
            resp = self._make_response(msg, "special_periods_result", {
                "ok": False,
                "error": str(e),
                "items": []
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                  ui_ctrl_queue, web_ctrl_queue):
        try:
            item_id = int((msg.payload or {}).get("id"))
            item = self._fetch_one_dict(
                self.SPECIAL_PERIOD_COLUMNS,
                """
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch,
                       end_ts_text, systems, schedule_set_name, enabled, note
                FROM special_periods
                WHERE id = ?
                LIMIT 1
                """,
                (item_id,)
            )

            if item is None:
                resp = self._make_response(msg, "special_period_result", {
                    "ok": False,
                    "error": "Special period not found"
                })
            else:
                resp = self._make_response(msg, "special_period_result", {
                    "ok": True,
                    "item": item
                })
        except Exception as e:
            resp = self._make_response(msg, "special_period_result", {
                "ok": False,
                "error": str(e)
            })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_create_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                     ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            start_ts_epoch = self._parse_epoch(p.get("start_ts_epoch"))
            end_ts_epoch = self._parse_epoch(p.get("end_ts_epoch"))
            start_ts_text = str(p.get("start_ts_text") or "").strip()
            end_ts_text = str(p.get("end_ts_text") or "").strip()
            systems = self._normalise_systems(p.get("systems"))
            schedule_set_name = str(p.get("schedule_set_name") or "").strip().upper()
            enabled = 1 if p.get("enabled") else 0
            note = str(p.get("note") or "").strip()

            self._validate_period(start_ts_epoch, end_ts_epoch)

            if not systems:
                raise ValueError("Systems required")
            if not schedule_set_name:
                raise ValueError("Schedule set name required")
            if schedule_set_name == "NORMAL":
                raise ValueError("NORMAL cannot be used as a special schedule")

            if enabled:
                overlap_id = self._find_overlapping_special(
                    start_ts_epoch, end_ts_epoch, systems, exclude_id=None
                )
                if overlap_id is not None:
                    raise ValueError("Overlaps existing special period #%s" % overlap_id)

            self._ensure_schedule_set_exists(schedule_set_name)

            new_id = self._insert_row(
                "special_periods",
                "start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, schedule_set_name, enabled, note",
                (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text,
                 systems, schedule_set_name, enabled, note)
            )

            resp = self._ok_id_response(msg, "create_special_period_result", new_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "create_special_period_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                     ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            item_id = int(p.get("id"))
            start_ts_epoch = self._parse_epoch(p.get("start_ts_epoch"))
            end_ts_epoch = self._parse_epoch(p.get("end_ts_epoch"))
            start_ts_text = str(p.get("start_ts_text") or "").strip()
            end_ts_text = str(p.get("end_ts_text") or "").strip()
            systems = self._normalise_systems(p.get("systems"))
            schedule_set_name = str(p.get("schedule_set_name") or "").strip().upper()
            enabled = 1 if p.get("enabled") else 0
            note = str(p.get("note") or "").strip()

            self._validate_period(start_ts_epoch, end_ts_epoch)

            if not systems:
                raise ValueError("Systems required")
            if not schedule_set_name:
                raise ValueError("Schedule set name required")
            if schedule_set_name == "NORMAL":
                raise ValueError("NORMAL cannot be used as a special schedule")

            if enabled:
                overlap_id = self._find_overlapping_special(
                    start_ts_epoch, end_ts_epoch, systems, exclude_id=item_id
                )
                if overlap_id is not None:
                    raise ValueError("Overlaps existing special period #%s" % overlap_id)

            self._ensure_schedule_set_exists(schedule_set_name)

            changed = self._update_row_by_id(
                "special_periods",
                "start_ts_epoch=?, start_ts_text=?, end_ts_epoch=?, end_ts_text=?, systems=?, schedule_set_name=?, enabled=?, note=?",
                (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text,
                 systems, schedule_set_name, enabled, note),
                item_id
            )

            if changed < 1:
                resp = self._error_response(msg, "update_special_period_result", "Special period not found")
            else:
                resp = self._ok_id_response(msg, "update_special_period_result", item_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "update_special_period_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_delete_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                     ui_ctrl_queue, web_ctrl_queue):
        try:
            item_id = int((msg.payload or {}).get("id"))

            changed = self._delete_by_id("special_periods", item_id)

            if changed < 1:
                resp = self._error_response(msg, "delete_special_period_result", "Special period not found")
            else:
                resp = self._ok_id_response(msg, "delete_special_period_result", item_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "delete_special_period_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_copy_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                   ui_ctrl_queue, web_ctrl_queue):
        try:
            item_id = int((msg.payload or {}).get("id"))

            row = self._fetch_one(
                """
                SELECT start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text,
                       systems, schedule_set_name, note
                FROM special_periods
                WHERE id = ?
                LIMIT 1
                """,
                (item_id,)
            )

            if not row:
                resp = self._error_response(msg, "copy_special_period_result", "Special period not found")
            else:
                new_id = self._insert_row(
                    "special_periods",
                    "start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, schedule_set_name, enabled, note",
                    (row[0], row[1], row[2], row[3], row[4], row[5], 0, row[6])
                )
                resp = self._ok_id_response(msg, "copy_special_period_result", new_id)

        except Exception as e:
            self._rollback_quiet()
            resp = self._error_response(msg, "copy_special_period_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_request_settings_snapshot(self, msg, engine_ctrl_queue, sensor_ctrl_queue,
                                         relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        resp = self._make_response(msg, "settings_snapshot", {
            "values": dict(self.settings)
        })

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_request_system_action(self, msg, engine_ctrl_queue, sensor_ctrl_queue,
                                     relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue,
                                     supervisor_queue):
        p = msg.payload or {}
        action = str(p.get("action") or "").strip().lower()

        if msg.source not in ("ui", "web"):
            resp = self._error_response(msg, "system_action_result", "Invalid source")
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        if action not in ("restart_dwellpi", "reboot_pi"):
            resp = self._error_response(msg, "system_action_result", "Invalid action")
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            supervisor_queue.put(Message(
                "db",
                "system_action_request",
                {
                    "action": action,
                    "source": msg.source
                },
                request_id=msg.request_id
            ))

            resp = self._make_response(msg, "system_action_result", {
                "ok": True,
                "action": action,
                "status": "accepted"
            })
        except Exception as e:
            resp = self._error_response(msg, "system_action_result", str(e))

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def run(self, queue, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
            ui_ctrl_queue, web_ctrl_queue, supervisor_queue, shutdown_event):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.connect()
        self.load_settings_cache()

        # Push snapshot FIRST so engine/sensor/relay/ui/web can start without RPC
        self.send_settings_snapshot(
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

        try:
            supervisor_queue.put(Message("db", "db_ready", {"ts": time.time()}))
        except Exception:
            pass

        print("[DB] Worker started: %s : mode=%s" % (self.db_path, self.mode))
        self.last_log_flush = time.time()

        handler_map = {
            "request_settings_snapshot": self.handle_request_settings_snapshot,
            "get_setting": self.handle_get_setting,
            "set_setting": self.handle_set_setting,
            "get_programs": self.handle_get_programs,
            "get_program": self.handle_get_program,
            "get_active_ch_program": self.handle_get_active_ch_program,
            "update_program_setpoint": self.handle_update_program_setpoint,
            "create_program": self.handle_create_program,
            "update_program": self.handle_update_program,
            "delete_program": self.handle_delete_program,
            "copy_program": self.handle_copy_program,
            "get_state_log": self.handle_get_state_log,
            "get_temperature_log": self.handle_get_temperature_log,
            "get_schedule_sets": self.handle_get_schedule_sets,
            "get_holidays": self.handle_get_holidays,
            "get_holiday": self.handle_get_holiday,
            "create_holiday": self.handle_create_holiday,
            "update_holiday": self.handle_update_holiday,
            "delete_holiday": self.handle_delete_holiday,
            "copy_holiday": self.handle_copy_holiday,
            "get_special_periods": self.handle_get_special_periods,
            "get_special_period": self.handle_get_special_period,
            "create_special_period": self.handle_create_special_period,
            "update_special_period": self.handle_update_special_period,
            "delete_special_period": self.handle_delete_special_period,
            "copy_special_period": self.handle_copy_special_period,
            "request_system_action": self.handle_request_system_action,
        }

        while not shutdown_event.is_set():
            try:
                now = time.time()

                # --- Auto-Prune Logic (Once every 24 hours) ---
                if (now - self.last_prune_ts) > 86400:
                    self.prune_old_data(days_to_keep=30)
                    self.last_prune_ts = now

                # flush logs periodically even if no messages arrive
                self.flush_logs_if_due(force=False)

                msg = queue.get(timeout=1)

                if msg.type == "heartbeat":
                    self.handle_heartbeat(msg, supervisor_queue)
                    continue

                if msg.type == "temperature":
                    self.handle_temperature_log(msg)
                    continue

                if msg.type == "state_change":
                    self.handle_state_change(msg)
                    continue

                if msg.type == "flush":
                    self.flush_settings()
                    self.flush_logs_if_due(force=True)
                    continue

                if msg.type == "cleanup_expired_overrides":
                    self.handle_cleanup_expired_overrides(msg)
                    continue

                if msg.type == "shutdown":
                    break

                handler = handler_map.get(msg.type)

                if handler is None:
                    print("[DB] WARNING: unknown message type %r from %r" % (msg.type, msg.source))
                    continue

                if msg.type == "request_system_action":
                    handler(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                        ui_ctrl_queue, web_ctrl_queue, supervisor_queue
                    )
                else:
                    handler(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                        ui_ctrl_queue, web_ctrl_queue
                    )

            except QueueEmpty:
                continue
            except Exception:
                print("[DB] Worker error")
                traceback.print_exc()
                time.sleep(1)

        # shutdown flush
        try:
            self.flush_settings()
            self.flush_logs_if_due(force=True)
        except Exception:
            pass

        print("[DB] Worker stopped")