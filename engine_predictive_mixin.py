#!/usr/bin/python
# -*- coding: utf-8 -*-
# engine_predictive_mixin.py

from __future__ import print_function

import time


class EnginePredictiveMixin(object):

    def _start_heat_learning_run(self, now_epoch, target, is_warmup=False):
        if self.current_temp is None:
            return
        if self.active_heat_run is not None:
            return

        try:
            start_temp = float(self.current_temp)
        except Exception:
            return

        try:
            target_temp = float(target) if target is not None else None
        except Exception:
            target_temp = None

        try:
            start_hour = int(time.localtime(now_epoch).tm_hour)
        except Exception:
            start_hour = None

        try:
            # Python weekday here matches your other logic well enough for analysis
            start_weekday = int(time.localtime(now_epoch).tm_wday)
        except Exception:
            start_weekday = None

        start_delta_temp = None
        if target_temp is not None:
            try:
                start_delta_temp = target_temp - start_temp
            except Exception:
                start_delta_temp = None

        try:
            ch_switch_mode = str(self.ch_system_switch or "")
        except Exception:
            ch_switch_mode = ""

        try:
            hw_was_on = 1 if str(self.hw_desired or "").upper() == "ON" else 0
        except Exception:
            hw_was_on = 0

        self.active_heat_run = {
            "start_ts": now_epoch,
            "start_temp": start_temp,
            "target": target_temp,
            "relay_on_seconds": 0.0,
            "last_tick": now_epoch,
            "warmup": bool(is_warmup),
            "sensor_stale": False,
            "relay_mismatch": False,

            # richer context
            "start_hour": start_hour,
            "start_weekday": start_weekday,
            "start_delta_temp": start_delta_temp,
            "ch_switch_mode": ch_switch_mode,
            "hw_was_on": hw_was_on,

            # tracking
            "sample_count_hint": 0,
            "max_temp_seen": start_temp,
            "min_temp_seen": start_temp,
        }

    def _update_heat_learning_run(self, now_epoch, actual_ch_on):
        run = self.active_heat_run
        if not run:
            return

        dt = now_epoch - run["last_tick"]
        run["last_tick"] = now_epoch

        if actual_ch_on:
            run["relay_on_seconds"] += dt

        if self._temp_stale_active:
            run["sensor_stale"] = True

        if self._relay_mismatch_active:
            run["relay_mismatch"] = True

        try:
            current_temp = float(self.current_temp)
            run["sample_count_hint"] = int(run.get("sample_count_hint", 0)) + 1

            if current_temp > run.get("max_temp_seen", current_temp):
                run["max_temp_seen"] = current_temp
            if current_temp < run.get("min_temp_seen", current_temp):
                run["min_temp_seen"] = current_temp
        except Exception:
            pass

    def _finish_heat_learning_run(self, now_epoch):
        run = self.active_heat_run
        self.active_heat_run = None

        if not run or self.current_temp is None:
            return

        try:
            end_temp = float(self.current_temp)
        except Exception:
            return

        duration = now_epoch - run["start_ts"]
        delta = end_temp - run["start_temp"]

        valid = True
        invalid_reason = None
        end_reason = "completed"

        if duration < self.predictive_min_run_seconds:
            valid = False
            invalid_reason = "too_short"
            end_reason = "too_short"

        elif delta < self.predictive_min_delta_c:
            valid = False
            invalid_reason = "no_temp_rise"
            end_reason = "no_temp_rise"

        elif run["relay_on_seconds"] < duration * 0.5:
            valid = False
            invalid_reason = "relay_not_on"
            end_reason = "relay_not_on"

        elif run["sensor_stale"]:
            valid = False
            invalid_reason = "sensor_stale"
            end_reason = "sensor_stale"

        elif run["relay_mismatch"]:
            valid = False
            invalid_reason = "relay_mismatch"
            end_reason = "relay_mismatch"

        elif not run["warmup"]:
            valid = False
            invalid_reason = "not_warmup"
            end_reason = "not_warmup"

        rate = None
        if valid:
            rate = (delta / duration) * 3600.0
            if rate <= 0:
                valid = False
                invalid_reason = "invalid_rate"
                end_reason = "invalid_rate"

        confidence_hint = 0.0
        try:
            confidence_hint += min(0.4, max(0.0, duration / 7200.0))
            confidence_hint += min(0.3, max(0.0, delta / 2.0))
            if run["relay_on_seconds"] >= duration * 0.8:
                confidence_hint += 0.2
            elif run["relay_on_seconds"] >= duration * 0.5:
                confidence_hint += 0.1
            if run.get("sample_count_hint", 0) >= 3:
                confidence_hint += 0.1

            confidence_hint = self._clamp(confidence_hint, 0.0, 1.0)
        except Exception:
            confidence_hint = 0.0

        try:
            cur = self.db_con.cursor()
            cur.execute("""
                INSERT INTO heatup_learning_log (
                    started_ts_epoch,
                    ended_ts_epoch,
                    duration_seconds,
                    start_temp,
                    end_temp,
                    delta_temp,
                    calculated_rate,
                    target_temp,
                    warmup_enabled,
                    relay_confirmed_seconds,
                    valid,
                    invalid_reason,
                    created_ts_epoch,
                    start_hour,
                    start_weekday,
                    start_delta_temp,
                    end_reason,
                    ch_switch_mode,
                    hw_was_on,
                    sample_count_hint,
                    confidence_hint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run["start_ts"],
                now_epoch,
                duration,
                run["start_temp"],
                end_temp,
                delta,
                rate,
                run["target"],
                int(run["warmup"]),
                run["relay_on_seconds"],
                int(valid),
                invalid_reason,
                time.time(),
                run.get("start_hour"),
                run.get("start_weekday"),
                run.get("start_delta_temp"),
                end_reason,
                run.get("ch_switch_mode"),
                run.get("hw_was_on", 0),
                run.get("sample_count_hint", 0),
                confidence_hint
            ))
            self.db_con.commit()
        except Exception as e:
            print("[Engine] Learning save failed:", e)
            return

        if valid:
            self._rebuild_learned_heatup_rate()

    def _rebuild_learned_heatup_rate(self):
        try:
            cur = self.db_con.cursor()
            cur.execute("""
                SELECT calculated_rate, duration_seconds, confidence_hint
                FROM heatup_learning_log
                WHERE valid = 1
                  AND warmup_enabled = 1
                ORDER BY ended_ts_epoch DESC
                LIMIT ?
            """, (self.predictive_sample_window,))
            rows = cur.fetchall()
        except Exception as e:
            print("[Engine] Load learning failed:", e)
            return

        self.learned_heatup_sample_count = len(rows)

        if not rows:
            self.learned_heatup_rate = None
            return

        total = 0.0
        weight_sum = 0.0

        for rate, duration, confidence_hint in rows:
            if not rate:
                continue

            rate = self._clamp(rate, self.predictive_min_rate, self.predictive_max_rate)

            try:
                duration_weight = max(1.0, min(float(duration) / 900.0, 4.0))
            except Exception:
                duration_weight = 1.0

            try:
                confidence_weight = max(0.5, min(float(confidence_hint or 0.0) + 0.5, 1.5))
            except Exception:
                confidence_weight = 1.0

            weight = duration_weight * confidence_weight

            total += rate * weight
            weight_sum += weight

        if weight_sum > 0:
            self.learned_heatup_rate = total / weight_sum
            self.learned_heatup_rate_updated_epoch = time.time()
            print("[Engine] Learned rate:", round(self.learned_heatup_rate, 3))

    def _update_live_heatup_rate(self, ch_calling_for_heat, actual_ch_on, current_temp, now_epoch):
        """
        Estimate live heat-up rate while CH is actually heating.
        Stores a smoothed °C/hour value in self.live_heatup_rate.
        """
        try:
            current_temp = float(current_temp)
            now_epoch = float(now_epoch)
        except Exception:
            return

        heating_active = bool(ch_calling_for_heat and actual_ch_on)

        if not heating_active:
            self.last_heatup_temp = current_temp
            self.last_heatup_ts = now_epoch
            self.live_heatup_run_start_ts = 0.0
            return

        if self.live_heatup_run_start_ts <= 0:
            self.live_heatup_run_start_ts = now_epoch

        if self.last_heatup_temp is None or self.last_heatup_ts <= 0:
            self.last_heatup_temp = current_temp
            self.last_heatup_ts = now_epoch
            return

        dt = now_epoch - self.last_heatup_ts
        if dt < float(self.predictive_min_learning_seconds):
            return

        dtemp = current_temp - self.last_heatup_temp
        raw_rate = (dtemp / dt) * 3600.0
        raw_rate = self._clamp(raw_rate, -0.5, 2.5)

        if self.live_heatup_rate is None:
            smoothed = raw_rate
        else:
            smoothed = (self.live_heatup_rate * 0.7) + (raw_rate * 0.3)

        self.live_heatup_rate = smoothed
        self.last_heatup_temp = current_temp
        self.last_heatup_ts = now_epoch

    def _get_predictive_heatup_rate(self, now_epoch=None):
        base = float(self.predictive_base_rate or 0.7)
        learned = self.learned_heatup_rate
        live = self.live_heatup_rate

        try:
            learned_samples = int(self.learned_heatup_sample_count or 0)
        except Exception:
            learned_samples = 0

        try:
            target_samples = float(self.predictive_sample_window or 20)
        except Exception:
            target_samples = 20.0

        learned_conf = self._clamp(
            float(learned_samples) / max(1.0, target_samples),
            0.0,
            1.0
        )

        live_conf = 0.0
        try:
            if now_epoch is None:
                now_epoch = time.time()

            if self.ch_desired == "ON" and self.live_heatup_run_start_ts > 0:
                active_seconds = max(0.0, float(now_epoch) - float(self.live_heatup_run_start_ts))
                live_conf = self._clamp(
                    active_seconds / 900.0,
                    0.0,
                    1.0
                )
        except Exception:
            live_conf = 0.0

        base_conf = 0.2

        if learned is None:
            learned_conf = 0.0

        if live is None:
            live_conf = 0.0

        total_conf = learned_conf + live_conf + base_conf

        if total_conf <= 0:
            return self._clamp(base, self.predictive_min_rate, self.predictive_max_rate)

        learned_w = learned_conf / total_conf
        live_w = live_conf / total_conf
        base_w = base_conf / total_conf

        rate = 0.0

        if learned is not None:
            rate += float(learned) * learned_w

        if live is not None:
            rate += float(live) * live_w

        rate += float(base) * base_w

        return self._clamp(rate, self.predictive_min_rate, self.predictive_max_rate)

    def _start_passive_cool_run(self, now_epoch):
        if self.current_temp is None:
            return
        if self.passive_cool_run is not None:
            return
        if self.ch_desired == "ON":
            return

        try:
            start_temp = float(self.current_temp)
        except Exception:
            return

        self.passive_cool_run = {
            "start_ts": now_epoch,
            "start_temp": start_temp,
            "last_tick": now_epoch,
            "sample_count_hint": 0,
            "min_temp_seen": start_temp,
            "max_temp_seen": start_temp,
        }

    def _update_passive_cool_run(self, now_epoch):
        run = self.passive_cool_run
        if not run:
            return

        run["last_tick"] = now_epoch

        try:
            current_temp = float(self.current_temp)
            run["sample_count_hint"] = int(run.get("sample_count_hint", 0)) + 1

            if current_temp < run.get("min_temp_seen", current_temp):
                run["min_temp_seen"] = current_temp
            if current_temp > run.get("max_temp_seen", current_temp):
                run["max_temp_seen"] = current_temp
        except Exception:
            pass

    def _finish_passive_cool_run(self, now_epoch, reason="completed"):
        run = self.passive_cool_run
        self.passive_cool_run = None

        if not run or self.current_temp is None:
            return

        try:
            end_temp = float(self.current_temp)
        except Exception:
            return

        duration = float(now_epoch - run["start_ts"])
        delta = float(end_temp - run["start_temp"])   # usually negative while cooling

        valid = True
        invalid_reason = None

        if duration < float(self.cooldown_min_off_seconds or 1800.0):
            valid = False
            invalid_reason = "too_short"
        elif abs(delta) < float(self.cooldown_min_delta_c or 0.2):
            valid = False
            invalid_reason = "small_delta"
        elif delta > 0.1:
            valid = False
            invalid_reason = "temp_rising"

        rate = None
        if valid:
            rate = (delta / duration) * 3600.0
            if rate >= 0:
                valid = False
                invalid_reason = "invalid_rate"

        try:
            cur = self.db_con.cursor()
            cur.execute("""
                INSERT INTO cooldown_learning_log (
                    started_ts_epoch,
                    ended_ts_epoch,
                    duration_seconds,
                    start_temp,
                    end_temp,
                    delta_temp,
                    calculated_rate,
                    valid,
                    invalid_reason,
                    end_reason,
                    sample_count_hint,
                    created_ts_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run["start_ts"],
                now_epoch,
                duration,
                run["start_temp"],
                end_temp,
                delta,
                rate,
                int(valid),
                invalid_reason,
                reason,
                run.get("sample_count_hint", 0),
                time.time()
            ))
            self.db_con.commit()
        except Exception as e:
            print("[Engine] Cooldown save failed:", e)
            return

        if valid:
            self._rebuild_learned_cooldown_rate()

    def _rebuild_learned_cooldown_rate(self):
        try:
            cur = self.db_con.cursor()
            cur.execute("""
                SELECT calculated_rate, duration_seconds
                FROM cooldown_learning_log
                WHERE valid = 1
                ORDER BY ended_ts_epoch DESC
                LIMIT ?
            """, (self.cooldown_sample_window,))
            rows = cur.fetchall()
        except Exception as e:
            print("[Engine] Cooldown load failed:", e)
            return

        if not rows:
            self.learned_cooldown_rate = None
            return

        total = 0.0
        weight_sum = 0.0

        for rate, duration in rows:
            try:
                rate = float(rate)
            except Exception:
                continue

            if rate >= 0:
                continue

            try:
                duration_weight = max(1.0, min(float(duration) / 1800.0, 4.0))
            except Exception:
                duration_weight = 1.0

            total += rate * duration_weight
            weight_sum += duration_weight

        if weight_sum > 0:
            self.learned_cooldown_rate = total / weight_sum
            self.learned_cooldown_rate_updated_epoch = time.time()
            print("[Engine] Learned cooldown rate:", round(self.learned_cooldown_rate, 3))

    def _get_effective_predictive_heatup_rate(self, now_epoch=None):
        """
        Return an effective heat-up rate that blends:
        - base / learned / live heating performance
        - passive cooling tendency

        The result is always clamped to a safe positive range.
        """
        heat_rate = self._get_predictive_heatup_rate(now_epoch=now_epoch)

        if not self.predictive_cooling_enabled:
            return heat_rate

        cooldown_rate = self.learned_cooldown_rate
        if cooldown_rate is None:
            return heat_rate

        try:
            cooldown_rate = float(cooldown_rate)
        except Exception:
            return heat_rate

        # cooldown_rate is usually negative; subtract only part of it
        # so we model net recovery rather than raw radiator output
        cooling_penalty = abs(cooldown_rate) * 0.5

        effective_rate = heat_rate - cooling_penalty

        return self._clamp(
            effective_rate,
            self.predictive_min_rate,
            self.predictive_max_rate
        )

    def _predict_time_to_target_seconds(self, current_temp, target_temp, now_epoch=None):
        try:
            current_temp = float(current_temp)
            target_temp = float(target_temp)
        except Exception:
            return None

        delta = target_temp - current_temp
        if delta <= 0:
            return 0.0

        rate = self._get_effective_predictive_heatup_rate(now_epoch=now_epoch)
        if rate <= 0:
            return None

        seconds = (delta / rate) * 3600.0
        return max(0.0, seconds)

    def _predictive_warmup_needed(self, current_temp, target_temp, now_epoch=None):
        seconds = self._predict_time_to_target_seconds(
            current_temp,
            target_temp,
            now_epoch=now_epoch
        )
        if seconds is None:
            return None

        try:
            min_s = int(float(self.warmup_minimum_lead_time)) * 60
        except Exception:
            min_s = 30 * 60

        try:
            max_s = int(float(self.warmup_maximum_lead_time)) * 60
        except Exception:
            max_s = 120 * 60

        return int(self._clamp(seconds, min_s, max_s))

    def _legacy_warmup_needed(self, current_temp, target_temp):
        try:
            current_temp = float(current_temp)
            target_temp = float(target_temp)
            heatup_rate = float(self.fallback_heatup_rate)
        except Exception:
            return None

        if heatup_rate <= 0:
            return None

        delta_c = max(0.0, target_temp - current_temp)
        seconds = (delta_c / heatup_rate) * 3600.0

        try:
            min_s = int(float(self.warmup_minimum_lead_time)) * 60
        except Exception:
            min_s = 30 * 60

        try:
            max_s = int(float(self.warmup_maximum_lead_time)) * 60
        except Exception:
            max_s = 120 * 60

        return int(self._clamp(seconds, min_s, max_s))

    def _fmt_predictive_minutes(self, seconds_value):
        if seconds_value is None:
            return "--"
        return str(int(round(float(seconds_value) / 60.0)))

    def _rebuild_warmup_bias(self):
        """
        Learn warmup timing bias (minutes) from warmup_outcomes.

        Negative miss_temp = late  -> increase lead time
        Positive miss_temp = early -> reduce lead time

        Bias is learned in two buckets:
            - morning: scheduled_start_hour < 12
            - evening: scheduled_start_hour >= 12

        Also maintains a global fallback bias.
        """
        try:
            cur = self.db_con.cursor()
            cur.execute("""
                SELECT scheduled_start_hour, delta_band, miss_temp, predictive_rate_used, outcome_confidence_hint
                FROM warmup_outcomes
                WHERE miss_temp IS NOT NULL
                ORDER BY started_ts_epoch DESC
                LIMIT 60
            """)
            rows = cur.fetchall()
        except Exception as e:
            print("[Engine] Warmup bias load failed:", e)
            return

        if not rows:
            self.learned_warmup_bias_minutes = 0.0
            self.learned_warmup_bias_morning_minutes = 0.0
            self.learned_warmup_bias_evening_minutes = 0.0
            self.learned_warmup_bias_sample_count = 0
            self.learned_warmup_bias_morning_sample_count = 0
            self.learned_warmup_bias_evening_sample_count = 0
            return

        global_items = []
        morning_items = []
        evening_items = []

        small_items = []
        medium_items = []
        large_items = []

        morning_small_items = []
        morning_medium_items = []
        morning_large_items = []

        evening_small_items = []
        evening_medium_items = []
        evening_large_items = []

        for scheduled_start_hour, delta_band, miss_temp, predictive_rate_used, outcome_confidence_hint in rows:
            try:
                miss = float(miss_temp)
            except Exception:
                continue

            try:
                rate = float(predictive_rate_used)
            except Exception:
                rate = None

            if rate is None or rate <= 0:
                rate = self._get_effective_predictive_heatup_rate()

            if rate is None or rate <= 0:
                continue

            # Convert temp miss into time miss.
            # miss > 0 means room was too warm at scheduled start -> started too early
            # miss < 0 means room was too cold at scheduled start -> started too late
            minutes = (miss / rate) * 60.0

            # invert so positive bias means "start earlier"
            minutes = -minutes

            minutes = self._clamp(
                minutes,
                -self.predictive_bias_max_minutes,
                self.predictive_bias_max_minutes
            )

            try:
                weight = max(0.1, min(float(outcome_confidence_hint or 0.0), 1.0))
            except Exception:
                weight = 0.25

            global_items.append((minutes, weight))

            band = str(delta_band or "").strip().lower()
            if band == "small":
                small_items.append((minutes, weight))
            elif band == "medium":
                medium_items.append((minutes, weight))
            elif band == "large":
                large_items.append((minutes, weight))

            try:
                hour = int(scheduled_start_hour)
            except Exception:
                hour = None

            if hour is None:
                continue

            if hour < 12:
                morning_items.append((minutes, weight))
                if band == "small":
                    morning_small_items.append((minutes, weight))
                elif band == "medium":
                    morning_medium_items.append((minutes, weight))
                elif band == "large":
                    morning_large_items.append((minutes, weight))
            else:
                evening_items.append((minutes, weight))
                if band == "small":
                    evening_small_items.append((minutes, weight))
                elif band == "medium":
                    evening_medium_items.append((minutes, weight))
                elif band == "large":
                    evening_large_items.append((minutes, weight))

        global_count = len(global_items)
        morning_count = len(morning_items)
        evening_count = len(evening_items)

        small_count = len(small_items)
        medium_count = len(medium_items)
        large_count = len(large_items)

        morning_small_count = len(morning_small_items)
        morning_medium_count = len(morning_medium_items)
        morning_large_count = len(morning_large_items)

        evening_small_count = len(evening_small_items)
        evening_medium_count = len(evening_medium_items)
        evening_large_count = len(evening_large_items)

        def weighted_avg_or_default(items, default_value):
            if not items:
                return default_value

            total = 0.0
            weight_sum = 0.0

            for value, weight in items:
                try:
                    value = float(value)
                    weight = float(weight)
                except Exception:
                    continue

                if weight <= 0:
                    continue

                total += value * weight
                weight_sum += weight

            if weight_sum <= 0:
                return default_value

            return total / weight_sum

        global_bias = weighted_avg_or_default(global_items, 0.0)
        morning_bias = weighted_avg_or_default(morning_items, global_bias)
        evening_bias = weighted_avg_or_default(evening_items, global_bias)

        small_bias = weighted_avg_or_default(small_items, global_bias)
        medium_bias = weighted_avg_or_default(medium_items, global_bias)
        large_bias = weighted_avg_or_default(large_items, global_bias)

        morning_small_bias = weighted_avg_or_default(morning_small_items, morning_bias)
        morning_medium_bias = weighted_avg_or_default(morning_medium_items, morning_bias)
        morning_large_bias = weighted_avg_or_default(morning_large_items, morning_bias)

        evening_small_bias = weighted_avg_or_default(evening_small_items, evening_bias)
        evening_medium_bias = weighted_avg_or_default(evening_medium_items, evening_bias)
        evening_large_bias = weighted_avg_or_default(evening_large_items, evening_bias)

        global_bias = self._clamp(
            global_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        morning_bias = self._clamp(
            morning_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        evening_bias = self._clamp(
            evening_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        small_bias = self._clamp(
            small_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        medium_bias = self._clamp(
            medium_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        large_bias = self._clamp(
            large_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )

        morning_small_bias = self._clamp(
            morning_small_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        morning_medium_bias = self._clamp(
            morning_medium_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        morning_large_bias = self._clamp(
            morning_large_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )

        evening_small_bias = self._clamp(
            evening_small_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        evening_medium_bias = self._clamp(
            evening_medium_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )
        evening_large_bias = self._clamp(
            evening_large_bias,
            -self.predictive_bias_max_minutes,
            self.predictive_bias_max_minutes
        )

        self.learned_warmup_bias_minutes = global_bias
        self.learned_warmup_bias_morning_minutes = morning_bias
        self.learned_warmup_bias_evening_minutes = evening_bias
        self.learned_warmup_bias_small_minutes = small_bias
        self.learned_warmup_bias_medium_minutes = medium_bias
        self.learned_warmup_bias_large_minutes = large_bias

        self.learned_warmup_bias_morning_small_minutes = morning_small_bias
        self.learned_warmup_bias_morning_medium_minutes = morning_medium_bias
        self.learned_warmup_bias_morning_large_minutes = morning_large_bias

        self.learned_warmup_bias_evening_small_minutes = evening_small_bias
        self.learned_warmup_bias_evening_medium_minutes = evening_medium_bias
        self.learned_warmup_bias_evening_large_minutes = evening_large_bias
        self.learned_warmup_bias_updated_epoch = time.time()
        self.learned_warmup_bias_sample_count = global_count
        self.learned_warmup_bias_morning_sample_count = morning_count
        self.learned_warmup_bias_evening_sample_count = evening_count
        self.learned_warmup_bias_small_sample_count = small_count
        self.learned_warmup_bias_medium_sample_count = medium_count
        self.learned_warmup_bias_large_sample_count = large_count

        self.learned_warmup_bias_morning_small_sample_count = morning_small_count
        self.learned_warmup_bias_morning_medium_sample_count = morning_medium_count
        self.learned_warmup_bias_morning_large_sample_count = morning_large_count

        self.learned_warmup_bias_evening_small_sample_count = evening_small_count
        self.learned_warmup_bias_evening_medium_sample_count = evening_medium_count
        self.learned_warmup_bias_evening_large_sample_count = evening_large_count

        print(
            "[Engine] Learned warmup bias:"
            " global=%.1f (%d)"
            " morning=%.1f (%d)"
            " evening=%.1f (%d)"
            " small=%.1f (%d)"
            " medium=%.1f (%d)"
            " large=%.1f (%d)"
            % (
                global_bias, global_count,
                morning_bias, morning_count,
                evening_bias, evening_count,
                small_bias, small_count,
                medium_bias, medium_count,
                large_bias, large_count,
            )
        )

    def _get_warmup_bias_minutes_for_hour_and_band(self, scheduled_start_hour, delta_band):
        if not self.predictive_bias_enabled:
            return 0.0

        try:
            hour = int(scheduled_start_hour)
        except Exception:
            hour = None

        band = str(delta_band or "").strip().lower()

        if hour is None:
            if band == "small":
                return float(self.learned_warmup_bias_small_minutes or self.learned_warmup_bias_minutes or 0.0)
            if band == "medium":
                return float(self.learned_warmup_bias_medium_minutes or self.learned_warmup_bias_minutes or 0.0)
            if band == "large":
                return float(self.learned_warmup_bias_large_minutes or self.learned_warmup_bias_minutes or 0.0)
            return float(self.learned_warmup_bias_minutes or 0.0)

        if hour < 12:
            if band == "small":
                return float(
                    self.learned_warmup_bias_morning_small_minutes
                    or self.learned_warmup_bias_morning_minutes
                    or self.learned_warmup_bias_small_minutes
                    or self.learned_warmup_bias_minutes
                    or 0.0
                )
            if band == "medium":
                return float(
                    self.learned_warmup_bias_morning_medium_minutes
                    or self.learned_warmup_bias_morning_minutes
                    or self.learned_warmup_bias_medium_minutes
                    or self.learned_warmup_bias_minutes
                    or 0.0
                )
            if band == "large":
                return float(
                    self.learned_warmup_bias_morning_large_minutes
                    or self.learned_warmup_bias_morning_minutes
                    or self.learned_warmup_bias_large_minutes
                    or self.learned_warmup_bias_minutes
                    or 0.0
                )
            return float(self.learned_warmup_bias_morning_minutes or self.learned_warmup_bias_minutes or 0.0)

        if band == "small":
            return float(
                self.learned_warmup_bias_evening_small_minutes
                or self.learned_warmup_bias_evening_minutes
                or self.learned_warmup_bias_small_minutes
                or self.learned_warmup_bias_minutes
                or 0.0
            )
        if band == "medium":
            return float(
                self.learned_warmup_bias_evening_medium_minutes
                or self.learned_warmup_bias_evening_minutes
                or self.learned_warmup_bias_medium_minutes
                or self.learned_warmup_bias_minutes
                or 0.0
            )
        if band == "large":
            return float(
                self.learned_warmup_bias_evening_large_minutes
                or self.learned_warmup_bias_evening_minutes
                or self.learned_warmup_bias_large_minutes
                or self.learned_warmup_bias_minutes
                or 0.0
            )
        return float(self.learned_warmup_bias_evening_minutes or self.learned_warmup_bias_minutes or 0.0)

    def _get_warmup_bias_sample_count_for_hour_and_band(self, scheduled_start_hour, delta_band):
        try:
            hour = int(scheduled_start_hour)
        except Exception:
            hour = None

        band = str(delta_band or "").strip().lower()

        if hour is None:
            if band == "small":
                if self.learned_warmup_bias_small_sample_count > 0:
                    return self.learned_warmup_bias_small_sample_count
                return self.learned_warmup_bias_sample_count

            if band == "medium":
                if self.learned_warmup_bias_medium_sample_count > 0:
                    return self.learned_warmup_bias_medium_sample_count
                return self.learned_warmup_bias_sample_count

            if band == "large":
                if self.learned_warmup_bias_large_sample_count > 0:
                    return self.learned_warmup_bias_large_sample_count
                return self.learned_warmup_bias_sample_count

            return self.learned_warmup_bias_sample_count

        if hour < 12:
            if band == "small":
                if self.learned_warmup_bias_morning_small_sample_count > 0:
                    return self.learned_warmup_bias_morning_small_sample_count
                if self.learned_warmup_bias_morning_sample_count > 0:
                    return self.learned_warmup_bias_morning_sample_count
                if self.learned_warmup_bias_small_sample_count > 0:
                    return self.learned_warmup_bias_small_sample_count
                return self.learned_warmup_bias_sample_count

            if band == "medium":
                if self.learned_warmup_bias_morning_medium_sample_count > 0:
                    return self.learned_warmup_bias_morning_medium_sample_count
                if self.learned_warmup_bias_morning_sample_count > 0:
                    return self.learned_warmup_bias_morning_sample_count
                if self.learned_warmup_bias_medium_sample_count > 0:
                    return self.learned_warmup_bias_medium_sample_count
                return self.learned_warmup_bias_sample_count

            if band == "large":
                if self.learned_warmup_bias_morning_large_sample_count > 0:
                    return self.learned_warmup_bias_morning_large_sample_count
                if self.learned_warmup_bias_morning_sample_count > 0:
                    return self.learned_warmup_bias_morning_sample_count
                if self.learned_warmup_bias_large_sample_count > 0:
                    return self.learned_warmup_bias_large_sample_count
                return self.learned_warmup_bias_sample_count

            if self.learned_warmup_bias_morning_sample_count > 0:
                return self.learned_warmup_bias_morning_sample_count
            return self.learned_warmup_bias_sample_count

        if band == "small":
            if self.learned_warmup_bias_evening_small_sample_count > 0:
                return self.learned_warmup_bias_evening_small_sample_count
            if self.learned_warmup_bias_evening_sample_count > 0:
                return self.learned_warmup_bias_evening_sample_count
            if self.learned_warmup_bias_small_sample_count > 0:
                return self.learned_warmup_bias_small_sample_count
            return self.learned_warmup_bias_sample_count

        if band == "medium":
            if self.learned_warmup_bias_evening_medium_sample_count > 0:
                return self.learned_warmup_bias_evening_medium_sample_count
            if self.learned_warmup_bias_evening_sample_count > 0:
                return self.learned_warmup_bias_evening_sample_count
            if self.learned_warmup_bias_medium_sample_count > 0:
                return self.learned_warmup_bias_medium_sample_count
            return self.learned_warmup_bias_sample_count

        if band == "large":
            if self.learned_warmup_bias_evening_large_sample_count > 0:
                return self.learned_warmup_bias_evening_large_sample_count
            if self.learned_warmup_bias_evening_sample_count > 0:
                return self.learned_warmup_bias_evening_sample_count
            if self.learned_warmup_bias_large_sample_count > 0:
                return self.learned_warmup_bias_large_sample_count
            return self.learned_warmup_bias_sample_count

        if self.learned_warmup_bias_evening_sample_count > 0:
            return self.learned_warmup_bias_evening_sample_count
        return self.learned_warmup_bias_sample_count

    def _bias_confidence_factor(self, sample_count):
        try:
            sample_count = float(sample_count or 0.0)
            full = float(self.predictive_bias_full_confidence_samples or 5.0)
        except Exception:
            return 0.0

        if full <= 0:
            return 1.0

        return self._clamp(sample_count / full, 0.0, 1.0)