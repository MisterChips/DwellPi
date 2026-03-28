#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/holiday_edit.py

def build_holiday_edit_lines(ui, display):
    he = ui.holiday_edit

    fields = [
        "Start",
        "End",
        "Systems",
        "Enabled",
        "Note",
        "Save",
        "Delete",
    ]

    if he.field_index < 0:
        he.field_index = 0
    if he.field_index >= len(fields):
        he.field_index = len(fields) - 1

    current = fields[he.field_index]

    if current == "Start":
        value = he.start_time
    elif current == "End":
        value = he.end_time
    elif current == "Systems":
        value = he.systems
    elif current == "Enabled":
        value = "Yes" if he.enabled else "No"
    elif current == "Note":
        value = he.note or "-"
    else:
        value = ""

    return [
        display.fit("Edit Holiday"),
        display.fit(">%s" % current),
        display.fit(str(value)),
        display.fit("UpDn Sel Left"),
    ]