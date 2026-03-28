#!/usr/bin/python
# -*- coding: utf-8 -*-
# temperature_reader.py

from __future__ import print_function

import time
import os

class TemperatureReader(object):
    def __init__(self, sensor_device_id, max_jump_c=3.0, retries=5, retry_delay=0.2):
        self.sensor_device_id = sensor_device_id
        self.max_jump_c = float(max_jump_c)
        self.retries = int(retries)
        self.retry_delay = float(retry_delay)
        self.last_good = None

        # Try both common locations
        self.paths = [
            "/sys/bus/w1/devices/%s/w1_slave" % sensor_device_id,
            "/sys/bus/w1/devices/w1_bus_master1/%s/w1_slave" % sensor_device_id,
        ]

    def _get_path(self):
        for p in self.paths:
            if os.path.exists(p):
                return p
        raise IOError("w1 sensor file not found. Tried: %s" % (", ".join(self.paths)))

    def read_c(self):
        path = self._get_path()

        last_exc = None
        for _ in range(self.retries):
            try:
                with open(path, "r") as f:
                    lines = f.read().strip().splitlines()

                if len(lines) < 2:
                    raise ValueError("bad w1_slave format")

                # Typical first line ends with 'YES' when CRC ok
                line0 = lines[0].strip()
                if not line0.endswith("YES"):
                    raise ValueError("crc not YES: %r" % line0)

                line1 = lines[1]
                idx = line1.find("t=")
                if idx == -1:
                    raise ValueError("no t= field: %r" % line1)

                raw = line1[idx + 2:].strip()
                temp_c = float(raw) / 1000.0
                temp_c = round(temp_c, 1)

                # Spike clamp vs last_good
                if self.last_good is not None:
                    if abs(temp_c - self.last_good) > self.max_jump_c:
                        raise ValueError("spike: %.1f -> %.1f" % (self.last_good, temp_c))

                self.last_good = temp_c
                return temp_c

            except Exception as e:
                last_exc = e
                time.sleep(self.retry_delay)

        # If we repeatedly fail, fall back to last good if we have it
        if self.last_good is not None:
            # Optional: helpful for debugging
            # print("[TempReader] WARNING: returning last_good=%.1f due to: %s" % (self.last_good, last_exc))
            return self.last_good

        raise last_exc