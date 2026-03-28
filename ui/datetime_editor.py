#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/datetime_editor.py

def build_datetime_editor_lines(ui_state, display):
    de = ui_state.datetime_editor

    if not de.active:
        return [
            display.fit("DateTime"),
            display.fit("Not active"),
            display.fit(""),
            display.fit("")
        ]

    markers = [" ", " ", " ", " ", " "]
    idx = min(max(de.part_index, 0), 4)
    markers[idx] = "^"

    line2 = "%02d/%02d/%02d,%02d:%02d" % (
        int(de.day),
        int(de.month),
        int(de.year),
        int(de.hour),
        int(de.minute),
    )

    line3 = "%s %s %s %s %s" % (
        markers[0], markers[1], markers[2], markers[3], markers[4]
    )

    return [
        display.fit(de.label[:16]),
        display.fit(line2),
        display.fit(line3),
        display.fit("L/R Sel Ent OK"),
    ]