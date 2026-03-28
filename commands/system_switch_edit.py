#!/usr/bin/python
# -*- coding: utf-8 -*-
# system_switch_edit.py

from __future__ import print_function
import sys
from commands.settings_set import main as settings_set_main

def main(argv):
    if len(argv) < 3:
        print("Usage: python -m commands.system_switch_edit CH|HW timed|on|off|once [--db /path]")
        return 2

    which = argv[1].upper()
    val = (("%s" % argv[2]).strip().lower())  # normalize

    if which not in ("CH", "HW"):
        print("ERROR: must be CH or HW")
        return 2

    key = "%s_SYSTEM_SWITCH" % which
    return settings_set_main([argv[0], key, val] + argv[3:])

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))