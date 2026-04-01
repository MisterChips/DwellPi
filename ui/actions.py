#!/usr/bin/python
# -*- coding: utf-8 -*-
# ui/actions.py

import time
from message_schema import Message


class UIActions(object):
    def __init__(self, db_queue, settings_dict, supervisor_queue=None):
        self.db_queue = db_queue
        self.settings = settings_dict
        self.supervisor_queue = supervisor_queue

    def set_setting(self, key, value):
        try:
            self.settings[key] = value
            self.db_queue.put(Message("ui", "set_setting", {
                "key": key,
                "value": value
            }))
            return True
        except Exception:
            return False

    def set_bool_setting(self, key, flag):
        return self.set_setting(key, "True" if flag else "False")

    def is_advance_active(self, system):
        return str(self.settings.get("%s_ADVANCE" % system, "False")) == "True"

    def get_boost_finish_epoch(self, system):
        try:
            return int(self.settings.get("%s_BOOST_FINISH_EPOCH" % system, "0") or "0")
        except Exception:
            return 0

    def get_boost_finish_text(self, system):
        return str(self.settings.get("%s_BOOST_FINISH_TIME" % system, "00:00") or "00:00")

    def is_boost_active(self, system):
        return self.get_boost_finish_epoch(system) > int(time.time())

    def clear_boost(self, system):
        key_epoch = "%s_BOOST_FINISH_EPOCH" % system
        key_time = "%s_BOOST_FINISH_TIME" % system

        ok1 = self.set_setting(key_epoch, "0")
        ok2 = self.set_setting(key_time, "00:00")
        return ok1 and ok2

    def add_boost(self, system, minutes=60, max_minutes=180):
        now_epoch = int(time.time())

        try:
            current_finish = int(self.settings.get("%s_BOOST_FINISH_EPOCH" % system, "0") or "0")
        except Exception:
            current_finish = 0

        base_epoch = current_finish if current_finish > now_epoch else now_epoch
        new_finish = base_epoch + (int(minutes) * 60)
        max_finish = now_epoch + (int(max_minutes) * 60)

        if new_finish > max_finish:
            new_finish = max_finish

        finish_time = time.strftime("%H:%M", time.localtime(new_finish))

        ok1 = self.set_setting("%s_BOOST_FINISH_EPOCH" % system, str(new_finish))
        ok2 = self.set_setting("%s_BOOST_FINISH_TIME" % system, finish_time)

        return (ok1 and ok2), finish_time

    def enable_advance(self, system):
        self.clear_boost(system)
        return self.set_bool_setting("%s_ADVANCE" % system, True)

    def cancel_advance(self, system):
        return self.set_bool_setting("%s_ADVANCE" % system, False)

    def get_active_boost_summary(self):
        parts = []

        if self.is_boost_active("CH"):
            parts.append("CHb %s" % self.get_boost_finish_text("CH"))

        if self.is_boost_active("HW"):
            parts.append("HWb %s" % self.get_boost_finish_text("HW"))

        return " | ".join(parts)

    def request_programs(self, system, schedule_set_name="NORMAL"):
        try:
            self.db_queue.put(Message("ui", "get_programs", {
                "system": system,
                "schedule_set_name": schedule_set_name
            }))
            return True
        except Exception:
            return False

    def request_program(self, program_id):
        try:
            self.db_queue.put(Message("ui", "get_program", {
                "id": program_id
            }))
            return True
        except Exception:
            return False

    def create_program(self, payload):
        try:
            self.db_queue.put(Message("ui", "create_program", dict(payload or {})))
            return True
        except Exception:
            return False

    def update_program(self, payload):
        try:
            self.db_queue.put(Message("ui", "update_program", dict(payload or {})))
            return True
        except Exception:
            return False

    def copy_program(self, program_id, system):
        try:
            self.db_queue.put(Message("ui", "copy_program", {
                "id": program_id,
                "system": system
            }))
            return True
        except Exception:
            return False

    def delete_program(self, program_id, system):
        try:
            self.db_queue.put(Message("ui", "delete_program", {
                "id": program_id,
                "system": system
            }))
            return True
        except Exception:
            return False

    def request_special_periods(self):
        try:
            self.db_queue.put(Message("ui", "get_special_periods", {}))
            return True
        except Exception:
            return False

    def request_holidays(self):
        try:
            self.db_queue.put(Message("ui", "get_holidays", {}))
            return True
        except Exception:
            return False

    def request_special_period(self, item_id):
        try:
            self.db_queue.put(Message("ui", "get_special_period", {
                "id": item_id
            }))
            return True
        except Exception:
            return False

    def request_holiday(self, item_id):
        try:
            self.db_queue.put(Message("ui", "get_holiday", {
                "id": item_id
            }))
            return True
        except Exception:
            return False

    def create_special_period(self, payload):
        try:
            self.db_queue.put(Message("ui", "create_special_period", dict(payload or {})))
            return True
        except Exception:
            return False

    def update_special_period(self, payload):
        try:
            self.db_queue.put(Message("ui", "update_special_period", dict(payload or {})))
            return True
        except Exception:
            return False

    def delete_special_period(self, item_id):
        try:
            self.db_queue.put(Message("ui", "delete_special_period", {
                "id": item_id
            }))
            return True
        except Exception:
            return False

    def create_holiday(self, payload):
        try:
            self.db_queue.put(Message("ui", "create_holiday", dict(payload or {})))
            return True
        except Exception:
            return False

    def update_holiday(self, payload):
        try:
            self.db_queue.put(Message("ui", "update_holiday", dict(payload or {})))
            return True
        except Exception:
            return False

    def delete_holiday(self, item_id):
        try:
            self.db_queue.put(Message("ui", "delete_holiday", {
                "id": item_id
            }))
            return True
        except Exception:
            return False

    def copy_special_period(self, item_id):
        try:
            self.db_queue.put(Message("ui", "copy_special_period", {
                "id": item_id
            }))
            return True
        except Exception:
            return False

    def copy_holiday(self, item_id):
        try:
            self.db_queue.put(Message("ui", "copy_holiday", {
                "id": item_id
            }))
            return True
        except Exception:
            return False

    def request_system_action(self, action):
        try:
            if action not in ("restart_dwellpi", "reboot_pi"):
                return False

            self.db_queue.put(Message("ui", "request_system_action", {
                "action": action
            }))
            return True
        except Exception:
            return False

    def request_restart_dwellpi(self):
        return self.request_system_action("restart_dwellpi")

    def request_reboot_pi(self):
        return self.request_system_action("reboot_pi")

    def request_supervisor_status(self):
        if self.supervisor_queue is None:
            return False

        try:
            self.supervisor_queue.put(Message("ui", "get_supervisor_status", {}))
            return True
        except Exception:
            return False