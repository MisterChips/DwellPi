#!/usr/bin/python
# -*- coding: utf-8 -*-
# sensor_process.py

from __future__ import print_function

import time

from message_schema import Message
from temperature_reader import TemperatureReader
from settings_client import SettingsClient

class SensorProcess(SettingsClient):
    def __init__(self, engine_queue, db_queue, ctrl_queue, ui_queue, web_queue, mode, shutdown_event):
        SettingsClient.__init__(self, ctrl_queue, shutdown_event, name="Sensor")
        self.engine_queue = engine_queue
        self.db_queue = db_queue
        self.ui_queue = ui_queue
        self.web_queue = web_queue
        self.mode = mode
        self.sensor_interval = 2.0
        self.temp_adjust = -4.0  # default; DB push will keep this current

        self.sensor_device_id = None
        self.reader = None

        # DB temperature log throttling
        self.last_logged_temp = None
        self.last_logged_temp_epoch = 0.0
        self.temp_log_min_delta = 0.1          # log if changed by >= 0.1C
        self.temp_log_max_interval = 600.0     # or at least once every 10 mins

    def _apply_setting_changed(self, key, value):
        if key == "SENSOR_INTERVAL":
            try:
                self.sensor_interval = float(value)
            except Exception:
                self.sensor_interval = 2.0
        elif key == "TEMP_SENSOR_ADJUSTMENT_DEGREES":
            try:
                self.temp_adjust = float(value)
            except Exception:
                self.temp_adjust = -4.0
        elif key == "SENSOR_DEVICE_ID":
            try:
                new_id = str(value or "").strip()
            except Exception:
                new_id = ""

            if new_id != self.sensor_device_id:
                self.sensor_device_id = new_id or None
                self.reader = None
                print("[Sensor] SENSOR_DEVICE_ID updated: %s" % self.sensor_device_id)

    def _should_log_temperature(self, temp_c, now_epoch):
        if self.last_logged_temp is None:
            return True

        try:
            if abs(float(temp_c) - float(self.last_logged_temp)) >= float(self.temp_log_min_delta):
                return True
        except Exception:
            return True

        if (now_epoch - float(self.last_logged_temp_epoch)) >= float(self.temp_log_max_interval):
            return True

        return False

    def run(self):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[Sensor] Started in mode: %s" % self.mode)

        ok = self.wait_for_initial_snapshot(timeout=3.0)
        if not ok:
            print("[Sensor] No settings snapshot received yet; using defaults")

        print("[Sensor] SENSOR_INTERVAL initial: %s" % self.sensor_interval)
        print("[Sensor] TEMP_SENSOR_ADJUSTMENT_DEGREES initial: %s" % self.temp_adjust)

        while not self.shutdown_event.is_set():

            # Drain ctrl queue (push updates)
            self.drain_ctrl_queue()

            # Heartbeat
            self.db_queue.put(Message("sensor", "heartbeat", {"status": "ok"}))

            if not self.sensor_device_id:
                print("[Sensor] waiting for SENSOR_DEVICE_ID...")
                time.sleep(self.sensor_interval)
                continue

            if self.reader is None:
                try:
                    self.reader = TemperatureReader(
                        self.sensor_device_id,
                        max_jump_c=3.0,
                        retries=6,
                        retry_delay=0.2
                    )
                    print("[Sensor] Reader created for SENSOR_DEVICE_ID=%s" % self.sensor_device_id)
                except Exception as e:
                    print("[Sensor] Failed to create reader: %s" % e)
                    time.sleep(self.sensor_interval)
                    continue

            try:
                raw_c = self.reader.read_c()
                adj_c = round(raw_c + float(self.temp_adjust), 1)

                print("[Sensor] raw=%.1fC adj=%.1fC (adj=%+.1f) interval=%.2f" %
                      (raw_c, adj_c, self.temp_adjust, self.sensor_interval))

                now_epoch = time.time()

                # Log adjusted temp only if changed enough or aged out
                if self._should_log_temperature(adj_c, now_epoch):
                    self.db_queue.put(Message("sensor", "temperature", {
                        "timestamp": now_epoch,
                        "value": adj_c
                    }))
                    self.last_logged_temp = adj_c
                    self.last_logged_temp_epoch = now_epoch

                # Send adjusted temp only
                try:
                    self.engine_queue.put(Message("sensor", "TEMP_UPDATE", {
                        "temperature": adj_c
                    }))
                except Exception:
                    pass

                try:
                    self.ui_queue.put(Message("sensor", "ui_state", {"temp": adj_c}))
                except Exception:
                    pass

                try:
                    self.web_queue.put(Message("sensor", "web_state", {"temp": adj_c}))
                except Exception:
                    pass

            except Exception as e:
                print("[Sensor] Temp read FAILED: %s" % e)
                self.reader = None
                self.db_queue.put(Message("sensor", "state_change", {
                    "system": "SENSOR",
                    "state": "Temp read failed: %s" % e
                }))

            time.sleep(self.sensor_interval)

        print("[Sensor] Shutting down cleanly")