#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/home.py

import time


def build_home_lines(ui, display, actions, controller):
    now_ts = time.time()
    cycle_pos = int(now_ts) % 12

    if cycle_pos < 6:
        header_right = "DwellPi"
    else:
        header_right = time.strftime("%H:%M")

    temp_str = display.fmt_temp(ui.live.temp)
    line1 = "{:<7}{:>9}".format(temp_str, header_right)

    line2 = "Target: {:<8}".format(display.fmt_temp(ui.live.target))

    if cycle_pos < 6:
        ch_txt = display.desired_text(ui.live.ch_desired)
        hw_txt = display.desired_text(ui.live.hw_desired)
        line3 = "D CH:{:<3} HW:{:<3}".format(ch_txt, hw_txt)
    else:
        ch_txt = display.relay_text(ui.live.relay_a)
        hw_txt = display.relay_text(ui.live.relay_b)
        line3 = "R CH:{:<3} HW:{:<3}".format(ch_txt, hw_txt)

    ch_sw = str(ui.live.ch_switch or "timed").upper()
    hw_sw = str(ui.live.hw_switch or "timed").upper()
    boost_summary = actions.get_active_boost_summary()

    parts = [
        "CH:%s" % ch_sw,
        "HW:%s" % hw_sw
    ]

    if boost_summary:
        parts.append(boost_summary)

    full_bottom = " | ".join(parts)

    if len(full_bottom) <= 16:
        line4 = full_bottom.ljust(16)
    else:
        padding = "     "
        scroll_str = full_bottom + padding

        if now_ts - ui.scroll.last_time > 0.4:
            ui.scroll.pos = (ui.scroll.pos + 1) % len(scroll_str)
            ui.scroll.last_time = now_ts

        line4 = (scroll_str + scroll_str)[ui.scroll.pos:ui.scroll.pos + 16]

    if controller.confirm_active():
        line3 = ui.overlay.confirm_line3
        line4 = ui.overlay.confirm_line4
    elif controller.message_active():
        line3 = ui.overlay.message_line3
        line4 = ui.overlay.message_line4

    return [
        display.fit(line1),
        display.fit(line2),
        display.fit(line3),
        display.fit(line4)
    ]