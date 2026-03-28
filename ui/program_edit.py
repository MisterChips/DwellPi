#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/program_edit.py

from ui.constants import UP_ARROW, DOWN_ARROW, RIGHT_ARROW

FIELD_LABELS_CH = [
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

FIELD_LABELS_HW = [
    "Start",
    "End",
    "Days",
    "Enabled",
    "Note",
    "Save",
    "Copy",
    "Delete",
]


def _field_names(pe):
    if pe.system == "CH":
        return FIELD_LABELS_CH
    return FIELD_LABELS_HW


def _field_value(pe, label):
    if label == "Start":
        return pe.start_time
    if label == "End":
        return pe.end_time
    if label == "Days":
        return pe.days
    if label == "Setpoint":
        return pe.setpoint
    if label == "Warmup":
        return "On" if pe.warmup else "Off"
    if label == "Enabled":
        return "On" if pe.enabled else "Off"
    if label == "Note":
        return pe.note or "-"
    if label == "Save":
        return "Press Enter"
    if label == "Copy":
        return "Press Enter"
    if label == "Delete":
        return "Press Enter"
    return ""


def build_program_edit_lines(ui_state, display):
    pe = ui_state.program_edit

    if not pe.active:
        return [
            display.fit("Program Edit"),
            display.fit("Not active"),
            display.fit(""),
            display.fit("")
        ]

    labels = _field_names(pe)
    total = len(labels)

    if pe.field_index < 0:
        pe.field_index = 0
    if pe.field_index >= total:
        pe.field_index = total - 1

    label = labels[pe.field_index]
    value = _field_value(pe, label)

    up_mark = UP_ARROW if pe.field_index > 0 else " "
    down_mark = DOWN_ARROW if pe.field_index < (total - 1) else " "

    title = "New %s Prog" % pe.system if pe.is_new else "Edit %s Prog" % pe.system

    return [
        display.fit("%-14s%s%s" % (title[:14], up_mark, down_mark)),
        display.fit(label[:16]),
        display.fit(str(value)[:16]),
        display.fit("UpDn Sel Ent Go")
    ]