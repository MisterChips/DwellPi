#!/usr/bin/python
# -*- coding: utf-8 -*-
# engine_schedule_mixin.py

from __future__ import print_function

import time

from commands.common import parse_bool


class EngineScheduleMixin(object):

    def _time_text_to_epoch_for_day(self, hhmm_text, day_epoch):
        from datetime import datetime

        dt_day = datetime.fromtimestamp(day_epoch)

        hh = int(str(hhmm_text).split(":")[0])
        mm = int(str(hhmm_text).split(":")[1])

        dt_value = dt_day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return time.mktime(dt_value.timetuple())

    def _entry_window_for_day(self, entry, day_epoch):
        start_epoch = self._time_text_to_epoch_for_day(entry["start_time"], day_epoch)
        end_epoch = self._time_text_to_epoch_for_day(entry["end_time"], day_epoch)

        if end_epoch <= start_epoch:
            end_epoch += 86400.0

        return start_epoch, end_epoch

    def _is_entry_active_now_for_day(self, entry, now_epoch, day_epoch):
        try:
            start_epoch, end_epoch = self._entry_window_for_day(entry, day_epoch)
            return start_epoch <= now_epoch < end_epoch
        except Exception:
            return False

    def _is_entry_active_now(self, entry, now_epoch, weekday_0_mon, days_str):
        today_epoch = now_epoch
        yesterday_epoch = now_epoch - 86400.0

        today_wd = weekday_0_mon
        yesterday_wd = (weekday_0_mon - 1) % 7

        try:
            start_text = str(entry["start_time"])
            end_text = str(entry["end_time"])
            overnight = (end_text <= start_text)
        except Exception:
            overnight = False

        if str(today_wd) in days_str:
            if self._is_entry_active_now_for_day(entry, now_epoch, today_epoch):
                return True

        if overnight and str(yesterday_wd) in days_str:
            if self._is_entry_active_now_for_day(entry, now_epoch, yesterday_epoch):
                return True

        return False

    def _system_in_csv(self, systems_csv, wanted):
        parts = [p.strip().upper() for p in (systems_csv or "").split(",") if p.strip()]
        return wanted.upper() in parts

    def _is_holiday_active(self, system, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT systems
                    FROM away_periods
                    WHERE enabled = 1
                      AND start_ts_epoch <= ?
                      AND ? < end_ts_epoch
                    ORDER BY start_ts_epoch DESC LIMIT 1
                    """, (now_epoch, now_epoch))
        row = cur.fetchone()
        if row and self._system_in_csv(row[0], system):
            return True
        return False

    def _get_active_special_set(self, system, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT systems, schedule_set_name
                    FROM special_periods
                    WHERE enabled = 1
                      AND start_ts_epoch <= ?
                      AND ? < end_ts_epoch
                    ORDER BY start_ts_epoch DESC LIMIT 1
                    """, (now_epoch, now_epoch))
        row = cur.fetchone()
        if row and self._system_in_csv(row[0], system):
            return row[1]
        return None

    def _get_active_schedule_entry(self, schedule_set_name, system, weekday_0_mon, hhmm, now_epoch):
        cur = self.db_con.cursor()

        if system == "CH":
            cur.execute("""
                SELECT id, start_time, end_time, setpoint, warmup, note, days
                FROM schedule_entries
                WHERE enabled = 1
                  AND schedule_set_name = ?
                  AND system = ?
                ORDER BY start_time ASC
            """, (schedule_set_name, system))
        else:
            cur.execute("""
                SELECT id, start_time, end_time, NULL as setpoint, 0 as warmup, note, days
                FROM schedule_entries
                WHERE enabled = 1
                  AND schedule_set_name = ?
                  AND system = ?
                ORDER BY start_time ASC
            """, (schedule_set_name, system))

        rows = cur.fetchall()
        matches = []

        for r in rows:
            entry = {
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "setpoint": r[3],
                "warmup": r[4],
                "note": r[5],
                "days": r[6],
            }

            days_str = str(entry["days"] or "")

            if self._is_entry_active_now(entry, now_epoch, weekday_0_mon, days_str):
                today_epoch = now_epoch
                yesterday_epoch = now_epoch - 86400.0
                today_wd = weekday_0_mon
                yesterday_wd = (weekday_0_mon - 1) % 7

                overnight = str(entry["end_time"]) <= str(entry["start_time"])

                if str(today_wd) in days_str and self._is_entry_active_now_for_day(entry, now_epoch, today_epoch):
                    start_epoch, end_epoch = self._entry_window_for_day(entry, today_epoch)
                    entry["window_start_epoch"] = start_epoch
                    entry["window_end_epoch"] = end_epoch
                    matches.append(entry)
                    continue

                if overnight and str(yesterday_wd) in days_str and \
                        self._is_entry_active_now_for_day(entry, now_epoch, yesterday_epoch):
                    start_epoch, end_epoch = self._entry_window_for_day(entry, yesterday_epoch)
                    entry["window_start_epoch"] = start_epoch
                    entry["window_end_epoch"] = end_epoch
                    matches.append(entry)

        if not matches:
            return None

        if len(matches) > 1:
            print("[Engine] WARNING: overlapping %s entries detected for %s at %s" %
                  (system, schedule_set_name, hhmm))

        return matches[0]

    def _get_active_entry_with_special_fallback(self, system, weekday_0_mon, hhmm, now_epoch, special_set_name=None):
        if special_set_name:
            entry = self._get_active_schedule_entry(special_set_name, system, weekday_0_mon, hhmm, now_epoch)
            if entry:
                entry["source_set"] = special_set_name
                return entry

        entry = self._get_active_schedule_entry("NORMAL", system, weekday_0_mon, hhmm, now_epoch)
        if entry:
            entry["source_set"] = "NORMAL"
            return entry

        return None

    def _get_active_hw_entry_with_special_fallback(self, weekday_0_mon, hhmm, now_epoch, special_set_name=None):
        return self._get_active_entry_with_special_fallback("HW", weekday_0_mon, hhmm, now_epoch, special_set_name)

    def _get_once_rows_for_set(self, set_name, system, weekday_0_mon, now_epoch):
        cur = self.db_con.cursor()

        if system == "CH":
            cur.execute("""
                        SELECT id, start_time, end_time, setpoint, warmup, note, days
                        FROM schedule_entries
                        WHERE enabled = 1
                          AND schedule_set_name = ?
                          AND system = ?
                        ORDER BY start_time ASC
                        """, (set_name, system))
        else:
            cur.execute("""
                        SELECT id, start_time, end_time, NULL as setpoint, 0 as warmup, note, days
                        FROM schedule_entries
                        WHERE enabled = 1
                          AND schedule_set_name = ?
                          AND system = ?
                        ORDER BY start_time ASC
                        """, (set_name, system))

        rows = cur.fetchall()
        items = []

        today_wd = weekday_0_mon
        yesterday_wd = (weekday_0_mon - 1) % 7

        for row in rows:
            base_entry = {
                "id": row[0],
                "start_time": row[1],
                "end_time": row[2],
                "setpoint": row[3],
                "warmup": row[4],
                "note": row[5],
                "days": row[6],
                "source_set": set_name,
            }

            days_str = str(base_entry["days"] or "")

            try:
                overnight = str(base_entry["end_time"]) <= str(base_entry["start_time"])
            except Exception:
                overnight = False

            if str(today_wd) in days_str:
                try:
                    start_epoch, end_epoch = self._entry_window_for_day(base_entry, now_epoch)
                    e = dict(base_entry)
                    e["window_start_epoch"] = start_epoch
                    e["window_end_epoch"] = end_epoch
                    items.append(e)
                except Exception:
                    pass

            if overnight and str(yesterday_wd) in days_str:
                try:
                    yesterday_epoch = now_epoch - 86400.0
                    start_epoch, end_epoch = self._entry_window_for_day(base_entry, yesterday_epoch)
                    e = dict(base_entry)
                    e["window_start_epoch"] = start_epoch
                    e["window_end_epoch"] = end_epoch
                    items.append(e)
                except Exception:
                    pass

        return items

    def _get_once_context(self, schedule_set_name, system, weekday_0_mon, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        normal_rows = self._get_once_rows_for_set("NORMAL", system, weekday_0_mon, now_epoch)
        special_rows = self._get_once_rows_for_set(
            special_set_name, system, weekday_0_mon, now_epoch
        ) if special_set_name else []

        all_rows = normal_rows + special_rows

        if not all_rows:
            return {
                "first_entry": None,
                "last_entry": None,
                "first_start_epoch": None,
                "last_end_epoch": None,
                "first_setpoint": None,
                "in_window": False,
            }

        first_entry = None
        first_start_epoch = None

        for entry in all_rows:
            start_epoch = entry.get("window_start_epoch")
            if start_epoch is None:
                continue

            if first_start_epoch is None or start_epoch < first_start_epoch:
                first_entry = entry
                first_start_epoch = start_epoch
            elif start_epoch == first_start_epoch:
                if entry.get("source_set") != "NORMAL" and first_entry.get("source_set") == "NORMAL":
                    first_entry = entry
                    first_start_epoch = start_epoch

        last_entry = None
        last_end_epoch = None

        for entry in all_rows:
            end_epoch = entry.get("window_end_epoch")
            if end_epoch is None:
                continue

            if last_end_epoch is None or end_epoch > last_end_epoch:
                last_entry = entry
                last_end_epoch = end_epoch
            elif end_epoch == last_end_epoch:
                if entry.get("source_set") != "NORMAL" and last_entry.get("source_set") == "NORMAL":
                    last_entry = entry
                    last_end_epoch = end_epoch

        if first_entry is None or last_entry is None:
            return {
                "first_entry": None,
                "last_entry": None,
                "first_start_epoch": None,
                "last_end_epoch": None,
                "first_setpoint": None,
                "in_window": False,
            }

        in_window = (first_start_epoch <= now_epoch < last_end_epoch)

        first_setpoint = None
        if system == "CH":
            try:
                first_setpoint = float(first_entry["setpoint"] or self.default_setpoint)
            except Exception:
                first_setpoint = float(self.default_setpoint)

        return {
            "first_entry": first_entry,
            "last_entry": last_entry,
            "first_start_epoch": first_start_epoch,
            "last_end_epoch": last_end_epoch,
            "first_setpoint": first_setpoint,
            "in_window": in_window,
        }

    def _get_ch_once_context(self, schedule_set_name, weekday_0_mon, now_epoch):
        return self._get_once_context(schedule_set_name, "CH", weekday_0_mon, now_epoch)

    def _get_hw_once_context(self, schedule_set_name, weekday_0_mon, now_epoch):
        return self._get_once_context(schedule_set_name, "HW", weekday_0_mon, now_epoch)

    def _get_next_entry_for_set(self, schedule_set_name, system, now_epoch):
        cur = self.db_con.cursor()
        cur.execute("""
                    SELECT id, start_time, end_time, setpoint, warmup, note, days
                    FROM schedule_entries
                    WHERE enabled = 1
                      AND schedule_set_name = ?
                      AND system = ?
                    ORDER BY start_time ASC
                    """, (schedule_set_name, system))
        rows = cur.fetchall()

        from datetime import datetime, timedelta

        dt_now = datetime.fromtimestamp(now_epoch)
        best_entry = None
        best_start_epoch = None

        for r in rows:
            entry = {
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "setpoint": r[3],
                "warmup": r[4],
                "note": r[5],
                "days": r[6],
                "source_set": schedule_set_name,
            }

            days_str = str(entry["days"] or "")

            for day_offset in range(0, 8):
                dt_day = dt_now + timedelta(days=day_offset)
                wd = dt_day.weekday()

                if str(wd) not in days_str:
                    continue

                try:
                    day_epoch = time.mktime(dt_day.timetuple())
                    start_epoch = self._time_text_to_epoch_for_day(entry["start_time"], day_epoch)
                except Exception:
                    continue

                if start_epoch <= now_epoch:
                    continue

                if best_start_epoch is None or start_epoch < best_start_epoch:
                    best_start_epoch = start_epoch
                    best_entry = dict(entry)

        return best_entry, best_start_epoch

    def _choose_earlier_entry(self, a_entry, a_epoch, b_entry, b_epoch):
        if a_entry is None:
            return b_entry, b_epoch
        if b_entry is None:
            return a_entry, a_epoch

        if a_epoch < b_epoch:
            return a_entry, a_epoch
        if b_epoch < a_epoch:
            return b_entry, b_epoch

        a_is_special = (a_entry.get("source_set") != "NORMAL")
        b_is_special = (b_entry.get("source_set") != "NORMAL")

        if a_is_special and not b_is_special:
            return a_entry, a_epoch
        if b_is_special and not a_is_special:
            return b_entry, b_epoch

        return a_entry, a_epoch

    def _get_ch_timed_context(self, schedule_set_name, weekday_0_mon, hhmm, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        current_entry = self._get_active_entry_with_special_fallback(
            "CH", weekday_0_mon, hhmm, now_epoch, special_set_name
        )

        normal_next, normal_next_epoch = self._get_next_entry_for_set("NORMAL", "CH", now_epoch)

        if special_set_name:
            special_next, special_next_epoch = self._get_next_entry_for_set(special_set_name, "CH", now_epoch)
        else:
            special_next, special_next_epoch = None, None

        best_next, best_start_epoch = self._choose_earlier_entry(
            special_next, special_next_epoch,
            normal_next, normal_next_epoch
        )

        ctx = {
            "current_entry": current_entry,
            "next_entry": best_next,
            "current_target": None,
            "advanced_target": None,
            "advance_until_epoch": None,
            "warmup_active": False,
            "warmup_entry": None,
            "warmup_entry_id": None,
            "warmup_entry_start_epoch": None,
            "warmup_entry_end_epoch": None,
            "warmup_target": None,
            "warmup_start_epoch": None,
            "warmup_seconds": None,
            "warmup_mode": None,
            "warmup_bias_minutes": 0.0,
            "is_warmup": False,
        }

        if current_entry:
            ctx["current_target"] = float(current_entry["setpoint"] or self.default_setpoint)
            try:
                end_epoch = current_entry.get("window_end_epoch")
            except Exception:
                end_epoch = None

            ctx["advanced_target"] = None
            ctx["advance_until_epoch"] = end_epoch

        else:
            if best_next:
                ctx["advanced_target"] = float(best_next["setpoint"] or self.default_setpoint)
                ctx["advance_until_epoch"] = best_start_epoch

                try:
                    warmup_enabled = parse_bool(best_next.get("warmup"))
                except Exception:
                    warmup_enabled = False

                if warmup_enabled and self.current_temp is not None:
                    try:
                        entry_setpoint = float(best_next.get("setpoint") or self.default_setpoint)
                    except Exception:
                        entry_setpoint = float(self.default_setpoint)

                    warm_target = entry_setpoint + float(self.warmup_target_offset or 0.0)

                    warmup_seconds = None
                    warmup_mode = "legacy"

                    if self.predictive_heating_enabled:
                        warmup_seconds = self._predictive_warmup_needed(
                            self.current_temp,
                            warm_target,
                            now_epoch=now_epoch
                        )
                        warmup_mode = "predictive"

                    if warmup_seconds is None:
                        warmup_seconds = self._legacy_warmup_needed(self.current_temp, warm_target)
                        warmup_mode = "legacy"

                    if warmup_seconds is not None:
                        bias_seconds = 0.0

                        if self.predictive_bias_enabled:
                            try:
                                scheduled_start_hour = time.localtime(best_start_epoch).tm_hour
                            except Exception:
                                scheduled_start_hour = None

                            try:
                                delta_band = self._get_warmup_delta_band(self.current_temp, entry_setpoint)
                                raw_bias = self._get_warmup_bias_minutes_for_hour_and_band(
                                    scheduled_start_hour,
                                    delta_band
                                )
                                sample_count = self._get_warmup_bias_sample_count_for_hour_and_band(
                                    scheduled_start_hour,
                                    delta_band
                                )
                                confidence = self._bias_confidence_factor(sample_count)
                                bias_minutes = raw_bias * confidence
                                bias_seconds = float(bias_minutes) * 60.0
                            except Exception:
                                bias_seconds = 0.0

                        raw_lead_seconds = (
                                float(warmup_seconds)
                                + float(bias_seconds)
                        )

                        try:
                            min_s = int(float(self.warmup_minimum_lead_time)) * 60
                        except Exception:
                            min_s = 30 * 60

                        try:
                            max_s = int(float(self.warmup_maximum_lead_time)) * 60
                        except Exception:
                            max_s = 120 * 60

                        total_lead_seconds = self._clamp(raw_lead_seconds, min_s, max_s)
                        effective_bias_seconds = total_lead_seconds - float(warmup_seconds)
                        ctx["warmup_bias_minutes"] = effective_bias_seconds / 60.0

                        warmup_start_epoch = best_start_epoch - total_lead_seconds

                        # calculate end epoch for the scheduled entry
                        warmup_entry_end_epoch = None
                        try:
                            warmup_entry_end_epoch = self._time_text_to_epoch_for_day(
                                best_next["end_time"], best_start_epoch
                            )
                            if warmup_entry_end_epoch <= best_start_epoch:
                                warmup_entry_end_epoch += 86400.0
                        except Exception:
                            warmup_entry_end_epoch = None

                        ctx["warmup_entry"] = best_next
                        ctx["warmup_entry_id"] = best_next.get("id")
                        ctx["warmup_entry_start_epoch"] = best_start_epoch
                        ctx["warmup_entry_end_epoch"] = warmup_entry_end_epoch
                        ctx["warmup_target"] = entry_setpoint
                        ctx["warmup_start_epoch"] = warmup_start_epoch
                        ctx["warmup_seconds"] = warmup_seconds
                        ctx["warmup_mode"] = warmup_mode

                        if warmup_start_epoch <= now_epoch < best_start_epoch:
                            ctx["warmup_active"] = True
                            ctx["is_warmup"] = True

        return ctx

    def _get_hw_timed_context(self, schedule_set_name, weekday_0_mon, hhmm, now_epoch):
        special_set_name = None if schedule_set_name == "NORMAL" else schedule_set_name

        current_entry = self._get_active_hw_entry_with_special_fallback(
            weekday_0_mon, hhmm, now_epoch, special_set_name
        )

        normal_next, normal_next_epoch = self._get_next_entry_for_set("NORMAL", "HW", now_epoch)

        if special_set_name:
            special_next, special_next_epoch = self._get_next_entry_for_set(special_set_name, "HW", now_epoch)
        else:
            special_next, special_next_epoch = None, None

        best_next, best_start_epoch = self._choose_earlier_entry(
            special_next, special_next_epoch,
            normal_next, normal_next_epoch
        )

        ctx = {
            "current_entry": current_entry,
            "next_entry": best_next,
            "current_on": bool(current_entry is not None),
            "advanced_on": False,
            "advance_until_epoch": None,
        }

        if current_entry:
            try:
                end_epoch = current_entry.get("window_end_epoch")
            except Exception:
                end_epoch = None

            ctx["advanced_on"] = False
            ctx["advance_until_epoch"] = end_epoch

        else:
            if best_next:
                ctx["advanced_on"] = True
                ctx["advance_until_epoch"] = best_start_epoch

        return ctx

    def _compute_ch_target(self, weekday, hhmm, now_epoch):
        sw = (self.ch_system_switch or "").lower()

        holiday_active = False
        special_set_name = None

        if sw != "off":
            holiday_active = self._is_holiday_active("CH", now_epoch)
            if not holiday_active:
                special_set_name = self._get_active_special_set("CH", now_epoch)

        ctx = None
        advance_applied = False

        if sw == "off":
            target = None
            reason = "switch=off"

        elif holiday_active:
            target = float(self.default_setpoint)
            reason = "holiday(fallback_default_setpoint)"

        elif sw == "on":
            target = float(self.default_on_setpoint)
            reason = "switch=on"

        elif sw == "once":
            active_set_name = special_set_name or "NORMAL"
            once_ctx = self._get_ch_once_context(active_set_name, weekday, now_epoch)

            has_once_entries = bool(once_ctx.get("first_entry")) and bool(once_ctx.get("last_entry"))

            if self.ch_advance:
                advance_until = None

                if not has_once_entries:
                    target = float(self.default_setpoint)
                    reason = "advance(no_once_entries fallback_default_setpoint)"
                    advance_until = None

                elif once_ctx["in_window"]:
                    target = float(self.default_on_setpoint)
                    advance_until = once_ctx["last_end_epoch"]
                    reason = "advance(skip_once_until %s set=%s)" % (
                        once_ctx["last_entry"]["end_time"],
                        once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                else:
                    target = float(once_ctx["first_setpoint"])
                    advance_until = once_ctx["first_start_epoch"]
                    reason = "advance(start_once_now %s-%s first_set=%s last_set=%s)" % (
                        once_ctx["first_entry"]["start_time"],
                        once_ctx["last_entry"]["end_time"],
                        once_ctx["first_entry"].get("source_set", active_set_name),
                        once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                if advance_until is None or now_epoch >= advance_until:
                    self._clear_advance("CH")
                    once_ctx = self._get_ch_once_context(active_set_name, weekday, now_epoch)
                    has_once_entries = bool(once_ctx.get("first_entry")) and bool(once_ctx.get("last_entry"))

                    if has_once_entries and once_ctx["in_window"]:
                        target = float(once_ctx["first_setpoint"])
                        reason = "once(set=%s %s-%s first_sp=%.1f)" % (
                            once_ctx["first_entry"].get("source_set", active_set_name),
                            once_ctx["first_entry"]["start_time"],
                            once_ctx["last_entry"]["end_time"],
                            once_ctx["first_setpoint"]
                        )
                    else:
                        target = float(self.default_setpoint)
                        reason = "once(outside_window fallback_default_setpoint)"

            else:
                if has_once_entries and once_ctx["in_window"]:
                    target = float(once_ctx["first_setpoint"])
                    reason = "once(set=%s %s-%s first_sp=%.1f)" % (
                        once_ctx["first_entry"].get("source_set", active_set_name),
                        once_ctx["first_entry"]["start_time"],
                        once_ctx["last_entry"]["end_time"],
                        once_ctx["first_setpoint"]
                    )
                else:
                    target = float(self.default_setpoint)
                    reason = "once(outside_window fallback_default_setpoint)"

        elif sw == "timed":
            active_set_name = special_set_name or "NORMAL"
            ctx = self._get_ch_timed_context(active_set_name, weekday, hhmm, now_epoch)
            entry = ctx["current_entry"]

            if self.ch_advance:
                advance_until = ctx["advance_until_epoch"]

                if advance_until is None or now_epoch >= advance_until:
                    self._clear_advance("CH")
                    ctx = self._get_ch_timed_context(active_set_name, weekday, hhmm, now_epoch)
                    entry = ctx["current_entry"]
                else:
                    target = ctx["advanced_target"]
                    if entry:
                        reason = "advance(skip_current_until %s set=%s)" % (
                            entry["end_time"],
                            entry.get("source_set", active_set_name)
                        )
                    else:
                        next_entry = ctx["next_entry"]
                        if next_entry:
                            reason = "advance(until_next_start %s then %s-%s set=%s active_now)" % (
                                next_entry["start_time"],
                                next_entry["start_time"],
                                next_entry["end_time"],
                                next_entry.get("source_set", active_set_name)
                            )
                        else:
                            reason = "advance(no_next_entry)"
                    entry = "__ADVANCE_APPLIED__"
                    advance_applied = True

            if entry != "__ADVANCE_APPLIED__":
                if entry:
                    target = float(entry["setpoint"] or self.default_setpoint)
                    reason = "id=%s set=%s %s-%s" % (
                        entry["id"], entry.get("source_set", active_set_name), entry["start_time"], entry["end_time"]
                    )
                elif ctx.get("warmup_active"):
                    warmup_entry = ctx.get("warmup_entry")
                    target = float(ctx.get("warmup_target") or self.default_setpoint)
                    reason = "warmup(id=%s starts=%s set=%s mode=%s eta=%sm bias=%+.1fm)" % (
                        warmup_entry["id"],
                        warmup_entry["start_time"],
                        warmup_entry.get("source_set", active_set_name),
                        ctx.get("warmup_mode") or "legacy",
                        self._fmt_predictive_minutes(ctx.get("warmup_seconds")),
                        float(ctx.get("warmup_bias_minutes") or 0.0)
                    )
                else:
                    target = float(self.default_setpoint)
                    reason = "default_setpoint set=%s" % active_set_name
        else:
            target = None
            reason = "unsupported_switch=%s" % sw

        boost_active, boost_finish = self._is_boost_active("CH", now_epoch)
        if boost_active and not holiday_active and sw != "off":
            if self.ch_advance:
                self._clear_advance("CH")

            try:
                target = float(self.settings.get("BOOST_SETPOINT", self.default_on_setpoint))
            except Exception:
                target = float(self.default_on_setpoint)

            reason = "boost(until %s)" % time.strftime("%H:%M", time.localtime(boost_finish))

        is_warmup = False
        warmup_entry_id = None
        warmup_entry_start_epoch = None
        warmup_entry_end_epoch = None

        if sw == "timed" and ctx is not None and not advance_applied:
            is_warmup = bool(ctx.get("is_warmup", False))
            warmup_entry_id = ctx.get("warmup_entry_id")
            warmup_entry_start_epoch = ctx.get("warmup_entry_start_epoch")
            warmup_entry_end_epoch = ctx.get("warmup_entry_end_epoch")

        if boost_active and not holiday_active and sw != "off":
            is_warmup = False
            warmup_entry_id = None
            warmup_entry_start_epoch = None
            warmup_entry_end_epoch = None

        return {
            "target": target,
            "reason": reason,
            "switch": sw,
            "holiday_active": holiday_active,
            "special_set_name": special_set_name,
            "is_warmup": is_warmup,
            "warmup_entry_id": warmup_entry_id,
            "warmup_entry_start_epoch": warmup_entry_start_epoch,
            "warmup_entry_end_epoch": warmup_entry_end_epoch,
        }

    def _compute_hw_target(self, weekday, hhmm, now_epoch):
        hw_sw = (self.hw_system_switch or "").lower()

        holiday_active = False
        special_set_name = None

        if hw_sw != "off":
            holiday_active = self._is_holiday_active("HW", now_epoch)
            if not holiday_active:
                special_set_name = self._get_active_special_set("HW", now_epoch)

        if hw_sw == "off":
            hw_target_on = False
            hw_reason = "switch=off"

        elif holiday_active:
            hw_target_on = False
            hw_reason = "holiday(active)"

        elif hw_sw == "on":
            hw_target_on = True
            hw_reason = "switch=on"

        elif hw_sw == "once":
            active_set_name = special_set_name or "NORMAL"
            hw_once_ctx = self._get_hw_once_context(active_set_name, weekday, now_epoch)

            has_once_entries = bool(hw_once_ctx.get("first_entry")) and bool(hw_once_ctx.get("last_entry"))

            if self.hw_advance:
                hw_advance_until = None
                if not has_once_entries:
                    hw_target_on = False
                    hw_reason = "advance(no_once_entries)"
                    hw_advance_until = None

                elif hw_once_ctx["in_window"]:
                    hw_target_on = False
                    hw_advance_until = hw_once_ctx["last_end_epoch"]
                    hw_reason = "advance(skip_once_until %s set=%s)" % (
                        hw_once_ctx["last_entry"]["end_time"],
                        hw_once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                else:
                    hw_target_on = True
                    hw_advance_until = hw_once_ctx["first_start_epoch"]
                    hw_reason = "advance(start_once_now %s-%s first_set=%s last_set=%s)" % (
                        hw_once_ctx["first_entry"]["start_time"],
                        hw_once_ctx["last_entry"]["end_time"],
                        hw_once_ctx["first_entry"].get("source_set", active_set_name),
                        hw_once_ctx["last_entry"].get("source_set", active_set_name)
                    )

                if hw_advance_until is None or now_epoch >= hw_advance_until:
                    self._clear_advance("HW")
                    hw_once_ctx = self._get_hw_once_context(active_set_name, weekday, now_epoch)
                    has_once_entries = bool(hw_once_ctx.get("first_entry")) and bool(hw_once_ctx.get("last_entry"))

                    if has_once_entries and hw_once_ctx["in_window"]:
                        hw_target_on = True
                        hw_reason = "once(set=%s %s-%s)" % (
                            hw_once_ctx["first_entry"].get("source_set", active_set_name),
                            hw_once_ctx["first_entry"]["start_time"],
                            hw_once_ctx["last_entry"]["end_time"]
                        )
                    else:
                        hw_target_on = False
                        hw_reason = "once(outside_window)"

            else:
                if has_once_entries and hw_once_ctx["in_window"]:
                    hw_target_on = True
                    hw_reason = "once(set=%s %s-%s)" % (
                        hw_once_ctx["first_entry"].get("source_set", active_set_name),
                        hw_once_ctx["first_entry"]["start_time"],
                        hw_once_ctx["last_entry"]["end_time"]
                    )
                else:
                    hw_target_on = False
                    hw_reason = "once(outside_window)"

        elif hw_sw == "timed":
            active_set_name = special_set_name or "NORMAL"
            hw_ctx = self._get_hw_timed_context(active_set_name, weekday, hhmm, now_epoch)
            hw_entry = hw_ctx["current_entry"]

            if self.hw_advance:
                hw_advance_until = hw_ctx["advance_until_epoch"]

                if hw_advance_until is None or now_epoch >= hw_advance_until:
                    self._clear_advance("HW")
                    hw_ctx = self._get_hw_timed_context(active_set_name, weekday, hhmm, now_epoch)
                    hw_entry = hw_ctx["current_entry"]
                else:
                    hw_target_on = hw_ctx["advanced_on"]
                    if hw_entry:
                        hw_reason = "advance(skip_current_until %s set=%s)" % (
                            hw_entry["end_time"],
                            hw_entry.get("source_set", active_set_name)
                        )
                    else:
                        hw_next_entry = hw_ctx["next_entry"]
                        if hw_next_entry:
                            hw_reason = "advance(until_next_start %s then %s-%s set=%s active_now)" % (
                                hw_next_entry["start_time"],
                                hw_next_entry["start_time"],
                                hw_next_entry["end_time"],
                                hw_next_entry.get("source_set", active_set_name)
                            )
                        else:
                            hw_reason = "advance(no_next_entry)"
                    hw_entry = "__ADVANCE_APPLIED__"

            if hw_entry != "__ADVANCE_APPLIED__":
                if not hw_entry:
                    hw_target_on = False
                    hw_reason = "no_entry set=%s" % active_set_name
                else:
                    hw_target_on = True
                    hw_reason = "id=%s set=%s %s-%s" % (
                        hw_entry["id"], hw_entry.get("source_set", active_set_name),
                        hw_entry["start_time"], hw_entry["end_time"]
                    )

        else:
            hw_target_on = False
            hw_reason = "unsupported_switch=%s" % hw_sw

        hw_boost_active, hw_boost_finish = self._is_boost_active("HW", now_epoch)
        if hw_boost_active and not holiday_active and hw_sw != "off":
            if self.hw_advance:
                self._clear_advance("HW")
            hw_target_on = True
            hw_reason = "boost(until %s)" % time.strftime("%H:%M", time.localtime(hw_boost_finish))

        return {
            "target_on": hw_target_on,
            "reason": hw_reason,
            "switch": hw_sw,
            "holiday_active": holiday_active,
            "special_set_name": special_set_name,
        }