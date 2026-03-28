#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/days_editor.py

DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"]


def build_days_editor_lines(ui_state, display):
    de = ui_state.days_editor

    if not de.active:
        return [
            display.fit("Days Editor"),
            display.fit("Not active"),
            display.fit(""),
            display.fit("")
        ]

    line2_parts = []
    for i, label in enumerate(DAY_LABELS):
        text = label if de.values[i] else "-"
        if i == de.cursor:
            text = "[" + text + "]"
        line2_parts.append(text)

    line2 = "".join(line2_parts)

    enabled_count = 0
    for flag in de.values:
        if flag:
            enabled_count += 1

    return [
        display.fit("Edit Days"),
        display.fit(line2[:16]),
        display.fit("On:%d/7" % enabled_count),
        display.fit("UpSav DnAll")
    ]