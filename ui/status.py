#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/status.py

import time


def _fmt_age_seconds(value):
    if value is None:
        return "--"
    try:
        return "%02ds" % int(round(float(value)))
    except Exception:
        return "--"


def _fmt_restart_count(value):
    try:
        return str(int(value))
    except Exception:
        return "0"


def _alive_text(flag):
    return "UP" if flag else "DN"


def _db_ready_text(flag):
    return "OK" if flag else "WAIT"


def build_status_lines(ui_state, display, actions):
    page = ui_state.status.page_index % 5

    if page == 0:
        return [
            display.fit("Status 1/5"),
            display.fit("Temp: %s" % display.fmt_temp(ui_state.live.temp)),
            display.fit("Tgt : %s" % display.fmt_temp(ui_state.live.target)),
            display.fit("CH:%s HW:%s" % (
                display.desired_text(ui_state.live.ch_desired),
                display.desired_text(ui_state.live.hw_desired)
            ))
        ]

    if page == 1:
        return [
            display.fit("Status 2/5"),
            display.fit("RA:%s RB:%s" % (
                display.relay_text(ui_state.live.relay_a),
                display.relay_text(ui_state.live.relay_b)
            )),
            display.fit("CH sw:%s" % display.switch_text(ui_state.live.ch_switch)),
            display.fit("HW sw:%s" % display.switch_text(ui_state.live.hw_switch))
        ]

    if page == 2:
        return [
            display.fit("Status 3/5"),
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

    if page == 3:
        now_ts = time.time()

        if now_ts - ui_state.scroll.last_time > 0.4:
            ui_state.scroll.pos += 1
            ui_state.scroll.last_time = now_ts

        ch_reason = display.scroll_window(
            "CH:" + display.short_reason(ui_state.live.reason),
            ui_state.scroll.pos
        )
        hw_reason = display.scroll_window(
            "HW:" + display.short_reason(ui_state.live.hw_reason),
            ui_state.scroll.pos + 4
        )

        return [
            display.fit("Status 4/5"),
            ch_reason,
            hw_reason,
            display.fit("Left=Back")
        ]

    sup = getattr(ui_state, "supervisor_status", {}) or {}
    procs = sup.get("processes", {}) or {}

    engine = procs.get("engine", {}) or {}
    sensor = procs.get("sensor", {}) or {}
    relay = procs.get("relay", {}) or {}

    status_age = None
    try:
        updated = float(getattr(ui_state, "supervisor_status_updated", 0.0) or 0.0)
        if updated > 0:
            status_age = max(0.0, time.time() - updated)
    except Exception:
        status_age = None

    line1 = "Status 5/5"

    line2 = "E%s S%s R%s" % (
        _fmt_age_seconds(engine.get("heartbeat_age")),
        _fmt_age_seconds(sensor.get("heartbeat_age")),
        _fmt_age_seconds(relay.get("heartbeat_age"))
    )

    line3 = "Er%s Sr%s Rr%s" % (
        _fmt_restart_count(engine.get("restart_count")),
        _fmt_restart_count(sensor.get("restart_count")),
        _fmt_restart_count(relay.get("restart_count"))
    )

    line4 = "DB:%s UI:%s W:%s %s" % (
        _db_ready_text(sup.get("db_ready")),
        _alive_text(procs.get("ui", {}).get("alive")),
        _alive_text(procs.get("web", {}).get("alive")),
        _fmt_age_seconds(status_age)
    )

    return [
        display.fit(line1),
        display.fit(line2),
        display.fit(line3),
        display.fit(line4)
    ]