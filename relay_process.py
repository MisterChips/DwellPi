#!/usr/bin/python
# -*- coding: utf-8 -*-
# relay_process.py

from __future__ import print_function

import time
try:
    from Queue import Empty as QueueEmpty  # Py2
except ImportError:
    from queue import Empty as QueueEmpty  # Py3

from message_schema import Message
from commands.common import parse_bool
from settings_client import SettingsClient


class RelayController(object):
    def __init__(self, mode, relay_device_id="RB"):
        self.mode = mode
        self.relay_device_id = relay_device_id

        # TEST mode simulation
        self.sim_status = {"A": False, "B": False}

        # PROD hardware
        self.hub = None
        self.rb = None
        self.started = False

    def start(self):
        """
        Start hardware comms (PRODUCTION only). Safe to call multiple times.
        """
        if self.started:
            return

        if self.mode == "PRODUCTION":
            # Ensure these match your renamed V2 modules.
            from llap.commsV2 import LlapHub
            from llap.devicesV2 import DualRelayBoard

            self.hub = LlapHub()
            self.rb = DualRelayBoard(self.hub, self.relay_device_id)
            self.hub.start()
            time.sleep(0.2) # small settle time
            self.started = True
            print("[Relay] LLAP started, relay_device_id=%s" % self.relay_device_id)
        else:
            # TEST mode never starts hardware
            self.started = True
            print("[Relay] TEST mode - no hardware. relay_device_id=%s" % self.relay_device_id)

    def stop(self):
        """
        Stop hardware comms (best effort). Safe to call multiple times.
        """
        if not self.started:
            return

        if self.mode == "PRODUCTION":
            try:
                if self.hub:
                    self.hub.stop()
            except Exception:
                pass
            self.hub = None
            self.rb = None
            self.started = False
            print("[Relay] LLAP stopped")
        else:
            self.started = False
            print("[Relay] TEST mode stopped")

    def _get_relay_obj(self, relay_letter):
        if relay_letter == "A":
            return self.rb.relay_a
        if relay_letter == "B":
            return self.rb.relay_b
        raise ValueError("unknown relay: %r" % relay_letter)

    def set_relay(self, relay_letter, on):
        relay_letter = (relay_letter or "").upper()
        if relay_letter not in ("A", "B"):
            raise ValueError("relay must be 'A' or 'B'")

        if self.mode == "PRODUCTION":
            if not self.rb:
                raise RuntimeError("LLAP not started")

            r = self._get_relay_obj(relay_letter)

            if on:
                result = r.on()
            else:
                result = r.off()

            if result is None:
                # Command worked well enough to not raise, but no status came back.
                # Keep software state aligned with commanded state.
                r._status = bool(on)
                return r._status

            return result
        else:
            self.sim_status[relay_letter] = bool(on)
            print("[Relay][TEST] RELAY%s -> %s" % (relay_letter, "ON" if on else "OFF"))
            return self.sim_status[relay_letter]

    def toggle_relay(self, relay_letter):
        relay_letter = (relay_letter or "").upper()
        if relay_letter not in ("A", "B"):
            raise ValueError("relay must be 'A' or 'B'")

        if self.mode == "PRODUCTION":
            if not self.rb:
                raise RuntimeError("LLAP not started")

            r = self._get_relay_obj(relay_letter)
            result = r.toggle()

            if result is None:
                if r._status is None:
                    return None
                r._status = not r._status
                return r._status

            return result
        else:
            self.sim_status[relay_letter] = not self.sim_status[relay_letter]
            print("[Relay][TEST] RELAY%s TOGGLE -> %s" % (
                relay_letter, "ON" if self.sim_status[relay_letter] else "OFF"
            ))
            return self.sim_status[relay_letter]

    def get_status(self):
        if self.mode == "PRODUCTION":
            if not self.rb:
                return {"A": None, "B": None}

            a = self._read_relay_status_with_retry(self.rb.relay_a, "A")
            time.sleep(0.15)
            b = self._read_relay_status_with_retry(self.rb.relay_b, "B")

            print("[Relay] get_status raw: A=%r B=%r" % (a, b))
            return {"A": a, "B": b}

        return dict(self.sim_status)

    def _read_relay_status_with_retry(self, relay_obj, label, retries=3, pause=0.25):
        last = relay_obj.status
        if last is not None:
            return last

        for i in range(retries):
            time.sleep(pause)
            try:
                last = relay_obj.status
            except Exception:
                last = None

            if last is not None:
                print("[Relay] %s status recovered on retry %s: %r" % (label, i + 1, last))
                return last

        print("[Relay] %s status still unknown after retries" % label)
        return last

    def get_board_info(self):
        def safe(getter, default=None):
            try:
                return getter()
            except Exception:
                return default

        if self.mode != "PRODUCTION":
            return {
                "device_id": self.relay_device_id,
                "llap_version": "TEST",
                "device_type": "TEST",
                "device_name": "TEST",
                "serial_number": "TEST",
                "firmware_version": "TEST",
                "battery_level": "TEST",
                "relay_a": self.sim_status.get("A"),
                "relay_b": self.sim_status.get("B"),
            }

        if not self.rb:
            return {
                "device_id": self.relay_device_id,
                "llap_version": None,
                "device_type": None,
                "device_name": None,
                "serial_number": None,
                "firmware_version": None,
                "battery_level": None,
                "relay_a": None,
                "relay_b": None,
            }

        st = safe(self.get_status, {"A": None, "B": None})

        return {
            "device_id": safe(lambda: self.rb.device_id, self.relay_device_id),
            "llap_version": safe(lambda: self.rb.llap_version),
            "device_type": safe(lambda: self.rb.device_type),
            "device_name": safe(lambda: self.rb.device_name),
            "serial_number": safe(lambda: self.rb.serial_number),
            "firmware_version": safe(lambda: self.rb.firmware_version),
            "battery_level": safe(lambda: self.rb.battery_level),
            "relay_a": st.get("A"),
            "relay_b": st.get("B"),
        }


class RelayProcess(SettingsClient):
    def __init__(self, relay_queue, db_queue, ctrl_queue, ui_queue, web_queue,
                 mode, shutdown_event, rpc_reply_queue=None, engine_rpc_queue=None,
                 web_rpc_queue=None):
        SettingsClient.__init__(self, ctrl_queue, shutdown_event, name="Relay")
        self.relay_queue = relay_queue
        self.db_queue = db_queue
        self.ui_queue = ui_queue
        self.web_queue = web_queue
        self.web_rpc_queue = web_rpc_queue
        self.mode = mode
        self.rpc_reply_queue = rpc_reply_queue
        self.engine_rpc_queue = engine_rpc_queue

        # settings-driven
        self.relay_device_id = "RB"
        self.relay_enable = False

        self.ctrl = RelayController(mode, relay_device_id=self.relay_device_id)

    def _publish_ui_state(self):
        try:
            st = self.ctrl.get_status()
            self.ui_queue.put(Message("relay", "ui_state", {
                "relay_a": st["A"],
                "relay_b": st["B"]
            }))
        except Exception as e:
            print("[Relay] _publish_ui_state failed: %s" % e)

    def _publish_web_state(self):
        try:
            st = self.ctrl.get_status()
            self.web_queue.put(Message("relay", "web_state", {
                "relay_a": st["A"],
                "relay_b": st["B"]
            }))
        except Exception as e:
            print("[Relay] _publish_web_state failed: %s" % e)

    def _apply_setting_changed(self, key, value):
        if key == "RELAY_BOARD_DEVICE_ID":
            try:
                new_id = str(value or "").strip()
            except Exception:
                new_id = ""

            if not new_id:
                return

            if new_id == self.relay_device_id:
                return

            self.relay_device_id = new_id

            if not self.ctrl.started:
                self.ctrl.relay_device_id = self.relay_device_id
                print("[Relay] RELAY_BOARD_DEVICE_ID updated: %s" % self.relay_device_id)
                return

            if self.mode == "PRODUCTION":
                try:
                    self.ctrl.stop()
                except Exception:
                    pass

                self.ctrl.relay_device_id = self.relay_device_id

                if self._hardware_allowed():
                    try:
                        self.ctrl.start()
                    except Exception:
                        pass

            print("[Relay] RELAY_BOARD_DEVICE_ID updated: %s" % self.relay_device_id)

        elif key == "RELAY_ENABLE":
            self.relay_enable = parse_bool(value)

    def _fmt_status(self, value):
        if value is True:
            return "ON"
        if value is False:
            return "OFF"
        return "--"

    def _hardware_allowed(self):
        # TEST never touches hardware regardless
        if self.mode == "TEST":
            return False
        return bool(self.relay_enable)

    def run(self):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[Relay] Started in mode: %s" % self.mode)

        ok = self.wait_for_initial_snapshot(timeout=3.0)
        if not ok:
            print("[Relay] No settings snapshot received yet; using defaults (RELAY_ENABLE=False)")

        print("[Relay] RELAY_ENABLE=%s RELAY_BOARD_DEVICE_ID=%s" % (self.relay_enable, self.relay_device_id))

        # Lazy-start rule:
        # - TEST: never start LLAP (only prints when commanded)
        # - PRODUCTION: only start LLAP if RELAY_ENABLE=True
        if self._hardware_allowed():
            if self.relay_device_id:
                self.ctrl.relay_device_id = self.relay_device_id
            self.ctrl.start()
        else:
            print("[Relay] Hardware disabled; LLAP will not start yet")

        try:
            _ = self.ctrl.get_status()
            print("[Relay] Initial relay status read attempted")
        except Exception as e:
            print("[Relay] Initial relay status read failed: %s" % e)

        self._publish_ui_state()
        self._publish_web_state()

        last_hb = 0.0

        try:
            while not self.shutdown_event.is_set():
                # settings updates
                self.drain_ctrl_queue()

                # Start/stop LLAP dynamically based on RELAY_ENABLE
                if self.mode == "PRODUCTION":
                    if self._hardware_allowed() and (not self.ctrl.started):
                        print("[Relay] RELAY_ENABLE=True -> starting LLAP")
                        self.ctrl.relay_device_id = self.relay_device_id
                        self.ctrl.start()
                        self._publish_ui_state()
                        self._publish_web_state()
                    elif (not self._hardware_allowed()) and self.ctrl.started:
                        print("[Relay] RELAY_ENABLE=False -> stopping LLAP")
                        try:
                            self.ctrl.stop()
                        except Exception:
                            pass
                        self._publish_ui_state()
                        self._publish_web_state()

                # heartbeat (so supervisor can watchdog it)
                now = time.time()
                if now - last_hb >= 5.0:
                    try:
                        self.db_queue.put(Message("relay", "heartbeat", {"status": "ok"}))
                    except Exception:
                        pass
                    last_hb = now

                # process relay messages
                try:
                    msg = self.relay_queue.get(timeout=1.0)
                except QueueEmpty:
                    continue
                except Exception as e:
                    print("[Relay] relay_queue get failed: %s" % e)
                    continue

                try:
                    if msg.type == "relay_set":
                        p = msg.payload or {}
                        relay = p.get("relay")
                        state = p.get("state")
                        reason = p.get("reason", "")

                        # state can be "ON"/"OFF" or bool-ish
                        try:
                            basestring  # noqa
                            is_str = isinstance(state, basestring)
                        except Exception:
                            is_str = isinstance(state, str)

                        if is_str:
                            on = (str(state).upper() == "ON")
                        else:
                            on = bool(state)

                        if self.mode == "PRODUCTION" and (not self._hardware_allowed()):
                            print("[Relay] BLOCKED relay_set (RELAY_ENABLE=False) relay=%s state=%s reason=%s" %
                                  (relay, "ON" if on else "OFF", reason))
                            continue

                        status = self.ctrl.set_relay(relay, on)
                        self._publish_ui_state()
                        self._publish_web_state()

                        fmt = self._fmt_status(status)

                        print("[Relay] %s relay=%s -> %s (%s)" %
                              (self.mode, relay, fmt, reason))

                        state_text = "UNKNOWN" if fmt == "--" else fmt

                        try:
                            self.db_queue.put(Message("relay", "state_change", {
                                "system": "RELAY%s" % str(relay).upper(),
                                "state": "SET_%s" % state_text
                            }))
                        except Exception:
                            pass

                    elif msg.type == "relay_toggle":
                        p = msg.payload or {}
                        relay = p.get("relay")

                        if self.mode == "PRODUCTION" and (not self._hardware_allowed()):
                            print("[Relay] BLOCKED relay_toggle (RELAY_ENABLE=False) relay=%s" % relay)
                            continue

                        status = self.ctrl.toggle_relay(relay)
                        self._publish_ui_state()
                        self._publish_web_state()

                        fmt = self._fmt_status(status)

                        print("[Relay] %s relay=%s -> %s (toggle)" %
                              (self.mode, relay,fmt))

                        state_text = "UNKNOWN" if fmt == "--" else fmt

                        try:
                            self.db_queue.put(Message("relay", "state_change", {
                                "system": "RELAY%s" % str(relay).upper(),
                                "state": "TOGGLE_%s" % state_text
                            }))
                        except Exception:
                            pass


                    elif msg.type == "relay_status":
                        request_id = getattr(msg, "request_id", None)
                        p = msg.payload or {}

                        try:
                            st = self.ctrl.get_status()
                        except Exception as e:
                            print("[Relay] relay_status failed: %s" % e)
                            st = {"A": None, "B": None}

                        print("[Relay] status A=%s B=%s" %
                              (self._fmt_status(st["A"]), self._fmt_status(st["B"])))

                        self._publish_ui_state()
                        self._publish_web_state()

                        reply_msg = Message(
                            "relay",
                            "relay_status_result",
                            {"A": st["A"], "B": st["B"]},
                            target=msg.source,
                            request_id=request_id
                        )

                        if msg.source == "engine":
                            if self.engine_rpc_queue is not None:
                                try:
                                    self.engine_rpc_queue.put(reply_msg)
                                except Exception:
                                    pass
                            else:
                                print("[Relay] WARNING: engine_rpc_queue is None; cannot return relay_status_result")

                        elif msg.source == "rpc":
                            if self.rpc_reply_queue is not None:
                                try:
                                    self.rpc_reply_queue.put(reply_msg)
                                except Exception:
                                    pass
                            else:
                                print("[Relay] WARNING: rpc_reply_queue is None; cannot return relay_status_result")

                        else:
                            print("[Relay] WARNING: unknown relay_status requester source=%r" % (msg.source,))



                    elif msg.type == "relay_info":
                        request_id = getattr(msg, "request_id", None)
                        p = msg.payload or {}

                        print("[Relay] relay_info request received request_id=%r" % request_id)

                        try:
                            info = self.ctrl.get_board_info()
                            print("[Relay] relay_info result: %r" % info)
                        except Exception as e:
                            print("[Relay] relay_info failed: %s" % e)
                            info = {
                                "device_id": self.relay_device_id,
                                "error": str(e)
                            }

                        reply_msg = Message(
                            "relay",
                            "relay_info_result",
                            info,
                            target=msg.source,
                            request_id=request_id
                        )

                        if msg.source == "web":
                            if self.web_rpc_queue is not None:
                                try:
                                    self.web_rpc_queue.put(reply_msg)
                                except Exception:
                                    pass

                            else:
                                print("[Relay] WARNING: web_rpc_queue is None; cannot return relay_info_result")

                        elif msg.source == "engine":
                            if self.engine_rpc_queue is not None:
                                try:
                                    self.engine_rpc_queue.put(reply_msg)
                                except Exception:
                                    pass
                            else:
                                print("[Relay] WARNING: engine_rpc_queue is None; cannot return relay_info_result")

                        else:
                            print("[Relay] WARNING: unknown relay_info requester source=%r" % (msg.source,))

                    elif msg.type == "shutdown":
                        break

                except Exception as e:
                    print("[Relay] ERROR handling %s: %s" % (getattr(msg, "type", "?"), e))
                    try:
                        self.db_queue.put(Message("relay", "state_change", {
                            "system": "RELAY",
                            "state": "ERROR: %s" % e
                        }))
                    except Exception:
                        pass

        finally:
            # Ensure hardware is closed cleanly (prevents shutdown thread errors)
            try:
                self.ctrl.stop()
            except Exception:
                pass

        print("[Relay] Shutting down cleanly")