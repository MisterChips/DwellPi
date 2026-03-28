#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/special_edit.py

def build_special_edit_lines(ui, display):
    se = ui.special_edit

    fields = [
        "Start",
        "End",
        "Systems",
        "SetName",
        "Enabled",
        "Note",
        "Save",
        "Delete",
    ]

    if se.field_index < 0:
        se.field_index = 0
    if se.field_index >= len(fields):
        se.field_index = len(fields) - 1

    current = fields[se.field_index]

    if current == "Start":
        value = se.start_time
    elif current == "End":
        value = se.end_time
    elif current == "Systems":
        value = se.systems
    elif current == "SetName":
        value = se.schedule_set_name
    elif current == "Enabled":
        value = "Yes" if se.enabled else "No"
    elif current == "Note":
        value = se.note or "-"
    else:
        value = ""

    return [
        display.fit("Edit Special"),
        display.fit(">%s" % current),
        display.fit(str(value)),
        display.fit("UpDn Sel Left"),
    ]