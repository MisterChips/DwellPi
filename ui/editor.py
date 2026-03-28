#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/editor.py

from ui.constants import UP_ARROW, DOWN_ARROW, RIGHT_ARROW


def _display_value(ed, value):
    if ed.key == "COMFORT":
        return "On" if str(value) == "True" else "Off"
    return str(value)


def build_editor_lines(ui_state, display):
    ed = ui_state.editor

    if not ed.active:
        return [
            display.fit("Editor"),
            display.fit("Not active"),
            display.fit(""),
            display.fit("")
        ]

    if ed.kind == "enum":
        current = "--"
        if ed.options and 0 <= ed.index < len(ed.options):
            current = _display_value(ed, ed.options[ed.index])

        up_mark = UP_ARROW if ed.index > 0 else " "
        down_mark = DOWN_ARROW if ed.index < (len(ed.options) - 1) else " "

        return [
            display.fit(ed.label[:16]),
            display.fit("Value"),
            display.fit("%s %-12s %s" % (up_mark, current[:12], down_mark)),
            display.fit("Ent=Save Left=Bk")
        ]

    if ed.kind == "number":
        return [
            display.fit(ed.label[:16]),
            display.fit("Value"),
            display.fit(str(ed.value_text or "")[:16]),
            display.fit("Up/Dn Edit EntOk")
        ]

    if ed.kind == "time":
        hh = int(ed.hour)
        mm = int(ed.minute)

        if ed.part_index == 0:
            line3 = "[%02d]:%02d %s" % (hh, mm, RIGHT_ARROW)
        else:
            line3 = "%02d:[%02d] %s" % (hh, mm, RIGHT_ARROW)

        return [
            display.fit(ed.label[:16]),
            display.fit("Time"),
            display.fit(line3[:16]),
            display.fit("Rt=Next Ent=Sv")
        ]

    return [
        display.fit("Editor"),
        display.fit("Unknown type"),
        display.fit(""),
        display.fit("")
    ]