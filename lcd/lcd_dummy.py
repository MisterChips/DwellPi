#!/usr/bin/python
# -*- coding: utf-8 -*-
# lcd/lcd_dummy.py

from __future__ import print_function


class lcd(object):
    def __init__(self, addr, port):
        self.addr = addr
        self.port = port
        self.lines = [" " * 16, " " * 16, " " * 16, " " * 16]
        self._last_dump = None
        print("[LCD-DUMMY] init addr=%s port=%s" % (addr, port))

    def lcd_clear(self):
        self.lines = [" " * 16, " " * 16, " " * 16, " " * 16]
        self._dump()

    def lcd_puts_left_justified(self, string, line, clsLine=True):
        idx = int(line) - 1
        if idx < 0 or idx > 3:
            return
        s = (string or "")[:16].ljust(16)
        self.lines[idx] = s
        self._dump()

    def _dump(self):
        snap = tuple(self.lines)
        if snap == self._last_dump:
            return
        self._last_dump = snap
        print("[LCD-DUMMY]")
        for i, line in enumerate(self.lines):
            print("  %d|%s|" % (i + 1, line))