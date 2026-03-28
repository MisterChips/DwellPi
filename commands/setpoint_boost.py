#!/usr/bin/python
# -*- coding: utf-8 -*-
# setpoint_boost.py

from __future__ import print_function
import sys
from commands.settings_set import main as settings_set_main

def main(argv):
    if len(argv) < 2:
        print("Usage: python -m commands.setpoint_boost 21.0 [--db /path]")
        return 2
    sp = ("%s" % argv[1]).strip()
    return settings_set_main([argv[0], "BOOST_SETPOINT", sp] + argv[2:])

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))