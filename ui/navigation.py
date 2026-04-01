#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/navigation.py

import time, datetime, calendar

from ui.constants import (
    UI_MODE_HOME,
    UI_MODE_MENU,
    UI_MODE_STATUS,
    UI_MODE_CONFIRM,
    CONFIRM_TIMEOUT_SECONDS,
    UI_MODE_EDITOR,
    UI_MODE_PROGRAMS,
    UI_MODE_PROGRAM_DETAILS,
    UI_MODE_PROGRAM_EDIT,
    UI_MODE_DAYS_EDITOR,
    UI_MODE_SPECIAL_PROGRAMS,
    UI_MODE_HOLIDAY_PROGRAMS,
    UI_MODE_SPECIAL_PROGRAM_DETAILS,
    UI_MODE_HOLIDAY_PROGRAM_DETAILS,
    UI_MODE_SPECIAL_PROGRAM_EDIT,
    UI_MODE_HOLIDAY_PROGRAM_EDIT,
    UI_MODE_DATETIME_EDITOR,
)
from ui.menu import get_menu_items
from ui.confirm import handle_confirm_button


def menu_open(ui_process, target_page):
    ui_process.ui.menu.stack.append(ui_process.ui.menu.page)
    ui_process.ui.menu.page = target_page
    ui_process.ui.menu.index = 0
    ui_process.ui.menu.dirty = True


def menu_go_back(ui_process):
    if ui_process.ui.menu.stack:
        ui_process.ui.menu.page = ui_process.ui.menu.stack.pop()
        ui_process.ui.menu.index = 0
        ui_process.ui.menu.dirty = True
    else:
        ui_process.controller.set_ui_mode(UI_MODE_HOME)


def _save_program_edit(ui_process):
    pe = ui_process.ui.program_edit

    payload = {
        "system": pe.system,
        "schedule_set_name": pe.schedule_set_name,
        "start_time": pe.start_time,
        "end_time": pe.end_time,
        "days": pe.days,
        "enabled": 1 if pe.enabled else 0,
        "note": pe.note,
    }

    if pe.system == "CH":
        try:
            payload["setpoint"] = float(pe.setpoint)
        except Exception:
            payload["setpoint"] = 20.0
        payload["warmup"] = 1 if pe.warmup else 0

    if pe.is_new:
        ok = ui_process.actions.create_program(payload)
        ui_process.controller.close_program_edit()
        ui_process.controller.show_message("Create Program", "Requested" if ok else "Failed", 2.0)
        return

    payload["id"] = pe.id
    ok = ui_process.actions.update_program(payload)
    ui_process.controller.close_program_edit()
    ui_process.controller.show_message("Save Program", "Requested" if ok else "Failed", 2.0)

def _days_in_month(year_2, month):
    year_full = 2000 + int(year_2)
    return calendar.monthrange(year_full, int(month))[1]


def _clamp_datetime_parts(de):
    if de.month < 1:
        de.month = 1
    if de.month > 12:
        de.month = 12

    if de.year < 0:
        de.year = 0
    if de.year > 99:
        de.year = 99

    max_day = _days_in_month(de.year, de.month)
    if de.day < 1:
        de.day = 1
    if de.day > max_day:
        de.day = max_day

    if de.hour < 0:
        de.hour = 0
    if de.hour > 23:
        de.hour = 23

    if de.minute < 0:
        de.minute = 0
    if de.minute > 59:
        de.minute = 59


def _save_datetime_editor_value(ui_process):
    de = ui_process.ui.datetime_editor
    text = "%02d/%02d/%02d,%02d:%02d" % (
        int(de.day), int(de.month), int(de.year), int(de.hour), int(de.minute)
    )

    if de.key == "SPECIAL_EDIT_START":
        ui_process.ui.special_edit.start_time = text
        ui_process.controller.close_datetime_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
        return

    if de.key == "SPECIAL_EDIT_END":
        ui_process.ui.special_edit.end_time = text
        ui_process.controller.close_datetime_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
        return

    if de.key == "HOLIDAY_EDIT_START":
        ui_process.ui.holiday_edit.start_time = text
        ui_process.controller.close_datetime_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
        return

    if de.key == "HOLIDAY_EDIT_END":
        ui_process.ui.holiday_edit.end_time = text
        ui_process.controller.close_datetime_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
        return

    ui_process.controller.close_datetime_editor()

def _parse_ui_datetime_to_epoch(text):
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Missing date/time")

    try:
        dt = datetime.datetime.strptime(raw, "%d/%m/%y,%H:%M")
    except Exception:
        raise ValueError("Use dd/mm/yy,HH:MM")

    return time.mktime(dt.timetuple())

def _save_special_edit(ui_process):
    se = ui_process.ui.special_edit

    try:
        start_ts_epoch = _parse_ui_datetime_to_epoch(se.start_time)
        end_ts_epoch = _parse_ui_datetime_to_epoch(se.end_time)
    except Exception as e:
        ui_process.controller.show_message("Special", str(e), 2.5)
        return

    if start_ts_epoch >= end_ts_epoch:
        ui_process.controller.show_message("Special", "Start < End", 2.5)
        return

    payload = {
        "start_ts_epoch": start_ts_epoch,
        "start_ts_text": se.start_time,
        "end_ts_epoch": end_ts_epoch,
        "end_ts_text": se.end_time,
        "systems": se.systems,
        "schedule_set_name": se.schedule_set_name,
        "enabled": 1 if se.enabled else 0,
        "note": se.note,
    }

    if se.is_new:
        ok = ui_process.actions.create_special_period(payload)
        ui_process.controller.close_special_edit()
        ui_process.controller.show_message("Create Special", "Requested" if ok else "Failed", 2.0)
        return

    payload["id"] = se.id
    ok = ui_process.actions.update_special_period(payload)
    ui_process.controller.close_special_edit()
    ui_process.controller.show_message("Save Special", "Requested" if ok else "Failed", 2.0)


def _save_holiday_edit(ui_process):
    he = ui_process.ui.holiday_edit

    try:
        start_ts_epoch = _parse_ui_datetime_to_epoch(he.start_time)
        end_ts_epoch = _parse_ui_datetime_to_epoch(he.end_time)
    except Exception as e:
        ui_process.controller.show_message("Holiday", str(e), 2.5)
        return

    if start_ts_epoch >= end_ts_epoch:
        ui_process.controller.show_message("Holiday", "Start < End", 2.5)
        return

    payload = {
        "start_ts_epoch": start_ts_epoch,
        "start_ts_text": he.start_time,
        "end_ts_epoch": end_ts_epoch,
        "end_ts_text": he.end_time,
        "systems": he.systems,
        "enabled": 1 if he.enabled else 0,
        "note": he.note,
    }

    if he.is_new:
        ok = ui_process.actions.create_holiday(payload)
        ui_process.controller.close_holiday_edit()
        ui_process.controller.show_message("Create Holiday", "Requested" if ok else "Failed", 2.0)
        return

    payload["id"] = he.id
    ok = ui_process.actions.update_holiday(payload)
    ui_process.controller.close_holiday_edit()
    ui_process.controller.show_message("Save Holiday", "Requested" if ok else "Failed", 2.0)


def _save_editor_value(ui_process):
    ed = ui_process.ui.editor
    pe = ui_process.ui.program_edit
    se = ui_process.ui.special_edit
    he = ui_process.ui.holiday_edit

    if not ed.active or not ed.key:
        ui_process.controller.close_editor()
        return

    if ed.key == "PROGRAM_EDIT_START":
        pe.start_time = "%02d:%02d" % (int(ed.hour), int(ed.minute))
        ui_process.controller.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
        return

    if ed.key == "PROGRAM_EDIT_END":
        pe.end_time = "%02d:%02d" % (int(ed.hour), int(ed.minute))
        ui_process.controller.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
        return

    if ed.key == "PROGRAM_EDIT_SETPOINT":
        pe.setpoint = str(ed.value_text or "").strip()
        ui_process.controller.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
        return

    if ed.key == "PROGRAM_EDIT_NOTE":
        if ed.options and 0 <= ed.index < len(ed.options):
            pe.note = str(ed.options[ed.index])
        else:
            pe.note = ""
        ui_process.controller.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
        return

    if ed.key == "SPECIAL_EDIT_SETNAME":
        if ed.options and 0 <= ed.index < len(ed.options):
            se.schedule_set_name = str(ed.options[ed.index])
        else:
            se.schedule_set_name = "BOOST"
        ui_process.controller.close_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
        return

    if ed.key == "SPECIAL_EDIT_NOTE":
        if ed.options and 0 <= ed.index < len(ed.options):
            se.note = str(ed.options[ed.index])
        else:
            se.note = ""
        ui_process.controller.close_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
        return

    if ed.key == "HOLIDAY_EDIT_NOTE":
        if ed.options and 0 <= ed.index < len(ed.options):
            he.note = str(ed.options[ed.index])
        else:
            he.note = ""
        ui_process.controller.close_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
        return

    if ed.kind == "enum":
        if not ed.options:
            ui_process.controller.close_editor()
            return

        value = ed.options[ed.index]
        ok = ui_process.actions.set_setting(ed.key, value)
        label = ed.label[:16]

        shown_value = value
        if ed.key == "COMFORT":
            shown_value = "On" if value == "True" else "Off"

        ui_process.controller.close_editor()
        ui_process.controller.show_message(label, shown_value if ok else "Failed", 2.0)
        return

    if ed.kind == "number":
        value = str(ed.value_text or "").strip()
        ok = ui_process.actions.set_setting(ed.key, value)
        label = ed.label[:16]
        ui_process.controller.close_editor()
        ui_process.controller.show_message(label, "Saved" if ok else "Failed", 2.0)
        return

    if ed.kind == "time":
        value = "%02d:%02d" % (int(ed.hour), int(ed.minute))
        ok = ui_process.actions.set_setting(ed.key, value)
        label = ed.label[:16]
        ui_process.controller.close_editor()
        ui_process.controller.show_message(label, value if ok else "Failed", 2.0)
        return

    ui_process.controller.close_editor()


def _adjust_editor_number(ui_process, direction):
    ed = ui_process.ui.editor

    try:
        value = float(ed.value_text)
    except Exception:
        value = 0.0

    value += (float(ed.step) * float(direction))

    if ed.min_value is not None and value < ed.min_value:
        value = ed.min_value
    if ed.max_value is not None and value > ed.max_value:
        value = ed.max_value

    fmt = "%%.%df" % int(ed.decimals)
    ed.value_text = fmt % value


def handle_editor_button(ui_process, name):
    name = (name or "").strip().lower()
    ed = ui_process.ui.editor

    if not ed.active:
        ui_process.controller.set_ui_mode(UI_MODE_MENU)
        return

    if ed.kind == "enum":
        if name == "up":
            if ed.index > 0:
                ed.index -= 1
            return

        if name == "down":
            if ed.index < (len(ed.options) - 1):
                ed.index += 1
            return

        if name == "left":
            if str(ed.key).startswith("PROGRAM_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
            elif str(ed.key).startswith("SPECIAL_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
            elif str(ed.key).startswith("HOLIDAY_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
            else:
                ui_process.controller.close_editor()
            return

        if name in ("enter", "right"):
            _save_editor_value(ui_process)
            return

        return

    if ed.kind == "number":
        if name == "up":
            _adjust_editor_number(ui_process, +1)
            return

        if name == "down":
            _adjust_editor_number(ui_process, -1)
            return

        if name == "left":
            if str(ed.key).startswith("PROGRAM_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
            elif str(ed.key).startswith("SPECIAL_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
            elif str(ed.key).startswith("HOLIDAY_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
            else:
                ui_process.controller.close_editor()
            return

        if name in ("enter", "right"):
            _save_editor_value(ui_process)
            return

        return

    if ed.kind == "time":
        if name == "up":
            if ed.part_index == 0:
                ed.hour = (int(ed.hour) + 1) % 24
            else:
                ed.minute = (int(ed.minute) + 1) % 60
            return

        if name == "down":
            if ed.part_index == 0:
                ed.hour = (int(ed.hour) - 1) % 24
            else:
                ed.minute = (int(ed.minute) - 1) % 60
            return

        if name == "right":
            if ed.part_index == 0:
                ed.part_index = 1
            else:
                _save_editor_value(ui_process)
            return

        if name == "enter":
            _save_editor_value(ui_process)
            return

        if name == "left":
            if str(ed.key).startswith("PROGRAM_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_PROGRAM_EDIT)
            elif str(ed.key).startswith("SPECIAL_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
            elif str(ed.key).startswith("HOLIDAY_EDIT_"):
                ui_process.controller.close_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
            else:
                ui_process.controller.close_editor()
            return

        return


def handle_program_edit_button(ui_process, name):
    name = (name or "").strip().lower()
    pe = ui_process.ui.program_edit

    if pe.system == "CH":
        fields = [
            "Start",
            "End",
            "Days",
            "Setpoint",
            "Warmup",
            "Enabled",
            "Note",
            "Save",
            "Copy",
            "Delete",
        ]
    else:
        fields = [
            "Start",
            "End",
            "Days",
            "Enabled",
            "Note",
            "Save",
            "Copy",
            "Delete",
        ]

    if pe.field_index < 0:
        pe.field_index = 0
    if pe.field_index >= len(fields):
        pe.field_index = len(fields) - 1

    if name == "up":
        if pe.field_index > 0:
            pe.field_index -= 1
        return

    if name == "down":
        if pe.field_index < (len(fields) - 1):
            pe.field_index += 1
        return

    current = fields[pe.field_index]

    if name == "left":
        ui_process.controller.close_program_edit()
        return

    if name in ("enter", "right"):
        if current == "Start":
            ui_process.controller.start_time_editor("PROGRAM_EDIT_START", "Start", pe.start_time)
            return

        if current == "End":
            ui_process.controller.start_time_editor("PROGRAM_EDIT_END", "End", pe.end_time)
            return

        if current == "Days":
            ui_process.controller.start_days_editor(pe.days)
            return

        if current == "Setpoint":
            ui_process.controller.start_number_editor(
                "PROGRAM_EDIT_SETPOINT", "Setpoint", pe.setpoint,
                min_value=5.0, max_value=30.0, step=0.5, decimals=1
            )
            return

        if current == "Warmup":
            pe.warmup = not pe.warmup
            return

        if current == "Enabled":
            pe.enabled = not pe.enabled
            return

        if current == "Note":
            current_note = pe.note or ""
            ui_process.controller.start_enum_editor(
                "PROGRAM_EDIT_NOTE",
                "Note",
                ["", "Morning", "Evening", "Workday", "Weekend", "Bath", "Boost", "Eco", "Guests"],
                current_note
            )
            return

        if current == "Save":
            _save_program_edit(ui_process)
            return

        if current == "Copy":
            if not pe.is_new and pe.id is not None:
                ok = ui_process.actions.copy_program(pe.id, pe.system)
                ui_process.controller.close_program_edit()
                ui_process.controller.show_message("Copy Program", "Requested" if ok else "Failed", 2.0)
                return

        if current == "Delete":
            if not pe.is_new and pe.id is not None:
                ok = ui_process.actions.delete_program(pe.id, pe.system)
                ui_process.controller.close_program_edit()
                ui_process.controller.show_message("Delete Program", "Requested" if ok else "Failed", 2.0)
                return


def handle_programs_button(ui_process, name):
    name = (name or "").strip().lower()
    ps = ui_process.ui.programs
    total = len(ps.items or [])

    if name == "up":
        if total > 0 and ps.selected_index > 0:
            ps.selected_index -= 1
        return

    if name == "down":
        if total > 0 and ps.selected_index < (total - 1):
            ps.selected_index += 1
        return

    if name == "left":
        ui_process.controller.set_ui_mode(UI_MODE_MENU)
        return

    if name == "enter":
        if ps.system in ("CH", "HW"):
            ui_process.controller.start_program_edit(item=None, system=ps.system, is_new=True)
        return

    if name == "right":
        if total > 0:
            item = ps.items[ps.selected_index]
            item_id = item.get("id")
            if item_id is not None:
                ui_process.actions.request_program(item_id)
                ui_process.controller.set_ui_mode(UI_MODE_PROGRAM_DETAILS)
        return


def handle_program_detail_button(ui_process, name):
    name = (name or "").strip().lower()

    if name == "left":
        ui_process.controller.set_ui_mode(UI_MODE_PROGRAMS)
        return

    if name == "up":
        if ui_process.ui.programs.details_page > 0:
            ui_process.ui.programs.details_page -= 1
        return

    if name == "down":
        ui_process.ui.programs.details_page = (ui_process.ui.programs.details_page + 1) % 2
        return

    if name in ("enter", "right"):
        item = ui_process.ui.programs.details_item
        if item:
            ui_process.controller.start_program_edit(item=item, system=item.get("system"), is_new=False)
        return

def handle_special_programs_button(ui_process, name):
    name = (name or "").strip().lower()
    sp = ui_process.ui.specials
    total = len(sp.items or [])

    if name == "up":
        if total > 0 and sp.selected_index > 0:
            sp.selected_index -= 1
        return

    if name == "down":
        if total > 0 and sp.selected_index < (total - 1):
            sp.selected_index += 1
        return

    if name == "left":
        ui_process.controller.set_ui_mode(UI_MODE_MENU)
        return

    if name == "enter":
        ui_process.controller.start_special_edit(item=None, is_new=True)
        return

    if name == "right":
        if total > 0:
            item = sp.items[sp.selected_index]
            item_id = item.get("id")
            if item_id is not None:
                sp.loading = True
                sp.details_item = None
                sp.details_page = 0
                ui_process.actions.request_special_period(item_id)
                ui_process.controller.set_ui_mode(UI_MODE_SPECIAL_PROGRAM_DETAILS)
        return


def handle_holiday_programs_button(ui_process, name):
    name = (name or "").strip().lower()
    hp = ui_process.ui.holidays
    total = len(hp.items or [])

    if name == "up":
        if total > 0 and hp.selected_index > 0:
            hp.selected_index -= 1
        return

    if name == "down":
        if total > 0 and hp.selected_index < (total - 1):
            hp.selected_index += 1
        return

    if name == "left":
        ui_process.controller.set_ui_mode(UI_MODE_MENU)
        return

    if name == "enter":
        ui_process.controller.start_holiday_edit(item=None, is_new=True)
        return

    if name == "right":
        if total > 0:
            item = hp.items[hp.selected_index]
            item_id = item.get("id")
            if item_id is not None:
                hp.loading = True
                hp.details_item = None
                hp.details_page = 0
                ui_process.actions.request_holiday(item_id)
                ui_process.controller.set_ui_mode(UI_MODE_HOLIDAY_PROGRAM_DETAILS)
        return

def handle_special_program_detail_button(ui_process, name):
    name = (name or "").strip().lower()

    if name == "left":
        ui_process.controller.set_ui_mode(UI_MODE_SPECIAL_PROGRAMS)
        return

    if name == "up":
        if ui_process.ui.specials.details_page > 0:
            ui_process.ui.specials.details_page -= 1
        return

    if name == "down":
        ui_process.ui.specials.details_page = (
            ui_process.ui.specials.details_page + 1
        ) % 2
        return

    if name in ("enter", "right"):
        item = ui_process.ui.specials.details_item
        if item:
            ui_process.controller.start_special_edit(item=item, is_new=False)
        return


def handle_holiday_program_detail_button(ui_process, name):
    name = (name or "").strip().lower()

    if name == "left":
        ui_process.controller.set_ui_mode(UI_MODE_HOLIDAY_PROGRAMS)
        return

    if name == "up":
        if ui_process.ui.holidays.details_page > 0:
            ui_process.ui.holidays.details_page -= 1
        return

    if name == "down":
        ui_process.ui.holidays.details_page = (
            ui_process.ui.holidays.details_page + 1
        ) % 2
        return

    if name in ("enter", "right"):
        item = ui_process.ui.holidays.details_item
        if item:
            ui_process.controller.start_holiday_edit(item=item, is_new=False)
        return

def handle_special_edit_button(ui_process, name):
    name = (name or "").strip().lower()
    se = ui_process.ui.special_edit

    fields = [
        "Start",
        "End",
        "Systems",
        "SetName",
        "Enabled",
        "Note",
        "Save",
        "Copy",
        "Delete",
    ]

    if se.field_index < 0:
        se.field_index = 0
    if se.field_index >= len(fields):
        se.field_index = len(fields) - 1

    current = fields[se.field_index]

    if name == "up":
        if se.field_index > 0:
            se.field_index -= 1
        return

    if name == "down":
        if se.field_index < (len(fields) - 1):
            se.field_index += 1
        return

    if name == "left":
        ui_process.controller.close_special_edit()
        return

    if name in ("enter", "right"):
        if current == "Start":
            ui_process.controller.start_datetime_editor(
                "SPECIAL_EDIT_START",
                "Special Start",
                se.start_time
            )
            return

        if current == "End":
            ui_process.controller.start_datetime_editor(
                "SPECIAL_EDIT_END",
                "Special End",
                se.end_time
            )
            return

        if current == "Systems":
            if se.systems == "CH":
                se.systems = "HW"
            elif se.systems == "HW":
                se.systems = "CH,HW"
            else:
                se.systems = "CH"
            return

        if current == "SetName":
            ui_process.controller.start_enum_editor(
                "SPECIAL_EDIT_SETNAME",
                "Set Name",
                ["BOOST", "AWAY", "WEEKEND", "WORKDAY"],
                se.schedule_set_name
            )
            return

        if current == "Enabled":
            se.enabled = not se.enabled
            return

        if current == "Note":
            ui_process.controller.start_enum_editor(
                "SPECIAL_EDIT_NOTE",
                "Note",
                ["", "Guests", "Trip", "Holiday", "Weekend", "Custom"],
                se.note
            )
            return

        if current == "Save":
            _save_special_edit(ui_process)
            return

        if current == "Copy":
            if not se.is_new and se.id is not None:
                ok = ui_process.actions.copy_special_period(se.id)
                ui_process.controller.close_special_edit()
                ui_process.controller.show_message("Copy Special", "Requested" if ok else "Failed", 2.0)
            return

        if current == "Delete":
            if not se.is_new and se.id is not None:
                ok = ui_process.actions.delete_special_period(se.id)
                ui_process.controller.close_special_edit()
                ui_process.controller.show_message("Delete Special", "Requested" if ok else "Failed", 2.0)
            return

        return


def handle_holiday_edit_button(ui_process, name):
    name = (name or "").strip().lower()
    he = ui_process.ui.holiday_edit

    fields = [
        "Start",
        "End",
        "Systems",
        "Enabled",
        "Note",
        "Save",
        "Copy",
        "Delete",
    ]

    if he.field_index < 0:
        he.field_index = 0
    if he.field_index >= len(fields):
        he.field_index = len(fields) - 1

    current = fields[he.field_index]

    if name == "up":
        if he.field_index > 0:
            he.field_index -= 1
        return

    if name == "down":
        if he.field_index < (len(fields) - 1):
            he.field_index += 1
        return

    if name == "left":
        ui_process.controller.close_holiday_edit()
        return

    if name in ("enter", "right"):
        if current == "Start":
            ui_process.controller.start_datetime_editor(
                "HOLIDAY_EDIT_START",
                "Holiday Start",
                he.start_time
            )
            return

        if current == "End":
            ui_process.controller.start_datetime_editor(
                "HOLIDAY_EDIT_END",
                "Holiday End",
                he.end_time
            )
            return

        if current == "Systems":
            if he.systems == "CH":
                he.systems = "HW"
            elif he.systems == "HW":
                he.systems = "CH,HW"
            else:
                he.systems = "CH"
            return

        if current == "Enabled":
            he.enabled = not he.enabled
            return

        if current == "Note":
            ui_process.controller.start_enum_editor(
                "HOLIDAY_EDIT_NOTE",
                "Note",
                ["", "Trip", "Away", "Holiday", "Visitors", "Custom"],
                he.note
            )
            return

        if current == "Save":
            _save_holiday_edit(ui_process)
            return

        if current == "Copy":
            if not he.is_new and he.id is not None:
                ok = ui_process.actions.copy_holiday(he.id)
                ui_process.controller.close_holiday_edit()
                ui_process.controller.show_message("Copy Holiday", "Requested" if ok else "Failed", 2.0)
            return

        if current == "Delete":
            if not he.is_new and he.id is not None:
                ok = ui_process.actions.delete_holiday(he.id)
                ui_process.controller.close_holiday_edit()
                ui_process.controller.show_message("Delete Holiday", "Requested" if ok else "Failed", 2.0)
            return

        return

def handle_datetime_editor_button(ui_process, name):
    name = (name or "").strip().lower()
    de = ui_process.ui.datetime_editor

    if not de.active:
        ui_process.controller.set_ui_mode(UI_MODE_MENU)
        return

    if name == "up":
        if de.part_index == 0:
            de.day += 1
        elif de.part_index == 1:
            de.month += 1
        elif de.part_index == 2:
            de.year += 1
        elif de.part_index == 3:
            de.hour = (de.hour + 1) % 24
        elif de.part_index == 4:
            de.minute = (de.minute + 1) % 60
        _clamp_datetime_parts(de)
        return

    if name == "down":
        if de.part_index == 0:
            de.day -= 1
        elif de.part_index == 1:
            de.month -= 1
        elif de.part_index == 2:
            de.year -= 1
        elif de.part_index == 3:
            de.hour = (de.hour - 1) % 24
        elif de.part_index == 4:
            de.minute = (de.minute - 1) % 60
        _clamp_datetime_parts(de)
        return

    if name == "right":
        if de.part_index < 4:
            de.part_index += 1
        else:
            _save_datetime_editor_value(ui_process)
        return

    if name == "left":
        if de.part_index > 0:
            de.part_index -= 1
        else:
            if str(de.key).startswith("SPECIAL_EDIT_"):
                ui_process.controller.close_datetime_editor(return_mode=UI_MODE_SPECIAL_PROGRAM_EDIT)
            elif str(de.key).startswith("HOLIDAY_EDIT_"):
                ui_process.controller.close_datetime_editor(return_mode=UI_MODE_HOLIDAY_PROGRAM_EDIT)
            else:
                ui_process.controller.close_datetime_editor()
        return

    if name == "enter":
        _save_datetime_editor_value(ui_process)
        return


def menu_activate(ui_process):
    items = get_menu_items(ui_process.ui.menu.page)
    if not items:
        return

    item = items[ui_process.ui.menu.index]
    action = item.get("action")

    if action == "open":
        target = item.get("target")

        if target == "HEAT_PROGRAMS":
            ui_process.ui.programs.system = "CH"
            ui_process.ui.programs.items = []
            ui_process.ui.programs.selected_index = 0
            ui_process.ui.programs.loading = True
            ui_process.ui.programs.error = ""
            ui_process.ui.programs.details_item = None
            ui_process.ui.programs.details_page = 0
            ui_process.actions.request_programs("CH", "NORMAL")
            ui_process.controller.set_ui_mode(UI_MODE_PROGRAMS)
            return

        if target == "WATER_PROGRAMS":
            ui_process.ui.programs.system = "HW"
            ui_process.ui.programs.items = []
            ui_process.ui.programs.selected_index = 0
            ui_process.ui.programs.loading = True
            ui_process.ui.programs.error = ""
            ui_process.ui.programs.details_item = None
            ui_process.ui.programs.details_page = 0
            ui_process.actions.request_programs("HW", "NORMAL")
            ui_process.controller.set_ui_mode(UI_MODE_PROGRAMS)
            return

        if target == "SPECIAL_PROGRAMS":
            ui_process.ui.specials.items = []
            ui_process.ui.specials.selected_index = 0
            ui_process.ui.specials.loading = True
            ui_process.ui.specials.error = ""
            ui_process.ui.specials.details_item = None
            ui_process.ui.specials.details_page = 0
            ui_process.ui.specials.preferred_selected_id = None
            ui_process.actions.request_special_periods()
            ui_process.controller.set_ui_mode(UI_MODE_SPECIAL_PROGRAMS)
            return

        if target == "HOLIDAY_PROGRAMS":
            ui_process.ui.holidays.items = []
            ui_process.ui.holidays.selected_index = 0
            ui_process.ui.holidays.loading = True
            ui_process.ui.holidays.error = ""
            ui_process.ui.holidays.details_item = None
            ui_process.ui.holidays.details_page = 0
            ui_process.ui.holidays.preferred_selected_id = None
            ui_process.actions.request_holidays()
            ui_process.controller.set_ui_mode(UI_MODE_HOLIDAY_PROGRAMS)
            return

        menu_open(ui_process, target)
        return

    if action == "home":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        return

    if action == "status":
        ui_process.ui.status.page_index = 0
        ui_process.ui.scroll.pos = 0
        ui_process.ui.scroll.last_time = 0.0
        ui_process.controller.set_ui_mode(UI_MODE_STATUS)
        return

    if action == "edit_ch_switch":
        current = str(ui_process.ui.settings.values.get("CH_SYSTEM_SWITCH", "timed") or "timed")
        ui_process.controller.start_enum_editor(
            "CH_SYSTEM_SWITCH",
            "Heat Switch",
            ["timed", "on", "off", "once"],
            current
        )
        return

    if action == "edit_hw_switch":
        current = str(ui_process.ui.settings.values.get("HW_SYSTEM_SWITCH", "timed") or "timed")
        ui_process.controller.start_enum_editor(
            "HW_SYSTEM_SWITCH",
            "Water Switch",
            ["timed", "on", "off", "once"],
            current
        )
        return

    if action == "edit_default_setpoint":
        current = ui_process.ui.settings.values.get("DEFAULT_SETPOINT", "10.0")
        ui_process.controller.start_number_editor(
            "DEFAULT_SETPOINT",
            "Default Temp",
            current,
            min_value=5.0,
            max_value=24.0,
            step=0.5,
            decimals=1
        )
        return

    if action == "edit_default_on_setpoint":
        current = ui_process.ui.settings.values.get("DEFAULT_ON_SETPOINT", "20.0")
        ui_process.controller.start_number_editor(
            "DEFAULT_ON_SETPOINT",
            "On Temp",
            current,
            min_value=5.0,
            max_value=24.0,
            step=0.5,
            decimals=1
        )
        return

    if action == "edit_boost_setpoint":
        current = ui_process.ui.settings.values.get("BOOST_SETPOINT", "21.0")
        ui_process.controller.start_number_editor(
            "BOOST_SETPOINT",
            "Boost Temp",
            current,
            min_value=5.0,
            max_value=24.0,
            step=0.5,
            decimals=1
        )
        return

    if action == "edit_lcd_brightness":
        current = ui_process.ui.settings.values.get("LCD_BRIGHTNESS", "80")
        ui_process.controller.start_number_editor(
            "LCD_BRIGHTNESS",
            "LCD Brightness",
            current,
            min_value=1,
            max_value=250,
            step=5,
            decimals=0
        )
        return

    if action == "edit_lcd_dim_level":
        current = ui_process.ui.settings.values.get("LCD_DIM_LEVEL", "20")
        ui_process.controller.start_number_editor(
            "LCD_DIM_LEVEL",
            "LCD Dim Level",
            current,
            min_value=1,
            max_value=250,
            step=5,
            decimals=0
        )
        return

    if action == "edit_lcd_dim_start_time":
        current = ui_process.ui.settings.values.get("LCD_DIM_START_TIME", "00:00")
        ui_process.controller.start_time_editor(
            "LCD_DIM_START_TIME",
            "Dim Start",
            current
        )
        return

    if action == "edit_lcd_dim_end_time":
        current = ui_process.ui.settings.values.get("LCD_DIM_END_TIME", "00:00")
        ui_process.controller.start_time_editor(
            "LCD_DIM_END_TIME",
            "Dim End",
            current
        )
        return

    if action == "edit_target_setpoint_offset":
        current = ui_process.ui.settings.values.get("TARGET_SETPOINT_OFFSET", "-0.5")
        ui_process.controller.start_number_editor(
            "TARGET_SETPOINT_OFFSET",
            "Target Offset",
            current,
            min_value=-5.0,
            max_value=5.0,
            step=0.1,
            decimals=1
        )
        return

    if action == "edit_heatup_rate":
        current = ui_process.ui.settings.values.get("HEATUP_RATE", "0.4")
        ui_process.controller.start_number_editor(
            "HEATUP_RATE",
            "Heatup Rate",
            current,
            min_value=0.1,
            max_value=5.0,
            step=0.1,
            decimals=1
        )
        return

    if action == "edit_temp_sensor_adjustment":
        current = ui_process.ui.settings.values.get("TEMP_SENSOR_ADJUSTMENT_DEGREES", "-4.0")
        ui_process.controller.start_number_editor(
            "TEMP_SENSOR_ADJUSTMENT_DEGREES",
            "Temp Adjust",
            current,
            min_value=-10.0,
            max_value=10.0,
            step=0.1,
            decimals=1
        )
        return

    if action == "edit_hysteresis_band":
        current = ui_process.ui.settings.values.get("HYSTERESIS_BAND", "0")
        ui_process.controller.start_number_editor(
            "HYSTERESIS_BAND",
            "Hysteresis",
            current,
            min_value=0.0,
            max_value=10.0,
            step=0.1,
            decimals=1
        )
        return

    if action == "edit_ch_min_on_seconds":
        current = ui_process.ui.settings.values.get("CH_MIN_ON_SECONDS", "120")
        ui_process.controller.start_number_editor(
            "CH_MIN_ON_SECONDS",
            "Min On Sec",
            current,
            min_value=0,
            max_value=3600,
            step=30,
            decimals=0
        )
        return

    if action == "edit_ch_min_off_seconds":
        current = ui_process.ui.settings.values.get("CH_MIN_OFF_SECONDS", "120")
        ui_process.controller.start_number_editor(
            "CH_MIN_OFF_SECONDS",
            "Min Off Sec",
            current,
            min_value=0,
            max_value=3600,
            step=30,
            decimals=0
        )
        return

    if action == "edit_minimum_heating_startup_time":
        current = ui_process.ui.settings.values.get("MINIMUM_HEATING_STARTUP_TIME", "30")
        ui_process.controller.start_number_editor(
            "MINIMUM_HEATING_STARTUP_TIME",
            "Warmup Min",
            current,
            min_value=5,
            max_value=240,
            step=5,
            decimals=0
        )
        return

    if action == "edit_maximum_heating_startup_time":
        current = ui_process.ui.settings.values.get("MAXIMUM_HEATING_STARTUP_TIME", "120")
        ui_process.controller.start_number_editor(
            "MAXIMUM_HEATING_STARTUP_TIME",
            "Warmup Max",
            current,
            min_value=5,
            max_value=360,
            step=5,
            decimals=0
        )
        return

    if action == "edit_comfort":
        current = str(ui_process.ui.settings.values.get("COMFORT", "True") or "True")
        ui_process.controller.start_bool_editor(
            "COMFORT",
            "Comfort Mode",
            current
        )
        return

    if action == "heat_boost":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        if ui_process.actions.is_boost_active("CH"):
            ui_process.controller.start_confirm(
                "Heat Boost %s" % ui_process.actions.get_boost_finish_text("CH"),
                "Ent:+1h Any:No",
                "add_ch_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Heat Boost +1h?",
                "Ent:Yes Any:No",
                "new_ch_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        return

    if action == "water_boost":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        if ui_process.actions.is_boost_active("HW"):
            ui_process.controller.start_confirm(
                "Water Boost %s" % ui_process.actions.get_boost_finish_text("HW"),
                "Ent:+1h Any:No",
                "add_hw_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Water Boost +1h?",
                "Ent:Yes Any:No",
                "new_hw_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        return

    if action == "heat_advance":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        if ui_process.actions.is_advance_active("CH"):
            ui_process.controller.start_confirm(
                "Cancel Heat Adv?",
                "Ent:Yes Any:No",
                "cancel_ch_advance",
                CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Heat Advance?",
                "Ent:Yes Any:No",
                "enable_ch_advance",
                CONFIRM_TIMEOUT_SECONDS
            )
        return

    if action == "water_advance":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        if ui_process.actions.is_advance_active("HW"):
            ui_process.controller.start_confirm(
                "Cancel WaterAdv?",
                "Ent:Yes Any:No",
                "cancel_hw_advance",
                CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Water Advance?",
                "Ent:Yes Any:No",
                "enable_hw_advance",
                CONFIRM_TIMEOUT_SECONDS
            )
        return

    if action == "heat_clear_boost":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        ok = ui_process.actions.clear_boost("CH")
        ui_process.controller.show_message("Heat Boost", "Cleared" if ok else "Failed", 2.0)
        return

    if action == "water_clear_boost":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        ok = ui_process.actions.clear_boost("HW")
        ui_process.controller.show_message("Water Boost", "Cleared" if ok else "Failed", 2.0)
        return

    if action == "noop":
        ui_process.controller.show_message("Menu Item", "Not built yet", 2.0)
        return

    if action == "restart_dwellpi":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        ui_process.controller.start_confirm(
            "Restart DwellPi?",
            "Ent:Yes Any:No",
            "restart_dwellpi",
            CONFIRM_TIMEOUT_SECONDS
        )
        return

    if action == "reboot_pi":
        ui_process.controller.set_ui_mode(UI_MODE_HOME)
        ui_process.controller.start_confirm(
            "Reboot Pi?",
            "Ent:Yes Any:No",
            "reboot_pi",
            CONFIRM_TIMEOUT_SECONDS
        )
        return


def handle_menu_button(ui_process, name):
    name = (name or "").strip().lower()
    items = get_menu_items(ui_process.ui.menu.page)
    total = len(items)

    if name == "up":
        if total > 0 and ui_process.ui.menu.index > 0:
            ui_process.ui.menu.index -= 1
            ui_process.ui.menu.dirty = True
        return

    if name == "down":
        if total > 0 and ui_process.ui.menu.index < (total - 1):
            ui_process.ui.menu.index += 1
            ui_process.ui.menu.dirty = True
        return

    if name == "left":
        menu_go_back(ui_process)
        return

    if name in ("enter", "right"):
        menu_activate(ui_process)
        return


def handle_status_button(ui_process, name):
    name = (name or "").strip().lower()

    if name == "left":
        ui_process.controller.set_ui_mode(UI_MODE_MENU)
        return

    if name == "up":
        if ui_process.ui.status.page_index > 0:
            ui_process.ui.status.page_index -= 1
            ui_process.ui.scroll.pos = 0
            ui_process.ui.scroll.last_time = 0.0
        return

    if name in ("down", "enter", "right"):
        ui_process.ui.status.page_index = (ui_process.ui.status.page_index + 1) % 5
        ui_process.ui.scroll.pos = 0
        ui_process.ui.scroll.last_time = 0.0
        return


def handle_home_button(ui_process, name):
    name = (name or "").strip().lower()

    if name == "up":
        if ui_process.actions.is_advance_active("CH"):
            ui_process.controller.start_confirm(
                "Cancel Heat Adv?", "Ent:Yes Any:No", "cancel_ch_advance", CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Heat Advance?", "Ent:Yes Any:No", "enable_ch_advance", CONFIRM_TIMEOUT_SECONDS
            )
        return

    if name == "down":
        if ui_process.actions.is_advance_active("HW"):
            ui_process.controller.start_confirm(
                "Cancel WaterAdv?", "Ent:Yes Any:No", "cancel_hw_advance", CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Water Advance?", "Ent:Yes Any:No", "enable_hw_advance", CONFIRM_TIMEOUT_SECONDS
            )
        return

    if name == "right":
        if ui_process.actions.is_boost_active("CH"):
            ui_process.controller.start_confirm(
                "Heat Boost %s" % ui_process.actions.get_boost_finish_text("CH"),
                "Ent:+1h Any:No",
                "add_ch_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Heat Boost +1h?",
                "Ent:Yes Any:No",
                "new_ch_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        return

    if name == "left":
        if ui_process.actions.is_boost_active("HW"):
            ui_process.controller.start_confirm(
                "Water Boost %s" % ui_process.actions.get_boost_finish_text("HW"),
                "Ent:+1h Any:No",
                "add_hw_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        else:
            ui_process.controller.start_confirm(
                "Water Boost +1h?",
                "Ent:Yes Any:No",
                "new_hw_boost_hour",
                CONFIRM_TIMEOUT_SECONDS
            )
        return

    if name == "enter":
        ui_process.ui.menu.page = "MAIN"
        ui_process.ui.menu.index = 0
        ui_process.ui.menu.stack = []
        ui_process.ui.menu.dirty = True
        ui_process.controller.set_ui_mode(UI_MODE_MENU)
        ui_process._log_ui_action("ENTER -> MENU")
        return

def handle_days_editor_button(ui_process, name):
    name = (name or "").strip().lower()
    de = ui_process.ui.days_editor

    if not de.active:
        ui_process.controller.set_ui_mode(UI_MODE_PROGRAM_EDIT)
        return

    if name == "left":
        if de.cursor > 0:
            de.cursor -= 1
        else:
            ui_process.controller.close_days_editor(save=False)
        return

    if name == "right":
        if de.cursor < 6:
            de.cursor += 1
        return

    if name == "enter":
        de.values[de.cursor] = not de.values[de.cursor]
        return

    if name == "up":
        ui_process.controller.close_days_editor(save=True)
        return

    if name == "down":
        all_on = True
        for v in de.values:
            if not v:
                all_on = False
                break

        de.values = [False, False, False, False, False, False, False] if all_on else [True, True, True, True, True, True, True]
        return


def handle_button(ui_process, name):
    name = (name or "").strip().lower()
    ui_process.ui.last_input_time = time.time()

    if ui_process.ui.mode == UI_MODE_MENU:
        handle_menu_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_STATUS:
        handle_status_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_PROGRAMS:
        handle_programs_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_PROGRAM_DETAILS:
        handle_program_detail_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_SPECIAL_PROGRAMS:
        handle_special_programs_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_HOLIDAY_PROGRAMS:
        handle_holiday_programs_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_SPECIAL_PROGRAM_DETAILS:
        handle_special_program_detail_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_HOLIDAY_PROGRAM_DETAILS:
        handle_holiday_program_detail_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_DAYS_EDITOR:
        handle_days_editor_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_PROGRAM_EDIT:
        handle_program_edit_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_EDITOR:
        handle_editor_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_CONFIRM:
        handle_confirm_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_SPECIAL_PROGRAM_EDIT:
        handle_special_edit_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_HOLIDAY_PROGRAM_EDIT:
        handle_holiday_edit_button(ui_process, name)
        return

    if ui_process.ui.mode == UI_MODE_DATETIME_EDITOR:
        handle_datetime_editor_button(ui_process, name)
        return

    handle_home_button(ui_process, name)