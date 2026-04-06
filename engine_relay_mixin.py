#!/usr/bin/python
# -*- coding: utf-8 -*-
# engine_relay_mixin.py

from __future__ import print_function

import time

from message_schema import Message


class EngineRelayMixin(object):

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

    def _get_relay_letter(self, system_name):
        system_name = str(system_name or "").strip().upper()

        if system_name == "CH":
            return str(self.settings.get("CH_RELAY_LETTER", "A") or "A").strip().upper()

        if system_name == "HW":
            return str(self.settings.get("HW_RELAY_LETTER", "B") or "B").strip().upper()

        return ""

    def _relay_allowed(self):
        if self.mode == "TEST":
            return True
        return bool(self.relay_enable)

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
            "relay_a": self._relay_state_to_bool(
                self.ch_actual_relay if self._get_relay_letter("CH") == "A" else self.hw_actual_relay
            ),
            "relay_b": self._relay_state_to_bool(
                self.ch_actual_relay if self._get_relay_letter("CH") == "B" else self.hw_actual_relay
            ),
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