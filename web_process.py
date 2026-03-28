#!/usr/bin/python
# -*- coding: utf-8 -*-
# web_process.py

from __future__ import print_function

import json
import time
import os

try:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from urlparse import urlparse, parse_qs
except ImportError:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

from message_schema import Message
from settings_sync import SettingsSyncMixin

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

STATIC_ROUTES = {
                # HTML Pages
                "/": ("index.html", "text/html; charset=utf-8"),
                "/web/chsettings.html": ("chsettings.html", "text/html; charset=utf-8"),
                "/web/chprogs.html": ("chprogs.html", "text/html; charset=utf-8"),
                "/web/hwsettings.html": ("hwsettings.html", "text/html; charset=utf-8"),
                "/web/hwprogs.html": ("hwprogs.html", "text/html; charset=utf-8"),
                "/web/chprogdetails.html": ("chprogdetails.html", "text/html; charset=utf-8"),
                "/web/hwprogdetails.html": ("hwprogdetails.html", "text/html; charset=utf-8"),
                "/web/syssettings.html": ("syssettings.html", "text/html; charset=utf-8"),
                "/web/statelog.html": ("statelog.html", "text/html; charset=utf-8"),
                "/web/templog.html": ("templog.html", "text/html; charset=utf-8"),
                "/web/specialprogs.html": ("specialprogs.html", "text/html; charset=utf-8"),
                "/web/specialprogdetails.html": ("specialprogdetails.html", "text/html; charset=utf-8"),
                "/web/holidayprogs.html": ("holidayprogs.html", "text/html; charset=utf-8"),
                "/web/holidayprogdetails.html": ("holidayprogdetails.html", "text/html; charset=utf-8"),

                # Javascript & Assets
                "/static/index.js": ("static/index.js", "application/javascript; charset=utf-8"),
                "/static/chsettings.js": ("static/chsettings.js", "application/javascript; charset=utf-8"),
                "/static/chprogs.js": ("static/chprogs.js", "application/javascript; charset=utf-8"),
                "/static/hwsettings.js": ("static/hwsettings.js", "application/javascript; charset=utf-8"),
                "/static/hwprogs.js": ("static/hwprogs.js", "application/javascript; charset=utf-8"),
                "/static/chprogdetails.js": ("static/chprogdetails.js", "application/javascript; charset=utf-8"),
                "/static/hwprogdetails.js": ("static/hwprogdetails.js", "application/javascript; charset=utf-8"),
                "/static/syssettings.js": ("static/syssettings.js", "application/javascript; charset=utf-8"),
                "/static/style.css": ("static/style.css", "text/css; charset=utf-8"),
                "/static/thermometer.js": ("static/thermometer.js", "application/javascript; charset=utf-8"),
                "/static/common.js": ("static/common.js", "application/javascript; charset=utf-8"),
                "/static/statelog.js": ("static/statelog.js", "application/javascript; charset=utf-8"),
                "/static/templog.js": ("static/templog.js", "application/javascript; charset=utf-8"),
                "/static/specialprogs.js": ("static/specialprogs.js", "application/javascript; charset=utf-8"),
                "/static/specialprogdetails.js": ("static/specialprogdetails.js", "application/javascript; charset=utf-8"),
                "/static/holidayprogs.js": ("static/holidayprogs.js", "application/javascript; charset=utf-8"),
                "/static/holidayprogdetails.js": ("static/holidayprogdetails.js", "application/javascript; charset=utf-8"),

            }

class WebProcess(SettingsSyncMixin, object):
    def __init__(self, web_queue, ctrl_queue, db_queue, relay_queue, web_rpc_queue, mode, db_path, shutdown_event):
        self.web_queue = web_queue
        self.ctrl_queue = ctrl_queue
        self.db_queue = db_queue
        self.relay_queue = relay_queue
        self.web_rpc_queue = web_rpc_queue
        self.mode = mode
        self.db_path = db_path
        self.shutdown_event = shutdown_event
        self.pending_replies = {}  # request_id -> Message

        self.settings = {}

        self.state = {
            "temp": None,
            "target": None,
            "ch_desired": None,
            "hw_desired": None,
            "reason": "",
            "hw_reason": "",
            "ch_switch": None,
            "hw_switch": None,
            "relay_a": None,
            "relay_b": None,
            "updated": 0,
        }

    def _rpc_db(self, msg_type, payload, timeout=2.0):
        import uuid

        request_id = uuid.uuid4().hex

        # Clear stale reply with same id if somehow present
        if request_id in self.pending_replies:
            del self.pending_replies[request_id]

        try:
            self.db_queue.put(Message(
                "web",
                msg_type,
                payload or {},
                target="db",
                request_id=request_id
            ))
        except Exception:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline and not self.shutdown_event.is_set():
            self._drain_ctrl_queue()
            self._drain_web_rpc_queue()

            reply = self.pending_replies.pop(request_id, None)
            if reply is not None:
                return reply

            time.sleep(0.05)

        return None

    def _rpc_relay(self, msg_type, payload, timeout=8.0):
        import uuid

        request_id = uuid.uuid4().hex

        if request_id in self.pending_replies:
            del self.pending_replies[request_id]

        try:
            self.relay_queue.put(Message(
                "web",
                msg_type,
                payload or {},
                target="relay",
                request_id=request_id
            ))
        except Exception:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline and not self.shutdown_event.is_set():
            self._drain_ctrl_queue()
            self._drain_web_rpc_queue()

            reply = self.pending_replies.pop(request_id, None)
            if reply is not None:
                return reply

            time.sleep(0.05)

        return None

    def _drain_ctrl_queue(self):
        while True:
            try:
                msg = self.ctrl_queue.get_nowait()
            except Exception:
                break

            if msg.type == "settings_snapshot":
                self.apply_settings_snapshot((msg.payload or {}).get("values"))
                continue

            elif msg.type == "setting_changed":
                p = msg.payload or {}
                self.apply_setting_changed(p.get("key"), p.get("value"))
                continue

            if getattr(msg, "request_id", None):
                self.pending_replies[msg.request_id] = msg

    def _drain_web_queue(self):
        while True:
            try:
                msg = self.web_queue.get_nowait()
            except Exception:
                break

            if msg.type != "web_state":
                continue

            p = msg.payload or {}
            self.state.update(p)
            self.state["updated"] = time.time()

    def _drain_web_rpc_queue(self):
        while True:
            try:
                msg = self.web_rpc_queue.get_nowait()
            except Exception:
                break

            if getattr(msg, "request_id", None):
                self.pending_replies[msg.request_id] = msg

    def _settings_store(self):
        return self.settings

    def _on_setting_changed(self, key, value):
        pass

    def _set_setting(self, key, value):
        self.settings[key] = value
        self.db_queue.put(Message("web", "set_setting", {"key": key, "value": value}))

    def _clear_boost(self, system):
        self._set_setting("%s_BOOST_FINISH_EPOCH" % system, "0")
        self._set_setting("%s_BOOST_FINISH_TIME" % system, "00:00")

    def _add_boost(self, system, minutes, max_minutes=180):
        minutes = int(minutes)
        max_minutes = int(max_minutes)

        if minutes <= 0:
            self._clear_boost(system)
            return

        now_epoch = int(time.time())

        key_epoch = "%s_BOOST_FINISH_EPOCH" % system
        key_time = "%s_BOOST_FINISH_TIME" % system

        try:
            current_finish = int(self.settings.get(key_epoch, "0") or "0")
        except Exception:
            current_finish = 0

        base_epoch = current_finish if current_finish > now_epoch else now_epoch
        new_finish = base_epoch + (minutes * 60)
        max_finish = now_epoch + (max_minutes * 60)

        if new_finish > max_finish:
            new_finish = max_finish

        finish_time = time.strftime("%H:%M", time.localtime(new_finish))

        self._set_setting(key_epoch, str(new_finish))
        self._set_setting(key_time, finish_time)

    def _toggle_advance(self, system):
        key = "%s_ADVANCE" % system
        current = str(self.settings.get(key, "False"))
        new_value = "False" if current == "True" else "True"
        self._set_setting(key, new_value)

    def _get_system_load_info(self):
        uptime_text = "Uptime: unavailable"
        load_text = "Load Average: unavailable"

        try:
            if os.path.exists("/proc/uptime"):
                from datetime import timedelta
                with open("/proc/uptime", "r") as f:
                    uptime_seconds = float(f.readline().split()[0])
                uptime_text = "Uptime: %s" % str(timedelta(seconds=int(uptime_seconds)))
        except Exception as e:
            uptime_text = "Uptime: error (%s)" % e

        try:
            loadavg = os.getloadavg()
            load_text = "Load Average: %.2f %.2f %.2f" % (loadavg[0], loadavg[1], loadavg[2])
        except Exception as e:
            load_text = "Load Average: error (%s)" % e

        return {
            "uptime": uptime_text,
            "loadavg": load_text
        }

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):

            def setup(self):
                BaseHTTPRequestHandler.setup(self)
                try:
                    self.connection.settimeout(2.0)
                except Exception:
                    pass

            def _serve_file(self, path, content_type):
                try:
                    with open(path, "rb") as f:
                        body = f.read()
                except IOError:
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
                    return

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    self.wfile.write(body)
                except Exception as e:
                    print("[Web] _serve_file write failed: %s" % e)


            def _send_json(self, code, data):
                body = json.dumps(data)
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    self.wfile.write(body.encode("utf-8"))
                except Exception:
                    self.wfile.write(body)

            def _read_json_body(self, raw_body):
                try:
                    text = raw_body.decode("utf-8") if hasattr(raw_body, "decode") else raw_body
                except Exception:
                    text = raw_body
                return json.loads(text or "{}")

            def _send_db_payload(self, msg):
                if msg is None:
                    self._send_json(504, {"ok": False, "error": "DB timeout"})
                else:
                    self._send_json(200, msg.payload)

            def _send_relay_payload(self, msg):
                if msg is None:
                    self._send_json(504, {"ok": False, "error": "Relay timeout"})
                else:
                    payload = msg.payload or {}
                    if payload.get("error"):
                        self._send_json(200, {"ok": False, "error": payload.get("error"), "info": payload})
                    else:
                        self._send_json(200, {"ok": True, "info": payload})

            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path

                print("[Web] GET %s" % self.path)

                # 1. Handle Static Routes
                route = STATIC_ROUTES.get(path)
                if route:
                    rel_path, content_type = route
                    return self._serve_file(os.path.join(WEB_DIR, rel_path), content_type)

                # 2. Handle API Status
                if path == "/api/status":
                    outer._drain_ctrl_queue()
                    outer._drain_web_queue()

                    keys = [
                        "CH_SYSTEM_SWITCH", "HW_SYSTEM_SWITCH", "CH_ADVANCE", "HW_ADVANCE",
                        "CH_BOOST_FINISH_TIME", "HW_BOOST_FINISH_TIME",
                        "CH_BOOST_FINISH_EPOCH", "HW_BOOST_FINISH_EPOCH",
                        "DEFAULT_ON_SETPOINT",
                        "DEFAULT_SETPOINT", "HEATUP_RATE", "MINIMUM_HEATING_STARTUP_TIME",
                        "MAXIMUM_HEATING_STARTUP_TIME", "TARGET_SETPOINT_OFFSET", "COMFORT",
                        "SENSOR_INTERVAL", "ENGINE_INTERVAL", "LOGGING_INTERVAL",
                        "RELAY_ENABLE", "RELAY_BOARD_DEVICE_ID", "CH_RELAY_LETTER", "HW_RELAY_LETTER",
                        "SENSOR_DEVICE_ID",
                        "BOOST_SETPOINT", "HYSTERESIS_BAND", "CH_MIN_ON_SECONDS",
                        "CH_MIN_OFF_SECONDS", "TEMP_SENSOR_ADJUSTMENT_DEGREES",
                        "LCD_BRIGHTNESS", "LCD_DIM_LEVEL", "LCD_DIM_START_TIME", "LCD_DIM_END_TIME"
                    ]

                    settings_blob = {k: outer.settings.get(k) for k in keys}

                    self._send_json(200, {
                        "ok": True,
                        "mode": outer.mode,
                        "state": outer.state,
                        "settings": settings_blob
                    })
                    return

                # 3. Handle API Bulk Programs (plural)
                if path in ("/api/ch/programs", "/api/hw/programs"):
                    system = "CH" if "ch" in path else "HW"
                    msg = outer._rpc_db("get_programs", {"system": system, "schedule_set_name": "NORMAL"})
                    self._send_db_payload(msg)
                    return

                # 4. Handle Individual Program Lookup (singular)
                if path in ("/api/ch/program", "/api/hw/program"):
                    qs = parse_qs(parsed.query or "")
                    program_id = qs.get("id", [None])[0]
                    msg = outer._rpc_db("get_program", {"id": program_id})
                    self._send_db_payload(msg)
                    return

                if path == "/api/system/load":
                    info = outer._get_system_load_info()
                    self._send_json(200, {
                        "ok": True,
                        "uptime": info["uptime"],
                        "loadavg": info["loadavg"]
                    })
                    return

                if path == "/api/relay/info":
                    msg = outer._rpc_relay("relay_info", {}, timeout=10.0)
                    print("[Web] /api/relay/info reply: %r" % (msg.payload if msg else None))
                    self._send_relay_payload(msg)
                    return

                if path == "/api/logs/state":
                    qs = parse_qs(parsed.query or "")
                    day = qs.get("date", [None])[0]
                    msg = outer._rpc_db("get_state_log", {"date": day}, timeout=5.0)
                    self._send_db_payload(msg)
                    return

                if path == "/api/logs/temp":
                    qs = parse_qs(parsed.query or "")
                    day = qs.get("date", [None])[0]
                    msg = outer._rpc_db("get_temperature_log", {"date": day}, timeout=5.0)
                    self._send_db_payload(msg)
                    return

                if path == "/api/special/programs":
                    msg = outer._rpc_db("get_special_periods", {}, timeout=5.0)
                    self._send_db_payload(msg)
                    return

                if path == "/api/special/program":
                    qs = parse_qs(parsed.query or "")
                    item_id = qs.get("id", [None])[0]
                    msg = outer._rpc_db("get_special_period", {"id": item_id}, timeout=5.0)
                    self._send_db_payload(msg)
                    return

                if path == "/api/holiday/programs":
                    msg = outer._rpc_db("get_holidays", {}, timeout=5.0)
                    self._send_db_payload(msg)
                    return

                if path == "/api/holiday/program":
                    qs = parse_qs(parsed.query or "")
                    item_id = qs.get("id", [None])[0]
                    msg = outer._rpc_db("get_holiday", {"id": item_id}, timeout=5.0)
                    self._send_db_payload(msg)
                    return

                if path == "/api/schedule_sets":
                    msg = outer._rpc_db("get_schedule_sets", {}, timeout=5.0)
                    self._send_db_payload(msg)
                    return

                # 5. Fallback
                self._send_json(404, {"ok": False, "error": "Not found"})

            def do_POST(self):
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query or "")
                print("[Web] POST %s" % self.path)

                outer._drain_ctrl_queue()
                outer._drain_web_queue()

                content_length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(content_length) if content_length > 0 else ""

                try:
                    if parsed.path == "/api/ch/boost":
                        outer._set_setting("CH_ADVANCE", "False")
                        mins = int(qs.get("mins", ["60"])[0])

                        if mins <= 0:
                            outer._clear_boost("CH")
                        else:
                            outer._add_boost("CH", mins, max_minutes=180)

                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/hw/boost":
                        outer._set_setting("HW_ADVANCE", "False")
                        mins = int(qs.get("mins", ["60"])[0])

                        if mins <= 0:
                            outer._clear_boost("HW")
                        else:
                            outer._add_boost("HW", mins, max_minutes=180)

                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/ch/advance":
                        outer._clear_boost("CH")
                        outer._toggle_advance("CH")
                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/hw/advance":
                        outer._clear_boost("HW")
                        outer._toggle_advance("HW")
                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/settings/set":
                        try:
                            body = self._read_json_body(raw_body)
                            key = body.get("key")
                            value = body.get("value")

                            if not key:
                                self._send_json(400, {"ok": False, "error": "Missing key"})
                                return

                            outer._set_setting(str(key), "" if value is None else str(value))
                            self._send_json(200, {"ok": True})
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/settings/bulk":
                        try:
                            body = self._read_json_body(raw_body)
                            items = body.get("items") or []

                            if not isinstance(items, list):
                                self._send_json(400, {"ok": False, "error": "items must be a list"})
                                return

                            changed = []

                            for item in items:
                                if not isinstance(item, dict):
                                    continue

                                key = item.get("key")
                                value = item.get("value")

                                if not key:
                                    continue

                                outer._set_setting(str(key), "" if value is None else str(value))
                                changed.append(str(key))

                            self._send_json(200, {
                                "ok": True,
                                "changed": changed
                            })
                            return

                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/system/restart_dwellpi":
                        try:
                            msg = outer._rpc_db("request_system_action", {
                                "action": "restart_dwellpi"
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/system/reboot_pi":
                        try:
                            msg = outer._rpc_db("request_system_action", {
                                "action": "reboot_pi"
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/ch/program/create":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("create_program", {
                                "schedule_set_name": body.get("schedule_set_name", "NORMAL"),
                                "system": "CH",
                                "start_time": body.get("start_time"),
                                "end_time": body.get("end_time"),
                                "days": body.get("days"),
                                "setpoint": body.get("setpoint"),
                                "warmup": body.get("warmup"),
                                "note": body.get("note"),
                                "enabled": body.get("enabled")
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/ch/program/update":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("update_program", {
                                "id": body.get("id"),
                                "schedule_set_name": body.get("schedule_set_name", "NORMAL"),
                                "system": "CH",
                                "start_time": body.get("start_time"),
                                "end_time": body.get("end_time"),
                                "days": body.get("days"),
                                "setpoint": body.get("setpoint"),
                                "warmup": body.get("warmup"),
                                "note": body.get("note"),
                                "enabled": body.get("enabled")
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/ch/program/delete":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("delete_program", {
                                "id": body.get("id"),
                                "system": "CH"
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/ch/program/copy":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("copy_program", {
                                "id": body.get("id"),
                                "system": "CH"
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/hw/program/create":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("create_program", {
                                "schedule_set_name": body.get("schedule_set_name", "NORMAL"),
                                "system": "HW",
                                "start_time": body.get("start_time"),
                                "end_time": body.get("end_time"),
                                "days": body.get("days"),
                                "note": body.get("note"),
                                "enabled": body.get("enabled")
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/hw/program/update":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("update_program", {
                                "id": body.get("id"),
                                "schedule_set_name": body.get("schedule_set_name", "NORMAL"),
                                "system": "HW",
                                "start_time": body.get("start_time"),
                                "end_time": body.get("end_time"),
                                "days": body.get("days"),
                                "note": body.get("note"),
                                "enabled": body.get("enabled")
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/hw/program/delete":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("delete_program", {
                                "id": body.get("id"),
                                "system": "HW"
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/hw/program/copy":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("copy_program", {
                                "id": body.get("id"),
                                "system": "HW"
                            })

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/special/program/create":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("create_special_period", {
                                "start_ts_epoch": body.get("start_ts_epoch"),
                                "start_ts_text": body.get("start_ts_text"),
                                "end_ts_epoch": body.get("end_ts_epoch"),
                                "end_ts_text": body.get("end_ts_text"),
                                "systems": body.get("systems"),
                                "schedule_set_name": body.get("schedule_set_name"),
                                "enabled": body.get("enabled"),
                                "note": body.get("note")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/special/program/update":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("update_special_period", {
                                "id": body.get("id"),
                                "start_ts_epoch": body.get("start_ts_epoch"),
                                "start_ts_text": body.get("start_ts_text"),
                                "end_ts_epoch": body.get("end_ts_epoch"),
                                "end_ts_text": body.get("end_ts_text"),
                                "systems": body.get("systems"),
                                "schedule_set_name": body.get("schedule_set_name"),
                                "enabled": body.get("enabled"),
                                "note": body.get("note")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/special/program/delete":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("delete_special_period", {
                                "id": body.get("id")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/special/program/copy":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("copy_special_period", {
                                "id": body.get("id")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/holiday/program/create":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("create_holiday", {
                                "start_ts_epoch": body.get("start_ts_epoch"),
                                "start_ts_text": body.get("start_ts_text"),
                                "end_ts_epoch": body.get("end_ts_epoch"),
                                "end_ts_text": body.get("end_ts_text"),
                                "systems": body.get("systems"),
                                "enabled": body.get("enabled"),
                                "note": body.get("note")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/holiday/program/update":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("update_holiday", {
                                "id": body.get("id"),
                                "start_ts_epoch": body.get("start_ts_epoch"),
                                "start_ts_text": body.get("start_ts_text"),
                                "end_ts_epoch": body.get("end_ts_epoch"),
                                "end_ts_text": body.get("end_ts_text"),
                                "systems": body.get("systems"),
                                "enabled": body.get("enabled"),
                                "note": body.get("note")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/holiday/program/delete":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("delete_holiday", {
                                "id": body.get("id")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/holiday/program/copy":
                        try:
                            body = self._read_json_body(raw_body)
                            msg = outer._rpc_db("copy_holiday", {
                                "id": body.get("id")
                            }, timeout=5.0)

                            self._send_db_payload(msg)
                            return
                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                    if parsed.path == "/api/ch/live_setpoint":
                        try:
                            body = self._read_json_body(raw_body)
                            value = str(body.get("value", "")).strip()
                            if not value:
                                self._send_json(400, {"ok": False, "error": "Missing value"})
                                return

                            try:
                                float(value)
                            except Exception:
                                self._send_json(400, {"ok": False, "error": "Invalid setpoint"})
                                return

                            now_epoch = time.time()

                            # 1. CH switch ON -> DEFAULT_ON_SETPOINT
                            ch_switch = str(outer.settings.get("CH_SYSTEM_SWITCH", "timed")).lower()
                            if ch_switch == "on":
                                outer._set_setting("DEFAULT_ON_SETPOINT", value)
                                self._send_json(200, {"ok": True, "target": "DEFAULT_ON_SETPOINT"})
                                return

                            # 2. Active boost -> BOOST_SETPOINT
                            try:
                                boost_finish = int(outer.settings.get("CH_BOOST_FINISH_EPOCH", "0") or "0")
                            except Exception:
                                boost_finish = 0

                            if boost_finish and now_epoch < boost_finish:
                                outer._set_setting("BOOST_SETPOINT", value)
                                self._send_json(200, {"ok": True, "target": "BOOST_SETPOINT"})
                                return

                            # 3. Timed/once active entry -> update program
                            msg = outer._rpc_db("get_active_ch_program", {"now_epoch": now_epoch})
                            if msg is not None and (msg.payload or {}).get("ok") and (msg.payload or {}).get("item"):
                                item = (msg.payload or {}).get("item")
                                program_id = item.get("id")

                                save_msg = outer._rpc_db("update_program_setpoint", {
                                    "id": program_id,
                                    "setpoint": value
                                })

                                if save_msg is not None and (save_msg.payload or {}).get("ok"):
                                    self._send_json(200, {"ok": True, "target": "PROGRAM", "id": program_id})
                                    return

                            # 4. Fallback -> DEFAULT_SETPOINT
                            outer._set_setting("DEFAULT_SETPOINT", value)
                            self._send_json(200, {"ok": True, "target": "DEFAULT_SETPOINT"})
                            return

                        except Exception as e:
                            self._send_json(500, {"ok": False, "error": str(e)})
                            return

                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
                    return

                self._send_json(404, {"ok": False, "error": "Not found"})

        return Handler

    def run(self):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[Web] Started in mode: %s" % self.mode)

        ok = self.wait_for_initial_snapshot(self.ctrl_queue, self.shutdown_event, timeout=3.0)

        if not ok:
            print("[Web] No settings snapshot received yet; using defaults")

        handler = self._make_handler()
        server = HTTPServer(("0.0.0.0", 80), handler)
        server.timeout = 1.0

        last_hb = 0.0

        try:
            while not self.shutdown_event.is_set():

                self._drain_ctrl_queue()
                self._drain_web_queue()
                self._drain_web_rpc_queue()

                now = time.time()
                if now - last_hb >= 5.0:
                    try:
                        self.db_queue.put(Message("web", "heartbeat", {"status": "ok"}))
                    except Exception as e:
                        print("[Web] heartbeat failed: %s" % e)
                    last_hb = now

                #print("[Web] handle_request start")
                try:
                    server.handle_request()
                except Exception as e:
                    print("[Web] handle_request error: %s" % e)
                #print("[Web] handle_request end")
        finally:
            try:
                server.server_close()
            except Exception:
                pass

        print("[Web] Shutting down cleanly")