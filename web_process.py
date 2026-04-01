#!/usr/bin/python
# -*- coding: utf-8 -*-
# web_process.py

from __future__ import print_function

import json
import time
import os
import threading

try:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from SocketServer import ThreadingMixIn
    from urlparse import urlparse, parse_qs
except ImportError:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
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


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class WebProcess(SettingsSyncMixin, object):
    def __init__(self, web_queue, ctrl_queue, db_queue, relay_queue, web_rpc_queue,
                 supervisor_queue, mode, db_path, shutdown_event):
        self.web_queue = web_queue
        self.ctrl_queue = ctrl_queue
        self.db_queue = db_queue
        self.relay_queue = relay_queue
        self.web_rpc_queue = web_rpc_queue
        self.supervisor_queue = supervisor_queue
        self.mode = mode
        self.db_path = db_path
        self.shutdown_event = shutdown_event

        self.pending_replies = {}  # request_id -> Message
        self.pending_replies_lock = threading.Lock()

        self.settings = {}
        self.settings_lock = threading.Lock()

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
        self.state_lock = threading.Lock()

        self.supervisor_status = {}
        self.supervisor_status_lock = threading.Lock()
        self.supervisor_status_updated = 0.0

    def _rpc_db(self, msg_type, payload, timeout=2.0):
        import uuid

        request_id = uuid.uuid4().hex

        with self.pending_replies_lock:
            self.pending_replies.pop(request_id, None)

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

        with self.pending_replies_lock:
            reply = self.pending_replies.pop(request_id, None)
        if reply is not None:
            return reply

        deadline = time.time() + timeout
        while time.time() < deadline and not self.shutdown_event.is_set():
            with self.pending_replies_lock:
                reply = self.pending_replies.pop(request_id, None)

            if reply is not None:
                return reply

            time.sleep(0.01)

        return None

    def _rpc_relay(self, msg_type, payload, timeout=8.0):
        import uuid

        request_id = uuid.uuid4().hex

        with self.pending_replies_lock:
            self.pending_replies.pop(request_id, None)

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

        with self.pending_replies_lock:
            reply = self.pending_replies.pop(request_id, None)
        if reply is not None:
            return reply

        deadline = time.time() + timeout
        while time.time() < deadline and not self.shutdown_event.is_set():
            with self.pending_replies_lock:
                reply = self.pending_replies.pop(request_id, None)

            if reply is not None:
                return reply

            time.sleep(0.01)

        return None

    def _request_supervisor_status(self):
        if self.supervisor_queue is None:
            return False

        try:
            self.supervisor_queue.put(Message("web", "get_supervisor_status", {}))
            return True
        except Exception:
            return False

    def _rpc_supervisor(self, msg_type, payload, timeout=5.0):
        import uuid

        if self.supervisor_queue is None:
            return None

        request_id = uuid.uuid4().hex

        with self.pending_replies_lock:
            self.pending_replies.pop(request_id, None)

        try:
            self.supervisor_queue.put(Message(
                "web",
                msg_type,
                payload or {},
                request_id=request_id
            ))
        except Exception:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline and not self.shutdown_event.is_set():
            with self.pending_replies_lock:
                reply = self.pending_replies.pop(request_id, None)

            if reply is not None:
                return reply

            time.sleep(0.01)

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

            if msg.type == "setting_changed":
                p = msg.payload or {}
                self.apply_setting_changed(p.get("key"), p.get("value"))
                continue

            if msg.type == "supervisor_status_result":
                payload = dict(msg.payload or {})
                with self.supervisor_status_lock:
                    self.supervisor_status = payload
                    self.supervisor_status_updated = payload.get("timestamp", time.time())
                continue

            if getattr(msg, "request_id", None):
                with self.pending_replies_lock:
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
            with self.state_lock:
                self.state.update(p)
                self.state["updated"] = time.time()

    def _drain_web_rpc_queue(self):
        while True:
            try:
                msg = self.web_rpc_queue.get_nowait()
            except Exception:
                break

            if getattr(msg, "request_id", None):
                with self.pending_replies_lock:
                    self.pending_replies[msg.request_id] = msg

    def _settings_store(self):
        return self.settings

    def _settings_lock(self):
        return self.settings_lock

    def _on_setting_changed(self, key, value):
        pass

    def _set_setting(self, key, value):
        try:
            self.db_queue.put(Message("web", "set_setting", {"key": key, "value": value}))
            with self.settings_lock:
                self.settings[key] = value
            return True
        except Exception:
            return False

    def _clear_boost(self, system):
        ok1 = self._set_setting("%s_BOOST_FINISH_EPOCH" % system, "0")
        ok2 = self._set_setting("%s_BOOST_FINISH_TIME" % system, "00:00")
        return bool(ok1 and ok2)

    def _add_boost(self, system, minutes, max_minutes=180):
        minutes = int(minutes)
        max_minutes = int(max_minutes)

        if minutes <= 0:
            return self._clear_boost(system)

        now_epoch = int(time.time())

        key_epoch = "%s_BOOST_FINISH_EPOCH" % system
        key_time = "%s_BOOST_FINISH_TIME" % system

        with self.settings_lock:
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

        ok1 = self._set_setting(key_epoch, str(new_finish))
        ok2 = self._set_setting(key_time, finish_time)
        return bool(ok1 and ok2)

    def _toggle_advance(self, system):
        key = "%s_ADVANCE" % system
        with self.settings_lock:
            current = str(self.settings.get(key, "False"))
        new_value = "False" if current == "True" else "True"
        return self._set_setting(key, new_value)

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

    def _get_settings_snapshot(self):
        keys = [
            "CH_SYSTEM_SWITCH", "HW_SYSTEM_SWITCH", "CH_ADVANCE", "HW_ADVANCE",
            "CH_BOOST_FINISH_TIME", "HW_BOOST_FINISH_TIME",
            "CH_BOOST_FINISH_EPOCH", "HW_BOOST_FINISH_EPOCH",
            "DEFAULT_ON_SETPOINT", "DEFAULT_SETPOINT", "HEATUP_RATE",
            "MINIMUM_HEATING_STARTUP_TIME", "MAXIMUM_HEATING_STARTUP_TIME",
            "TARGET_SETPOINT_OFFSET", "COMFORT", "SENSOR_INTERVAL",
            "ENGINE_INTERVAL", "LOGGING_INTERVAL", "RELAY_ENABLE",
            "RELAY_BOARD_DEVICE_ID", "CH_RELAY_LETTER", "HW_RELAY_LETTER",
            "SENSOR_DEVICE_ID", "BOOST_SETPOINT", "HYSTERESIS_BAND",
            "CH_MIN_ON_SECONDS", "CH_MIN_OFF_SECONDS",
            "TEMP_SENSOR_ADJUSTMENT_DEGREES", "LCD_BRIGHTNESS",
            "LCD_DIM_LEVEL", "LCD_DIM_START_TIME", "LCD_DIM_END_TIME"
        ]

        with self.settings_lock:
            return {k: self.settings.get(k) for k in keys}

    def _get_state_snapshot(self):
        with self.state_lock:
            return dict(self.state)

    def _get_supervisor_status_snapshot(self):
        with self.supervisor_status_lock:
            return {
                "data": dict(self.supervisor_status),
                "updated": self.supervisor_status_updated
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

            def log_message(self, fmt, *args):
                return

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
                body_bytes = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                self.wfile.write(body_bytes)

            def _read_json_body(self, raw_body):
                try:
                    text = raw_body.decode("utf-8") if hasattr(raw_body, "decode") else raw_body
                except Exception:
                    text = raw_body
                return json.loads(text or "{}")

            def _read_body_or_400(self, raw_body):
                try:
                    return self._read_json_body(raw_body)
                except Exception as e:
                    self._send_json(400, {"ok": False, "error": "Invalid JSON: %s" % e})
                    return None

            def _send_db_payload(self, msg):
                if msg is None:
                    self._send_json(504, {"ok": False, "error": "DB timeout"})
                else:
                    self._send_json(200, msg.payload or {"ok": False, "error": "Empty DB reply"})

            def _send_relay_payload(self, msg):
                if msg is None:
                    self._send_json(504, {"ok": False, "error": "Relay timeout"})
                    return

                payload = msg.payload or {}
                if payload.get("error"):
                    self._send_json(200, {"ok": False, "error": payload.get("error"), "info": payload})
                else:
                    self._send_json(200, {"ok": True, "info": payload})

            def _db_post(self, msg_type, payload, timeout=5.0):
                try:
                    msg = outer._rpc_db(msg_type, payload, timeout=timeout)
                    self._send_db_payload(msg)
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})

            def _db_post_from_body(self, raw_body, msg_type, payload_builder, timeout=5.0):
                body = self._read_body_or_400(raw_body)
                if body is None:
                    return True

                try:
                    payload = payload_builder(body)
                except Exception as e:
                    self._send_json(400, {"ok": False, "error": str(e)})
                    return True

                self._db_post(msg_type, payload, timeout=timeout)
                return True

            def _db_simple_id_post(self, raw_body, msg_type, timeout=5.0):
                body = self._read_body_or_400(raw_body)
                if body is None:
                    return True

                self._db_post(msg_type, {"id": body.get("id")}, timeout=timeout)
                return True

            def _setting_update_or_500(self, key, value, error_text=None):
                ok = outer._set_setting(str(key), "" if value is None else str(value))
                if ok:
                    return True

                self._send_json(500, {
                    "ok": False,
                    "error": error_text or ("Failed to update %s" % key)
                })
                return False

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path

                print("[Web] GET %s" % self.path)

                route = STATIC_ROUTES.get(path)
                if route:
                    rel_path, content_type = route
                    self._serve_file(os.path.join(WEB_DIR, rel_path), content_type)
                    return

                if path == "/api/status":
                    self._send_json(200, {
                        "ok": True,
                        "mode": outer.mode,
                        "state": outer._get_state_snapshot(),
                        "settings": outer._get_settings_snapshot(),
                        "supervisor": outer._get_supervisor_status_snapshot()
                    })
                    return

                if path in ("/api/ch/programs", "/api/hw/programs"):
                    system = "CH" if "ch" in path else "HW"
                    msg = outer._rpc_db("get_programs", {
                        "system": system,
                        "schedule_set_name": "NORMAL"
                    })
                    self._send_db_payload(msg)
                    return

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

                self._send_json(404, {"ok": False, "error": "Not found"})

            def do_POST(self):
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query or "")
                print("[Web] POST %s" % self.path)

                content_length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(content_length) if content_length > 0 else ""

                try:
                    if parsed.path == "/api/ch/boost":
                        if not self._setting_update_or_500("CH_ADVANCE", "False", "Failed to clear CH advance"):
                            return

                        mins = int(qs.get("mins", ["60"])[0])
                        if mins <= 0:
                            if not outer._clear_boost("CH"):
                                self._send_json(500, {"ok": False, "error": "Failed to clear CH boost"})
                                return
                        else:
                            if not outer._add_boost("CH", mins, max_minutes=180):
                                self._send_json(500, {"ok": False, "error": "Failed to add CH boost"})
                                return

                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/hw/boost":
                        if not self._setting_update_or_500("HW_ADVANCE", "False", "Failed to clear HW advance"):
                            return

                        mins = int(qs.get("mins", ["60"])[0])
                        if mins <= 0:
                            if not outer._clear_boost("HW"):
                                self._send_json(500, {"ok": False, "error": "Failed to clear HW boost"})
                                return
                        else:
                            if not outer._add_boost("HW", mins, max_minutes=180):
                                self._send_json(500, {"ok": False, "error": "Failed to add HW boost"})
                                return

                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/ch/advance":
                        if not outer._clear_boost("CH"):
                            self._send_json(500, {"ok": False, "error": "Failed to clear CH boost"})
                            return
                        if not outer._toggle_advance("CH"):
                            self._send_json(500, {"ok": False, "error": "Failed to toggle CH advance"})
                            return
                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/hw/advance":
                        if not outer._clear_boost("HW"):
                            self._send_json(500, {"ok": False, "error": "Failed to clear HW boost"})
                            return
                        if not outer._toggle_advance("HW"):
                            self._send_json(500, {"ok": False, "error": "Failed to toggle HW advance"})
                            return
                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/settings/set":
                        body = self._read_body_or_400(raw_body)
                        if body is None:
                            return

                        key = body.get("key")
                        value = body.get("value")

                        if not key:
                            self._send_json(400, {"ok": False, "error": "Missing key"})
                            return

                        if not self._setting_update_or_500(key, value):
                            return

                        self._send_json(200, {"ok": True})
                        return

                    if parsed.path == "/api/settings/bulk":
                        body = self._read_body_or_400(raw_body)
                        if body is None:
                            return

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

                            if not self._setting_update_or_500(key, value, "Failed updating key %s" % key):
                                return

                            changed.append(str(key))

                        self._send_json(200, {"ok": True, "changed": changed})
                        return

                    if parsed.path == "/api/system/restart_dwellpi":
                        self._db_post("request_system_action", {"action": "restart_dwellpi"}, timeout=5.0)
                        return

                    if parsed.path == "/api/system/reboot_pi":
                        self._db_post("request_system_action", {"action": "reboot_pi"}, timeout=5.0)
                        return

                    if parsed.path == "/api/system/restart_process":
                        body = self._read_body_or_400(raw_body)
                        if body is None:
                            return

                        proc_name = str(body.get("name") or "").strip().lower()
                        msg = outer._rpc_supervisor("restart_process", {"name": proc_name}, timeout=5.0)

                        if msg is None:
                            self._send_json(504, {"ok": False, "error": "Supervisor timeout"})
                        else:
                            self._send_json(200, msg.payload or {"ok": False, "error": "Empty supervisor reply"})
                        return

                    db_post_routes = {
                        "/api/ch/program/create": ("create_program", "CH"),
                        "/api/ch/program/update": ("update_program", "CH"),
                        "/api/ch/program/delete": ("delete_program", "CH"),
                        "/api/ch/program/copy": ("copy_program", "CH"),
                        "/api/hw/program/create": ("create_program", "HW"),
                        "/api/hw/program/update": ("update_program", "HW"),
                        "/api/hw/program/delete": ("delete_program", "HW"),
                        "/api/hw/program/copy": ("copy_program", "HW"),
                    }

                    if parsed.path in db_post_routes:
                        body = self._read_body_or_400(raw_body)
                        if body is None:
                            return

                        msg_type, system = db_post_routes[parsed.path]

                        payload = {"system": system}

                        if msg_type in ("delete_program", "copy_program", "update_program"):
                            payload["id"] = body.get("id")

                        if msg_type in ("create_program", "update_program"):
                            payload.update({
                                "schedule_set_name": body.get("schedule_set_name", "NORMAL"),
                                "start_time": body.get("start_time"),
                                "end_time": body.get("end_time"),
                                "days": body.get("days"),
                                "note": body.get("note"),
                                "enabled": body.get("enabled")
                            })
                            if system == "CH":
                                payload["setpoint"] = body.get("setpoint")
                                payload["warmup"] = body.get("warmup")

                        self._db_post(msg_type, payload)
                        return

                    if parsed.path == "/api/special/program/create":
                        if self._db_post_from_body(
                                raw_body,
                                "create_special_period",
                                lambda body: {
                                    "start_ts_epoch": body.get("start_ts_epoch"),
                                    "start_ts_text": body.get("start_ts_text"),
                                    "end_ts_epoch": body.get("end_ts_epoch"),
                                    "end_ts_text": body.get("end_ts_text"),
                                    "systems": body.get("systems"),
                                    "schedule_set_name": body.get("schedule_set_name"),
                                    "enabled": body.get("enabled"),
                                    "note": body.get("note")
                                },
                                timeout=5.0):
                            return

                    if parsed.path == "/api/special/program/update":
                        if self._db_post_from_body(
                                raw_body,
                                "update_special_period",
                                lambda body: {
                                    "id": body.get("id"),
                                    "start_ts_epoch": body.get("start_ts_epoch"),
                                    "start_ts_text": body.get("start_ts_text"),
                                    "end_ts_epoch": body.get("end_ts_epoch"),
                                    "end_ts_text": body.get("end_ts_text"),
                                    "systems": body.get("systems"),
                                    "schedule_set_name": body.get("schedule_set_name"),
                                    "enabled": body.get("enabled"),
                                    "note": body.get("note")
                                },
                                timeout=5.0):
                            return

                    if parsed.path == "/api/special/program/delete":
                        if self._db_simple_id_post(raw_body, "delete_special_period", timeout=5.0):
                            return

                    if parsed.path == "/api/special/program/copy":
                        if self._db_simple_id_post(raw_body, "copy_special_period", timeout=5.0):
                            return

                    if parsed.path == "/api/holiday/program/create":
                        if self._db_post_from_body(
                                raw_body,
                                "create_holiday",
                                lambda body: {
                                    "start_ts_epoch": body.get("start_ts_epoch"),
                                    "start_ts_text": body.get("start_ts_text"),
                                    "end_ts_epoch": body.get("end_ts_epoch"),
                                    "end_ts_text": body.get("end_ts_text"),
                                    "systems": body.get("systems"),
                                    "enabled": body.get("enabled"),
                                    "note": body.get("note")
                                },
                                timeout=5.0):
                            return

                    if parsed.path == "/api/holiday/program/update":
                        if self._db_post_from_body(
                                raw_body,
                                "update_holiday",
                                lambda body: {
                                    "id": body.get("id"),
                                    "start_ts_epoch": body.get("start_ts_epoch"),
                                    "start_ts_text": body.get("start_ts_text"),
                                    "end_ts_epoch": body.get("end_ts_epoch"),
                                    "end_ts_text": body.get("end_ts_text"),
                                    "systems": body.get("systems"),
                                    "enabled": body.get("enabled"),
                                    "note": body.get("note")
                                },
                                timeout=5.0):
                            return

                    if parsed.path == "/api/holiday/program/delete":
                        if self._db_simple_id_post(raw_body, "delete_holiday", timeout=5.0):
                            return

                    if parsed.path == "/api/holiday/program/copy":
                        if self._db_simple_id_post(raw_body, "copy_holiday", timeout=5.0):
                            return

                    if parsed.path == "/api/ch/live_setpoint":
                        body = self._read_body_or_400(raw_body)
                        if body is None:
                            return

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

                        with outer.settings_lock:
                            ch_switch = str(outer.settings.get("CH_SYSTEM_SWITCH", "timed")).lower()

                        if ch_switch == "on":
                            if not self._setting_update_or_500("DEFAULT_ON_SETPOINT", value):
                                return
                            self._send_json(200, {"ok": True, "target": "DEFAULT_ON_SETPOINT"})
                            return

                        with outer.settings_lock:
                            try:
                                boost_finish = int(outer.settings.get("CH_BOOST_FINISH_EPOCH", "0") or "0")
                            except Exception:
                                boost_finish = 0

                        if boost_finish and now_epoch < boost_finish:
                            if not self._setting_update_or_500("BOOST_SETPOINT", value):
                                return
                            self._send_json(200, {"ok": True, "target": "BOOST_SETPOINT"})
                            return

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

                        if not self._setting_update_or_500("DEFAULT_SETPOINT", value):
                            return

                        self._send_json(200, {"ok": True, "target": "DEFAULT_SETPOINT"})
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

        try:
            self.db_queue.put(Message("web", "request_settings_snapshot", {}))
        except Exception:
            pass

        ok = self.wait_for_initial_snapshot(self.ctrl_queue, self.shutdown_event, timeout=3.0)
        if not ok:
            print("[Web] No settings snapshot received yet; using defaults")

        handler = self._make_handler()
        server = ThreadedHTTPServer(("0.0.0.0", 80), handler)
        server.timeout = 1.0

        last_hb = 0.0
        last_supervisor_request = 0.0

        try:
            while not self.shutdown_event.is_set():
                self._drain_ctrl_queue()
                self._drain_web_queue()
                self._drain_web_rpc_queue()

                now = time.time()

                if now - last_supervisor_request >= 5.0:
                    self._request_supervisor_status()
                    last_supervisor_request = now

                if now - last_hb >= 5.0:
                    try:
                        self.db_queue.put(Message("web", "heartbeat", {"status": "ok"}))
                    except Exception as e:
                        print("[Web] heartbeat failed: %s" % e)
                    last_hb = now

                try:
                    server.handle_request()
                except Exception as e:
                    print("[Web] handle_request error: %s" % e)
        finally:
            try:
                server.server_close()
            except Exception:
                pass

        print("[Web] Shutting down cleanly")