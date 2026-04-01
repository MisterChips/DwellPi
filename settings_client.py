#!/usr/bin/python
# -*- coding: utf-8 -*-
#settings_client.py

from __future__ import print_function
import time
try:
    from Queue import Empty as QueueEmpty       # Py2
except ImportError:
    from queue import Empty as QueueEmpty       # Py3


class SettingsClient(object):
    """
    Small helper for processes that receive:
      - settings_snapshot
      - setting_changed

    Subclass or compose it with a process object that implements:
      _apply_setting_changed(key, value)

    Optional:
  _on_settings_snapshot_applied(values_dict)   # preferred
  _on_settings_snapshot(values_dict)           # legacy fallback
  _on_unknown_ctrl_message(msg)
    """

    def __init__(self, ctrl_queue, shutdown_event, name="Process"):
        self.ctrl_queue = ctrl_queue
        self.shutdown_event = shutdown_event
        self.settings = {}
        self._settings_client_name = name

    def _apply_settings_snapshot(self, values_dict):
        if not values_dict:
            return

        self.settings.update(values_dict)

        for key, value in values_dict.items():
            try:
                self._apply_setting_changed(key, value)
            except Exception:
                pass

        hook = getattr(self, "_on_settings_snapshot_applied", None)
        if not hook:
            hook = getattr(self, "_on_settings_snapshot", None)

        if hook:
            try:
                hook(values_dict)
            except Exception:
                pass

    def _handle_ctrl_message(self, msg):
        if msg.type == "settings_snapshot":
            self._apply_settings_snapshot((msg.payload or {}).get("values"))
            return "snapshot"

        if msg.type == "setting_changed":
            p = msg.payload or {}
            key = p.get("key")
            value = p.get("value")

            if key is not None:
                self.settings[key] = value

            try:
                self._apply_setting_changed(key, value)
            except Exception:
                pass

            return "changed"

        hook = getattr(self, "_on_unknown_ctrl_message", None)
        if hook:
            try:
                hook(msg)
            except Exception:
                pass

        return "other"

    def drain_ctrl_queue(self):
        got_snapshot = False

        while True:
            try:
                msg = self.ctrl_queue.get_nowait()
            except QueueEmpty:
                break

            result = self._handle_ctrl_message(msg)
            if result == "snapshot":
                got_snapshot = True

        return got_snapshot

    def wait_for_initial_snapshot(self, timeout=3.0):
        deadline = time.time() + timeout

        while time.time() < deadline and not self.shutdown_event.is_set():
            try:
                msg = self.ctrl_queue.get(timeout=0.5)
            except QueueEmpty:
                continue

            result = self._handle_ctrl_message(msg)
            if result == "snapshot":
                return True

        return False

    def get_setting_cached(self, key, default=None):
        value = self.settings.get(key)
        return value if value is not None else default