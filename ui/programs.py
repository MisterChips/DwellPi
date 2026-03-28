#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/programs.py

from ui.constants import RIGHT_ARROW, UP_ARROW, DOWN_ARROW


DAY_MAP = {
    "0": "M",
    "1": "T",
    "2": "W",
    "3": "T",
    "4": "F",
    "5": "S",
    "6": "S",
}


def _days_short(days_text):
    raw = str(days_text or "")
    out = []
    for ch in raw:
        if ch in DAY_MAP:
            out.append(DAY_MAP[ch])
    return "".join(out) or "-"


def _program_list_title(system):
    if system == "CH":
        return "Heat Programs"
    if system == "HW":
        return "Water Progs"
    return "Programs"


def _program_action_items(item):
    system = str((item or {}).get("system") or "").upper()

    if system == "CH":
        return [
            {"label": "Edit Setpoint", "action": "edit_setpoint"},
            {"label": "Toggle Warmup", "action": "toggle_warmup"},
            {"label": "Toggle Enabled", "action": "toggle_enabled"},
            {"label": "Copy Program", "action": "copy_program"},
            {"label": "Delete Program", "action": "delete_program"},
        ]

    return [
        {"label": "Toggle Enabled", "action": "toggle_enabled"},
        {"label": "Copy Program", "action": "copy_program"},
        {"label": "Delete Program", "action": "delete_program"},
    ]


def build_program_list_lines(ui_state, display):
    ps = ui_state.programs
    items = ps.items or []
    total = len(items)

    title = _program_list_title(ps.system)

    if ps.loading:
        return [
            display.fit(title[:14]),
            display.fit("Loading..."),
            display.fit(""),
            display.fit("Left=Back"),
        ]

    if ps.error:
        return [
            display.fit(title[:14]),
            display.fit("Error"),
            display.fit(str(ps.error)[:16]),
            display.fit("Left=Back"),
        ]

    if total < 1:
        return [
            display.fit(title[:14]),
            display.fit("No programs"),
            display.fit(""),
            display.fit("Left=Back"),
        ]

    if ps.selected_index < 0:
        ps.selected_index = 0
    if ps.selected_index >= total:
        ps.selected_index = total - 1

    window_size = 3
    start = 0

    if ps.selected_index >= window_size:
        start = ps.selected_index - (window_size - 1)

    end = min(start + window_size, total)
    visible = items[start:end]

    up_mark = UP_ARROW if start > 0 else " "
    down_mark = DOWN_ARROW if end < total else " "
    line1 = display.fit("%-14s%s%s" % (title[:14], up_mark, down_mark))

    lines = [line1]

    for idx, item in enumerate(visible):
        actual_index = start + idx
        prefix = RIGHT_ARROW if actual_index == ps.selected_index else " "

        start_time = str(item.get("start_time") or "--:--")

        if ps.system == "CH":
            try:
                setpoint = float(item.get("setpoint"))
                temp_text = "%.1f%s" % (setpoint, "\x06")
            except Exception:
                temp_text = "--.-"
            text = "%s%s %s" % (prefix, start_time, temp_text)
        else:
            text = "%s%s %s" % (prefix, start_time, _days_short(item.get("days")))

        lines.append(display.fit(text[:16]))

    while len(lines) < 4:
        lines.append(display.fit(""))

    return lines


def build_program_detail_lines(ui_state, display):
    ps = ui_state.programs
    item = ps.details_item

    if not item:
        return [
            display.fit("Program Detail"),
            display.fit("No item"),
            display.fit(""),
            display.fit("Left=Back"),
        ]

    page = ps.details_page % 2

    system = str(item.get("system") or "")
    start_time = str(item.get("start_time") or "--:--")
    end_time = str(item.get("end_time") or "--:--")
    days = _days_short(item.get("days"))
    enabled = "On" if item.get("enabled") else "Off"
    note = str(item.get("note") or "")
    set_name = str(item.get("schedule_set_name") or "NORMAL")

    if system == "CH":
        try:
            setpoint = "%.1f%s" % (float(item.get("setpoint")), "\x06")
        except Exception:
            setpoint = "--.-"
        warmup = "On" if item.get("warmup") else "Off"

        if page == 0:
            return [
                display.fit("Heat Program"),
                display.fit("%s-%s" % (start_time, end_time)),
                display.fit("%s %s" % (days, setpoint)),
                display.fit("W:%s A:%s Ent:Act" % (warmup, enabled)),
            ]

        return [
            display.fit("Heat Program"),
            display.fit("Set:%s" % set_name),
            display.fit(("Note:" + note)[:16]),
            display.fit("Left=Back Dn=N"),
        ]

    if page == 0:
        return [
            display.fit("Water Program"),
            display.fit("%s-%s" % (start_time, end_time)),
            display.fit(days),
            display.fit("A:%s Ent:Act" % enabled),
        ]

    return [
        display.fit("Water Program"),
        display.fit("Set:%s" % set_name),
        display.fit(("Note:" + note)[:16]),
        display.fit("Left=Back Dn=N"),
    ]


def build_program_action_lines(ui_state, display):
    ps = ui_state.programs
    item = ps.details_item

    if not item:
        return [
            display.fit("Prog Actions"),
            display.fit("No item"),
            display.fit(""),
            display.fit("Left=Back"),
        ]

    items = _program_action_items(item)
    total = len(items)

    if ps.action_index < 0:
        ps.action_index = 0
    if ps.action_index >= total:
        ps.action_index = total - 1

    window_size = 3
    start = 0
    if ps.action_index >= window_size:
        start = ps.action_index - (window_size - 1)

    end = min(start + window_size, total)
    visible = items[start:end]

    up_mark = UP_ARROW if start > 0 else " "
    down_mark = DOWN_ARROW if end < total else " "
    line1 = display.fit("%-14s%s%s" % ("Prog Actions", up_mark, down_mark))

    lines = [line1]

    for idx, item in enumerate(visible):
        actual_index = start + idx
        prefix = RIGHT_ARROW if actual_index == ps.action_index else " "
        lines.append(display.fit("%s%s" % (prefix, item["label"])))

    while len(lines) < 4:
        lines.append(display.fit(""))

    return lines