#!/usr/bin/python
# -*- coding: utf-8 -*-
# engine_alerts_mixin.py

from __future__ import print_function

from message_schema import Message


class EngineAlertsMixin(object):

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