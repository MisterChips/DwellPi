#!/usr/bin/python
# -*- coding: utf-8 -*-
# lcd.lcd_test.py

from time import sleep
import lcd_library
lcd = lcd_library.lcd(58,1)

#lcd.lcd_write_char(0)
#lcd.lcd_write_char(1)
#lcd.lcd_write_char(2)
#lcd.lcd_write_char(3)
#lcd.lcd_write_char(4)
#lcd.lcd_write_char(5)
#lcd.lcd_write_char(6)
#lcd.lcd_write_char(7)

#sleep(10)
#lcd.lcd_write_char(16)
#for i in range(100):
    #lcd.lcd_puts("Temp 20890123456",1)  #display "Raspberry Pi" on line 1
    #lcd.lcd_puts("Target 220123456",2)  #display "Take a byte!" on line 2
    #lcd.lcd_puts("1234567890123456",3)  #display " This is Line3!" on line 3
    #sleep(0.08)
    #lcd.lcd_puts("1234567890123456",4)  #display "and Line 4!" on line 4
    #sleep (5)
    #lcd.lcd_clear()
#lcd.lcd_cmd(208)
#for i in range(16):
#    sleep (2)
#    lcd.lcd_putc("A")
#    #lcd.lcd_cmd(20)

while True:

    lcd.lcd_puts_right_justified("CH Boost",1, pad=1)
    lcd.lcd_write_char(4)
    lcd.lcd_puts_left_justified("       HW Boost",2)
    lcd.lcd_write_char(5)
    lcd.lcd_puts_left_justified("     CH Advance",3)
    lcd.lcd_write_char(2)
    lcd.lcd_puts_left_justified("     HW Advanc ",4)
    lcd.lcd_write_char(3)

    sleep (5)

    lcd.lcd_puts_left_justified("20.2",1)
    lcd.lcd_write_char(6)
    lcd.lcd_puts_right_justified("HeatiePi",1)
    lcd.lcd_puts_left_justified("Target 22.5",2)
    lcd.lcd_write_char(6)

    lcd.lcd_puts_left_justified("CH:ON",3)
    lcd.lcd_puts_right_justified("HW:off",3)
    lcd.lcd_puts_left_justified("CH:Timed|HW:Timed ",4)

    lcd.lcd_scroll_text(string="CH Program: ACTIVE Days Mo,Tu,We,Th,Fr,Sa,Su; 20:30 - 22:30 | HW Program: inactive", delay=0.4, line =4)
    sleep (1)


