#!/usr/bin/python
# -*- coding: utf-8 -*-
# engine_process.py

from __future__ import print_function

import time
import sqlite3

from message_schema import Message
from commands.common import parse_bool
from settings_client import SettingsClient
from engine_predictive_mixin import EnginePredictiveMixin
from engine_schedule_mixin import EngineScheduleMixin
from engine_relay_mixin import EngineRelayMixin
from engine_alerts_mixin import EngineAlertsMixin


class EngineProcess(EnginePredictiveMixin, EngineScheduleMixin, EngineRelayMixin, EngineAlertsMixin, SettingsClient):
    def __init__(self, engine_queue, engine_rpc_queue, ui_queue, web_queue,
                 db_queue, ctrl_queue, relay_queue, email_queue, mode, db_path, shutdown_event):
        SettingsClient.__init__(self, ctrl_queue, shutdown_event, name="Engine")

        self.engine_queue = engine_queue
        self.engine_rpc_queue = engine_rpc_queue
        self.ui_queue = ui_queue
        self.web_queue = web_queue
        self.email_queue = email_queue
        self.db_queue = db_queue
        self.ctrl_queue = ctrl_queue
        self.mode = mode
        self.shutdown_event = shutdown_event

        self.relay_queue = relay_queue

        self.db_path = db_path
        self.db_con = None

        # relay safety / mapping
        self.relay_enable = False
        self.ch_relay_letter = "A"
        self.hw_relay_letter = "B"

        # actual relay states reported by relay process / board
        self.ch_actual_relay = None   # "ON"/"OFF"/None
        self.hw_actual_relay = None   # "ON"/"OFF"/None
        self.last_actual_relay_update_epoch = 0.0

        # defaults (will be overwritten by snapshot/push)
        self.engine_interval = 2.0
        self.current_temp = None
        self.last_temp_update_epoch = 0.0
        self.temp_stale_timeout = 300.0   # seconds
        self._temp_stale_active = False

        self.ch_system_switch = "timed"   # timed/on/off/once
        self.hw_system_switch = "timed"   # timed/on/off/once
        self.ch_advance = False
        self.hw_advance = False

        self.default_setpoint = 10.0
        self.default_on_setpoint = 20.0
        self.hysteresis_band = 0.0

        # warmup / legacy heat-up settings
        self.fallback_heatup_rate = 0.4
        self.warmup_minimum_lead_time = 30   # minutes
        self.warmup_maximum_lead_time = 120  # minutes
        self.warmup_target_offset = 0.0

        # ---- warmup outcome tracking ----
        self._active_warmup_outcome = None

        # relay reply checking
        self._last_relay_sync = 0.0
        self._pending_sync_request_id = None

        # short cycling protection
        self.ch_last_change_epoch = None
        self.ch_last_on_epoch = None
        self.ch_last_off_epoch = None
        self.ch_min_on_seconds = 120
        self.ch_min_off_seconds = 120

        # CH/HW decision state
        self.ch_desired = None  # "ON"/"OFF"
        self.hw_desired = None  # "ON"/"OFF"

        # alert thresholds / state
        self.alert_relay_timeout_seconds = 10.0
        self.alert_temp_rise_check_seconds = 900.0
        self.alert_temp_rise_min_delta = 0.3

        self._relay_mismatch_active = False
        self._pending_relay_verification = None

        self._temp_rise_active = False
        self._temp_rise_start_epoch = None
        self._temp_rise_start_temp = None
        self._temp_rise_alert_active = False

        # ---- predictive heating / adaptive heat-up model ----
        self.predictive_heating_enabled = True
        self.predictive_base_rate = 0.7   # °C/hour, derived from legacy data
        self.predictive_min_rate = 0.15   # floor to avoid divide-by-zero / nonsense
        self.predictive_max_rate = 1.50   # clamp for safety
        self.predictive_min_learning_seconds = 600.0
        self.learned_heatup_sample_count = 0

        # ---- passive cooling / thermal inertia learning ----
        self.learned_cooldown_rate = None       # °C/hour, usually negative
        self.learned_cooldown_rate_updated_epoch = 0.0
        self.cooldown_sample_window = 30
        self.cooldown_min_off_seconds = 1800.0
        self.cooldown_min_delta_c = 0.2
        self.predictive_cooling_enabled = True

        self.passive_cool_run = None

        # ---- predictive learning (persistent) ----
        self.active_heat_run = None
        self.learned_heatup_rate = None
        self.learned_heatup_rate_updated_epoch = 0.0
        self.live_heatup_run_start_ts = 0.0

        self.predictive_sample_window = 20
        self.predictive_min_run_seconds = 900.0
        self.predictive_min_delta_c = 0.3

        self.predictive_bias_enabled = True
        self.predictive_bias_max_minutes = 45.0

        self.learned_warmup_bias_minutes = 0.0
        self.learned_warmup_bias_morning_minutes = 0.0
        self.learned_warmup_bias_evening_minutes = 0.0

        self.learned_warmup_bias_small_minutes = 0.0
        self.learned_warmup_bias_medium_minutes = 0.0
        self.learned_warmup_bias_large_minutes = 0.0

        self.learned_warmup_bias_morning_small_minutes = 0.0
        self.learned_warmup_bias_morning_medium_minutes = 0.0
        self.learned_warmup_bias_morning_large_minutes = 0.0

        self.learned_warmup_bias_evening_small_minutes = 0.0
        self.learned_warmup_bias_evening_medium_minutes = 0.0
        self.learned_warmup_bias_evening_large_minutes = 0.0

        self.learned_warmup_bias_updated_epoch = 0.0

        self.learned_warmup_bias_sample_count = 0
        self.learned_warmup_bias_morning_sample_count = 0
        self.learned_warmup_bias_evening_sample_count = 0

        self.learned_warmup_bias_small_sample_count = 0
        self.learned_warmup_bias_medium_sample_count = 0
        self.learned_warmup_bias_large_sample_count = 0

        self.learned_warmup_bias_morning_small_sample_count = 0
        self.learned_warmup_bias_morning_medium_sample_count = 0
        self.learned_warmup_bias_morning_large_sample_count = 0

        self.learned_warmup_bias_evening_small_sample_count = 0
        self.learned_warmup_bias_evening_medium_sample_count = 0
        self.learned_warmup_bias_evening_large_sample_count = 0

        self.predictive_bias_full_confidence_samples = 5

        self.last_heatup_temp = None
        self.last_heatup_ts = 0.0
        self.live_heatup_rate = None      # °C/hour

    def _apply_setting_changed(self, key, value):
        try:
            if key == "ENGINE_INTERVAL":
                self.engine_interval = float(value)
            elif key == "CH_SYSTEM_SWITCH":
                self.ch_system_switch = str(value)
            elif key == "HW_SYSTEM_SWITCH":
                self.hw_system_switch = str(value)
            elif key == "CH_ADVANCE":
                self.ch_advance = parse_bool(value)
            elif key == "HW_ADVANCE":
                self.hw_advance = parse_bool(value)
            elif key == "DEFAULT_SETPOINT":
                self.default_setpoint = float(value)
            elif key == "DEFAULT_ON_SETPOINT":
                self.default_on_setpoint = float(value)
            elif key == "HYSTERESIS_BAND":
                self.hysteresis_band = float(value)
            elif key == "FALLBACK_HEATUP_RATE":
                self.fallback_heatup_rate = float(value)
            elif key == "WARMUP_MINIMUM_LEAD_TIME":
                self.warmup_minimum_lead_time = max(0, int(float(value)))
            elif key == "WARMUP_MAXIMUM_LEAD_TIME":
                self.warmup_maximum_lead_time = max(0, int(float(value)))
            elif key == "WARMUP_TARGET_OFFSET":
                self.warmup_target_offset = float(value)
            elif key == "RELAY_ENABLE":
                self.relay_enable = parse_bool(value)
            elif key == "CH_RELAY_LETTER":
                self.ch_relay_letter = str(value).upper()
            elif key == "HW_RELAY_LETTER":
                self.hw_relay_letter = str(value).upper()
            elif key == "CH_LAST_DESIRED":
                v = (str(value) or "").strip().upper()
                if v in ("ON", "OFF"):
                    self.ch_desired = v
            elif key == "HW_LAST_DESIRED":
                v = (str(value) or "").strip().upper()
                if v in ("ON", "OFF"):
                    self.hw_desired = v
            elif key == "CH_MIN_ON_SECONDS":
                self.ch_min_on_seconds = max(0, int(float(value)))
            elif key == "CH_MIN_OFF_SECONDS":
                self.ch_min_off_seconds = max(0, int(float(value)))
            elif key == "ALERT_SENSOR_STALE_SECONDS":
                self.temp_stale_timeout = max(10.0, float(value))
            elif key == "ALERT_RELAY_TIMEOUT_SECONDS":
                self.alert_relay_timeout_seconds = max(1.0, float(value))
            elif key == "ALERT_TEMP_RISE_CHECK_SECONDS":
                self.alert_temp_rise_check_seconds = max(60.0, float(value))
            elif key == "ALERT_TEMP_RISE_MIN_DELTA":
                self.alert_temp_rise_min_delta = max(0.1, float(value))
            elif key == "PREDICTIVE_HEATING_ENABLED":
                self.predictive_heating_enabled = parse_bool(value)
            elif key == "PREDICTIVE_BASE_RATE":
                try:
                    self.predictive_base_rate = max(0.05, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_MIN_LEARNING_SECONDS":
                try:
                    self.predictive_min_learning_seconds = max(60.0, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_MIN_RATE":
                try:
                    self.predictive_min_rate = max(0.01, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_MAX_RATE":
                try:
                    self.predictive_max_rate = max(0.05, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_WARMUP_BIAS_MAX_MINUTES":
                try:
                    self.predictive_bias_max_minutes = max(5.0, float(value))
                except Exception:
                    pass
            elif key == "PREDICTIVE_WARMUP_BIAS_ENABLED":
                self.predictive_bias_enabled = parse_bool(value)
            elif key == "PREDICTIVE_WARMUP_BIAS_FULL_CONFIDENCE_SAMPLES":
                try:
                    self.predictive_bias_full_confidence_samples = max(1, int(float(value)))
                except Exception:
                    pass
            elif key == "PREDICTIVE_COOLING_ENABLED":
                self.predictive_cooling_enabled = parse_bool(value)
        except Exception:
            pass

    def _drain_engine_queue(self):
        while True:
            try:
                m = self.engine_queue.get_nowait()
            except Exception:
                break
            if m.type == "TEMP_UPDATE":
                try:
                    self.current_temp = float((m.payload or {}).get("temperature"))
                    self.last_temp_update_epoch = time.time()
                except Exception:
                    pass

    def _db_connect(self):
        if self.db_con:
            return
        self.db_con = sqlite3.connect(self.db_path, timeout=2)
        self.db_con.execute("PRAGMA journal_mode=WAL")
        self.db_con.execute("PRAGMA synchronous=NORMAL")
        self.db_con.execute("PRAGMA foreign_keys=ON")

    def _get_setting_cached(self, key, default=None):
        v = self.settings.get(key)
        return v if v is not None else default

    def _is_boost_active(self, system, now_epoch):
        key_epoch = "%s_BOOST_FINISH_EPOCH" % system
        key_time = "%s_BOOST_FINISH_TIME" % system

        try:
            finish_epoch = int(self._get_setting_cached(key_epoch, "0") or "0")
        except Exception:
            finish_epoch = 0

        if finish_epoch and now_epoch < finish_epoch:
            return True, finish_epoch

        if finish_epoch and now_epoch >= finish_epoch:
            try:
                self.db_queue.put(Message("engine", "set_setting", {"key": key_epoch, "value": "0"}))
                self.db_queue.put(Message("engine", "set_setting", {"key": key_time, "value": "00:00"}))
            except Exception:
                pass

        return False, finish_epoch

    def _request_cleanup_overrides(self):
        now = time.time()
        last = getattr(self, "_last_cleanup_req", 0.0)
        if now - last < 60.0:
            return
        self._last_cleanup_req = now
        try:
            self.db_queue.put(Message("engine", "cleanup_expired_overrides", {"now_epoch": now}))
        except Exception:
            pass

    def _is_temperature_stale(self, now_epoch):
        if self.current_temp is None:
            return True

        try:
            last_update = float(self.last_temp_update_epoch or 0.0)
        except Exception:
            last_update = 0.0

        if last_update <= 0.0:
            return True

        return (now_epoch - last_update) >= float(self.temp_stale_timeout)

    def _clear_advance(self, system):
        key = "%s_ADVANCE" % system
        try:
            self.settings[key] = "False"
            if system == "CH":
                self.ch_advance = False
            elif system == "HW":
                self.hw_advance = False

            self.db_queue.put(Message("engine", "set_setting", {
                "key": key,
                "value": "False"
            }))
            print("[Engine] %s advance auto-cleared" % system)
        except Exception:
            pass

    def _get_warmup_delta_band(self, start_temp, target_temp):
        try:
            start_temp = float(start_temp)
            target_temp = float(target_temp)
        except Exception:
            return None

        delta = max(0.0, target_temp - start_temp)

        if delta < 1.0:
            return "small"
        if delta < 2.5:
            return "medium"
        return "large"

    def _clamp(self, value, low, high):
        if value < low:
            return low
        if value > high:
            return high
        return value

    def _decide_ch(self, temp_c, target_c):
        if target_c is None:
            return "OFF", None, None

        band = float(self.hysteresis_band or 0.0)
        lower = target_c - band
        upper = target_c

        if self.ch_desired is None:
            if temp_c <= lower:
                return "ON", lower, upper
            elif temp_c >= upper:
                return "OFF", lower, upper
            return "OFF", lower, upper

        if self.ch_desired == "ON":
            if temp_c >= upper:
                return "OFF", lower, upper
            return "ON", lower, upper

        if temp_c <= lower:
            return "ON", lower, upper
        return "OFF", lower, upper

    def _record_warmup_outcome_if_due(self, now_epoch):
        outcome = self._active_warmup_outcome
        if not outcome:
            return

        scheduled_start = outcome.get("scheduled_start_ts_epoch")

        scheduled_start_hour = outcome.get("scheduled_start_hour")

        if scheduled_start is None:
            return

        # only trigger once we pass scheduled start
        if now_epoch < scheduled_start:
            return

        try:
            actual_temp = float(self.current_temp) if self.current_temp is not None else None
        except Exception:
            actual_temp = None

        target_temp = outcome.get("target_temp")

        miss_temp = None
        if actual_temp is not None and target_temp is not None:
            miss_temp = actual_temp - target_temp

        outcome_confidence_hint = outcome.get("outcome_confidence_hint")

        if outcome_confidence_hint is None:
            outcome_confidence_hint = 0.0

            try:
                if outcome.get("live_rate_used") is not None:
                    outcome_confidence_hint += 0.35
                elif outcome.get("learned_rate_used") is not None:
                    outcome_confidence_hint += 0.25
                else:
                    outcome_confidence_hint += 0.10
            except Exception:
                pass

            try:
                if outcome.get("predictive_rate_used") is not None:
                    outcome_confidence_hint += 0.15
            except Exception:
                pass

            try:
                started_ts = outcome.get("started_ts_epoch")
                if started_ts is not None and scheduled_start is not None:
                    runup_seconds = float(scheduled_start) - float(started_ts)
                    if runup_seconds >= 3600.0:
                        outcome_confidence_hint += 0.25
                    elif runup_seconds >= 1800.0:
                        outcome_confidence_hint += 0.15
                    elif runup_seconds >= 900.0:
                        outcome_confidence_hint += 0.08
            except Exception:
                pass

            try:
                if actual_temp is not None and target_temp is not None:
                    outcome_confidence_hint += 0.15
            except Exception:
                pass

            outcome_confidence_hint = self._clamp(outcome_confidence_hint, 0.0, 1.0)

        try:
            cur = self.db_con.cursor()
            cur.execute("""
                INSERT INTO warmup_outcomes (
                    scheduled_entry_id,
                    schedule_set_name,
                    started_ts_epoch,
                    scheduled_start_ts_epoch,
                    scheduled_end_ts_epoch,
                    scheduled_start_hour,
                    delta_band,
                    target_temp,
                    actual_temp_at_start,
                    miss_temp,
                    predictive_rate_used,
                    learned_rate_used,
                    live_rate_used,
                    base_rate_used,
                    outcome_confidence_hint,
                    created_ts_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,(
                    outcome.get("scheduled_entry_id"),
                    outcome.get("schedule_set_name"),
                    outcome.get("started_ts_epoch"),
                    outcome.get("scheduled_start_ts_epoch"),
                    outcome.get("scheduled_end_ts_epoch"),
                    scheduled_start_hour,
                    outcome.get("delta_band"),
                    outcome.get("target_temp"),
                    actual_temp,
                    miss_temp,
                    outcome.get("predictive_rate_used"),
                    outcome.get("learned_rate_used"),
                    outcome.get("live_rate_used"),
                    outcome.get("base_rate_used"),
                    outcome_confidence_hint,
                    time.time()
                ))
            self.db_con.commit()

            try:
                self._rebuild_warmup_bias()
            except Exception as e:
                print("[Engine] Warmup bias rebuild failed:", e)

            if miss_temp is None:
                print("[Engine] Warmup outcome recorded: miss=unknown")
            else:
                print("[Engine] Warmup outcome recorded: miss=%.2f°C" % miss_temp)

        except Exception as e:
            print("[Engine] Warmup outcome save failed:", e)

        # IMPORTANT: clear so it only records once
        self._active_warmup_outcome = None

    def run(self):
        from datetime import datetime
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[Engine] Started in mode: %s" % self.mode)

        try:
            self.db_queue.put(Message("engine", "request_settings_snapshot", {}))
        except Exception:
            pass

        ok = self.wait_for_initial_snapshot(timeout=3.0)
        if not ok:
            print("[Engine] No settings snapshot received yet; using defaults")

        print("[Engine] ENGINE_INTERVAL initial: %.2f" % self.engine_interval)

        seeded_from_relay = self._request_relay_status_startup(timeout=2.0)

        if not seeded_from_relay:
            now_epoch = time.time()
            if self.ch_desired == "ON" and self.ch_last_on_epoch is None:
                self.ch_last_on_epoch = now_epoch
                self.ch_last_change_epoch = now_epoch
            elif self.ch_desired == "OFF" and self.ch_last_off_epoch is None:
                self.ch_last_off_epoch = now_epoch
                self.ch_last_change_epoch = now_epoch

            if self.hw_desired is None:
                self.hw_desired = "OFF"

            print("[Engine] Startup relay status unavailable; seeded CH_LAST_DESIRED=%s HW=%s" %
                  (self.ch_desired, self.hw_desired))

        print("[Engine] CH_SYSTEM_SWITCH=%s DEFAULT_SETPOINT=%.1f DEFAULT_ON_SETPOINT=%.1f HYSTERESIS_BAND=%.1f" %
              (self.ch_system_switch, self.default_setpoint, self.default_on_setpoint, self.hysteresis_band))

        self._db_connect()
        self._rebuild_learned_heatup_rate()
        try:
            self._rebuild_learned_cooldown_rate()
        except Exception:
            pass
        try:
            self._rebuild_warmup_bias()
        except Exception:
            pass

        while not self.shutdown_event.is_set():
            self.drain_ctrl_queue()
            self._drain_engine_queue()

            self.db_queue.put(Message("engine", "heartbeat", {"status": "ok"}))

            now_epoch = time.time()
            temp_is_stale = self._is_temperature_stale(now_epoch)

            self._handle_periodic_relay_sync_reply()

            if temp_is_stale:
                stale_for = 0.0
                if self.active_heat_run:
                    self.active_heat_run["sensor_stale"] = True
                    self._finish_heat_learning_run(now_epoch)
                try:
                    last_update = float(self.last_temp_update_epoch or 0.0)
                    if last_update > 0.0:
                        stale_for = now_epoch - last_update
                except Exception:
                    stale_for = 0.0

                if not self._temp_stale_active:
                    self._temp_stale_active = True
                    self._send_email_alert(
                        "engine_sensor_stale",
                        "SENSOR_STALE",
                        "Temperature updates have stopped. CH has been forced OFF for safety.",
                        severity="error",
                        extra={
                            "last_temp": self.current_temp,
                            "last_temp_update_epoch": self.last_temp_update_epoch,
                            "stale_timeout_seconds": self.temp_stale_timeout
                        }
                    )
                    try:
                        self.db_queue.put(Message("engine", "state_change", {
                            "system": "CH",
                            "state": "SENSOR_STALE"
                        }))
                    except Exception:
                        pass

                reason = "sensor_stale(%.0fs)" % stale_for
                hw_reason = "sensor_stale_ignored"

                print("[Engine] temperature stale for %.0fs - forcing CH OFF" % stale_for)

                self._publish_state(None, "OFF", reason, (self.hw_desired == "ON"), hw_reason)

                if self.ch_desired != "OFF":
                    self.ch_desired = "OFF"
                    self.ch_last_change_epoch = now_epoch
                    self.ch_last_off_epoch = now_epoch

                    try:
                        self.db_queue.put(Message("engine", "set_setting", {
                            "key": "CH_LAST_DESIRED",
                            "value": "OFF"
                        }))
                    except Exception:
                        pass

                    try:
                        self.db_queue.put(Message("engine", "state_change", {
                            "system": "CH",
                            "state": "DESIRED_OFF_SENSOR_STALE"
                        }))
                    except Exception:
                        pass

                    self._send_relay_desired(self._get_relay_letter("CH"), "OFF", "CH")
                    self._mark_relay_verification(self._get_relay_letter("CH"), "OFF", "CH")

                if self._active_warmup_outcome is not None:
                    print("[Engine] Clearing warmup outcome due to sensor stale forced-off")
                    self._active_warmup_outcome = None

                self._stop_temp_rise_watch()
                time.sleep(self.engine_interval)
                continue
            else:
                if self._temp_stale_active:
                    self._temp_stale_active = False
                    self._send_email_alert(
                        "engine_sensor_stale",
                        "SENSOR_RECOVERED",
                        "Temperature updates have resumed. Engine is operating normally again.",
                        severity="info",
                        is_recovery=True,
                        extra={
                            "current_temp": self.current_temp,
                            "last_temp_update_epoch": self.last_temp_update_epoch
                        }
                    )

                    try:
                        self.db_queue.put(Message("engine", "state_change", {
                            "system": "CH",
                            "state": "SENSOR_OK"
                        }))
                    except Exception:
                        pass

            now_epoch = time.time()
            dt = datetime.fromtimestamp(now_epoch)
            weekday = dt.weekday()
            hhmm = dt.strftime("%H:%M")

            self._request_cleanup_overrides()

            ch_ctx = self._compute_ch_target(weekday, hhmm, now_epoch)
            self._record_warmup_outcome_if_due(now_epoch)

            target = ch_ctx["target"]
            reason = ch_ctx["reason"]

            hw_ctx = self._compute_hw_target(weekday, hhmm, now_epoch)
            hw_target_on = hw_ctx["target_on"]
            hw_reason = hw_ctx["reason"]

            desired_raw, lower, upper = self._decide_ch(self.current_temp, target)
            desired = desired_raw

            prev = self.ch_desired

            try:
                min_on = float(self.ch_min_on_seconds or 0)
            except Exception:
                min_on = 0.0

            try:
                min_off = float(self.ch_min_off_seconds or 0)
            except Exception:
                min_off = 0.0

            if prev == "ON" and desired == "OFF" and min_on > 0:
                if self.ch_last_on_epoch is not None:
                    since_on = now_epoch - self.ch_last_on_epoch
                    if since_on < min_on:
                        desired = "ON"
                        reason = reason + " + min_on_block(%.0fs<%ss)" % (since_on, int(min_on))

            elif prev == "OFF" and desired == "ON" and min_off > 0:
                if self.ch_last_off_epoch is not None:
                    since_off = now_epoch - self.ch_last_off_epoch
                    if since_off < min_off:
                        desired = "OFF"
                        reason = reason + " + min_off_block(%.0fs<%ss)" % (since_off, int(min_off))

            if target is None:
                print("[Engine] temp=%.1fC CH=FORCED_OFF raw=%s (%s) band=%.1f switch=%s interval=%.2f" %
                      (self.current_temp, desired_raw, reason, self.hysteresis_band,
                       self.ch_system_switch, self.engine_interval))
            else:
                print("[Engine] temp=%.1fC target=%.1fC band=%.1f thr=[%.1f..%.1f] CH=%s raw=%s (%s) switch=%s interval=%.2f" %
                      (self.current_temp, target, self.hysteresis_band, lower, upper,
                       desired, desired_raw, reason, self.ch_system_switch, self.engine_interval))

            print("[Engine] HW=%s (%s) switch=%s" %
                  ("ON" if hw_target_on else "OFF", hw_reason, self.hw_system_switch))

            self._publish_state(target, desired, reason, hw_target_on, hw_reason)

            if desired != self.ch_desired:
                self.ch_desired = desired
                self.ch_last_change_epoch = now_epoch

                if desired == "ON":
                    self.ch_last_on_epoch = now_epoch
                else:
                    self.ch_last_off_epoch = now_epoch

                try:
                    self.db_queue.put(Message("engine", "set_setting", {
                        "key": "CH_LAST_DESIRED",
                        "value": desired
                    }))
                except Exception:
                    pass

                self.db_queue.put(Message("engine", "state_change", {
                    "system": "CH",
                    "state": "DESIRED_%s" % desired
                }))

                self._send_relay_desired(self._get_relay_letter("CH"), desired, "CH")
                self._mark_relay_verification(self._get_relay_letter("CH"), desired, "CH")

                if desired == "ON":
                    self._start_temp_rise_watch(now_epoch)

                    if ch_ctx.get("is_warmup", False):
                        self._start_heat_learning_run(now_epoch, target, True)

                        # ---- start warmup outcome tracking ----
                        if self._active_warmup_outcome is None:
                            try:
                                start_epoch = ch_ctx.get("warmup_entry_start_epoch")
                                if start_epoch is not None:
                                    scheduled_start_hour = time.localtime(start_epoch).tm_hour
                                else:
                                    scheduled_start_hour = None

                                self._active_warmup_outcome = {
                                    "scheduled_entry_id": ch_ctx.get("warmup_entry_id"),
                                    "schedule_set_name": ch_ctx.get("special_set_name") or "NORMAL",
                                    "started_ts_epoch": now_epoch,
                                    "scheduled_start_ts_epoch": ch_ctx.get("warmup_entry_start_epoch"),
                                    "scheduled_end_ts_epoch": ch_ctx.get("warmup_entry_end_epoch"),
                                    "scheduled_start_hour": scheduled_start_hour,
                                    "delta_band": self._get_warmup_delta_band(
                                        self.current_temp,
                                        ch_ctx.get("target")
                                    ),
                                    "target_temp": ch_ctx.get("target"),

                                    # snapshot model state
                                    "predictive_rate_used": self._get_effective_predictive_heatup_rate(now_epoch=now_epoch),
                                    "learned_rate_used": self.learned_heatup_rate,
                                    "live_rate_used": self.live_heatup_rate,
                                    "base_rate_used": self.predictive_base_rate,

                                    # outcome weighting hint for later bias learning
                                    "outcome_confidence_hint": None,
                                }
                            except Exception:
                                self._active_warmup_outcome = None
                else:
                    self._stop_temp_rise_watch()
                    self._finish_heat_learning_run(now_epoch)

                    if self._active_warmup_outcome is not None:
                        scheduled_start = self._active_warmup_outcome.get("scheduled_start_ts_epoch")
                        if scheduled_start is not None and now_epoch < scheduled_start:
                            print("[Engine] Clearing abandoned warmup outcome before scheduled start")
                            self._active_warmup_outcome = None

            hw_desired = "ON" if hw_target_on else "OFF"

            if hw_desired != self.hw_desired:
                self.hw_desired = hw_desired

                try:
                    self.db_queue.put(Message("engine", "set_setting", {
                        "key": "HW_LAST_DESIRED",
                        "value": hw_desired
                    }))
                except Exception:
                    pass

                self.db_queue.put(Message("engine", "state_change", {
                    "system": "HW",
                    "state": "DESIRED_%s" % hw_desired
                }))

                self._send_relay_desired(self._get_relay_letter("HW"), hw_desired, "HW")
                self._mark_relay_verification(self._get_relay_letter("HW"), hw_desired, "HW")

            loop_now = time.time()

            # use ACTUAL relay state for predictive learning when available
            if self.ch_actual_relay is not None:
                actual_ch_on = (self.ch_actual_relay == "ON")
            else:
                actual_ch_on = (self.ch_desired == "ON")

            try:
                self._update_live_heatup_rate(
                    ch_calling_for_heat=(self.ch_desired == "ON"),
                    actual_ch_on=actual_ch_on,
                    current_temp=self.current_temp,
                    now_epoch=loop_now
                )
            except Exception:
                pass

            self._update_heat_learning_run(loop_now, actual_ch_on)

            if self.ch_desired == "OFF":
                if self.passive_cool_run is None:
                    self._start_passive_cool_run(loop_now)
                else:
                    self._update_passive_cool_run(loop_now)
            else:
                if self.passive_cool_run is not None:
                    self._finish_passive_cool_run(loop_now, reason="heating_started")

            if self.ch_desired == "ON":
                if not self._temp_rise_active:
                    self._start_temp_rise_watch(loop_now)
            else:
                self._stop_temp_rise_watch()

            self._check_temp_rise_watch(loop_now)
            self._check_pending_relay_verification(loop_now)

            # sync actual relay state more often while heating is active,
            # otherwise keep the lighter periodic cadence
            relay_sync_interval = 60.0 if self.ch_desired == "ON" else 300.0
            if loop_now - self._last_relay_sync > relay_sync_interval:
                self._last_relay_sync = loop_now
                self._request_periodic_relay_sync()

            time.sleep(self.engine_interval)

        try:
            if self.db_con:
                self.db_con.close()
        except Exception:
            pass
        print("[Engine] Shutting down cleanly")