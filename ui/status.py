#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/status.py

import time


def build_status_lines(ui_state, display, actions):
    page = ui_state.status.page_index % 4

    if page == 0:
        return [
            display.fit("Status 1/4"),
            display.fit("Temp: %s" % display.fmt_temp(ui_state.live.temp)),
            display.fit("Tgt : %s" % display.fmt_temp(ui_state.live.target)),
            display.fit("CH:%s HW:%s" % (
                display.desired_text(ui_state.live.ch_desired),
                display.desired_text(ui_state.live.hw_desired)
            ))
        ]

    if page == 1:
        return [
            display.fit("Status 2/4"),
            display.fit("RA:%s RB:%s" % (
                display.relay_text(ui_state.live.relay_a),
                display.relay_text(ui_state.live.relay_b)
            )),
            display.fit("CH sw:%s" % display.switch_text(ui_state.live.ch_switch)),
            display.fit("HW sw:%s" % display.switch_text(ui_state.live.hw_switch))
        ]

    if page == 2:
        return [
            display.fit("Status 3/4"),
            display.fit("CH b:%s a:%s" % (
                actions.get_boost_finish_text("CH") if actions.is_boost_active("CH") else "--:--",
                "ON" if actions.is_advance_active("CH") else "OFF"
            )),
            display.fit("HW b:%s a:%s" % (
                actions.get_boost_finish_text("HW") if actions.is_boost_active("HW") else "--:--",
                "ON" if actions.is_advance_active("HW") else "OFF"
            )),
            display.fit("Left=Back")
        ]

    now_ts = time.time()

    if now_ts - ui_state.scroll.last_time > 0.4:
        ui_state.scroll.pos += 1
        ui_state.scroll.last_time = now_ts

    ch_reason = display.scroll_window("CH:" + display.short_reason(ui_state.live.reason), ui_state.scroll.pos)
    hw_reason = display.scroll_window("HW:" + display.short_reason(ui_state.live.hw_reason), ui_state.scroll.pos + 4)

    return [
        display.fit("Status 4/4"),
        ch_reason,
        hw_reason,
        display.fit("Left=Back")
    ]