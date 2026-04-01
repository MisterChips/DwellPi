#!/usr/bin/python
# -*- coding: utf-8 -*-
# settings_sync.py

from __future__ import print_function
import time


class _NoOpLock(object):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class SettingsSyncMixin(object):
    def _settings_store(self):
        raise NotImplementedError

    def _settings_lock(self):
        return _NoOpLock()

    def _on_setting_changed(self, key, value):
        pass

    def _on_settings_snapshot_applied(self, values):
        pass

    def apply_settings_snapshot(self, values):
        if not values:
            return

        try:
            with self._settings_lock():
                store = self._settings_store()
                store.update(values)

            for key, value in values.items():
                self._on_setting_changed(key, value)

            self._on_settings_snapshot_applied(values)
        except Exception as e:
            print("[SettingsSync] Failed to apply snapshot: %s" % e)

    def apply_setting_changed(self, key, value):
        try:
            with self._settings_lock():
                store = self._settings_store()
                store[key] = value

            self._on_setting_changed(key, value)
        except Exception as e:
            print("[SettingsSync] Failed to apply setting %s=%r: %s" % (key, value, e))

    def wait_for_initial_snapshot(self, ctrl_queue, shutdown_event, timeout=3.0):
        deadline = time.time() + timeout

        while time.time() < deadline and not shutdown_event.is_set():
            try:
                msg = ctrl_queue.get(timeout=0.5)
            except Exception:
                continue

            if msg.type == "settings_snapshot":
                self.apply_settings_snapshot((msg.payload or {}).get("values"))
                return True

            elif msg.type == "setting_changed":
                p = msg.payload or {}
                self.apply_setting_changed(p.get("key"), p.get("value"))

            else:
                self.handle_non_settings_ctrl_message(msg)

        return False

    def drain_ctrl_queue_settings(self, ctrl_queue):
        while True:
            try:
                msg = ctrl_queue.get_nowait()
            except Exception:
                break

            if msg.type == "settings_snapshot":
                self.apply_settings_snapshot((msg.payload or {}).get("values"))

            elif msg.type == "setting_changed":
                p = msg.payload or {}
                self.apply_setting_changed(p.get("key"), p.get("value"))

            else:
                self.handle_non_settings_ctrl_message(msg)

    def handle_non_settings_ctrl_message(self, msg):
        """
        Optional override for process-specific ctrl_queue messages.
        """
        pass