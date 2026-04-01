#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui_process.py

from __future__ import print_function
import time
from message_schema import Message
from settings_sync import SettingsSyncMixin

from ui.constants import (
    BUTTON_PINS,
    UI_MODE_MENU,
    UI_MODE_STATUS,
    UI_MODE_EDITOR,
    UI_MODE_PROGRAMS,
    UI_MODE_PROGRAM_DETAILS,
    UI_MODE_PROGRAM_EDIT,
    UI_MODE_DAYS_EDITOR,
    UI_MODE_SPECIAL_PROGRAMS,
    UI_MODE_HOLIDAY_PROGRAMS,
    UI_MODE_SPECIAL_PROGRAM_DETAILS,
    UI_MODE_HOLIDAY_PROGRAM_DETAILS,
    UI_MODE_SPECIAL_PROGRAM_EDIT,
    UI_MODE_HOLIDAY_PROGRAM_EDIT,
    UI_MODE_DATETIME_EDITOR,
)

from ui.state import UIState
from ui.display import DisplayHelper
from ui.actions import UIActions
from ui.home import build_home_lines
from ui.menu import build_menu_lines
from ui.status import build_status_lines
from ui.navigation import handle_button
from ui import input as ui_input
from ui.controller import UIController
from ui.editor import build_editor_lines
from ui.programs import build_program_list_lines, build_program_detail_lines
from ui.program_edit import build_program_edit_lines
from ui.days_editor import build_days_editor_lines
from ui.specials import build_special_list_lines, build_special_program_detail_lines
from ui.holidays import build_holiday_list_lines, build_holiday_program_detail_lines
from ui.special_edit import build_special_edit_lines
from ui.holiday_edit import build_holiday_edit_lines
from ui.datetime_editor import build_datetime_editor_lines


class UIProcess(SettingsSyncMixin, object):
    def __init__(self, ui_queue, ctrl_queue, db_queue, supervisor_queue, mode, shutdown_event):
        self.ui_queue = ui_queue
        self.ctrl_queue = ctrl_queue
        self.db_queue = db_queue
        self.supervisor_queue = supervisor_queue
        self.mode = mode
        self.shutdown_event = shutdown_event

        self.ui = UIState()
        self.ui.supervisor_status = {}
        self.ui.supervisor_status_updated = 0.0

        self.lcd = None
        self.display = None
        self.actions = None
        self.controller = None

        self.last_button_state = {}

    def _init_lcd(self):
        if self.mode == "TEST":
            try:
                import lcd.lcd_dummy as lcd_library
                self.lcd = lcd_library.lcd(58, 1)
                self.lcd.lcd_clear()
                print("[UI] Using dummy LCD (TEST mode)")
                return
            except Exception as e:
                print("[UI] Dummy LCD init failed:", e)
                self.lcd = None
                return

        try:
            import lcd.lcd_library as lcd_library
            self.lcd = lcd_library.lcd(58, 1)
            self.lcd.lcd_clear()
            print("[UI] Using real LCD (PRODUCTION mode)")
        except Exception as e:
            print("[UI] Real LCD init failed:", e)
            self.lcd = None

    def _settings_store(self):
        return self.ui.settings.values

    def _on_setting_changed(self, key, value):
        brightness_related = False

        if key == "LCD_BRIGHTNESS":
            self.ui.settings.lcd_brightness = int(float(value))
            brightness_related = True

        elif key == "LCD_DIM_LEVEL":
            self.ui.settings.lcd_dim_level = int(float(value))
            brightness_related = True

        elif key == "LCD_DIM_START_TIME":
            self.ui.settings.lcd_dim_start_time = str(value or "00:00")
            brightness_related = True

        elif key == "LCD_DIM_END_TIME":
            self.ui.settings.lcd_dim_end_time = str(value or "00:00")
            brightness_related = True

        if brightness_related:
            self._apply_lcd_brightness_if_needed(force=False)

    def _on_settings_snapshot_applied(self, values):
        self._apply_lcd_brightness_if_needed(force=True)

    def _setup_helpers(self):
        self.display = DisplayHelper(self.lcd)
        self.actions = UIActions(self.db_queue, self.ui.settings.values, self.supervisor_queue)
        self.controller = UIController(self)

    def _log_ui_action(self, text):
        try:
            self.db_queue.put(Message("ui", "state_change", {
                "system": "UI",
                "state": text
            }))
        except Exception:
            pass

    def _apply_lcd_brightness_if_needed(self, force=False):
        try:
            dim_active = self.display.is_dim_period_active(
                self.ui.settings.lcd_dim_start_time,
                self.ui.settings.lcd_dim_end_time
            )

            if dim_active:
                target = int(self.ui.settings.lcd_dim_level)
            else:
                target = int(self.ui.settings.lcd_brightness)

            if (force or
                    target != self.display.last_applied_brightness or
                    dim_active != self.display.last_dim_state):
                self.display.set_backlight(target)
                self.display.last_applied_brightness = target
                self.display.last_dim_state = dim_active
                print("[UI] LCD brightness -> %s (%s)" % (
                    target,
                    "dimmed" if dim_active else "normal"
                ))
        except Exception as e:
            print("[UI] _apply_lcd_brightness_if_needed failed: %s" % e)

    def _force_full_redraw(self):
        self.ui.lines = ["", "", "", ""]
        self.display.force_full_redraw()

    def _handle_button(self, name):
        handle_button(self, name)

    def _build_lines(self):
        if self.ui.mode == UI_MODE_MENU:
            self.ui.lines = build_menu_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_STATUS:
            self.ui.lines = build_status_lines(self.ui, self.display, self.actions)
        elif self.ui.mode == UI_MODE_EDITOR:
            self.ui.lines = build_editor_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_PROGRAMS:
            self.ui.lines = build_program_list_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_PROGRAM_DETAILS:
            self.ui.lines = build_program_detail_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_PROGRAM_EDIT:
            self.ui.lines = build_program_edit_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_DAYS_EDITOR:
            self.ui.lines = build_days_editor_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_SPECIAL_PROGRAMS:
            self.ui.lines = build_special_list_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_HOLIDAY_PROGRAMS:
            self.ui.lines = build_holiday_list_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_SPECIAL_PROGRAM_DETAILS:
            self.ui.lines = build_special_program_detail_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_HOLIDAY_PROGRAM_DETAILS:
            self.ui.lines = build_holiday_program_detail_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_SPECIAL_PROGRAM_EDIT:
            self.ui.lines = build_special_edit_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_HOLIDAY_PROGRAM_EDIT:
            self.ui.lines = build_holiday_edit_lines(self.ui, self.display)
        elif self.ui.mode == UI_MODE_DATETIME_EDITOR:
            self.ui.lines = build_datetime_editor_lines(self.ui, self.display)
        else:
            self.ui.lines = build_home_lines(self.ui, self.display, self.actions, self.controller)

    def _render_if_changed(self):
        if self.lcd is None:
            return

        if self.ui.mode == UI_MODE_MENU:
            if (self.ui.menu.dirty or
                    self.ui.menu.page != self.ui.menu.last_page or
                    self.ui.menu.index != self.ui.menu.last_index):
                self.ui.menu.last_page = self.ui.menu.page
                self.ui.menu.last_index = self.ui.menu.index
                self.ui.menu.dirty = False
                self._force_full_redraw()

        self.display.render(self.ui.lines)

    def run(self):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[UI] Started in mode: %s" % self.mode)
        last_brightness_check = 0.0
        last_hb = 0.0
        last_supervisor_request = 0.0

        try:
            ui_input.init_gpio(BUTTON_PINS, self.last_button_state)
        except Exception as e:
            print("[UI] GPIO init failed:", e)

        try:
            self._init_lcd()
        except Exception as e:
            print("[UI] LCD init failed:", e)

        self._setup_helpers()

        ok = self.wait_for_initial_snapshot(self.ctrl_queue, self.shutdown_event, timeout=3.0)
        if not ok:
            print("[UI] No settings snapshot received yet; using defaults")

        if not ok:
            self._apply_lcd_brightness_if_needed(force=True)

        while not self.shutdown_event.is_set():
            now = time.time()

            ui_input.drain_ctrl_queue(self)
            ui_input.drain_ui_queue(self)
            ui_input.poll_buttons(self, BUTTON_PINS, self.last_button_state)

            if self.ui.mode == UI_MODE_STATUS:
                if (now - last_supervisor_request) >= 5.0:
                    self.actions.request_supervisor_status()
                    last_supervisor_request = now

            self.controller.update_ui_timers()
            self._build_lines()
            self._render_if_changed()

            if now - last_brightness_check >= 30.0:
                self._apply_lcd_brightness_if_needed(force=False)
                last_brightness_check = now

            if now - last_hb >= 5.0:
                try:
                    self.db_queue.put(Message("ui", "heartbeat", {"status": "ok"}))
                except Exception:
                    pass
                last_hb = now

            time.sleep(0.3)

        ui_input.cleanup_gpio()
        print("[UI] Shutting down cleanly")