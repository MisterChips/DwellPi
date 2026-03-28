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
import calendar

try:
    # reuse your validation + schema
    from db_init import SETTINGS_SCHEMA, validate_setting
except Exception:
    SETTINGS_SCHEMA = {}
    def validate_setting(key, value, schema):
        return True


class DBWorker(object):
    def __init__(self, db_path, mode):
        self.db_path = db_path
        self.mode = mode
        self.running = True
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

        # ensure tables exist (init script should do this, but harmless here)
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

    def prune_old_data(self, days_to_keep=30):
        now = time.time()
        # 86400 seconds in a day
        cutoff_epoch = now - (days_to_keep * 86400)

        cur = self.conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")

            # Delete old temperatures
            cur.execute("DELETE FROM temperature_log WHERE ts_epoch < ?", (cutoff_epoch,))
            temp_deleted = cur.rowcount

            # Delete old state changes
            cur.execute("DELETE FROM state_log WHERE ts_epoch < ?", (cutoff_epoch,))
            state_deleted = cur.rowcount

            self.conn.commit()

            if temp_deleted > 0 or state_deleted > 0:
                print("[DB] Pruning Complete: Removed %d temp rows and %d state rows." %
                      (temp_deleted, state_deleted))

                # Optional: If you deleted a HUGE amount of data (e.g. first prune)
                # you can run VACUUM, but it's slow. Usually not needed daily.
                # self.conn.execute("VACUUM")

        except Exception:
            self.conn.rollback()
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

        start_epoch = calendar.timegm(start_dt.timetuple())
        end_epoch = calendar.timegm(end_dt.timetuple())

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
            cur.execute("BEGIN IMMEDIATE")
            for key in keys:
                val = self.settings.get(key)
                cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val))
            self.conn.commit()
            self.dirty.clear()
            print("[DB] Flushed settings:", keys)
        except Exception:
            self.conn.rollback()
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
            cur.execute("BEGIN IMMEDIATE")

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

            self.conn.commit()
            self.last_log_flush = now
            # print("[DB] Log flush OK")
        except Exception:
            self.conn.rollback()
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

    def _reply_to_source(self, msg, resp, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                         web_ctrl_queue):
        if msg.source == "engine":
            engine_ctrl_queue.put(resp)
        elif msg.source == "sensor":
            sensor_ctrl_queue.put(resp)
        elif msg.source == "relay":
            relay_ctrl_queue.put(resp)
        elif msg.source == "ui":
            ui_ctrl_queue.put(resp)
        elif msg.source == "web":
            web_ctrl_queue.put(resp)

    def handle_get_setting(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                           web_ctrl_queue):
        key = msg.payload.get("key")
        val = self.settings.get(key)

        resp = Message(
            source="db",
            msg_type="setting_value",
            payload={"key": key, "value": val},
            target=msg.source,
            request_id=msg.request_id
        )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_programs(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                            web_ctrl_queue):
        p = msg.payload or {}
        system = str(p.get("system") or "").upper()
        schedule_set_name = str(p.get("schedule_set_name") or "NORMAL").strip().upper()

        if system not in ("CH", "HW"):
            resp = Message(
                "db",
                "programs_result",
                {
                    "ok": False,
                    "error": "invalid system",
                    "system": system,
                    "schedule_set_name": schedule_set_name,
                    "items": []
                },
                target=msg.source,
                request_id=msg.request_id
            )
            print("[DB] programs_result -> %s ok=%s items=%s" % (
                msg.source,
                resp.payload.get("ok"),
                len(resp.payload.get("items") or [])
            ))
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            items = []
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
                        WHERE schedule_set_name = ?
                          AND system = ?
                        ORDER BY start_time ASC, id ASC
                        """, (schedule_set_name, system))

            rows = cur.fetchall()
            for r in rows:
                items.append({
                    "id": r[0],
                    "schedule_set_name": r[1],
                    "system": r[2],
                    "start_time": r[3],
                    "end_time": r[4],
                    "days": r[5],
                    "setpoint": r[6],
                    "warmup": r[7],
                    "note": r[8],
                    "enabled": r[9],
                })
            resp = Message(
                "db",
                "programs_result",
                {
                    "ok": True,
                    "system": system,
                    "schedule_set_name": schedule_set_name,
                    "items": items
                },
                target=msg.source,
                request_id=msg.request_id
            )

        except Exception as e:
            resp = Message(
                "db",
                "programs_result",
                {
                    "ok": False,
                    "error": str(e),
                    "system": system,
                    "schedule_set_name": schedule_set_name,
                    "items": []
                },
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                           web_ctrl_queue):
        p = msg.payload or {}
        try:
            program_id = int(p.get("id"))
        except Exception:
            program_id = None

        if program_id is None:
            resp = Message(
                "db",
                "program_result",
                {"ok": False, "error": "Invalid program id"},
                target=msg.source,
                request_id=msg.request_id
            )
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

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
                    WHERE id = ?
                    LIMIT 1
                    """, (program_id,))
        row = cur.fetchone()

        if not row:
            resp = Message(
                "db",
                "program_result",
                {"ok": False, "error": "Program not found", "id": program_id},
                target=msg.source,
                request_id=msg.request_id
            )
        else:
            resp = Message(
                "db",
                "program_result",
                {
                    "ok": True,
                    "item": {
                        "id": row[0],
                        "schedule_set_name": row[1],
                        "system": row[2],
                        "start_time": row[3],
                        "end_time": row[4],
                        "days": row[5],
                        "setpoint": row[6],
                        "warmup": row[7],
                        "note": row[8],
                        "enabled": row[9],
                    }
                },
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_create_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                              web_ctrl_queue):
        p = msg.payload or {}

        try:
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
                setpoint = float(p.get("setpoint"))
                warmup = 1 if p.get("warmup") else 0
            else:
                setpoint = None
                warmup = 0

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("""
                        INSERT INTO schedule_entries
                        (schedule_set_name, system, start_time, end_time, days, setpoint, warmup, note, enabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (schedule_set_name, system, start_time, end_time, days, setpoint, warmup, note, enabled))
            new_id = cur.lastrowid
            self.conn.commit()

            resp = Message(
                "db",
                "create_program_result",
                {"ok": True, "id": new_id},
                target=msg.source,
                request_id=msg.request_id
            )

        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "create_program_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                              web_ctrl_queue):
        p = msg.payload or {}

        try:
            program_id = int(p.get("id"))
            start_time = str(p.get("start_time") or "").strip()
            end_time = str(p.get("end_time") or "").strip()
            days = str(p.get("days") or "").strip()
            note = str(p.get("note") or "").strip()
            schedule_set_name = str(p.get("schedule_set_name") or "NORMAL").strip().upper()
            enabled = 1 if p.get("enabled") else 0
            system = str(p.get("system") or "").strip().upper()

            if system not in ("CH", "HW"):
                raise ValueError("Invalid system")

            if not start_time or not end_time or not days:
                raise ValueError("Missing required fields")

            if system == "CH":
                setpoint = float(p.get("setpoint"))
                warmup = 1 if p.get("warmup") else 0
            else:
                setpoint = None
                warmup = 0

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
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
                        """,
                        (schedule_set_name, start_time, end_time, days, setpoint, warmup, note, enabled, program_id,
                         system))
            changed = cur.rowcount
            self.conn.commit()

            if changed < 1:
                resp = Message(
                    "db",
                    "update_program_result",
                    {"ok": False, "error": "Program not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "update_program_result",
                    {"ok": True, "id": program_id},
                    target=msg.source,
                    request_id=msg.request_id
                )

        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "update_program_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_delete_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            program_id = int(p.get("id"))

            system = str(p.get("system") or "").strip().upper()

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("DELETE FROM schedule_entries WHERE id = ? AND system = ?", (program_id,system,))
            changed = cur.rowcount
            self.conn.commit()

            if changed < 1:
                resp = Message(
                    "db",
                    "delete_program_result",
                    {"ok": False, "error": "Program not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "delete_program_result",
                    {"ok": True, "id": program_id},
                    target=msg.source,
                    request_id=msg.request_id
                )

        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "delete_program_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_copy_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        p = msg.payload or {}

        try:
            program_id = int(p.get("id"))

            system = str(p.get("system") or "").strip().upper()

            cur = self.conn.cursor()
            cur.execute("""
                SELECT schedule_set_name, system, start_time, end_time, days, setpoint, warmup, note, enabled
                FROM schedule_entries
                WHERE id = ? AND system = ?
                LIMIT 1
            """, (program_id,system,))
            row = cur.fetchone()

            if not row:
                resp = Message(
                    "db",
                    "copy_program_result",
                    {"ok": False, "error": "Program not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute("""
                    INSERT INTO schedule_entries
                    (schedule_set_name, system, start_time, end_time, days, setpoint, warmup, note, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, row)
                new_id = cur.lastrowid
                self.conn.commit()

                resp = Message(
                    "db",
                    "copy_program_result",
                    {"ok": True, "id": new_id},
                    target=msg.source,
                    request_id=msg.request_id
                )

        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "copy_program_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_active_ch_program(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                                     web_ctrl_queue):
        try:
            now_epoch = float((msg.payload or {}).get("now_epoch", time.time()))
        except Exception:
            now_epoch = time.time()

        try:
            from datetime import datetime
            dt = datetime.fromtimestamp(now_epoch)
            weekday = dt.weekday()   # 0 = Mon
            hhmm = dt.strftime("%H:%M")

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
                          AND instr(days, ?) > 0
                          AND start_time <= ?
                          AND ? < end_time
                        ORDER BY start_time ASC, id ASC
                        LIMIT 1
                        """, (str(weekday), hhmm, hhmm))

            row = cur.fetchone()

            if not row:
                resp = Message(
                    "db",
                    "active_ch_program_result",
                    {"ok": True, "item": None},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "active_ch_program_result",
                    {
                        "ok": True,
                        "item": {
                            "id": row[0],
                            "schedule_set_name": row[1],
                            "system": row[2],
                            "start_time": row[3],
                            "end_time": row[4],
                            "days": row[5],
                            "setpoint": row[6],
                            "warmup": row[7],
                            "note": row[8],
                            "enabled": row[9],
                        }
                    },
                    target=msg.source,
                    request_id=msg.request_id
                )

        except Exception as e:
            resp = Message(
                "db",
                "active_ch_program_result",
                {"ok": False, "error": str(e), "item": None},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_program_setpoint(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                                       web_ctrl_queue):
        p = msg.payload or {}

        try:
            program_id = int(p.get("id"))
        except Exception:
            program_id = None

        setpoint = p.get("setpoint")

        if program_id is None:
            resp = Message(
                "db",
                "update_program_setpoint_result",
                {"ok": False, "error": "Invalid program id"},
                target=msg.source,
                request_id=msg.request_id
            )
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            setpoint = float(setpoint)
        except Exception:
            resp = Message(
                "db",
                "update_program_setpoint_result",
                {"ok": False, "error": "Invalid setpoint"},
                target=msg.source,
                request_id=msg.request_id
            )
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        try:
            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("""
                        UPDATE schedule_entries
                        SET setpoint = ?
                        WHERE id = ?
                        """, (setpoint, program_id))

            changed = cur.rowcount
            self.conn.commit()

            if changed < 1:
                resp = Message(
                    "db",
                    "update_program_setpoint_result",
                    {"ok": False, "error": "Program not found", "id": program_id},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                ts_epoch = time.time()
                ts_text = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts_epoch))
                self.state_buf.append((ts_epoch, ts_text, "PROGRAM", "Program %s setpoint=%.1f" % (program_id, setpoint)))

                resp = Message(
                    "db",
                    "update_program_setpoint_result",
                    {"ok": True, "id": program_id, "setpoint": setpoint},
                    target=msg.source,
                    request_id=msg.request_id
                )

        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "update_program_setpoint_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

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

    def handle_set_setting(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        key = msg.payload.get("key")
        value = msg.payload.get("value")

        ok, final_val = self._validate_or_default(key, value)
        self.settings[key] = final_val
        self.dirty.add(key)

        self.flush_settings()

        # Push live update (DB push model)
        self._push_setting_changed(key, final_val, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                                   ui_ctrl_queue, web_ctrl_queue)

        # Audit buffered
        ts_epoch = time.time()
        ts_text = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(ts_epoch))
        state_msg = "Setting %s=%s" % (key, final_val)
        if not ok:
            state_msg = "Invalid %s=%s -> default %s" % (key, value, final_val)
        self.state_buf.append((ts_epoch, ts_text, "SETTINGS", state_msg))

    def handle_temperature_log(self, msg):
        data = msg.payload
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
        data = msg.payload
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
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("DELETE FROM away_periods WHERE enabled=1 AND end_ts_epoch < ?", (now_epoch,))
            cur.execute("DELETE FROM special_periods WHERE enabled=1 AND end_ts_epoch < ?", (now_epoch,))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            # keep quiet-ish; or log if you prefer

    def handle_get_state_log(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            req_date = (msg.payload or {}).get("date")
            start_epoch, end_epoch, day_used = self._get_day_range_epoch(req_date)

            cur = self.conn.cursor()
            cur.execute("""
                SELECT ts_epoch, ts, system, state
                FROM state_log
                WHERE ts_epoch >= ? AND ts_epoch < ?
                ORDER BY ts_epoch DESC
            """, (start_epoch, end_epoch))

            rows = cur.fetchall()
            items = []
            for row in rows:
                items.append({
                    "ts_epoch": row[0],
                    "ts": row[1],
                    "system": row[2],
                    "state": row[3]
                })

            resp = Message(
                "db",
                "state_log_result",
                {"ok": True, "date": day_used, "items": items},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            resp = Message(
                "db",
                "state_log_result",
                {"ok": False, "error": str(e), "items": []},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_temperature_log(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            req_date = (msg.payload or {}).get("date")
            start_epoch, end_epoch, day_used = self._get_day_range_epoch(req_date)

            cur = self.conn.cursor()
            cur.execute("""
                SELECT ts_epoch, ts, source, value
                FROM temperature_log
                WHERE ts_epoch >= ? AND ts_epoch < ?
                ORDER BY ts_epoch DESC
            """, (start_epoch, end_epoch))

            rows = cur.fetchall()
            items = []
            for row in rows:
                items.append({
                    "ts_epoch": row[0],
                    "ts": row[1],
                    "source": row[2],
                    "value": row[3]
                })

            resp = Message(
                "db",
                "temperature_log_result",
                {"ok": True, "date": day_used, "items": items},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            resp = Message(
                "db",
                "temperature_log_result",
                {"ok": False, "error": str(e), "items": []},
                target=msg.source,
                request_id=msg.request_id
            )

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

    def _find_overlapping_special(self, start_ts_epoch, end_ts_epoch, systems, exclude_id=None):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT id, start_ts_epoch, end_ts_epoch, systems
            FROM special_periods
            WHERE enabled = 1
        """)
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

    def handle_get_schedule_sets(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                                 web_ctrl_queue):
        try:
            cur = self.conn.cursor()
            cur.execute("""
                        SELECT name, enabled, note
                        FROM schedule_sets
                        ORDER BY name ASC
                        """)
            rows = cur.fetchall()

            items = []
            for row in rows:
                items.append({
                    "name": row[0],
                    "enabled": row[1],
                    "note": row[2],
                })

            resp = Message(
                "db",
                "schedule_sets_result",
                {"ok": True, "items": items},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            resp = Message(
                "db",
                "schedule_sets_result",
                {"ok": False, "error": str(e), "items": []},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def _find_overlapping_holiday(self, start_ts_epoch, end_ts_epoch, systems, exclude_id=None):
        cur = self.conn.cursor()
        cur.execute("""
                    SELECT id, start_ts_epoch, end_ts_epoch, systems
                    FROM away_periods
                    WHERE enabled = 1
                    """)
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

    def handle_get_holidays(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note
                FROM away_periods
                ORDER BY start_ts_epoch DESC, id DESC
            """)
            rows = cur.fetchall()

            items = []
            for row in rows:
                items.append({
                    "id": row[0],
                    "start_ts_epoch": row[1],
                    "start_ts_text": row[2],
                    "end_ts_epoch": row[3],
                    "end_ts_text": row[4],
                    "systems": row[5],
                    "enabled": row[6],
                    "note": row[7],
                })

            resp = Message(
                "db",
                "holidays_result",
                {"ok": True, "items": items},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            resp = Message(
                "db",
                "holidays_result",
                {"ok": False, "error": str(e), "items": []},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            holiday_id = int((msg.payload or {}).get("id"))
            cur = self.conn.cursor()
            cur.execute("""
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note
                FROM away_periods
                WHERE id = ?
                LIMIT 1
            """, (holiday_id,))
            row = cur.fetchone()

            if not row:
                resp = Message(
                    "db",
                    "holiday_result",
                    {"ok": False, "error": "Holiday not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "holiday_result",
                    {
                        "ok": True,
                        "item": {
                            "id": row[0],
                            "start_ts_epoch": row[1],
                            "start_ts_text": row[2],
                            "end_ts_epoch": row[3],
                            "end_ts_text": row[4],
                            "systems": row[5],
                            "enabled": row[6],
                            "note": row[7],
                        }
                    },
                    target=msg.source,
                    request_id=msg.request_id
                )
        except Exception as e:
            resp = Message(
                "db",
                "holiday_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_create_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
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

            overlap_id = self._find_overlapping_holiday(start_ts_epoch, end_ts_epoch, systems, exclude_id=None)
            if overlap_id is not None:
                raise ValueError("Overlaps existing holiday #%s" % overlap_id)

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("""
                INSERT INTO away_periods
                (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note))
            new_id = cur.lastrowid
            self.conn.commit()

            resp = Message(
                "db",
                "create_holiday_result",
                {"ok": True, "id": new_id},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "create_holiday_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
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

            overlap_id = self._find_overlapping_holiday(start_ts_epoch, end_ts_epoch, systems, exclude_id=holiday_id)
            if overlap_id is not None:
                raise ValueError("Overlaps existing holiday #%s" % overlap_id)

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("""
                UPDATE away_periods
                SET start_ts_epoch = ?,
                    start_ts_text = ?,
                    end_ts_epoch = ?,
                    end_ts_text = ?,
                    systems = ?,
                    enabled = ?,
                    note = ?
                WHERE id = ?
            """, (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note, holiday_id))
            changed = cur.rowcount
            self.conn.commit()

            if changed < 1:
                resp = Message(
                    "db",
                    "update_holiday_result",
                    {"ok": False, "error": "Holiday not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "update_holiday_result",
                    {"ok": True, "id": holiday_id},
                    target=msg.source,
                    request_id=msg.request_id
                )
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "update_holiday_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_delete_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            holiday_id = int((msg.payload or {}).get("id"))

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("DELETE FROM away_periods WHERE id = ?", (holiday_id,))
            changed = cur.rowcount
            self.conn.commit()

            if changed < 1:
                resp = Message(
                    "db",
                    "delete_holiday_result",
                    {"ok": False, "error": "Holiday not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "delete_holiday_result",
                    {"ok": True, "id": holiday_id},
                    target=msg.source,
                    request_id=msg.request_id
                )
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "delete_holiday_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_copy_holiday(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue,
                            web_ctrl_queue):
        try:
            holiday_id = int((msg.payload or {}).get("id"))

            cur = self.conn.cursor()
            cur.execute("""
                        SELECT start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note
                        FROM away_periods
                        WHERE id = ? LIMIT 1
                        """, (holiday_id,))
            row = cur.fetchone()

            if not row:
                resp = Message(
                    "db",
                    "copy_holiday_result",
                    {"ok": False, "error": "Holiday not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                overlap_id = self._find_overlapping_holiday(
                    float(row[0]), float(row[2]), row[4], exclude_id=None
                )

                if overlap_id is not None:
                    resp = Message(
                        "db",
                        "copy_holiday_result",
                        {"ok": False, "error": "Copied holiday would overlap existing holiday #%s" % overlap_id},
                        target=msg.source,
                        request_id=msg.request_id
                    )
                else:
                    cur.execute("BEGIN IMMEDIATE")
                    cur.execute("""
                                INSERT INTO away_periods
                                (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, enabled, note)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, row)
                    new_id = cur.lastrowid
                    self.conn.commit()

                    resp = Message(
                        "db",
                        "copy_holiday_result",
                        {"ok": True, "id": new_id},
                        target=msg.source,
                        request_id=msg.request_id
                    )

        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "copy_holiday_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_special_periods(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text,
                       systems, schedule_set_name, enabled, note
                FROM special_periods
                ORDER BY start_ts_epoch DESC, id DESC
            """)
            rows = cur.fetchall()

            items = []
            for row in rows:
                items.append({
                    "id": row[0],
                    "start_ts_epoch": row[1],
                    "start_ts_text": row[2],
                    "end_ts_epoch": row[3],
                    "end_ts_text": row[4],
                    "systems": row[5],
                    "schedule_set_name": row[6],
                    "enabled": row[7],
                    "note": row[8],
                })

            resp = Message(
                "db",
                "special_periods_result",
                {"ok": True, "items": items},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            resp = Message(
                "db",
                "special_periods_result",
                {"ok": False, "error": str(e), "items": []},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_get_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            item_id = int((msg.payload or {}).get("id"))
            cur = self.conn.cursor()
            cur.execute("""
                SELECT id, start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text,
                       systems, schedule_set_name, enabled, note
                FROM special_periods
                WHERE id = ?
                LIMIT 1
            """, (item_id,))
            row = cur.fetchone()

            if not row:
                resp = Message(
                    "db",
                    "special_period_result",
                    {"ok": False, "error": "Special period not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "special_period_result",
                    {
                        "ok": True,
                        "item": {
                            "id": row[0],
                            "start_ts_epoch": row[1],
                            "start_ts_text": row[2],
                            "end_ts_epoch": row[3],
                            "end_ts_text": row[4],
                            "systems": row[5],
                            "schedule_set_name": row[6],
                            "enabled": row[7],
                            "note": row[8],
                        }
                    },
                    target=msg.source,
                    request_id=msg.request_id
                )
        except Exception as e:
            resp = Message(
                "db",
                "special_period_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_create_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
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

            overlap_id = self._find_overlapping_special(start_ts_epoch, end_ts_epoch, systems, exclude_id=None)
            if overlap_id is not None:
                raise ValueError("Overlaps existing special period #%s" % overlap_id)

            cur = self.conn.cursor()
            cur.execute("SELECT name FROM schedule_sets WHERE name = ?", (schedule_set_name,))
            if cur.fetchone() is None:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    "INSERT INTO schedule_sets (name, enabled, note) VALUES (?, ?, ?)",
                    (schedule_set_name, 1, "")
                )
                self.conn.commit()

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("""
                INSERT INTO special_periods
                (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, schedule_set_name, enabled, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, schedule_set_name, enabled, note))
            new_id = cur.lastrowid
            self.conn.commit()

            resp = Message(
                "db",
                "create_special_period_result",
                {"ok": True, "id": new_id},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "create_special_period_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_update_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
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

            overlap_id = self._find_overlapping_special(start_ts_epoch, end_ts_epoch, systems, exclude_id=item_id)
            if overlap_id is not None:
                raise ValueError("Overlaps existing special period #%s" % overlap_id)

            cur = self.conn.cursor()
            cur.execute("SELECT name FROM schedule_sets WHERE name = ?", (schedule_set_name,))
            if cur.fetchone() is None:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    "INSERT INTO schedule_sets (name, enabled, note) VALUES (?, ?, ?)",
                    (schedule_set_name, 1, "")
                )
                self.conn.commit()

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("""
                UPDATE special_periods
                SET start_ts_epoch = ?,
                    start_ts_text = ?,
                    end_ts_epoch = ?,
                    end_ts_text = ?,
                    systems = ?,
                    schedule_set_name = ?,
                    enabled = ?,
                    note = ?
                WHERE id = ?
            """, (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, schedule_set_name, enabled, note, item_id))
            changed = cur.rowcount
            self.conn.commit()

            if changed < 1:
                resp = Message(
                    "db",
                    "update_special_period_result",
                    {"ok": False, "error": "Special period not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "update_special_period_result",
                    {"ok": True, "id": item_id},
                    target=msg.source,
                    request_id=msg.request_id
                )
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "update_special_period_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_delete_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            item_id = int((msg.payload or {}).get("id"))

            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("DELETE FROM special_periods WHERE id = ?", (item_id,))
            changed = cur.rowcount
            self.conn.commit()

            if changed < 1:
                resp = Message(
                    "db",
                    "delete_special_period_result",
                    {"ok": False, "error": "Special period not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                resp = Message(
                    "db",
                    "delete_special_period_result",
                    {"ok": True, "id": item_id},
                    target=msg.source,
                    request_id=msg.request_id
                )
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "delete_special_period_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )

    def handle_copy_special_period(self, msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue):
        try:
            item_id = int((msg.payload or {}).get("id"))

            cur = self.conn.cursor()
            cur.execute("""
                SELECT start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text,
                       systems, schedule_set_name, enabled, note
                FROM special_periods
                WHERE id = ?
                LIMIT 1
            """, (item_id,))
            row = cur.fetchone()

            if not row:
                resp = Message(
                    "db",
                    "copy_special_period_result",
                    {"ok": False, "error": "Special period not found"},
                    target=msg.source,
                    request_id=msg.request_id
                )
            else:
                overlap_id = self._find_overlapping_special(float(row[0]), float(row[2]), row[4], exclude_id=None)
                if overlap_id is not None:
                    resp = Message(
                        "db",
                        "copy_special_period_result",
                        {"ok": False, "error": "Copied period would overlap existing special period #%s" % overlap_id},
                        target=msg.source,
                        request_id=msg.request_id
                    )
                else:
                    cur.execute("BEGIN IMMEDIATE")
                    cur.execute("""
                        INSERT INTO special_periods
                        (start_ts_epoch, start_ts_text, end_ts_epoch, end_ts_text, systems, schedule_set_name, enabled, note)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, row)
                    new_id = cur.lastrowid
                    self.conn.commit()

                    resp = Message(
                        "db",
                        "copy_special_period_result",
                        {"ok": True, "id": new_id},
                        target=msg.source,
                        request_id=msg.request_id
                    )
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass

            resp = Message(
                "db",
                "copy_special_period_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

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
            resp = Message(
                "db",
                "system_action_result",
                {"ok": False, "error": "Invalid source"},
                target=msg.source,
                request_id=msg.request_id
            )
            self._reply_to_source(
                msg, resp,
                engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
            )
            return

        if action not in ("restart_dwellpi", "reboot_pi"):
            resp = Message(
                "db",
                "system_action_result",
                {"ok": False, "error": "Invalid action"},
                target=msg.source,
                request_id=msg.request_id
            )
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

            resp = Message(
                "db",
                "system_action_result",
                {"ok": True, "action": action, "status": "accepted"},
                target=msg.source,
                request_id=msg.request_id
            )
        except Exception as e:
            resp = Message(
                "db",
                "system_action_result",
                {"ok": False, "error": str(e)},
                target=msg.source,
                request_id=msg.request_id
            )

        self._reply_to_source(
            msg, resp,
            engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
        )


    def run(self, queue, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue, supervisor_queue, shutdown_event):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.connect()
        self.load_settings_cache()

        # Push snapshot FIRST so engine/sensor/relay/ui/web can start without RPC
        self.send_settings_snapshot(engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

        try:
            supervisor_queue.put(Message("db", "db_ready", {"ts": time.time()}))
        except Exception:
            pass

        print("[DB] Worker started: %s : mode=%s" % (self.db_path, self.mode))
        self.last_log_flush = time.time()

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

                # ---- settings RPC ----
                if msg.type == "get_setting":
                    self.handle_get_setting(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)


                elif msg.type == "set_setting":
                    self.handle_set_setting(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "get_programs":
                    print("[DB] get_programs request from %s payload=%r" % (msg.source, msg.payload))
                    self.handle_get_programs(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "get_program":
                    self.handle_get_program(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "get_active_ch_program":
                    self.handle_get_active_ch_program(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "update_program_setpoint":
                    self.handle_update_program_setpoint(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "create_program":
                    self.handle_create_program(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "update_program":
                    self.handle_update_program(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "delete_program":
                    self.handle_delete_program(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "copy_program":
                    self.handle_copy_program(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "heartbeat":
                    self.handle_heartbeat(msg, supervisor_queue)

                # ---- logs ----
                elif msg.type == "temperature":
                    self.handle_temperature_log(msg)
                elif msg.type == "state_change":
                    self.handle_state_change(msg)

                elif msg.type == "flush":
                    # force flush logs/settings now
                    self.flush_settings()
                    self.flush_logs_if_due(force=True)

                elif msg.type == "cleanup_expired_overrides":
                    self.handle_cleanup_expired_overrides(msg)

                elif msg.type == "get_state_log":
                    self.handle_get_state_log(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "get_temperature_log":
                    self.handle_get_temperature_log(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "get_schedule_sets":
                    self.handle_get_schedule_sets(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue
                    )

                elif msg.type == "get_holidays":
                    self.handle_get_holidays(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "get_holiday":
                    self.handle_get_holiday(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "create_holiday":
                    self.handle_create_holiday(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "update_holiday":
                    self.handle_update_holiday(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "delete_holiday":
                    self.handle_delete_holiday(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "copy_holiday":
                    self.handle_copy_holiday(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "get_special_periods":
                    self.handle_get_special_periods(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "get_special_period":
                    self.handle_get_special_period(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "create_special_period":
                    self.handle_create_special_period(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "update_special_period":
                    self.handle_update_special_period(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "delete_special_period":
                    self.handle_delete_special_period(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "copy_special_period":
                    self.handle_copy_special_period(msg, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue)

                elif msg.type == "request_system_action":
                    self.handle_request_system_action(
                        msg,
                        engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
                        ui_ctrl_queue, web_ctrl_queue, supervisor_queue
                    )

                elif msg.type == "shutdown":
                    break

            except QueueEmpty:
                # no message this second; periodic flush already handled
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