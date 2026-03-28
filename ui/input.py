#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/input.py

import time

from ui.constants import (
    UI_MODE_PROGRAMS,
    UI_MODE_PROGRAM_DETAILS,
    UI_MODE_SPECIAL_PROGRAMS,
    UI_MODE_HOLIDAY_PROGRAMS,
)

try:
    import RPi.GPIO as GPIO
    HAVE_GPIO = True
except Exception:
    HAVE_GPIO = False


def init_gpio(button_pins, last_button_state):
    if not HAVE_GPIO:
        return

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    for pin in button_pins.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    for name in button_pins:
        last_button_state[name] = False


def cleanup_gpio():
    if not HAVE_GPIO:
        return

    try:
        GPIO.cleanup()
    except Exception:
        pass


def _select_program_by_id(ui_process, item_id):
    if item_id is None:
        return False

    items = ui_process.ui.programs.items or []
    for idx, item in enumerate(items):
        if item.get("id") == item_id:
            ui_process.ui.programs.selected_index = idx
            return True

    return False

def _select_special_by_id(ui_process, item_id):
    if item_id is None:
        return False

    items = ui_process.ui.specials.items or []
    for idx, item in enumerate(items):
        if item.get("id") == item_id:
            ui_process.ui.specials.selected_index = idx
            return True

    return False


def _select_holiday_by_id(ui_process, item_id):
    if item_id is None:
        return False

    items = ui_process.ui.holidays.items or []
    for idx, item in enumerate(items):
        if item.get("id") == item_id:
            ui_process.ui.holidays.selected_index = idx
            return True

    return False


def drain_ctrl_queue(ui_process):
    while True:
        try:
            msg = ui_process.ctrl_queue.get_nowait()
        except Exception:
            break

        if msg.type == "settings_snapshot":
            ui_process.apply_settings_snapshot((msg.payload or {}).get("values"))
            continue

        elif msg.type == "setting_changed":
            p = msg.payload or {}
            ui_process.apply_setting_changed(p.get("key"), p.get("value"))
            continue

        if msg.type == "programs_result":
            p = msg.payload or {}
            ui_process.ui.programs.loading = False

            print("[UI] programs_result ok=%s items=%s" % (
                p.get("ok"),
                len(p.get("items") or [])
            ))

            if not p.get("ok"):
                ui_process.ui.programs.error = p.get("error") or "Load failed"
                ui_process.ui.programs.items = []
                ui_process.ui.programs.selected_index = 0
                ui_process.ui.programs.details_item = None
                ui_process.ui.programs.details_page = 0
            else:
                ui_process.ui.programs.error = ""
                ui_process.ui.programs.items = p.get("items") or []

                preferred_id = ui_process.ui.programs.preferred_selected_id
                if preferred_id is not None and _select_program_by_id(ui_process, preferred_id):
                    ui_process.ui.programs.preferred_selected_id = None
                else:
                    items = ui_process.ui.programs.items or []
                    if not items:
                        ui_process.ui.programs.selected_index = 0
                    elif ui_process.ui.programs.selected_index >= len(items):
                        ui_process.ui.programs.selected_index = len(items) - 1
                    elif ui_process.ui.programs.selected_index < 0:
                        ui_process.ui.programs.selected_index = 0

        elif msg.type == "program_result":
            p = msg.payload or {}
            ui_process.ui.programs.loading = False

            if not p.get("ok"):
                ui_process.ui.programs.error = p.get("error") or "Detail failed"
                ui_process.ui.programs.details_item = None
                ui_process.ui.programs.details_page = 0
            else:
                ui_process.ui.programs.error = ""
                ui_process.ui.programs.details_item = p.get("item")
                ui_process.ui.programs.details_page = 0

        elif msg.type == "special_periods_result":
            p = msg.payload or {}
            ui_process.ui.specials.loading = False

            if not p.get("ok"):
                ui_process.ui.specials.error = p.get("error") or "Load failed"
                ui_process.ui.specials.items = []
                ui_process.ui.specials.selected_index = 0
                ui_process.ui.specials.details_item = None
                ui_process.ui.specials.details_page = 0
            else:
                ui_process.ui.specials.error = ""
                ui_process.ui.specials.items = p.get("items") or []

                preferred_id = ui_process.ui.specials.preferred_selected_id
                if preferred_id is not None and _select_special_by_id(ui_process, preferred_id):
                    ui_process.ui.specials.preferred_selected_id = None
                else:
                    items = ui_process.ui.specials.items or []
                    if not items:
                        ui_process.ui.specials.selected_index = 0
                    elif ui_process.ui.specials.selected_index >= len(items):
                        ui_process.ui.specials.selected_index = len(items) - 1
                    elif ui_process.ui.specials.selected_index < 0:
                        ui_process.ui.specials.selected_index = 0

        elif msg.type == "special_period_result":
            p = msg.payload or {}
            ui_process.ui.specials.loading = False

            if not p.get("ok"):
                ui_process.ui.specials.error = p.get("error") or "Detail failed"
                ui_process.ui.specials.details_item = None
                ui_process.ui.specials.details_page = 0
            else:
                ui_process.ui.specials.error = ""
                ui_process.ui.specials.details_item = p.get("item")
                ui_process.ui.specials.details_page = 0

        elif msg.type == "holidays_result":
            p = msg.payload or {}
            ui_process.ui.holidays.loading = False

            if not p.get("ok"):
                ui_process.ui.holidays.error = p.get("error") or "Load failed"
                ui_process.ui.holidays.items = []
                ui_process.ui.holidays.selected_index = 0
                ui_process.ui.holidays.details_item = None
                ui_process.ui.holidays.details_page = 0
            else:
                ui_process.ui.holidays.error = ""
                ui_process.ui.holidays.items = p.get("items") or []

                preferred_id = ui_process.ui.holidays.preferred_selected_id
                if preferred_id is not None and _select_holiday_by_id(ui_process, preferred_id):
                    ui_process.ui.holidays.preferred_selected_id = None
                else:
                    items = ui_process.ui.holidays.items or []
                    if not items:
                        ui_process.ui.holidays.selected_index = 0
                    elif ui_process.ui.holidays.selected_index >= len(items):
                        ui_process.ui.holidays.selected_index = len(items) - 1
                    elif ui_process.ui.holidays.selected_index < 0:
                        ui_process.ui.holidays.selected_index = 0

        elif msg.type == "holiday_result":
            p = msg.payload or {}
            ui_process.ui.holidays.loading = False

            if not p.get("ok"):
                ui_process.ui.holidays.error = p.get("error") or "Detail failed"
                ui_process.ui.holidays.details_item = None
                ui_process.ui.holidays.details_page = 0
            else:
                ui_process.ui.holidays.error = ""
                ui_process.ui.holidays.details_item = p.get("item")
                ui_process.ui.holidays.details_page = 0

        elif msg.type == "update_program_setpoint_result":
            p = msg.payload or {}
            if p.get("ok"):
                item_id = p.get("id")
                if item_id is not None:
                    ui_process.actions.request_program(item_id)
                    ui_process.actions.request_programs(
                        ui_process.ui.programs.system or "CH",
                        "NORMAL"
                    )
            else:
                ui_process.controller.show_message("Setpoint", "Failed", 2.0)

        elif msg.type == "update_program_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.programs.preferred_selected_id = item_id

                if item_id is not None:
                    ui_process.actions.request_program(item_id)

                ui_process.actions.request_programs(
                    ui_process.ui.programs.system or "CH",
                    "NORMAL"
                )

                ui_process.controller.set_ui_mode(UI_MODE_PROGRAM_DETAILS)
                ui_process.controller.show_message("Save Program", "Done", 2.0)
            else:
                ui_process.controller.show_message("Save Program", "Failed", 2.0)

        elif msg.type == "copy_program_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.programs.preferred_selected_id = item_id

                ui_process.ui.programs.details_item = None
                ui_process.ui.programs.details_page = 0

                ui_process.actions.request_programs(
                    ui_process.ui.programs.system or "CH",
                    "NORMAL"
                )

                ui_process.controller.set_ui_mode(UI_MODE_PROGRAMS)
                ui_process.controller.show_message("Copy Program", "Done", 2.0)
            else:
                ui_process.controller.show_message("Copy Program", "Failed", 2.0)

        elif msg.type == "delete_program_result":
            p = msg.payload or {}

            if p.get("ok"):
                current_index = ui_process.ui.programs.selected_index

                ui_process.ui.programs.preferred_selected_id = None
                ui_process.ui.programs.selected_index = current_index

                ui_process.ui.programs.details_item = None
                ui_process.ui.programs.details_page = 0

                ui_process.actions.request_programs(
                    ui_process.ui.programs.system or "CH",
                    "NORMAL"
                )

                ui_process.controller.set_ui_mode(UI_MODE_PROGRAMS)
                ui_process.controller.show_message("Delete Program", "Done", 2.0)
            else:
                ui_process.controller.show_message("Delete Program", "Failed", 2.0)

        elif msg.type == "create_program_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.programs.preferred_selected_id = item_id
                ui_process.ui.programs.details_item = None
                ui_process.ui.programs.details_page = 0
                ui_process.actions.request_programs(
                    ui_process.ui.programs.system or "CH",
                    "NORMAL"
                )

                if item_id is not None:
                    ui_process.actions.request_program(item_id)
                ui_process.controller.set_ui_mode(UI_MODE_PROGRAMS)
                ui_process.controller.show_message("Create Program", "Done", 2.0)
            else:
                ui_process.controller.show_message("Create Program", "Failed", 2.0)

        elif msg.type == "create_special_period_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.specials.preferred_selected_id = item_id
                ui_process.ui.specials.details_item = None
                ui_process.ui.specials.details_page = 0

                ui_process.actions.request_special_periods()

                ui_process.controller.set_ui_mode(UI_MODE_SPECIAL_PROGRAMS)
                ui_process.controller.show_message("Create Special", "Done", 2.0)
            else:
                ui_process.controller.show_message("Create Special", "Failed", 2.0)

        elif msg.type == "update_special_period_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.specials.preferred_selected_id = item_id
                ui_process.ui.specials.details_item = None
                ui_process.ui.specials.details_page = 0

                ui_process.actions.request_special_periods()

                ui_process.controller.set_ui_mode(UI_MODE_SPECIAL_PROGRAMS)
                ui_process.controller.show_message("Save Special", "Done", 2.0)
            else:
                ui_process.controller.show_message("Save Special", "Failed", 2.0)

        elif msg.type == "delete_special_period_result":
            p = msg.payload or {}

            if p.get("ok"):
                current_index = ui_process.ui.specials.selected_index

                ui_process.ui.specials.preferred_selected_id = None
                ui_process.ui.specials.selected_index = current_index
                ui_process.ui.specials.details_item = None
                ui_process.ui.specials.details_page = 0

                ui_process.actions.request_special_periods()

                ui_process.controller.set_ui_mode(UI_MODE_SPECIAL_PROGRAMS)
                ui_process.controller.show_message("Delete Special", "Done", 2.0)
            else:
                ui_process.controller.show_message("Delete Special", "Failed", 2.0)

        elif msg.type == "copy_special_period_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.specials.preferred_selected_id = item_id
                ui_process.ui.specials.details_item = None
                ui_process.ui.specials.details_page = 0

                ui_process.actions.request_special_periods()

                ui_process.controller.set_ui_mode(UI_MODE_SPECIAL_PROGRAMS)
                ui_process.controller.show_message("Copy Special", "Done", 2.0)
            else:
                ui_process.controller.show_message("Copy Special", "Failed", 2.0)

        elif msg.type == "create_holiday_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.holidays.preferred_selected_id = item_id
                ui_process.ui.holidays.details_item = None
                ui_process.ui.holidays.details_page = 0

                ui_process.actions.request_holidays()

                ui_process.controller.set_ui_mode(UI_MODE_HOLIDAY_PROGRAMS)
                ui_process.controller.show_message("Create Holiday", "Done", 2.0)
            else:
                ui_process.controller.show_message("Create Holiday", "Failed", 2.0)

        elif msg.type == "update_holiday_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.holidays.preferred_selected_id = item_id
                ui_process.ui.holidays.details_item = None
                ui_process.ui.holidays.details_page = 0

                ui_process.actions.request_holidays()

                ui_process.controller.set_ui_mode(UI_MODE_HOLIDAY_PROGRAMS)
                ui_process.controller.show_message("Save Holiday", "Done", 2.0)
            else:
                ui_process.controller.show_message("Save Holiday", "Failed", 2.0)

        elif msg.type == "delete_holiday_result":
            p = msg.payload or {}

            if p.get("ok"):
                current_index = ui_process.ui.holidays.selected_index

                ui_process.ui.holidays.preferred_selected_id = None
                ui_process.ui.holidays.selected_index = current_index
                ui_process.ui.holidays.details_item = None
                ui_process.ui.holidays.details_page = 0

                ui_process.actions.request_holidays()

                ui_process.controller.set_ui_mode(UI_MODE_HOLIDAY_PROGRAMS)
                ui_process.controller.show_message("Delete Holiday", "Done", 2.0)
            else:
                ui_process.controller.show_message("Delete Holiday", "Failed", 2.0)

        elif msg.type == "copy_holiday_result":
            p = msg.payload or {}

            if p.get("ok"):
                item_id = p.get("id")
                ui_process.ui.holidays.preferred_selected_id = item_id
                ui_process.ui.holidays.details_item = None
                ui_process.ui.holidays.details_page = 0

                ui_process.actions.request_holidays()

                ui_process.controller.set_ui_mode(UI_MODE_HOLIDAY_PROGRAMS)
                ui_process.controller.show_message("Copy Holiday", "Done", 2.0)
            else:
                ui_process.controller.show_message("Copy Holiday", "Failed", 2.0)

        elif msg.type == "system_action_result":
            p = msg.payload or {}
            action = str(p.get("action") or "")
            ok = bool(p.get("ok"))

            if ok:
                if action == "restart_dwellpi":
                    ui_process.controller.show_message("DwellPi", "Restarting...", 2.5)
                elif action == "reboot_pi":
                    ui_process.controller.show_message("Raspberry Pi", "Rebooting...", 2.5)
                else:
                    ui_process.controller.show_message("System Action", "Accepted", 2.5)
            else:
                ui_process.controller.show_message("System Action", p.get("error") or "Failed", 2.5)


def drain_ui_queue(ui_process):
    while True:
        try:
            msg = ui_process.ui_queue.get_nowait()
        except Exception:
            break

        if msg.type == "button_press":
            p = msg.payload or {}
            ui_process._handle_button(p.get("button"))
            continue

        if msg.type != "ui_state":
            continue

        p = msg.payload or {}

        if "temp" in p:
            ui_process.ui.live.temp = p.get("temp")
        if "target" in p:
            ui_process.ui.live.target = p.get("target")
        if "ch_desired" in p:
            ui_process.ui.live.ch_desired = p.get("ch_desired")
        if "hw_desired" in p:
            ui_process.ui.live.hw_desired = p.get("hw_desired")
        if "reason" in p:
            ui_process.ui.live.reason = p.get("reason") or ""
        if "hw_reason" in p:
            ui_process.ui.live.hw_reason = p.get("hw_reason") or ""
        if "ch_switch" in p:
            ui_process.ui.live.ch_switch = p.get("ch_switch")
        if "hw_switch" in p:
            ui_process.ui.live.hw_switch = p.get("hw_switch")
        if "relay_a" in p:
            ui_process.ui.live.relay_a = p.get("relay_a")
        if "relay_b" in p:
            ui_process.ui.live.relay_b = p.get("relay_b")


def poll_buttons(ui_process, button_pins, last_button_state):
    if not HAVE_GPIO:
        return

    for name, pin in button_pins.items():
        pressed = (GPIO.input(pin) == 0)
        prev = last_button_state.get(name, False)

        if pressed and not prev:
            print("[UI] button press:", name)
            ui_process.ui.last_input_time = time.time()
            ui_process._handle_button(name)

        last_button_state[name] = pressed