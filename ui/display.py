#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/display.py

import time
from ui.constants import DISPLAY_WIDTH, DEGREE_CHAR


class DisplayHelper(object):
    def __init__(self, lcd):
        self.lcd = lcd
        self.width = DISPLAY_WIDTH
        self.last_applied_brightness = None
        self.last_dim_state = None

    def fit(self, text):
        return str(text or "")[:self.width].ljust(self.width)

    def fmt_temp(self, value):
        try:
            return "%.1f%s" % (float(value), DEGREE_CHAR)
        except Exception:
            return "--.-%s" % DEGREE_CHAR

    def relay_text(self, value):
        if value is True:
            return "ON"
        if value is False:
            return "OFF"
        return "--"

    def desired_text(self, value):
        if value in ("ON", "OFF"):
            return value
        return "--"

    def switch_text(self, value):
        return str(value or "--").upper()[:5]

    def short_reason(self, text):
        s = str(text or "").strip()
        if not s:
            return "--"

        s = s.replace("entry_id=", "id=")
        s = s.replace("default_setpoint", "default")
        s = s.replace("fallback_default_setpoint", "fallback")
        s = s.replace("unsupported_switch=", "bad_sw=")
        s = s.replace("switch=", "sw=")
        s = s.replace("advance(", "adv(")
        s = s.replace("warmup(", "wu(")
        s = s.replace("holiday(", "hol(")
        s = s.replace("outside_window", "out")
        s = s.replace("no_once_entries", "no_once")
        s = s.replace("no_next_entry", "no_next")
        s = s.replace("skip_current_until", "skip_to")
        s = s.replace("until_next_start", "til_next")
        return s

    def hhmm_to_minutes(self, hhmm):
        try:
            parts = str(hhmm).split(":")
            return (int(parts[0]) * 60) + int(parts[1])
        except Exception:
            return 0

    def is_dim_period_active(self, start_hhmm, end_hhmm, now_epoch=None):
        if now_epoch is None:
            now_epoch = time.time()

        lt = time.localtime(now_epoch)
        now_mins = (lt.tm_hour * 60) + lt.tm_min

        start_mins = self.hhmm_to_minutes(start_hhmm)
        end_mins = self.hhmm_to_minutes(end_hhmm)

        if start_mins == end_mins:
            return False
        if start_mins < end_mins:
            return start_mins <= now_mins < end_mins
        return now_mins >= start_mins or now_mins < end_mins

    def set_backlight(self, level):
        try:
            level = max(1, min(250, int(level)))
        except Exception:
            level = 80

        if self.lcd is not None:
            self.lcd.lcd_backlight(level)

    def force_full_redraw(self):
        try:
            if self.lcd is not None and hasattr(self.lcd, "buffer"):
                self.lcd.buffer = [None, None, None, None]
        except Exception:
            pass

    def clear(self):
        try:
            if self.lcd is not None:
                self.lcd.lcd_clear()
        except Exception:
            pass

    def render(self, lines):
        if self.lcd is None:
            return

        for i in range(4):
            self.lcd.smart_write(i + 1, lines[i])

    def scroll_window(self, text, scroll_pos):
        if len(text) <= self.width:
            return text.ljust(self.width)

        padding = "     "
        scroll_str = text + padding
        pos = scroll_pos % len(scroll_str)
        return (scroll_str + scroll_str)[pos:pos + self.width]