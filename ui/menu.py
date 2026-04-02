#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/menu.py

from ui.constants import RIGHT_ARROW, UP_ARROW, DOWN_ARROW

MENU_TREE = {
    "MAIN": [
        {"label": "Heat",      "action": "open", "target": "HEAT"},
        {"label": "Water",     "action": "open", "target": "WATER"},
        {"label": "Programs",  "action": "open", "target": "PROGRAMS"},
        {"label": "Settings",  "action": "open", "target": "SETTINGS"},
        {"label": "Status",    "action": "status"},
        {"label": "Exit Menu", "action": "home"},
    ],

    "HEAT": [
        {"label": "Boost +1h",    "action": "heat_boost"},
        {"label": "Advance",      "action": "heat_advance"},
        {"label": "Clear Boost",  "action": "heat_clear_boost"},
    ],

    "WATER": [
        {"label": "Boost +1h",    "action": "water_boost"},
        {"label": "Advance",      "action": "water_advance"},
        {"label": "Clear Boost",  "action": "water_clear_boost"},
    ],

    "PROGRAMS": [
        {"label": "Heat Programs",    "action": "open", "target": "HEAT_PROGRAMS"},
        {"label": "Water Programs",   "action": "open", "target": "WATER_PROGRAMS"},
        {"label": "Special Periods",  "action": "open", "target": "SPECIAL_PROGRAMS"},
        {"label": "Holiday Periods",  "action": "open", "target": "HOLIDAY_PROGRAMS"},
    ],

    "SETTINGS": [
        {"label": "Heat Settings",   "action": "open", "target": "HEAT_SETTINGS"},
        {"label": "Water Settings",  "action": "open", "target": "WATER_SETTINGS"},
        {"label": "Sys Settings",    "action": "open", "target": "SYS_SETTINGS"},
    ],

            "HEAT_SETTINGS": [
        {"label": "System Switch", "action": "edit_ch_switch"},
        {"label": "Boost Temp", "action": "edit_boost_setpoint"},
        {"label": "On Temp", "action": "edit_default_on_setpoint"},
        {"label": "Default Temp",  "action": "edit_default_setpoint"},
        {"label": "Temp Adjust",   "action": "edit_temp_sensor_adjustment"},
        {"label": "Heatup Rate",   "action": "edit_fallback_heatup_rate"},
        {"label": "Hysteresis",    "action": "edit_hysteresis_band"},
        {"label": "Min On Secs",   "action": "edit_ch_min_on_seconds"},
        {"label": "Min Off Secs",  "action": "edit_ch_min_off_seconds"},
        {"label": "Warmup Min",    "action": "edit_warmup_minimum_lead_time"},
        {"label": "Warmup Max",    "action": "edit_warmup_maximum_lead_time"},
        {"label": "Target Offset", "action": "edit_warmup_target_offset"},
        {"label": "Comfort Mode", "action": "edit_comfort"},
    ],

    "WATER_SETTINGS": [
        {"label": "System Switch", "action": "edit_hw_switch"},
    ],

        "SYS_SETTINGS": [
        {"label": "LCD Bright",       "action": "edit_lcd_brightness"},
        {"label": "LCD Dim",          "action": "edit_lcd_dim_level"},
        {"label": "Dim Start",        "action": "edit_lcd_dim_start_time"},
        {"label": "Dim End",          "action": "edit_lcd_dim_end_time"},
        {"label": "Restart DwellPi",  "action": "restart_dwellpi"},
        {"label": "Reboot Pi",        "action": "reboot_pi"},
    ],

    "HEAT_PROGRAMS": [
        {"label": "Not built yet", "action": "noop"},
    ],

    "WATER_PROGRAMS": [
        {"label": "Not built yet", "action": "noop"},
    ],

    "SPECIAL_PROGRAMS": [
        {"label": "Not built yet", "action": "noop"},
    ],

    "HOLIDAY_PROGRAMS": [
        {"label": "Not built yet", "action": "noop"},
    ],
}


def get_menu_items(page):
    return MENU_TREE.get(page, [])


def build_menu_lines(ui_state, display):
    items = get_menu_items(ui_state.menu.page)
    total = len(items)

    if total < 1:
        return [
            display.fit("Menu"),
            display.fit("No items"),
            display.fit(""),
            display.fit("")
        ]

    if ui_state.menu.index < 0:
        ui_state.menu.index = 0
    if ui_state.menu.index >= total:
        ui_state.menu.index = total - 1

    window_size = 3
    start = 0

    if ui_state.menu.index >= window_size:
        start = ui_state.menu.index - (window_size - 1)

    end = min(start + window_size, total)
    visible = items[start:end]

    up_mark = UP_ARROW if start > 0 else " "
    down_mark = DOWN_ARROW if end < total else " "
    title = ui_state.menu.page[:14]
    line1 = display.fit("%-14s%s%s" % (title, up_mark, down_mark))

    lines = [line1]

    for idx, item in enumerate(visible):
        actual_index = start + idx
        prefix = RIGHT_ARROW if actual_index == ui_state.menu.index else " "
        lines.append(display.fit("%s%s" % (prefix, item["label"])))

    while len(lines) < 4:
        lines.append(display.fit(""))

    return lines