#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/confirm.py

from ui.constants import UI_MODE_PROGRAMS


def execute_confirm_enter(ui_process):
    action = ui_process.ui.overlay.confirm_action
    ui_process.controller.clear_confirm()

    if action == "enable_ch_advance":
        ok = ui_process.actions.enable_advance("CH")
        ui_process.controller.show_message("Heat Advance", "Enabled" if ok else "Failed", 2.5)
        return

    if action == "cancel_ch_advance":
        ok = ui_process.actions.cancel_advance("CH")
        ui_process.controller.show_message("Heat Advance", "Cancelled" if ok else "Failed", 2.5)
        return

    if action == "enable_hw_advance":
        ok = ui_process.actions.enable_advance("HW")
        ui_process.controller.show_message("Water Advance", "Enabled" if ok else "Failed", 2.5)
        return

    if action == "cancel_hw_advance":
        ok = ui_process.actions.cancel_advance("HW")
        ui_process.controller.show_message("Water Advance", "Cancelled" if ok else "Failed", 2.5)
        return

    if action == "new_ch_boost_hour":
        ui_process.actions.cancel_advance("CH")
        ok, until_text = ui_process.actions.add_boost("CH", 60, 180)
        ui_process.controller.show_message("Heat Boost +1h", ("Until %s" % until_text) if ok else "Failed", 2.5)
        return

    if action == "add_ch_boost_hour":
        ui_process.actions.cancel_advance("CH")
        ok, until_text = ui_process.actions.add_boost("CH", 60, 180)
        ui_process.controller.show_message("Heat Boost +1h", ("Until %s" % until_text) if ok else "Failed", 2.5)
        return

    if action == "new_hw_boost_hour":
        ui_process.actions.cancel_advance("HW")
        ok, until_text = ui_process.actions.add_boost("HW", 60, 180)
        ui_process.controller.show_message("Water Boost +1h", ("Until %s" % until_text) if ok else "Failed", 2.5)
        return

    if action == "add_hw_boost_hour":
        ui_process.actions.cancel_advance("HW")
        ok, until_text = ui_process.actions.add_boost("HW", 60, 180)
        ui_process.controller.show_message("Water Boost +1h", ("Until %s" % until_text) if ok else "Failed", 2.5)
        return

    if action == "delete_program":
        item = ui_process.ui.programs.details_item or {}
        ok = ui_process.actions.delete_program(item.get("id"), item.get("system"))
        ui_process.controller.show_message("Delete Program", "Requested" if ok else "Failed", 2.5)
        if ok:
            ui_process.controller.set_ui_mode(UI_MODE_PROGRAMS)
        return

    if action == "restart_dwellpi":
        ok = ui_process.actions.request_restart_dwellpi()
        ui_process.controller.show_message("DwellPi", "Restarting..." if ok else "Failed", 2.5)
        return

    if action == "reboot_pi":
        ok = ui_process.actions.request_reboot_pi()
        ui_process.controller.show_message("Raspberry Pi", "Rebooting..." if ok else "Failed", 2.5)
        return


def handle_confirm_button(ui_process, name):
    name = (name or "").strip().lower()

    if name == "enter":
        execute_confirm_enter(ui_process)
    else:
        ui_process.controller.clear_confirm()