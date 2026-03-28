#!/usr/bin/python
# -*- coding: utf-8 -*-
# lcd_library.py

from __future__ import print_function
import smbus
from time import sleep

sleep_time = 0.01


class i2c_device:
    def __init__(self, addr, port):
        self.addr = addr
        self.bus = smbus.SMBus(port)

    def write_byte_data(self, cmd, byte):
        self.bus.write_byte_data(self.addr, cmd, byte)

    def write_i2c_block_data(self, cmd, byteList):
        self.bus.write_i2c_block_data(self.addr, cmd, byteList)


class lcd:
    def __init__(self, addr, port):
        # Initialize buffer with something that ISN'T spaces
        # to force the first write to happen.
        self.buffer = [None, None, None, None]
        self.lcd_device = i2c_device(addr, port)

        # Legacy 9-byte fonts
        self.font_data = [
            [2, 8, 12, 14, 15, 14, 12, 8, 0],  # Right
            [3, 2, 6, 14, 30, 14, 6, 2, 0],  # Left
            [4, 0, 4, 4, 14, 14, 31, 31, 0],  # Up
            [5, 0, 31, 31, 14, 14, 4, 4, 0],  # Down
            [6, 8, 20, 8, 7, 8, 8, 7, 0]  # Degree
        ]

        # 1. Reset Hardware Mode
        self.lcd_backlight(80)
        self.lcd_write(5, [4, 16])  # Set 16x4
        self.lcd_clear()
        sleep(0.1)

        # 2. Load Fonts
        for font in self.font_data:
            self.lcd_load_custom_chars(font)
            sleep(0.01)

        # 3. Final Prep
        self.lcd_HD44_cmd(12)  # Cursor off
        self.lcd_set_row(1, 1)

    def smart_write(self, line, text):
        clean_text = str(text)[:16].ljust(16)
        if self.buffer[line - 1] == clean_text:
            return

        self.lcd_set_row(line, 1)
        sleep(0.002)

        for char in clean_text:
            self.lcd_write_char(ord(char))
            sleep(0.001)

        self.buffer[line - 1] = clean_text

    def lcd_write(self, cmd, val):
        self.lcd_device.write_i2c_block_data(cmd, val)

    def lcd_write_char(self, charvalue):
        self.lcd_device.write_byte_data(1, charvalue)

    def lcd_putc(self, char):
        self.lcd_write_char(ord(char))

    def lcd_HD44_cmd(self, cmd):
        self.lcd_device.write_byte_data(6, cmd)

    def lcd_backlight(self, level):
        self.lcd_device.write_byte_data(7, level)

    def lcd_clear(self):
        self.lcd_write(4, [0])
        self.buffer = [None, None, None, None]

    def lcd_set_row(self, row, column):
        self.lcd_write(2, [row, column])

    def lcd_load_custom_chars(self, fontdata):
        self.lcd_write(64, fontdata)

    # --- Legacy Compatibility Methods ---
    def lcd_change_temp(self, temp):
        self.lcd_set_row(1, 1)
        self.lcd_puts(str(temp))

    def lcd_puts(self, string):
        for char in string:
            self.lcd_putc(char)