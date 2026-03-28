#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/specials.py

def build_special_list_lines(ui_state, display):
    sp = ui_state.specials

    if sp.loading:
        return [
            display.fit("Special Programs"),
            display.fit("Loading..."),
            display.fit(""),
            display.fit("")
        ]

    if sp.error:
        return [
            display.fit("Special Programs"),
            display.fit("Error"),
            display.fit(sp.error),
            display.fit("")
        ]

    items = sp.items or []
    if not items:
        return [
            display.fit("Special Programs"),
            display.fit("No entries"),
            display.fit(""),
            display.fit("")
        ]

    idx = max(0, min(sp.selected_index, len(items) - 1))
    item = items[idx]

    line2 = item.get("start_ts_text") or item.get("start_time") or "Start?"
    line3 = item.get("end_ts_text") or item.get("end_time") or "End?"
    line4 = item.get("schedule_set_name") or "Set?"

    return [
        display.fit("Special %d/%d" % (idx + 1, len(items))),
        display.fit(line2),
        display.fit(line3),
        display.fit(line4),
    ]

def build_special_program_detail_lines(ui, display):
    item = ui.specials.details_item
    page = ui.specials.details_page

    if not item:
        if ui.specials.loading:
            return [
                display.fit("Special Detail"),
                display.fit("Loading..."),
                display.fit(""),
                display.fit("")
            ]
        if ui.specials.error:
            return [
                display.fit("Special Detail"),
                display.fit("Error"),
                display.fit(ui.specials.error),
                display.fit("")
            ]
        return [
            display.fit("Special Detail"),
            display.fit("No item"),
            display.fit(""),
            display.fit("")
        ]

    if page == 0:
        return [
            display.fit("Special Period"),
            display.fit(str(item.get("start_ts_text") or "")),
            display.fit(str(item.get("end_ts_text") or "")),
            display.fit(str(item.get("systems") or "")),
        ]

    return [
        display.fit("Set:%s" % str(item.get("schedule_set_name") or "")),
        display.fit("En:%s" % str(item.get("enabled"))),
        display.fit(str(item.get("note") or "")),
        display.fit("ID:%s" % str(item.get("id") or "")),
    ]