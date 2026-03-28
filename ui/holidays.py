#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/holidays.py

def build_holiday_list_lines(ui_state, display):
    hp = ui_state.holidays

    if hp.loading:
        return [
            display.fit("Holidays"),
            display.fit("Loading..."),
            display.fit(""),
            display.fit("")
        ]

    if hp.error:
        return [
            display.fit("Holidays"),
            display.fit("Error"),
            display.fit(hp.error),
            display.fit("")
        ]

    items = hp.items or []
    if not items:
        return [
            display.fit("Holidays"),
            display.fit("No entries"),
            display.fit(""),
            display.fit("")
        ]

    idx = max(0, min(hp.selected_index, len(items) - 1))
    item = items[idx]

    line2 = item.get("start_ts_text") or item.get("start_time") or "Start?"
    line3 = item.get("end_ts_text") or item.get("end_time") or "End?"
    line4 = item.get("systems") or "Systems?"

    return [
        display.fit("Holiday %d/%d" % (idx + 1, len(items))),
        display.fit(line2),
        display.fit(line3),
        display.fit(line4),
    ]

def build_holiday_program_detail_lines(ui, display):
    item = ui.holidays.details_item
    page = ui.holidays.details_page

    if not item:
        if ui.holidays.loading:
            return [
                display.fit("Holiday Detail"),
                display.fit("Loading..."),
                display.fit(""),
                display.fit("")
            ]
        if ui.holidays.error:
            return [
                display.fit("Holiday Detail"),
                display.fit("Error"),
                display.fit(ui.holidays.error),
                display.fit("")
            ]
        return [
            display.fit("Holiday Detail"),
            display.fit("No item"),
            display.fit(""),
            display.fit("")
        ]

    if page == 0:
        return [
            display.fit("Holiday"),
            display.fit(str(item.get("start_ts_text") or "")),
            display.fit(str(item.get("end_ts_text") or "")),
            display.fit(str(item.get("systems") or "")),
        ]

    return [
        display.fit("Enabled:%s" % str(item.get("enabled"))),
        display.fit("Note:%s" % str(item.get("note") or "")),
        display.fit("ID:%s" % str(item.get("id") or "")),
        display.fit(""),
    ]