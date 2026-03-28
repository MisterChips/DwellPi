#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/state.py

import time

class LiveState(object):
    def __init__(self):
        self.temp = None
        self.target = None
        self.ch_desired = None
        self.hw_desired = None
        self.reason = ""
        self.hw_reason = ""
        self.ch_switch = None
        self.hw_switch = None
        self.relay_a = None
        self.relay_b = None


class SettingsState(object):
    def __init__(self):
        self.values = {}

        self.lcd_brightness = 80
        self.lcd_dim_level = 20
        self.lcd_dim_start_time = "00:00"
        self.lcd_dim_end_time = "00:00"


class OverlayState(object):
    def __init__(self):
        self.message_line3 = ""
        self.message_line4 = ""
        self.message_until = 0.0

        self.confirm_action = None
        self.confirm_line3 = ""
        self.confirm_line4 = ""
        self.confirm_until = 0.0


class MenuState(object):
    def __init__(self):
        self.stack = []
        self.page = "MAIN"
        self.index = 0
        self.dirty = False
        self.last_page = None
        self.last_index = None


class StatusState(object):
    def __init__(self):
        self.page_index = 0


class ScrollState(object):
    def __init__(self):
        self.pos = 0
        self.last_time = 0.0


class EditorState(object):
    def __init__(self):
        self.active = False
        self.kind = None
        self.key = None
        self.label = ""

        self.options = []
        self.index = 0

        self.value_text = ""
        self.min_value = None
        self.max_value = None
        self.step = 1.0
        self.decimals = 0

        # time editor
        self.hour = 0
        self.minute = 0
        self.part_index = 0   # 0 = hour, 1 = minute

        self.original_value = None


class ProgramsState(object):
    def __init__(self):
        self.system = None
        self.items = []
        self.selected_index = 0
        self.loading = False
        self.error = ""
        self.details_item = None
        self.details_page = 0
        self.action_index = 0
        self.preferred_selected_id = None

class SpecialPeriodsState(object):
    def __init__(self):
        self.items = []
        self.selected_index = 0
        self.loading = False
        self.error = ""
        self.details_item = None
        self.details_page = 0
        self.preferred_selected_id = None


class HolidaysState(object):
    def __init__(self):
        self.items = []
        self.selected_index = 0
        self.loading = False
        self.error = ""
        self.details_item = None
        self.details_page = 0
        self.preferred_selected_id = None

class ProgramEditState(object):
    def __init__(self):
        self.active = False
        self.is_new = False

        self.id = None
        self.system = None
        self.schedule_set_name = "NORMAL"

        self.start_time = "06:00"
        self.end_time = "07:00"
        self.days = "0123456"
        self.setpoint = "20.0"
        self.warmup = False
        self.enabled = True
        self.note = ""

        self.field_index = 0

class DaysEditorState(object):
    def __init__(self):
        self.active = False
        self.cursor = 0
        self.values = [True, True, True, True, True, True, True]

class SpecialEditState(object):
    def __init__(self):
        self.active = False
        self.is_new = False

        self.id = None

        self.start_time = "01/01/25,00:00"
        self.end_time = "01/01/25,00:00"
        self.systems = "CH"
        self.schedule_set_name = "BOOST"
        self.enabled = True
        self.note = ""

        self.field_index = 0


class HolidayEditState(object):
    def __init__(self):
        self.active = False
        self.is_new = False

        self.id = None

        self.start_time = "01/01/25,00:00"
        self.end_time = "01/01/25,00:00"
        self.systems = "CH"
        self.enabled = True
        self.note = ""

        self.field_index = 0

class DateTimeEditorState(object):
    def __init__(self):
        self.active = False
        self.key = None
        self.label = ""
        self.day = 1
        self.month = 1
        self.year = 25
        self.hour = 0
        self.minute = 0
        self.part_index = 0   # 0=day 1=month 2=year 3=hour 4=minute


class UIState(object):
    def __init__(self):
        self.mode = "HOME"
        self.lines = ["", "", "", ""]
        self.last_input_time = time.time()

        self.live = LiveState()
        self.settings = SettingsState()
        self.overlay = OverlayState()
        self.menu = MenuState()
        self.status = StatusState()
        self.scroll = ScrollState()
        self.editor = EditorState()
        self.programs = ProgramsState()
        self.program_edit = ProgramEditState()
        self.days_editor = DaysEditorState()
        self.specials = SpecialPeriodsState()
        self.holidays = HolidaysState()
        self.special_edit = SpecialEditState()
        self.holiday_edit = HolidayEditState()
        self.datetime_editor = DateTimeEditorState()