#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/controller.py

from __future__ import print_function
import time, datetime
from ui.constants import (
    UI_MODE_HOME,
    UI_MODE_CONFIRM,
    UI_MODE_MENU,
    UI_MODE_STATUS,
    UI_MODE_EDITOR,
    UI_MODE_PROGRAMS,
    UI_MODE_PROGRAM_DETAILS,
    UI_MODE_PROGRAM_ACTIONS,
    UI_MODE_PROGRAM_EDIT,
    UI_MODE_DAYS_EDITOR,
    UI_MODE_SPECIAL_PROGRAMS,
    UI_MODE_SPECIAL_PROGRAM_DETAILS,
    UI_MODE_SPECIAL_PROGRAM_EDIT,
    UI_MODE_HOLIDAY_PROGRAMS,
    UI_MODE_HOLIDAY_PROGRAM_DETAILS,
    UI_MODE_HOLIDAY_PROGRAM_EDIT,
    UI_MODE_DATETIME_EDITOR,
    MENU_TIMEOUT_SECONDS,
)


class UIController(object):
    def __init__(self, ui_process):
        self.ui_process = ui_process

    def set_ui_mode(self, new_mode):
        ui = self.ui_process.ui
        old_mode = ui.mode
        ui.mode = new_mode

        if old_mode != new_mode:
            ui.scroll.pos = 0
            ui.scroll.last_time = 0.0
            ui.last_input_time = time.time()

            if old_mode == UI_MODE_MENU or new_mode == UI_MODE_MENU:
                ui.menu.dirty = True
                ui.menu.last_page = None
                ui.menu.last_index = None

            self.ui_process._force_full_redraw()

    def show_message(self, line3, line4="", seconds=2.5):
        ui = self.ui_process.ui
        display = self.ui_process.display

        ui.overlay.message_line3 = display.fit(line3)
        ui.overlay.message_line4 = display.fit(line4)
        ui.overlay.message_until = time.time() + float(seconds)

    def clear_message(self):
        ui = self.ui_process.ui
        ui.overlay.message_line3 = ""
        ui.overlay.message_line4 = ""
        ui.overlay.message_until = 0.0

    def message_active(self):
        ui = self.ui_process.ui
        return bool(ui.overlay.message_until and time.time() < ui.overlay.message_until)

    def start_confirm(self, line3, line4, action, timeout=4.0):
        ui = self.ui_process.ui
        display = self.ui_process.display

        self.set_ui_mode(UI_MODE_CONFIRM)
        ui.overlay.confirm_action = action
        ui.overlay.confirm_line3 = display.fit(line3)
        ui.overlay.confirm_line4 = display.fit(line4)
        ui.overlay.confirm_until = time.time() + float(timeout)
        print("[UI] confirm started:", action)

    def clear_confirm(self):
        ui = self.ui_process.ui
        ui.overlay.confirm_action = None
        ui.overlay.confirm_line3 = ""
        ui.overlay.confirm_line4 = ""
        ui.overlay.confirm_until = 0.0

        if ui.mode == UI_MODE_CONFIRM:
            self.set_ui_mode(UI_MODE_HOME)

    def confirm_active(self):
        ui = self.ui_process.ui
        return ui.mode == UI_MODE_CONFIRM and ui.overlay.confirm_until and time.time() < ui.overlay.confirm_until

    def _default_period_times(self):
        start_dt = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        end_dt = start_dt + datetime.timedelta(hours=1)
        return (
            start_dt.strftime("%d/%m/%y,%H:%M"),
            end_dt.strftime("%d/%m/%y,%H:%M"),
        )

    def update_ui_timers(self):
        ui = self.ui_process.ui
        now = time.time()

        if ui.mode == UI_MODE_CONFIRM and ui.overlay.confirm_until and now >= ui.overlay.confirm_until:
            print("[UI] confirm timed out")
            self.clear_confirm()

        if ui.overlay.message_until and now >= ui.overlay.message_until:
            self.clear_message()

        if ui.mode in (
                UI_MODE_MENU,
                UI_MODE_STATUS,
                UI_MODE_EDITOR,
                UI_MODE_PROGRAMS,
                UI_MODE_PROGRAM_DETAILS,
                UI_MODE_PROGRAM_ACTIONS,
                UI_MODE_PROGRAM_EDIT,
                UI_MODE_DAYS_EDITOR,
                UI_MODE_SPECIAL_PROGRAMS,
                UI_MODE_SPECIAL_PROGRAM_DETAILS,
                UI_MODE_SPECIAL_PROGRAM_EDIT,
                UI_MODE_HOLIDAY_PROGRAMS,
                UI_MODE_HOLIDAY_PROGRAM_DETAILS,
                UI_MODE_HOLIDAY_PROGRAM_EDIT,
                UI_MODE_DATETIME_EDITOR,
        ):
            if (now - ui.last_input_time) >= MENU_TIMEOUT_SECONDS:
                print("[UI] inactivity timeout")

                self.clear_message()
                self.clear_confirm()

                if ui.mode == UI_MODE_EDITOR:
                    print("[UI] timeout -> close editor")

                    key = str(ui.editor.key or "")
                    if key.startswith("PROGRAM_EDIT_"):
                        self.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
                    elif key.startswith("SPECIAL_EDIT_"):
                        self.close_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
                    elif key.startswith("HOLIDAY_EDIT_"):
                        self.close_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
                    else:
                        self.close_editor()

                elif ui.mode == UI_MODE_PROGRAM_EDIT:
                    print("[UI] timeout -> close program edit")
                    self.close_program_edit()

                elif ui.mode == UI_MODE_SPECIAL_PROGRAM_EDIT:
                    print("[UI] timeout -> close special edit")
                    self.close_special_edit()

                elif ui.mode == UI_MODE_HOLIDAY_PROGRAM_EDIT:
                    print("[UI] timeout -> close holiday edit")
                    self.close_holiday_edit()

                elif ui.mode == UI_MODE_DAYS_EDITOR:
                    print("[UI] timeout -> close days editor")
                    self.close_days_editor(save=False)

                elif ui.mode == UI_MODE_DATETIME_EDITOR:
                    print("[UI] timeout -> close datetime editor")

                    key = str(ui.datetime_editor.key or "")
                    if key.startswith("SPECIAL_EDIT_"):
                        self.close_datetime_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
                    elif key.startswith("HOLIDAY_EDIT_"):
                        self.close_datetime_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
                    else:
                        self.close_datetime_editor()

                else:
                    print("[UI] timeout -> HOME")

                    ui.menu.stack = []
                    ui.menu.page = "MAIN"
                    ui.menu.index = 0
                    ui.menu.dirty = True

                    ui.programs.details_item = None
                    ui.programs.details_page = 0
                    ui.specials.details_item = None
                    ui.specials.details_page = 0
                    ui.holidays.details_item = None
                    ui.holidays.details_page = 0

                    self.set_ui_mode(UI_MODE_HOME)

    def start_enum_editor(self, key, label, options, current_value):
        ui = self.ui_process.ui

        ui.editor.active = True
        ui.editor.kind = "enum"
        ui.editor.key = key
        ui.editor.label = label
        ui.editor.options = list(options or [])
        ui.editor.original_value = current_value

        try:
            ui.editor.index = ui.editor.options.index(current_value)
        except Exception:
            ui.editor.index = 0

        ui.editor.value_text = ""
        ui.editor.min_value = None
        ui.editor.max_value = None
        ui.editor.step = 1.0
        ui.editor.decimals = 0
        ui.editor.hour = 0
        ui.editor.minute = 0
        ui.editor.part_index = 0

        self.set_ui_mode(UI_MODE_EDITOR)

    def start_number_editor(self, key, label, current_value,
                            min_value=None, max_value=None,
                            step=1.0, decimals=0):
        ui = self.ui_process.ui

        ui.editor.active = True
        ui.editor.kind = "number"
        ui.editor.key = key
        ui.editor.label = label
        ui.editor.options = []
        ui.editor.index = 0
        ui.editor.original_value = current_value

        ui.editor.min_value = min_value
        ui.editor.max_value = max_value
        ui.editor.step = float(step)
        ui.editor.decimals = int(decimals)

        try:
            numeric_value = float(current_value)
        except Exception:
            numeric_value = 0.0

        fmt = "%%.%df" % ui.editor.decimals
        ui.editor.value_text = fmt % numeric_value

        ui.editor.hour = 0
        ui.editor.minute = 0
        ui.editor.part_index = 0

        self.set_ui_mode(UI_MODE_EDITOR)

    def start_bool_editor(self, key, label, current_value):
        ui = self.ui_process.ui

        ui.editor.active = True
        ui.editor.kind = "enum"
        ui.editor.key = key
        ui.editor.label = label
        ui.editor.options = ["False", "True"]
        ui.editor.original_value = current_value

        try:
            ui.editor.index = ui.editor.options.index(str(current_value))
        except Exception:
            ui.editor.index = 0

        ui.editor.value_text = ""
        ui.editor.min_value = None
        ui.editor.max_value = None
        ui.editor.step = 1.0
        ui.editor.decimals = 0
        ui.editor.hour = 0
        ui.editor.minute = 0
        ui.editor.part_index = 0

        self.set_ui_mode(UI_MODE_EDITOR)

    def start_time_editor(self, key, label, current_value):
        ui = self.ui_process.ui

        ui.editor.active = True
        ui.editor.kind = "time"
        ui.editor.key = key
        ui.editor.label = label
        ui.editor.options = []
        ui.editor.index = 0
        ui.editor.original_value = current_value
        ui.editor.value_text = ""
        ui.editor.min_value = None
        ui.editor.max_value = None
        ui.editor.step = 1.0
        ui.editor.decimals = 0

        try:
            parts = str(current_value or "00:00").split(":")
            ui.editor.hour = max(0, min(23, int(parts[0])))
            ui.editor.minute = max(0, min(59, int(parts[1])))
        except Exception:
            ui.editor.hour = 0
            ui.editor.minute = 0

        ui.editor.part_index = 0

        self.set_ui_mode(UI_MODE_EDITOR)

    def start_datetime_editor(self, key, label, current_value):
        ui = self.ui_process.ui
        de = ui.datetime_editor

        de.active = True
        de.key = key
        de.label = label

        try:
            dt = datetime.datetime.strptime(str(current_value or "01/01/25,00:00"), "%d/%m/%y,%H:%M")
            de.day = dt.day
            de.month = dt.month
            de.year = dt.year % 100
            de.hour = dt.hour
            de.minute = dt.minute
        except Exception:
            de.day = 1
            de.month = 1
            de.year = 25
            de.hour = 0
            de.minute = 0

        de.part_index = 0
        self.set_ui_mode(UI_MODE_DATETIME_EDITOR)

    def close_datetime_editor(self, return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT):
        ui = self.ui_process.ui
        de = ui.datetime_editor

        de.active = False
        de.key = None
        de.label = ""
        de.day = 1
        de.month = 1
        de.year = 25
        de.hour = 0
        de.minute = 0
        de.part_index = 0

        self.set_ui_mode(return_mode)

    def start_program_edit(self, item=None, system=None, is_new=False):
        ui = self.ui_process.ui
        pe = ui.program_edit

        pe.active = True
        pe.is_new = bool(is_new)

        if item:
            pe.id = item.get("id")
            pe.system = item.get("system")
            pe.schedule_set_name = str(item.get("schedule_set_name") or "NORMAL")
            pe.start_time = str(item.get("start_time") or "06:00")
            pe.end_time = str(item.get("end_time") or "07:00")
            pe.days = str(item.get("days") or "0123456")
            pe.setpoint = str(item.get("setpoint") if item.get("setpoint") is not None else "20.0")
            pe.warmup = bool(item.get("warmup"))
            pe.enabled = bool(item.get("enabled"))
            pe.note = str(item.get("note") or "")
        else:
            pe.id = None
            pe.system = system or "CH"
            pe.schedule_set_name = "NORMAL"
            pe.start_time = "06:00"
            pe.end_time = "07:00"
            pe.days = "0123456"
            pe.setpoint = "20.0"
            pe.warmup = False
            pe.enabled = True
            pe.note = ""

        pe.field_index = 0
        self.set_ui_mode(UI_MODE_PROGRAM_EDIT)

    def close_program_edit(self):
        ui = self.ui_process.ui
        pe = ui.program_edit

        pe.active = False
        pe.is_new = False
        pe.id = None
        pe.system = None
        pe.schedule_set_name = "NORMAL"
        pe.start_time = "06:00"
        pe.end_time = "07:00"
        pe.days = "0123456"
        pe.setpoint = "20.0"
        pe.warmup = False
        pe.enabled = True
        pe.note = ""
        pe.field_index = 0

        self.set_ui_mode(UI_MODE_PROGRAMS)

    def start_days_editor(self, days_text):
        ui = self.ui_process.ui
        de = ui.days_editor

        de.active = True
        de.cursor = 0
        raw = str(days_text or "")

        de.values = []
        for i in range(7):
            de.values.append(str(i) in raw)

        self.set_ui_mode(UI_MODE_DAYS_EDITOR)

    def close_days_editor(self, save=False):
        ui = self.ui_process.ui
        de = ui.days_editor
        pe = ui.program_edit

        if save:
            out = []
            for i, enabled in enumerate(de.values):
                if enabled:
                    out.append(str(i))
            pe.days = "".join(out)

        de.active = False
        de.cursor = 0
        de.values = [True, True, True, True, True, True, True]

        self.set_ui_mode(UI_MODE_PROGRAM_EDIT)

    def start_special_edit(self, item=None, is_new=False):
        ui = self.ui_process.ui
        se = ui.special_edit

        se.active = True
        se.is_new = bool(is_new)

        if item:
            se.id = item.get("id")
            se.start_time = str(item.get("start_ts_text") or "01/01/25,00:00")
            se.end_time = str(item.get("end_ts_text") or "01/01/25,00:00")
            se.systems = str(item.get("systems") or "CH")
            se.schedule_set_name = str(item.get("schedule_set_name") or "NORMAL")
            se.enabled = bool(item.get("enabled"))
            se.note = str(item.get("note") or "")
        else:
            default_start, default_end = self._default_period_times()
            se.id = None
            se.start_time = default_start
            se.end_time = default_end
            se.systems = "CH"
            se.schedule_set_name = "HOLIDAY"
            se.enabled = True
            se.note = ""

        se.field_index = 0
        self.set_ui_mode(UI_MODE_SPECIAL_PROGRAM_EDIT)

    def close_special_edit(self):
        ui = self.ui_process.ui
        se = ui.special_edit

        se.active = False
        se.is_new = False
        se.id = None
        se.start_time = "01/01/25,00:00"
        se.end_time = "01/01/25,00:00"
        se.systems = "CH"
        se.schedule_set_name = "HOLIDAY"
        se.enabled = True
        se.note = ""
        se.field_index = 0

        self.set_ui_mode(UI_MODE_SPECIAL_PROGRAMS)

    def start_holiday_edit(self, item=None, is_new=False):
        ui = self.ui_process.ui
        he = ui.holiday_edit

        he.active = True
        he.is_new = bool(is_new)

        if item:
            he.id = item.get("id")
            he.start_time = str(item.get("start_ts_text") or "01/01/25,00:00")
            he.end_time = str(item.get("end_ts_text") or "01/01/25,00:00")
            he.systems = str(item.get("systems") or "CH")
            he.enabled = bool(item.get("enabled"))
            he.note = str(item.get("note") or "")
        else:
            default_start, default_end = self._default_period_times()
            he.id = None
            he.start_time = default_start
            he.end_time = default_end
            he.systems = "CH"
            he.enabled = True
            he.note = ""

        he.field_index = 0
        self.set_ui_mode(UI_MODE_HOLIDAY_PROGRAM_EDIT)

    def close_holiday_edit(self):
        ui = self.ui_process.ui
        he = ui.holiday_edit

        he.active = False
        he.is_new = False
        he.id = None
        he.start_time = "01/01/25,00:00"
        he.end_time = "01/01/25,00:00"
        he.systems = "CH"
        he.enabled = True
        he.note = ""
        he.field_index = 0

        self.set_ui_mode(UI_MODE_HOLIDAY_PROGRAMS)

    def close_editor(self, return_mode=UI_MODE_MENU):
        ui = self.ui_process.ui

        ui.editor.active = False
        ui.editor.kind = None
        ui.editor.key = None
        ui.editor.label = ""
        ui.editor.options = []
        ui.editor.index = 0
        ui.editor.value_text = ""
        ui.editor.min_value = None
        ui.editor.max_value = None
        ui.editor.step = 1.0
        ui.editor.decimals = 0
        ui.editor.hour = 0
        ui.editor.minute = 0
        ui.editor.part_index = 0
        ui.editor.original_value = None

        self.set_ui_mode(return_mode)